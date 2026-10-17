"""AC-32–49: independent storage, bounded calls, visibility and incremental speech.

All identities and text are invented fixtures, never user conversations or credentials.
"""

import asyncio
import copy
import json
import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from test_providers import sse_response, wav

from narravo_engine import contracts as c
from narravo_engine import roleplay_models as r
from narravo_engine.domain import Domain, DomainError
from narravo_engine.providers.models import NetworkSet, ProviderConfig, ProviderSave
from narravo_engine.providers.transport import Transport
from narravo_engine.roleplay.domain import sealed
from narravo_engine.storage import Storage


def character(d: Domain, name: str = "小舟", **overrides: Any) -> r.Character:
    return d.roleplay.character_save(
        r.CharacterSave(
            persona=r.Persona(name=name, introduction="公开简介", personality="谨慎", **overrides)
        )
    )


def setup(d: Domain, count: int = 1, **persona: Any) -> r.ChatView:
    chars = [character(d, name="同名角色", **persona) for _ in range(count)]
    return d.roleplay.create(r.ChatCreate(character_ids=[x.id for x in chars]))


def configure(d: Domain, protocol: str = "openai_chat") -> ProviderConfig:
    config = ProviderConfig(
        id=("b" if protocol == "openai_speech" else "a") * 32,
        name="替身",
        kind="tts" if protocol == "openai_speech" else "llm",
        protocol=protocol,
        base_url="https://provider.example/v1",
        model="fixture-v1",
        voice="stable-voice",
        requires_key=False,
        context_limit=32768,
        max_output_tokens=128,
    )
    d.providers.save(ProviderSave(config=config), False)
    d.providers.network_set(NetworkSet(enabled=True))
    return config


def send(d: Domain, view: r.ChatView, config: ProviderConfig, **kwargs: Any) -> r.Turn:
    return d.roleplay.send(
        r.ChatSend(
            conversation_id=view.id,
            expected_snapshot=view.snapshot_id,
            idempotency_key=kwargs.pop("idempotency_key", "send-" + view.snapshot_id),
            text=kwargs.pop("text", "你好"),
            config_id=config.id,
            **kwargs,
        ),
        "",
    )


async def completed(d: Domain, turn: r.Turn) -> r.Turn:
    worker = d.providers.workers.get(turn.task_id)
    if worker:
        await asyncio.wait_for(asyncio.shield(worker), 5)
    return d.roleplay.turn_get(r.TurnTarget(turn_id=turn.id))


def fake(
    monkeypatch: pytest.MonkeyPatch, seen: list[Any] | None = None, text: str = "你好😀。今天很好！"
) -> None:
    async def stream(
        config: Any, secret: str, messages: Any, transport: Any
    ) -> AsyncIterator[dict[str, Any]]:
        if seen is not None:
            seen.append(copy.deepcopy(messages))
        for word in text:
            yield {"delta": word}
            await asyncio.sleep(0)
        yield {
            "usage": {"prompt_tokens": 30, "completion_tokens": 12},
            "model": "actual-fixture-v1",
        }

    monkeypatch.setattr("narravo_engine.roleplay.domain.generate", stream)


def expected(view: r.ChatView, key: str = "operation") -> dict[str, Any]:
    return {
        "conversation_id": view.id,
        "expected_snapshot": view.snapshot_id,
        "idempotency_key": key,
    }


def test_local_persona_snapshots_and_no_book(domain: Domain) -> None:
    char = character(domain, private_knowledge="虚构秘密", opening="预设问候")
    user = domain.roleplay.character_save(
        r.CharacterSave(kind="user", persona=r.Persona(name="访客", background="虚构用户身份"))
    )
    view = domain.roleplay.create(
        r.ChatCreate(character_ids=[char.id], user_character_id=user.id, scene="灯塔")
    )
    assert view.messages[0].status == "preset"
    updated = domain.roleplay.character_save(
        r.CharacterSave(
            id=char.id,
            expected_revision=char.revision,
            persona=char.persona.model_copy(update={"personality": "开朗"}),
        )
    )
    reopened = domain.roleplay.get(r.ChatTarget(conversation_id=view.id))
    assert reopened.members[0].persona_revision == char.revision != updated.revision
    assert reopened.user_persona_revision == user.revision
    assert domain.book_list(c.Empty()).books == []
    exported = domain.roleplay.export(r.ChatTarget(conversation_id=view.id))
    assert "预设问候" in exported.content and "虚构秘密" not in exported.content
    with pytest.raises(DomainError, match="角色库人设已修改"):
        domain.roleplay.character_save(
            r.CharacterSave(id=char.id, expected_revision=char.revision, persona=char.persona)
        )


