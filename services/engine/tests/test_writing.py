import base64
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import sqlalchemy as sa

from narravo_engine import contracts as c
from narravo_engine.domain import Domain, DomainError, count
from narravo_engine.storage import Storage


def call(domain: Domain, method: str, **params: object) -> c.Model:
    return domain.dispatch(method, params)


def create(domain: Domain) -> c.Workspace:
    return domain.book_create(c.BookCreate(title="雨停之前"))


def save(domain: Domain, w: c.Workspace, text: str, index: int = 0) -> c.Workspace:
    return domain.chapter_save(
        c.ChapterSave(
            branch_id=w.branch_id,
            expected_snapshot=w.snapshot_id,
            chapter_id=w.chapters[index].id,
            text=text,
        )
    )


def generate(domain: Domain, w: c.Workspace, intent: str = "写一次重逢") -> c.Task:
    return domain.writing_generate(
        c.Generate(
            branch_id=w.branch_id,
            chapter_id=w.chapters[0].id,
            offset=0,
            context_policy="author_plan",
            intent=intent,
            expected_snapshot=w.snapshot_id,
            provider="demo",
        )
    )


def complete(domain: Domain, task: c.Task) -> c.Task:
    for _ in range(200):
        domain.tick()
        current = domain.task_get(c.TaskTarget(task_id=task.task_id))
        if current.status != "running":
            return current
    pytest.fail("task did not complete")


def accept_request(w: c.Workspace, task: c.Task) -> c.Accept:
    assert task.generation
    return c.Accept(
        generation_id=task.generation.id,
        expected_snapshot=w.snapshot_id,
        candidate_revision=task.generation.candidate_revision,
        start=0,
        end=5,
        edited_text="她打开了门。😀",
        idempotency_key="accept-one",
    )


def test_original_empty_lifecycle_persists_without_sources(domain: Domain, tmp_path: Path) -> None:
    w = create(domain)
    assert w.word_count == 0 and w.chapters[0].anchor
    with domain.db.transaction() as conn:
        book = domain.row(conn, "books", w.book_id)
        assert book["source_asset_id"] is None and book["source_hash"] is None
        assert book["import_status"] == "not_applicable"
    text = "窗外，雨停了。😀\n\n一封信。\n"
    w = save(domain, w, text)
    reopened = Domain(Storage(tmp_path))
    assert (
        reopened.chapter_get(
            c.ChapterTarget(branch_id=w.branch_id, chapter_id=w.chapters[0].id)
        ).text
        == text
    )
    assert w.word_count == count(text) == 12
    assert reopened.book_export(c.Export(branch_id=w.branch_id)).content.endswith(text)
    reopened.db.close()


def test_atomic_create_rolls_back_partial_book(
    domain: Domain, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = domain.insert

    def fail(conn, table, **values):  # type: ignore[no-untyped-def]
        if table == "branches":
            raise RuntimeError("injected write failure")
        original(conn, table, **values)

    monkeypatch.setattr(domain, "insert", fail)
    with pytest.raises(RuntimeError):
        create(domain)
    assert domain.book_list(c.Empty()).books == []


def test_concurrent_save_only_one_expected_snapshot_wins(domain: Domain) -> None:
    w = create(domain)

    def attempt(text: str) -> str:
        try:
            save(domain, w, text)
            return "saved"
        except DomainError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, ["甲", "乙"])) == ["REVISION_CONFLICT", "saved"]


def test_fork_isolates_body_planning_and_chapter_structure(domain: Domain) -> None:
    parent = save(domain, create(domain), "原始正文")
    child = domain.branch_fork(
        c.BranchFork(branch_id=parent.branch_id, expected_snapshot=parent.snapshot_id)
    )
    child = save(domain, child, "分支正文")
    child = domain.chapter_create(
        c.ChapterCreate(branch_id=child.branch_id, expected_snapshot=child.snapshot_id)
    )
    child = domain.planning_save(
        c.PlanningSave(
            branch_id=child.branch_id,
            expected_snapshot=child.snapshot_id,
            entries=[
                c.PlanningEntry(
                    id="ending",
                    kind="outline",
                    title="结局",
                    text="新的结局",
                    context_role="planned_event",
                )
            ],
        )
    )
    child = domain.chapter_reorder(
        c.ChapterReorder(
            branch_id=child.branch_id,
            expected_snapshot=child.snapshot_id,
            ordered_ids=[ch.id for ch in reversed(child.chapters)],
        )
    )
    original = domain.branch_get(c.BranchTarget(branch_id=parent.branch_id))
    assert len(original.chapters) == 1 and original.planning == []
    assert original.snapshot_id == parent.snapshot_id
    assert (
        domain.chapter_get(
            c.ChapterTarget(branch_id=parent.branch_id, chapter_id=parent.chapters[0].id)
        ).text
        == "原始正文"
    )


def test_candidate_is_separate_partial_edited_accept_is_idempotent(domain: Domain) -> None:
    w = create(domain)
    task = complete(domain, generate(domain, w))
    assert domain.branch_get(c.BranchTarget(branch_id=w.branch_id)).word_count == 0
    request = accept_request(w, task)
    result = domain.writing_accept(request)
    replay = domain.writing_accept(request)
    assert result.snapshot_id == replay.snapshot_id
    assert result.chapters[0].status == "draft"
    assert (
        domain.chapter_get(c.ChapterTarget(branch_id=w.branch_id, chapter_id=w.chapters[0].id)).text
        == request.edited_text
    )
    with pytest.raises(DomainError, match="已有接纳记录"):
        domain.writing_accept(
            request.model_copy(
                update={"idempotency_key": "other", "expected_snapshot": result.snapshot_id}
            )
        )
    with pytest.raises(DomainError) as error:
        domain.writing_accept(request.model_copy(update={"edited_text": "different"}))
    assert error.value.code == "IDEMPOTENCY_CONFLICT"


def test_planning_change_alone_conflicts_with_accept(domain: Domain) -> None:
    w = create(domain)
    task = complete(domain, generate(domain, w))
    changed = domain.planning_save(
        c.PlanningSave(
            branch_id=w.branch_id,
            expected_snapshot=w.snapshot_id,
            entries=[c.PlanningEntry(id="person", kind="character", title="林舟", text="不再失忆")],
        )
    )
    assert changed.chapters[0].revision == w.chapters[0].revision
    request = accept_request(changed, task)
    with pytest.raises(DomainError) as error:
        domain.writing_accept(request)
    assert error.value.code == "REVISION_CONFLICT"
    assert changed.word_count == 0


def test_cancelled_stream_has_no_further_events_and_partial_can_be_accepted(domain: Domain) -> None:
    w = create(domain)
    task = generate(domain, w)
    events = domain.tick()
    assert events[0]["params"]["seq"] == 1
    stopped = domain.task_cancel(c.TaskTarget(task_id=task.task_id))
    assert domain.tick() == []
    assert domain.task_cancel(c.TaskTarget(task_id=task.task_id)).seq == stopped.seq
    assert stopped.generation and len(stopped.generation.text) == 8
    result = domain.writing_accept(accept_request(w, stopped))
    assert result.word_count > 0


def test_empty_intent_rejected_before_task_creation(domain: Domain) -> None:
    w = create(domain)
    with pytest.raises(DomainError) as error:
        generate(domain, w, " \n ")
    assert error.value.code == "EMPTY_INTENT"
    with domain.db.transaction() as conn:
        assert (
            conn.execute(sa.select(sa.func.count()).select_from(domain.db.tables["tasks"])).scalar()
            == 0
        )