def test_real_adapter_path_streams_saves_and_does_not_pollute_book(domain: Domain) -> None:
    async def scenario() -> None:
        cfg = configure(domain)
        seen = []

        def reply(request: httpx.Request) -> httpx.Response:
            seen.append(json.loads(request.content))
            return sse_response(
                [
                    {"choices": [{"delta": {"content": "你好，访客。"}}]},
                    {
                        "choices": [{"delta": {}, "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 40, "completion_tokens": 8},
                    },
                    "[DONE]",
                ]
            )

        domain.providers.transport = Transport(httpx.MockTransport(reply))
        view = setup(domain, private_knowledge="仅我知道")
        turn = await completed(domain, send(domain, view, cfg))
        assert turn.status == "completed" and turn.charges[0].status == "settled"
        reopened = domain.roleplay.get(r.ChatTarget(conversation_id=view.id))
        assert [m.role for m in reopened.messages] == ["user", "assistant"]
        assert reopened.messages[-1].text == "你好，访客。"
        assert len(seen) == 1 and "仅我知道" in seen[0]["messages"][0]["content"]
        assert domain.book_list(c.Empty()).books == []
        await domain.providers.close()

    asyncio.run(scenario())


def test_send_idempotence_and_snapshot_conflict(
    domain: Domain, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake(monkeypatch)

    async def scenario() -> None:
        view, cfg = setup(domain), configure(domain)
        first = send(domain, view, cfg)
        duplicate = send(domain, view, cfg)
        assert first.id == duplicate.id
        await completed(domain, first)
        with pytest.raises(DomainError) as exc:
            send(domain, view, cfg, idempotency_key="different")
        assert exc.value.code == "REVISION_CONFLICT"
        with pytest.raises(DomainError) as exc:
            send(domain, view, cfg, text="changed")
        assert exc.value.code == "IDEMPOTENCY_CONFLICT"

    asyncio.run(scenario())


@pytest.mark.parametrize("count", [2, 4, 8])
def test_all_is_serial_finite_and_stable_ids(
    domain: Domain, monkeypatch: pytest.MonkeyPatch, count: int
) -> None:
    seen: list[Any] = []
    fake(monkeypatch, seen)

    async def scenario() -> None:
        view, cfg = setup(domain, count), configure(domain)
        turn = await completed(domain, send(domain, view, cfg, mode="all"))
        assert turn.status == "completed" and len(turn.messages) == count
        assert turn.completed_members == [m.id for m in view.members]
        assert len(seen) == count and len(turn.charges) == count
        assert len(turn.contexts[0].source_revisions) == 1
        assert len(turn.contexts[-1].source_revisions) == count
        await asyncio.sleep(0.02)
        assert len(seen) == count

    asyncio.run(scenario())


def test_mentions_round_robin_and_muted_members(
    domain: Domain, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake(monkeypatch)

    async def scenario() -> None:
        cfg, view = configure(domain), setup(domain, 3)
        with pytest.raises(DomainError) as exc:
            send(domain, view, cfg)
        assert exc.value.code == "MEMBER_REQUIRED"
        first = await completed(domain, send(domain, view, cfg, mode="round_robin"))
        assert first.queue == [view.members[0].id]
        view = domain.roleplay.get(r.ChatTarget(conversation_id=view.id))
        second = await completed(domain, send(domain, view, cfg, mode="round_robin"))
        assert second.queue == [view.members[1].id]
        view = domain.roleplay.get(r.ChatTarget(conversation_id=view.id))
        members = [m.model_copy(update={"muted": i == 2}) for i, m in enumerate(view.members)]
        view = domain.roleplay.configure(
            r.ChatConfigure(**expected(view), title=view.title, scene=view.scene, members=members)
        )
        with pytest.raises(DomainError) as exc:
            send(domain, view, cfg, member_ids=[view.members[2].id])
        assert exc.value.code == "INVALID_SPEAKER_QUEUE"
        turn = await completed(domain, send(domain, view, cfg, member_ids=[view.members[1].id]))
        assert turn.queue == [view.members[1].id]

    asyncio.run(scenario())


@pytest.mark.parametrize("queue", [[], ["unknown"], ["same", "same"], ["1", "2", "3", "4"]])
def test_invalid_situation_queue_never_guesses(
    domain: Domain, monkeypatch: pytest.MonkeyPatch, queue: list[str]
) -> None:
    fake(monkeypatch, text=json.dumps(queue))

    async def scenario() -> None:
        view, cfg = setup(domain, 3), configure(domain)
        turn = await completed(domain, send(domain, view, cfg, mode="situation"))
        assert turn.status == "failed" and turn.error_code == "INVALID_SPEAKER_QUEUE"
        assert len(turn.charges) == 1 and turn.messages == []

    asyncio.run(scenario())


def test_private_knowledge_selection_and_join_memory_isolation(
    domain: Domain, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[Any] = []
    fake(monkeypatch, seen)

    async def scenario() -> None:
        cfg = configure(domain)
        a = character(domain, "A", private_knowledge="A 私有口令")
        b = character(domain, "B", private_knowledge="B 私有口令")
        view = domain.roleplay.create(r.ChatCreate(character_ids=[a.id, b.id]))
        turn = await completed(domain, send(domain, view, cfg, mode="all", text="加入前消息"))
        assert "A 私有口令" in json.dumps(seen[0], ensure_ascii=False)
        assert "A 私有口令" not in json.dumps(seen[1], ensure_ascii=False)
        assert "B 私有口令" not in json.dumps(seen[0], ensure_ascii=False)
        view = domain.roleplay.get(r.ChatTarget(conversation_id=view.id))
        memory = r.Memory(
            id="memory", text="加入前记忆", source_revisions=[view.messages[0].revision]
        )
        view = domain.roleplay.memory_save(r.MemorySave(**expected(view), memory=memory))
        newcomer = character(domain, "C")
        view = domain.roleplay.configure(
            r.ChatConfigure(
                **expected(view, "add"),
                title=view.title,
                scene=view.scene,
                members=view.members,
                add_character_ids=[newcomer.id],
            )
        )
        preview = domain.roleplay.preview_context(
            r.ChatContextRequest(
                conversation_id=view.id, member_id=view.members[-1].id, config_id=cfg.id
            )
        )
        assert "加入前消息" not in json.dumps(preview.messages, ensure_ascii=False)
        assert "加入前记忆" not in json.dumps(preview.messages, ensure_ascii=False)
        with pytest.raises(DomainError) as exc:
            domain.roleplay.memory_save(
                r.MemorySave(
                    **expected(view, "leak"),
                    memory=memory.model_copy(update={"recipient_ids": [view.members[-1].id]}),
                )
            )
        assert exc.value.code == "INVALID_MEMORY_SOURCE"
        with domain.db.transaction() as conn:
            state = domain.roleplay.state(conn, view.id)
            selection = domain.roleplay.context(
                conn, state, view.members[0].id, cfg, selection=True
            )
        serial = json.dumps(selection.messages, ensure_ascii=False)
        assert "私有口令" not in serial and "加入前消息" not in serial
        other = setup(domain)
        with pytest.raises(DomainError) as exc:
            domain.roleplay.get(
                r.ChatTarget(conversation_id=other.id, snapshot_id=view.snapshot_id)
            )
        assert exc.value.code == "INVALID_SCOPE"
        assert turn.status == "completed"

    asyncio.run(scenario())


def test_history_variants_keep_paths_and_invalidate_memory(
    domain: Domain, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake(monkeypatch, text="第一版本。")

    async def scenario() -> None:
        view, cfg = setup(domain), configure(domain)
        await completed(domain, send(domain, view, cfg))
        view = domain.roleplay.get(r.ChatTarget(conversation_id=view.id))
        original = view.messages[-1]
        old_snapshot = view.snapshot_id
        fake(monkeypatch, text="第二版本。")
        retry = await completed(
            domain,
            send(
                domain,
                view,
                cfg,
                text="",
                retry_revision=original.revision,
                idempotency_key="retry",
            ),
        )
        current = domain.roleplay.get(r.ChatTarget(conversation_id=view.id))
        assert (
            current.snapshot_id == old_snapshot
            and current.messages[-1].revision == original.revision
        )
        variant = retry.messages[0]
        assert variant.id == original.id and variant.revision != original.revision
        current = domain.roleplay.change_history(
            r.HistoryChange(**expected(current), revision=variant.revision, action="select")
        )
        assert current.messages[-1].text == "第二版本。"
        again = domain.roleplay.change_history(
            r.HistoryChange(**expected(view), revision=variant.revision, action="select")
        )
        assert again.snapshot_id == current.snapshot_id
        old = domain.roleplay.get(r.ChatTarget(conversation_id=view.id, snapshot_id=old_snapshot))
        assert old.messages[-1].text == "第一版本。"
        memory = r.Memory(id="x", text="有来源的事实", source_revisions=[variant.revision])
        current = domain.roleplay.memory_save(
            r.MemorySave(**expected(current, "mem"), memory=memory)
        )
        current = domain.roleplay.change_history(
            r.HistoryChange(
                **expected(current, "edit"),
                revision=current.messages[0].revision,
                action="edit",
                text="另一条用户输入",
            )
        )
        assert len(current.messages) == 1 and not current.memories
        preview = domain.roleplay.preview_context(
            r.ChatContextRequest(conversation_id=view.id, member_id=current.members[0].id)
        )
        assert "第二版本" not in json.dumps(preview.messages, ensure_ascii=False)

    asyncio.run(scenario())


def test_incremental_seal_and_first_audio_before_text_done(
    domain: Domain, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        cfg, tts = configure(domain), configure(domain, "openai_speech")
        view = setup(domain)
        gate, sentence = asyncio.Event(), asyncio.Event()

        async def stream(*args: Any) -> AsyncIterator[dict[str, Any]]:
            yield {"delta": "你好😀。"}
            sentence.set()
            await gate.wait()
            yield {"delta": "这是第二句！"}

        monkeypatch.setattr("narravo_engine.roleplay.domain.generate", stream)
        seen = []

        def respond(request: httpx.Request) -> httpx.Response:
            seen.append(json.loads(request.content))
            return httpx.Response(200, content=wav())

        domain.providers.transport = Transport(httpx.MockTransport(respond))
        turn = send(domain, view, cfg, auto_speech=True, tts_config_id=tts.id)
        await sentence.wait()
        turn = domain.roleplay.turn_get(r.TurnTarget(turn_id=turn.id))
        assert len(turn.speech) == 1 and turn.status == "running"
        segment = turn.speech[0].segment
        assert (segment.start, segment.end, segment.text) == (0, 4, "你好😀。")
        domain.roleplay.synthesize(
            r.SpeechRequest(
                turn_id=turn.id,
                config_id=tts.id,
                segment_id=segment.id,
                playback_epoch=turn.playback_epoch,
            ),
            "",
        )
        await asyncio.wait_for(domain.roleplay.speech_workers[turn.id][1], 5)
        ready = domain.roleplay.turn_get(r.TurnTarget(turn_id=turn.id))
        assert ready.speech[0].status == "ready" and ready.status == "running"
        assert list(seen[0]) == ["model", "voice", "input", "response_format"]
        assert seen[0]["input"] == "你好😀。" and seen[0]["voice"] == tts.voice
        gate.set()
        turn = await completed(domain, turn)
        assert "".join(s.segment.text for s in turn.speech) == turn.messages[0].text
        await domain.providers.close()

    asyncio.run(scenario())


def test_seal_does_not_submit_unfinished_tail_or_split_unicode() -> None:
    text = "你好👩‍🚀。后续还没写完"
    pieces = sealed(text, 0)
    assert len(pieces) == 1 and pieces[0][2] == "你好👩‍🚀。"
    tail = sealed(text, pieces[-1][1], final=True)
    assert "".join(v[2] for v in pieces + tail) == text


def test_stop_speech_keeps_text_stop_turn_freezes_partial(
    domain: Domain, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        view, cfg = setup(domain, 2), configure(domain)
        gate, started = asyncio.Event(), asyncio.Event()

        async def stream(*args: Any) -> AsyncIterator[dict[str, Any]]:
            yield {"delta": "未完成句。"}
            started.set()
            await gate.wait()
            yield {"delta": "尾句。"}

        monkeypatch.setattr("narravo_engine.roleplay.domain.generate", stream)
        turn = send(domain, view, cfg, mode="all")
        await started.wait()
        stopped = domain.roleplay.control(r.TurnControl(turn_id=turn.id, action="stop_speech"))
        assert stopped.status == "running" and stopped.speech_stopped
        stopped = domain.roleplay.control(r.TurnControl(turn_id=turn.id, action="stop_turn"))
        assert stopped.status == "cancelled" and len(stopped.messages) == 1
        assert stopped.messages[0].status == "interrupted"
        gate.set()
        await completed(domain, turn)
        view = domain.roleplay.get(r.ChatTarget(conversation_id=view.id))
        assert [m.role for m in view.messages] == ["user"]
        context = domain.roleplay.preview_context(
            r.ChatContextRequest(conversation_id=view.id, member_id=view.members[0].id)
        )
        assert "未完成句" not in json.dumps(context.messages, ensure_ascii=False)
        used = domain.roleplay.change_history(
            r.HistoryChange(
                **expected(view), revision=stopped.messages[0].revision, action="use_interrupted"
            )
        )
        assert used.messages[-1].text == "未完成句。"

    asyncio.run(scenario())


def test_budget_stops_group_and_unknown_usage_stays_reserved(
    domain: Domain, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake(monkeypatch)

    async def scenario() -> None:
        view, cfg = setup(domain, 3), configure(domain)
        turn = await completed(
            domain, send(domain, view, cfg, mode="all", budget=r.Budget(max_requests=1))
        )
        assert turn.status == "failed" and turn.error_code == "BUDGET_EXHAUSTED"
        assert len(turn.completed_members) == 1 and len(turn.charges) == 1
        view = domain.roleplay.get(r.ChatTarget(conversation_id=view.id))
        assert len(view.messages) == 2
        turn = await completed(
            domain, send(domain, view, cfg, mode="all", budget=r.Budget(max_cost=1))
        )
        assert turn.error_code == "BUDGET_PRICE_UNKNOWN" and not turn.charges

    asyncio.run(scenario())


def test_backpressure_cache_and_late_epoch(domain: Domain, monkeypatch: pytest.MonkeyPatch) -> None:
    fake(monkeypatch, text="第一句。第二句。第三句。第四句。")

    async def scenario() -> None:
        cfg, tts = configure(domain), configure(domain, "openai_speech")
        view = setup(domain)
        requests = []

        def respond(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, content=wav())

        domain.providers.transport = Transport(httpx.MockTransport(respond))
        turn = await completed(
            domain, send(domain, view, cfg, auto_speech=True, tts_config_id=tts.id)
        )
        for item in turn.speech[:3]:
            domain.roleplay.synthesize(
                r.SpeechRequest(
                    turn_id=turn.id,
                    config_id=tts.id,
                    segment_id=item.segment.id,
                    playback_epoch=turn.playback_epoch,
                ),
                "",
            )
            await domain.roleplay.speech_workers[turn.id][1]
            await asyncio.sleep(0)
        with pytest.raises(DomainError) as exc:
            domain.roleplay.synthesize(
                r.SpeechRequest(
                    turn_id=turn.id,
                    config_id=tts.id,
                    segment_id=turn.speech[3].segment.id,
                    playback_epoch=turn.playback_epoch,
                ),
                "",
            )
        assert exc.value.code == "SPEECH_BACKPRESSURE" and len(requests) == 3
        domain.roleplay.control(
            r.TurnControl(
                turn_id=turn.id,
                action="played",
                segment_id=turn.speech[0].segment.id,
                playback_epoch=turn.playback_epoch,
            )
        )
        domain.roleplay.synthesize(
            r.SpeechRequest(
                turn_id=turn.id,
                config_id=tts.id,
                segment_id=turn.speech[3].segment.id,
                playback_epoch=turn.playback_epoch,
            ),
            "",
        )
        await domain.roleplay.speech_workers[turn.id][1]
        await asyncio.sleep(0)
        view = domain.roleplay.get(r.ChatTarget(conversation_id=view.id))
        replay = domain.roleplay.playback(
            r.ChatPlayback(
                **expected(view), message_revision=view.messages[-1].revision, tts_config_id=tts.id
            )
        )
        domain.roleplay.synthesize(
            r.SpeechRequest(
                turn_id=replay.id,
                config_id=tts.id,
                segment_id=replay.speech[0].segment.id,
                playback_epoch=replay.playback_epoch,
            ),
            "",
        )
        await domain.roleplay.speech_workers[replay.id][1]
        await asyncio.sleep(0)
        assert len(requests) == 4
        current = domain.roleplay.turn_get(r.TurnTarget(turn_id=replay.id))
        assert current.speech[0].cache_hit
        domain.roleplay.silence(r.ChatTarget(conversation_id=view.id))
        with pytest.raises(DomainError) as exc:
            domain.roleplay.control(
                r.TurnControl(
                    turn_id=replay.id,
                    action="played",
                    segment_id=replay.speech[0].segment.id,
                    playback_epoch=replay.playback_epoch,
                )
            )
        assert exc.value.code == "STALE_PLAYBACK"
        await domain.providers.close()

    asyncio.run(scenario())


def test_context_required_budget_and_scope(domain: Domain) -> None:
    view = setup(domain, background="虚构资料" * 1800)
    cfg = configure(domain)
    cfg = cfg.model_copy(update={"context_limit": 2048})
    with domain.db.transaction() as conn:
        state = domain.roleplay.state(conn, view.id)
        with pytest.raises(DomainError) as exc:
            domain.roleplay.context(conn, state, view.members[0].id, cfg)
    assert exc.value.code == "CONTEXT_BUDGET_EXCEEDED"


def test_0003_upgrade_backup_and_failure_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).parents[1] / "src/narravo_engine/migrations")
    )
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'library.db'}")
    with engine.connect() as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "0003")
        conn.commit()
    original = command.upgrade

    def broken(cfg: Any, target: str) -> None:
        original(cfg, target)
        raise RuntimeError("injected after DDL")

    monkeypatch.setattr(command, "upgrade", broken)
    with pytest.raises(RuntimeError):
        Storage(tmp_path)
    with sqlite3.connect(tmp_path / "library.db") as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone() == ("0003",)
        assert not conn.execute(
            "SELECT name FROM sqlite_master WHERE name='rp_conversations'"
        ).fetchall()
    with sqlite3.connect(tmp_path / "pre-migration.db") as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone() == ("0003",)
    monkeypatch.setattr(command, "upgrade", original)
    storage = Storage(tmp_path)
    with storage.engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT version_num FROM alembic_version").scalar() == "0004"
    storage.close()
    engine.dispose()


def test_stop_speech_only_does_not_prevent_text_commit(
    domain: Domain, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        view, cfg = setup(domain), configure(domain)
        gate, started = asyncio.Event(), asyncio.Event()

        async def stream(*args: Any) -> AsyncIterator[dict[str, Any]]:
            yield {"delta": "第一句。"}
            started.set()
            await gate.wait()
            yield {"delta": "完整尾句。"}

        monkeypatch.setattr("narravo_engine.roleplay.domain.generate", stream)
        turn = send(domain, view, cfg)
        await started.wait()
        domain.roleplay.control(r.TurnControl(turn_id=turn.id, action="stop_speech"))
        gate.set()
        done = await completed(domain, turn)
        assert done.status == "completed" and done.speech_stopped
        assert all(item.status == "stopped" for item in done.speech)
        assert (
            domain.roleplay.get(r.ChatTarget(conversation_id=view.id)).messages[-1].text
            == "第一句。完整尾句。"
        )

    asyncio.run(scenario())


def test_old_stop_cannot_cancel_new_turn_and_skipping_is_bounded(
    domain: Domain, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        cfg, view = configure(domain), setup(domain, 3)
        gate, started = asyncio.Event(), asyncio.Event()

        async def stream(*args: Any) -> AsyncIterator[dict[str, Any]]:
            yield {"delta": "第一句话。"}
            started.set()
            await gate.wait()
            yield {"delta": "尾句。"}

        monkeypatch.setattr("narravo_engine.roleplay.domain.generate", stream)
        first = send(domain, view, cfg, mode="all")
        await started.wait()
        current = domain.roleplay.get(r.ChatTarget(conversation_id=view.id))
        second = send(domain, current, cfg, mode="all", text="新消息", idempotency_key="new")
        domain.roleplay.control(r.TurnControl(turn_id=first.id, action="stop_turn"))
        assert domain.roleplay.turn_get(r.TurnTarget(turn_id=second.id)).status == "running"
        domain.roleplay.control(
            r.TurnControl(turn_id=second.id, action="skip", member_id=view.members[-1].id)
        )
        gate.set()
        done = await completed(domain, second)
        assert done.status == "completed" and len(done.messages) == 2
        assert view.members[-1].id in done.skipped_members
        await domain.providers.close()

    asyncio.run(scenario())


def test_dependency_change_stops_old_turn_preserves_original_personas(
    domain: Domain, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        cfg, view = configure(domain), setup(domain)
        started, gate = asyncio.Event(), asyncio.Event()

        async def stream(*args: Any) -> AsyncIterator[dict[str, Any]]:
            yield {"delta": "旧场景未完成。"}
            started.set()
            await gate.wait()

        monkeypatch.setattr("narravo_engine.roleplay.domain.generate", stream)
        turn = send(domain, view, cfg)
        await started.wait()
        view = domain.roleplay.get(r.ChatTarget(conversation_id=view.id))
        old_snapshot = view.snapshot_id
        updated = domain.roleplay.configure(
            r.ChatConfigure(
                **expected(view), title=view.title, scene="新场景", members=view.members
            )
        )
        gate.set()
        await completed(domain, turn)
        assert updated.scene == "新场景"
        now = domain.roleplay.get(r.ChatTarget(conversation_id=view.id))
        assert now.snapshot_id == updated.snapshot_id and len(now.messages) == 1
        before = domain.roleplay.get(
            r.ChatTarget(conversation_id=view.id, snapshot_id=old_snapshot)
        )
        assert before.scene != now.scene

    asyncio.run(scenario())


def test_tts_failure_does_not_break_text_and_late_result_cannot_become_ready(
    domain: Domain, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake(monkeypatch)

    async def scenario() -> None:
        cfg, tts = configure(domain), configure(domain, "openai_speech")
        view = setup(domain)
        turn = await completed(
            domain, send(domain, view, cfg, tts_config_id=tts.id, auto_speech=True)
        )
        gate, started = asyncio.Event(), asyncio.Event()

        async def late(*args: Any, **kwargs: Any) -> Any:
            started.set()
            try:
                await gate.wait()
            except asyncio.CancelledError:
                pass  # A non-cooperative remote result must still be rejected at commit.
            return __import__(
                "narravo_engine.providers.models", fromlist=["AudioSegment"]
            ).AudioSegment(asset_id="c" * 32, start=0, end=4, duration=0.1, mime_type="audio/wav")

        monkeypatch.setattr(domain.providers, "cached_audio", late)
        segment = turn.speech[0].segment
        domain.roleplay.synthesize(
            r.SpeechRequest(
                turn_id=turn.id,
                config_id=tts.id,
                segment_id=segment.id,
                playback_epoch=turn.playback_epoch,
            ),
            "",
        )
        worker = domain.roleplay.speech_workers[turn.id][1]
        await started.wait()
        domain.roleplay.silence(r.ChatTarget(conversation_id=view.id))
        gate.set()
        await worker
        now = domain.roleplay.turn_get(r.TurnTarget(turn_id=turn.id))
        assert (
            now.status == "completed"
            and now.speech[0].status == "stopped"
            and now.speech[0].asset_id is None
        )
        assert len(domain.roleplay.get(r.ChatTarget(conversation_id=view.id)).messages) == 2

    asyncio.run(scenario())


def test_http_tts_failure_retains_complete_chat(
    domain: Domain, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake(monkeypatch)

    async def scenario() -> None:
        cfg, tts = configure(domain), configure(domain, "openai_speech")
        domain.providers.transport = Transport(
            httpx.MockTransport(
                lambda _: httpx.Response(401, json={"error": "secret fixture failure"})
            )
        )
        view = setup(domain)
        turn = await completed(domain, send(domain, view, cfg, tts_config_id=tts.id))
        domain.roleplay.synthesize(
            r.SpeechRequest(
                turn_id=turn.id,
                config_id=tts.id,
                segment_id=turn.speech[0].segment.id,
                playback_epoch=turn.playback_epoch,
            ),
            "",
        )
        await domain.roleplay.speech_workers[turn.id][1]
        now = domain.roleplay.turn_get(r.TurnTarget(turn_id=turn.id))
        assert now.status == "completed" and now.speech[0].status == "failed"
        assert len(now.charges) == 2 and now.charges[-1].status == "unknown"
        assert "secret fixture failure" not in (now.speech[0].error or "")
        await domain.providers.close()

    asyncio.run(scenario())


def test_restart_keeps_partial_and_unknown_ledger_without_replay(
    domain: Domain, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def scenario() -> None:
        cfg, view = configure(domain), setup(domain)
        gate, started = asyncio.Event(), asyncio.Event()
        calls = []

        async def stream(*args: Any) -> AsyncIterator[dict[str, Any]]:
            calls.append(1)
            yield {"delta": "中断前保存的文字。"}
            started.set()
            await gate.wait()

        monkeypatch.setattr("narravo_engine.roleplay.domain.generate", stream)
        turn = send(domain, view, cfg)
        await started.wait()
        recovered_dir = tmp_path / "simulated-crash"
        recovered_dir.mkdir()
        domain.db.backup(recovered_dir / "library.db")
        recovered = Domain(Storage(recovered_dir))
        restored = recovered.roleplay.get(r.ChatTarget(conversation_id=view.id))
        assert (
            restored.turns[0].status == "failed"
            and restored.turns[0].error_code == "UNKNOWN_OUTCOME"
        )
        assert restored.turns[0].messages[0].status == "interrupted"
        assert restored.turns[0].charges[0].status == "unknown"
        assert restored.turns[0].speech_stopped and not recovered.providers.workers
        assert len(calls) == 1
        assert len(restored.messages) == 1
        recovered.db.close()
        domain.roleplay.control(r.TurnControl(turn_id=turn.id, action="stop_turn"))
        gate.set()
        await completed(domain, turn)

    asyncio.run(scenario())


@pytest.mark.parametrize("include_audio", [False, True])
def test_complete_backup_roleplay_variants_memory_audio_and_no_configs(
    domain: Domain, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, include_audio: bool
) -> None:
    from narravo_engine.backup import create_backup, prepare_restore

    fake(monkeypatch)

    async def scenario() -> None:
        cfg, tts = configure(domain), configure(domain, "openai_speech")
        domain.providers.transport = Transport(
            httpx.MockTransport(lambda _: httpx.Response(200, content=wav()))
        )
        view = setup(domain, private_knowledge="需保留的虚构私人设定")
        turn = await completed(domain, send(domain, view, cfg, tts_config_id=tts.id))
        domain.roleplay.synthesize(
            r.SpeechRequest(
                turn_id=turn.id,
                config_id=tts.id,
                segment_id=turn.speech[0].segment.id,
                playback_epoch=turn.playback_epoch,
            ),
            "",
        )
        await domain.roleplay.speech_workers[turn.id][1]
        await asyncio.sleep(0)
        view = domain.roleplay.get(r.ChatTarget(conversation_id=view.id))
        reply = view.messages[-1]
        await completed(
            domain,
            send(
                domain, view, cfg, text="", retry_revision=reply.revision, idempotency_key="retry"
            ),
        )
        view = domain.roleplay.get(r.ChatTarget(conversation_id=view.id))
        view = domain.roleplay.memory_save(
            r.MemorySave(
                **expected(view),
                memory=r.Memory(id="m", text="虚构记忆", source_revisions=[reply.revision]),
            )
        )
        output = tmp_path / "backup.narravo"
        create_backup(domain.db.directory, output, tmp_path / "work", include_audio)
        restored_dir = tmp_path / "restored"
        prepare_restore(output, restored_dir, domain.db.path)
        restored = Domain(Storage(restored_dir))
        result = restored.roleplay.get(r.ChatTarget(conversation_id=view.id))
        assert (
            result.messages == view.messages
            and len(result.variants) == 1
            and len(result.memories) == 1
        )
        assert (
            restored.providers.provider_list(None).providers == []
            and not restored.providers.provider_list(None).external_enabled
        )
        assert result.turns[0].speech_stopped and result.turns[0].speech[0].status == "stopped"
        assert bool(result.turns[0].speech[0].asset_id) == include_audio
        assert not restored.providers.workers
        restored.db.close()
        await domain.providers.close()

    asyncio.run(scenario())


def test_backup_running_draft_is_frozen_and_reference_tamper_rejected(
    domain: Domain, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from narravo_engine.backup import create_backup, prepare_restore, validate_database

    async def scenario() -> None:
        cfg, view = configure(domain), setup(domain)
        started, gate = asyncio.Event(), asyncio.Event()

        async def stream(*args: Any) -> AsyncIterator[dict[str, Any]]:
            yield {"delta": "尚未结束。"}
            started.set()
            await gate.wait()

        monkeypatch.setattr("narravo_engine.roleplay.domain.generate", stream)
        turn = send(domain, view, cfg)
        await started.wait()
        output = tmp_path / "backup.narravo"
        create_backup(domain.db.directory, output, tmp_path / "work", False)
        destination = tmp_path / "restored"
        prepare_restore(output, destination, domain.db.path)
        with sqlite3.connect(destination / "library.db") as conn:
            payload = json.loads(conn.execute("SELECT payload FROM rp_turns").fetchone()[0])
            assert (
                payload["messages"][0]["status"] == "interrupted" and payload["status"] == "failed"
            )
            message_id = payload["messages"][0]["revision"]
            conn.execute("DELETE FROM rp_messages WHERE id=?", (message_id,))
            conn.commit()
        with pytest.raises(DomainError):
            validate_database(
                destination / "library.db",
                domain.db.path,
                {"schema_version": "0004", "book_count": 0, "include_audio": False, "files": {}},
                destination,
            )
        domain.roleplay.control(r.TurnControl(turn_id=turn.id, action="stop_turn"))
        gate.set()
        await completed(domain, turn)

    asyncio.run(scenario())


def test_character_copy_filters_author_secrets_and_is_independent(domain: Domain) -> None:
    workspace = domain.book_create(c.BookCreate(title="自创测试作品"))
    ch = workspace.chapters[0]
    workspace = domain.planning_save(
        c.PlanningSave(
            branch_id=workspace.branch_id,
            expected_snapshot=workspace.snapshot_id,
            entries=[
                c.PlanningEntry(
                    id="fictional-character",
                    kind="character",
                    title="旅人",
                    text="尚未披露的虚构身份",
                    author_only=True,
                )
            ],
        )
    )
    params = {
        "branch_id": workspace.branch_id,
        "expected_snapshot": workspace.snapshot_id,
        "chapter_id": ch.id,
        "offset": 0,
        "planning_id": "fictional-character",
    }
    with pytest.raises(DomainError) as exc:
        domain.roleplay.copy_book_character(r.BookCharacterCopy(**params))
    assert exc.value.code == "CHARACTER_NOT_VISIBLE"
    preview = domain.roleplay.copy_book_character(
        r.BookCharacterCopy(**params, include_author=True)
    )
    assert "包含作者资料" in preview.warning and preview.character is None
    result = domain.roleplay.copy_book_character(
        r.BookCharacterCopy(**params, include_author=True, confirm=True)
    )
    assert result.character and result.character.source
    view = domain.roleplay.create(r.ChatCreate(character_ids=[result.character.id]))
    context = domain.roleplay.preview_context(
        r.ChatContextRequest(conversation_id=view.id, member_id=view.members[0].id)
    )
    assert "尚未披露的虚构身份" in json.dumps(context.messages, ensure_ascii=False)
    assert (
        domain.branch_get(c.BranchTarget(branch_id=workspace.branch_id)).snapshot_id
        == workspace.snapshot_id
    )


def test_minimax_opt_in_expression_stable_voice_and_cache_fingerprint(
    domain: Domain, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake(monkeypatch, text="我陪着你。")

    async def scenario() -> None:
        cfg = configure(domain)
        tts = ProviderConfig(
            id="b" * 32,
            name="虚构 MiniMax",
            kind="tts",
            protocol="minimax_speech",
            base_url="https://provider.example/v1",
            model="speech-2.6-hd",
            voice="fixture-voice",
            requires_key=False,
            speech_expression=True,
        )
        domain.providers.save(ProviderSave(config=tts), False)
        seen = []

        def respond(request: httpx.Request) -> httpx.Response:
            seen.append(json.loads(request.content))
            return httpx.Response(200, json={"data": {"audio": wav().hex(), "status": 2}})

        domain.providers.transport = Transport(httpx.MockTransport(respond))
        view = setup(
            domain, voice=r.Voice(config_id=tts.id, voice=tts.voice, emotion="angry", speed=0.9)
        )
        turn = await completed(domain, send(domain, view, cfg, tts_config_id=tts.id))
        segment = turn.speech[0].segment
        assert (
            segment.requested_emotion == segment.effective_emotion == "angry"
            and segment.effective_speed == 0.9
        )
        domain.roleplay.synthesize(
            r.SpeechRequest(
                turn_id=turn.id,
                config_id=tts.id,
                segment_id=segment.id,
                playback_epoch=turn.playback_epoch,
            ),
            "",
        )
        await domain.roleplay.speech_workers[turn.id][1]
        await asyncio.sleep(0)
        assert (
            seen[0]["voice_setting"]["emotion"] == "angry"
            and seen[0]["voice_setting"]["speed"] == 0.9
            and seen[0]["voice_setting"]["voice_id"] == tts.voice
        )
        view = domain.roleplay.get(r.ChatTarget(conversation_id=view.id))
        replay = domain.roleplay.playback(
            r.ChatPlayback(
                **expected(view),
                message_revision=view.messages[-1].revision,
                tts_config_id=tts.id,
                voice=r.Voice(voice=tts.voice, emotion="sad"),
            )
        )
        domain.roleplay.synthesize(
            r.SpeechRequest(
                turn_id=replay.id,
                config_id=tts.id,
                segment_id=replay.speech[0].segment.id,
                playback_epoch=replay.playback_epoch,
            ),
            "",
        )
        await domain.roleplay.speech_workers[replay.id][1]
        assert len(seen) == 2 and seen[-1]["voice_setting"]["emotion"] == "sad"
        await domain.providers.close()

    asyncio.run(scenario())


def test_shared_budget_reservation_is_transactional(domain: Domain) -> None:
    from concurrent.futures import ThreadPoolExecutor

    configure(domain)
    view = setup(domain)
    with domain.db.transaction() as conn:
        turn = domain.roleplay.new_turn(
            conn,
            domain.roleplay.state(conn, view.id),
            r.Budget(
                max_requests=1,
                max_tokens=512,
                max_cost=0.001,
                input_per_million=10,
                output_per_million=10,
                price_source="fixture rate",
                price_date="2026-10-17",
            ),
            auto=False,
        )

    def reserve(_: int) -> str:
        try:
            domain.roleplay.reserve(turn["id"], "reply", 50, 50)
            return "reserved"
        except DomainError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = list(executor.map(reserve, range(8)))
    assert outcomes.count("reserved") == 1 and outcomes.count("BUDGET_EXHAUSTED") == 7
    saved = domain.roleplay.turn_get(r.TurnTarget(turn_id=turn["id"]))
    assert len(saved.charges) == 1 and saved.charges[0].reserved_cost == 0.001


def test_user_identity_stays_pinned_until_explicit_application(domain: Domain) -> None:
    char = character(domain)
    user = domain.roleplay.character_save(
        r.CharacterSave(kind="user", persona=r.Persona(name="旧身份", background="虚构背景"))
    )
    view = domain.roleplay.create(r.ChatCreate(character_ids=[char.id], user_character_id=user.id))
    updated = domain.roleplay.character_save(
        r.CharacterSave(
            id=user.id,
            expected_revision=user.revision,
            kind="user",
            persona=user.persona.model_copy(update={"name": "新身份"}),
        )
    )
    view = domain.roleplay.configure(
        r.ChatConfigure(
            **expected(view),
            title=view.title,
            scene="仅改场景",
            members=view.members,
            user_character_id=user.id,
        )
    )
    assert view.user_persona_revision == user.revision
    view = domain.roleplay.configure(
        r.ChatConfigure(
            **expected(view, "apply"),
            title=view.title,
            scene=view.scene,
            members=view.members,
            user_character_id=user.id,
            user_persona_revision=updated.revision,
        )
    )
    assert view.user_persona_revision == updated.revision


def test_missing_tts_config_does_not_prevent_text_chat(
    domain: Domain, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake(monkeypatch)

    async def scenario() -> None:
        cfg, view = (
            configure(domain),
            setup(domain, voice=r.Voice(config_id="f" * 32, voice="old-voice")),
        )
        turn = await completed(
            domain, send(domain, view, cfg, tts_config_id="e" * 32, auto_speech=True)
        )
        assert turn.status == "completed" and len(turn.charges) == 1
        assert len(domain.roleplay.get(r.ChatTarget(conversation_id=view.id)).messages) == 2

    asyncio.run(scenario())


def test_explicit_truncation_is_interrupted_not_history(
    domain: Domain, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        async def stream(*args: Any) -> AsyncIterator[dict[str, Any]]:
            yield {"delta": "还没说完"}
            yield {"finish_reason": "length"}

        monkeypatch.setattr("narravo_engine.roleplay.domain.generate", stream)
        cfg, view = configure(domain), setup(domain)
        turn = await completed(domain, send(domain, view, cfg))
        assert turn.error_code == "OUTPUT_LIMIT" and turn.messages[0].status == "interrupted"
        assert len(domain.roleplay.get(r.ChatTarget(conversation_id=view.id)).messages) == 1
        assert not turn.speech

    asyncio.run(scenario())


def test_single_sentence_override_and_first_speaker_scope(
    domain: Domain, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake(monkeypatch, text="第一句。第二句。")

    async def scenario() -> None:
        cfg, tts = configure(domain), configure(domain, "openai_speech")
        view = setup(domain, 2)
        turn = await completed(
            domain,
            send(
                domain,
                view,
                cfg,
                mode="all",
                auto_speech=True,
                speech_scope="first",
                tts_config_id=tts.id,
            ),
        )
        assert [s.status for s in turn.speech] == ["pending", "pending", "stopped", "stopped"]
        view = domain.roleplay.get(r.ChatTarget(conversation_id=view.id))
        sentence = turn.speech[-1].segment
        replay = domain.roleplay.playback(
            r.ChatPlayback(
                **expected(view),
                message_revision=view.messages[-1].revision,
                source_segment_id=sentence.id,
                tts_config_id=tts.id,
                voice=r.Voice(emotion="whisper"),
            )
        )
        assert len(replay.speech) == 1 and replay.speech[0].segment.start == sentence.start
        assert (
            replay.speech[0].segment.requested_emotion == "whisper"
            and replay.speech[0].segment.effective_emotion == "neutral"
        )
        assert "回退" in replay.speech[0].segment.warning

    asyncio.run(scenario())


def test_avatar_local_bounded_png_never_sent_to_llm(domain: Domain) -> None:
    import base64
    import struct
    import zlib

    from pydantic import ValidationError

    def chunk(name: bytes, raw: bytes) -> bytes:
        return len(raw).to_bytes(4) + name + raw + zlib.crc32(name + raw).to_bytes(4)

    raw = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00"))
        + chunk(b"IEND", b"")
    )
    avatar = "data:image/png;base64," + base64.b64encode(raw).decode()
    view = setup(domain, avatar=avatar)
    preview = domain.roleplay.preview_context(
        r.ChatContextRequest(conversation_id=view.id, member_id=view.members[0].id)
    )
    assert avatar not in json.dumps(preview.messages)
    for invalid in [
        "https://example.com/avatar.png",
        "data:image/svg+xml;base64,PHN2Zy8+",
        avatar[:-8],
    ]:
        with pytest.raises((ValidationError, ValueError)):
            r.Persona(name="头像", avatar=invalid)


def test_user_private_identity_is_not_injected_into_speaker_selection(domain: Domain) -> None:
    char = character(domain)
    user = domain.roleplay.character_save(
        r.CharacterSave(
            kind="user",
            persona=r.Persona(
                name="旅客",
                introduction="公开身份",
                background="所选共享背景",
                private_knowledge="用户自己的秘密",
            ),
        )
    )
    view = domain.roleplay.create(r.ChatCreate(character_ids=[char.id], user_character_id=user.id))
    with domain.db.transaction() as conn:
        state = domain.roleplay.state(conn, view.id)
        selection = domain.roleplay.context(conn, state, view.members[0].id, selection=True)
        reply = domain.roleplay.context(conn, state, view.members[0].id)
    assert "所选共享背景" not in json.dumps(selection.messages, ensure_ascii=False)
    assert "所选共享背景" in json.dumps(reply.messages, ensure_ascii=False)
    assert "用户自己的秘密" not in json.dumps(
        selection.messages + reply.messages, ensure_ascii=False
    )


def test_manual_action_segment_can_be_skipped_or_explicitly_spoken(
    domain: Domain, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake(monkeypatch)

    async def scenario() -> None:
        cfg, tts = configure(domain), configure(domain, "openai_speech")
        view = setup(domain)
        await completed(domain, send(domain, view, cfg))
        view = domain.roleplay.get(r.ChatTarget(conversation_id=view.id))
        view = domain.roleplay.change_history(
            r.HistoryChange(
                **expected(view),
                revision=view.messages[-1].revision,
                action="edit",
                text="他望着远处的灯。",
                kind="action",
            )
        )
        skipped = domain.roleplay.playback(
            r.ChatPlayback(
                **expected(view, "skip-action"),
                message_revision=view.messages[-1].revision,
                tts_config_id=tts.id,
            )
        )
        assert all(
            item.status == "stopped" and item.segment.kind == "action" for item in skipped.speech
        )
        assert not skipped.charges
        spoken = domain.roleplay.playback(
            r.ChatPlayback(
                **expected(view, "speak-action"),
                message_revision=view.messages[-1].revision,
                tts_config_id=tts.id,
                include_actions=True,
            )
        )
        assert all(
            item.status == "pending" and item.segment.kind == "action" for item in spoken.speech
        )

    asyncio.run(scenario())


def test_provider_voice_change_stops_dependent_round_before_later_sentences(
    domain: Domain, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        cfg, tts = configure(domain), configure(domain, "openai_speech")
        view = setup(domain, voice=r.Voice(config_id=tts.id, voice=tts.voice))
        gate, started = asyncio.Event(), asyncio.Event()

        async def stream(*args: Any) -> AsyncIterator[dict[str, Any]]:
            yield {"delta": "旧声音计划。"}
            started.set()
            await gate.wait()
            yield {"delta": "不应使用新模型合成。"}

        monkeypatch.setattr("narravo_engine.roleplay.domain.generate", stream)
        turn = send(domain, view, cfg, auto_speech=True)
        await started.wait()
        domain.providers.save(
            ProviderSave(config=tts.model_copy(update={"model": "changed-fixture-model"})), False
        )
        gate.set()
        result = await completed(domain, turn)
        assert result.status == "cancelled" and result.speech_stopped
        assert (
            result.messages[0].status == "interrupted"
            and "不应使用新模型" not in result.messages[0].text
        )
        assert all(item.status == "stopped" for item in result.speech)

    asyncio.run(scenario())


def test_model_markup_is_retained_as_data_and_not_submitted_as_speech(
    domain: Domain, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake(monkeypatch, text='<script>fetch("https://untrusted.invalid")</script>。')

    async def scenario() -> None:
        cfg, tts = configure(domain), configure(domain, "openai_speech")
        view = setup(domain, private_knowledge="读取任意文件是虚构设定，不能授予权限")
        turn = await completed(domain, send(domain, view, cfg, tts_config_id=tts.id))
        assert turn.status == "completed" and "<script>" in turn.messages[0].text
        with pytest.raises(DomainError) as exc:
            domain.roleplay.synthesize(
                r.SpeechRequest(
                    turn_id=turn.id,
                    config_id=tts.id,
                    segment_id=turn.speech[0].segment.id,
                    playback_epoch=turn.playback_epoch,
                ),
                "",
            )
        assert exc.value.code == "UNSAFE_SPEECH_MARKUP"
        assert len(domain.roleplay.turn_get(r.TurnTarget(turn_id=turn.id)).charges) == 1
        assert not domain.book_list(c.Empty()).books

    asyncio.run(scenario())