def test_context_separates_future_body_secrets_and_plans(domain: Domain) -> None:
    w = save(domain, create(domain), "第一章的已发生事实😀")
    w = domain.chapter_create(
        c.ChapterCreate(branch_id=w.branch_id, expected_snapshot=w.snapshot_id, title="第二章")
    )
    w = save(domain, w, "第十章身份揭晓：她是女王", 1)
    w = domain.planning_save(
        c.PlanningSave(
            branch_id=w.branch_id,
            expected_snapshot=w.snapshot_id,
            entries=[
                c.PlanningEntry(
                    id="secret",
                    kind="character",
                    title="隐藏身份",
                    text="她是女王",
                    author_only=True,
                ),
                c.PlanningEntry(
                    id="future",
                    kind="outline",
                    title="未来揭示",
                    text="第五章才公开身份",
                    context_role="planned_event",
                ),
            ],
        )
    )
    params = c.ContextRequest(
        branch_id=w.branch_id,
        chapter_id=w.chapters[0].id,
        offset=2,
        context_policy="reader_safe",
        selected_planning_ids=["secret", "future"],
    )
    safe = domain.writing_preview_context(params)
    assert safe.preceding_text == "第一" and safe.planning == []
    author = domain.writing_preview_context(
        params.model_copy(update={"context_policy": "author_plan"})
    )
    assert len(author.planning) == 2 and "女王" not in author.preceding_text
    assert author.planning[1].context_role == "planned_event"
    with pytest.raises(DomainError):
        domain.writing_preview_context(params.model_copy(update={"context_policy": "full_rewrite"}))
    rewrite = domain.writing_preview_context(
        params.model_copy(
            update={"context_policy": "full_rewrite", "rewrite_chapter_ids": [w.chapters[1].id]}
        )
    )
    assert "女王" in rewrite.preceding_text


def test_missing_chapters_and_deleted_disclosure_remain_hidden(domain: Domain) -> None:
    w = create(domain)
    first = w.chapters[0].id
    for _ in range(2):
        w = domain.chapter_create(
            c.ChapterCreate(branch_id=w.branch_id, expected_snapshot=w.snapshot_id)
        )
    w = domain.planning_save(
        c.PlanningSave(
            branch_id=w.branch_id,
            expected_snapshot=w.snapshot_id,
            entries=[
                c.PlanningEntry(
                    id="secret", kind="lore", title="秘密", text="身份", visible_from=first
                )
            ],
        )
    )
    preview = domain.writing_preview_context(
        c.ContextRequest(
            branch_id=w.branch_id,
            chapter_id=w.chapters[2].id,
            offset=0,
            context_policy="reader_safe",
            selected_planning_ids=["secret"],
        )
    )
    assert len(preview.missing_chapter_ids) == 2
    w = domain.chapter_remove(
        c.ChapterRemove(branch_id=w.branch_id, expected_snapshot=w.snapshot_id, chapter_id=first)
    )
    preview = domain.writing_preview_context(
        c.ContextRequest(
            branch_id=w.branch_id,
            chapter_id=w.chapters[-1].id,
            offset=0,
            context_policy="reader_safe",
            selected_planning_ids=["secret"],
        )
    )
    assert preview.planning == []
    assert w.planning[0].visible_from == first


def test_export_excludes_plans_and_unaccepted_candidates(domain: Domain) -> None:
    w = save(domain, create(domain), "正式正文")
    w = domain.planning_save(
        c.PlanningSave(
            branch_id=w.branch_id,
            expected_snapshot=w.snapshot_id,
            entries=[
                c.PlanningEntry(
                    id="secret", kind="lore", title="秘密结局", text="所有人死亡", author_only=True
                )
            ],
        )
    )
    complete(domain, generate(domain, w))
    exported = domain.book_export(c.Export(branch_id=w.branch_id, format="md"))
    assert "正式正文" in exported.content
    assert (
        "秘密" not in exported.content
        and "所有人死亡" not in exported.content
        and "本地演示" not in exported.content
    )


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16", "gb18030"])
def test_txt_encodings_preview_then_confirm(domain: Domain, encoding: str) -> None:
    body = "第一章 雨\r\n林舟来了。😀\r\n第二章 门\r\n门开了。"
    if encoding == "gb18030":
        body = body.replace("😀", "")
    raw = body.encode(encoding)
    preview = domain.book_preview_import(
        c.PreviewImport(
            filename="测试.txt",
            content_b64=base64.b64encode(raw).decode(),
            encoding="gb18030" if encoding == "gb18030" else "auto",
        )
    )
    assert domain.book_list(c.Empty()).books == []
    assert len(preview.chapters) == 2
    result = domain.book_confirm_import(
        c.ConfirmImport(import_id=preview.import_id, title="导入作品")
    )
    assert result.origin_type == "imported"
    assert (
        domain.book_confirm_import(
            c.ConfirmImport(import_id=preview.import_id, title="重复")
        ).book_id
        == result.book_id
    )
    with domain.db.transaction() as conn:
        manifest = domain.row(conn, "imports", preview.import_id)["payload"]
        assert (domain.db.directory / "sources" / manifest["source_hash"]).read_bytes() == raw
        for ch in manifest["chapters"]:
            assert 0 <= ch["byte_start"] < ch["byte_end"] <= len(raw)


def test_snapshot_backup_includes_wal_and_migration_reopen(domain: Domain, tmp_path: Path) -> None:
    w = save(domain, create(domain), "来自 WAL 的新正文")
    destination = tmp_path / "backup"
    destination.mkdir()
    domain.db.backup(destination / "library.db")
    restored = Domain(Storage(destination))
    assert restored.branch_get(c.BranchTarget(branch_id=w.branch_id)).word_count == w.word_count
    assert (
        restored.chapter_get(
            c.ChapterTarget(branch_id=w.branch_id, chapter_id=w.chapters[0].id)
        ).text
        == "来自 WAL 的新正文"
    )
    restored.db.close()


def test_import_preserves_empty_chapters_and_last_heading(domain: Domain) -> None:
    raw = "第一章 空\n第二章 有\n正文\n第三章 空".encode()
    preview = domain.book_preview_import(
        c.PreviewImport(filename="空章.txt", content_b64=base64.b64encode(raw).decode())
    )
    assert len(preview.chapters) == 3
    result = domain.book_confirm_import(
        c.ConfirmImport(import_id=preview.import_id, title="空章作品")
    )
    assert [ch.word_count for ch in result.chapters] == [0, 2, 0]


def test_persisted_task_checkpoint_survives_restart_and_candidate_is_recoverable(
    domain: Domain, tmp_path: Path
) -> None:
    w = create(domain)
    task = generate(domain, w)
    domain.tick()
    before = domain.task_get(c.TaskTarget(task_id=task.task_id))
    restarted = Domain(Storage(tmp_path))
    listed = restarted.task_list(c.Empty()).tasks
    assert listed[0].task_id == task.task_id and listed[0].branch_id == w.branch_id
    assert restarted.task_get(c.TaskTarget(task_id=task.task_id)).seq == before.seq
    final = complete(restarted, task)
    assert final.seq > before.seq and final.status == "completed"
    assert restarted.branch_get(c.BranchTarget(branch_id=w.branch_id)).word_count == 0
    restarted.db.close()


def test_history_restoration_is_new_revision_and_preserves_both_versions(domain: Domain) -> None:
    original = save(domain, create(domain), "原始正文")
    changed = save(domain, original, "修改后的正文")
    changed = domain.chapter_create(
        c.ChapterCreate(branch_id=changed.branch_id, expected_snapshot=changed.snapshot_id)
    )
    restored = domain.branch_restore(
        c.RestoreSnapshot(
            branch_id=changed.branch_id,
            expected_snapshot=changed.snapshot_id,
            snapshot_id=original.snapshot_id,
        )
    )
    assert len(restored.chapters) == 1 and restored.word_count == original.word_count
    assert restored.snapshot_id not in {original.snapshot_id, changed.snapshot_id}
    history = domain.branch_history(c.BranchTarget(branch_id=changed.branch_id))
    assert history.entries[0].snapshot_id == restored.snapshot_id
    assert history.entries[1].snapshot_id == changed.snapshot_id
    other = create(domain)
    with pytest.raises(DomainError):
        domain.branch_restore(
            c.RestoreSnapshot(
                branch_id=restored.branch_id,
                expected_snapshot=restored.snapshot_id,
                snapshot_id=other.snapshot_id,
            )
        )
