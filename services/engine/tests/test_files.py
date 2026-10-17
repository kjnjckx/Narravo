import asyncio
import base64
import hashlib
import io
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from narravo_engine import contracts as c
from narravo_engine.archive import inspect_zip
from narravo_engine.backup import create_backup, prepare_restore
from narravo_engine.domain import Domain, DomainError
from narravo_engine.importers import epub
from narravo_engine.storage import Storage


def epub_bytes(*, malicious: str | None = None, ncx: bool = False) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr(
            "META-INF/container.xml",
            '<container><rootfiles><rootfile full-path="OPS/book.opf"/></rootfiles></container>',
        )
        archive.writestr(
            "OPS/book.opf",
            f'''<package><metadata><title>倒序测试</title><creator>叙声测试</creator></metadata>
        <manifest><item id="a" href="Text/a.xhtml" media-type="application/xhtml+xml"/>
        <item id="b" href="Text/b.xhtml" media-type="application/xhtml+xml"/>
        <item id="nav" href="{"toc.ncx" if ncx else "nav.xhtml"}" media-type="{"application/x-dtbncx+xml" if ncx else "application/xhtml+xml"}" properties="{" " if ncx else "nav"}"/></manifest>
        <spine><itemref idref="b"/><itemref idref="a"/></spine></package>''',
        )
        if ncx:
            archive.writestr(
                "OPS/toc.ncx",
                '<ncx><navMap><navPoint><navLabel><text>目录标题</text></navLabel><content src="Text/b.xhtml"/></navPoint></navMap></ncx>',
            )
        else:
            archive.writestr(
                "OPS/nav.xhtml",
                '<html><body><nav><a href="Text/b.xhtml#start">目录标题</a></nav></body></html>',
            )
        archive.writestr(
            "OPS/Text/b.xhtml",
            '<!DOCTYPE html><html><body><h1>第一章</h1><p id="start">雨停了。😀</p><script>窃取密钥</script><style>hide</style><iframe src="http://localhost">bad</iframe></body></html>',
        )
        archive.writestr(
            "OPS/Text/a.xhtml", "<html><body><h1>第二章</h1><p>门开了。</p></body></html>"
        )
        if malicious:
            archive.writestr(malicious, "unsafe")
    return stream.getvalue()


def pdf_bytes(*, blank: bool = False, mixed: bool = False, password: str = "") -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    if not blank:
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
        )
        content = DecodedStreamObject()
        content.set_data(b"BT /F1 12 Tf 50 700 Td (The door opened.) Tj ET")
        page[NameObject("/Contents")] = writer._add_object(content)
    if mixed:
        writer.add_blank_page(width=600, height=800)
    if password:
        writer.encrypt(password)
    stream = io.BytesIO()
    writer.write(stream)
    return stream.getvalue()


async def wait_operation(domain: Domain, operation: c.FileOperation) -> c.FileOperation:
    async with asyncio.timeout(25):
        while operation.status == "running":
            await asyncio.sleep(0.02)
            operation = domain.files.file_get(
                c.OperationTarget(operation_id=operation.operation_id)
            )
    return operation


def import_file(domain: Domain, filename: str, raw: bytes, password: str = "") -> c.FileOperation:
    async def run() -> c.FileOperation:
        operation = domain.files.file_start_import(
            c.PreviewImport(
                filename=filename, content_b64=base64.b64encode(raw).decode(), password=password
            )
        )
        return await wait_operation(domain, operation)

    return asyncio.run(run())


@pytest.mark.parametrize("ncx", [False, True])
def test_epub_spine_navigation_and_sanitization(ncx: bool) -> None:
    parsed = epub(epub_bytes(ncx=ncx))
    assert parsed["metadata"] == {"title": "倒序测试", "creator": "叙声测试"}
    assert parsed["sections"][0]["title"] == "目录标题"
    assert "雨停了。😀" in parsed["sections"][0]["text"]
    assert "门开了" in parsed["sections"][1]["text"]
    assert "窃取" not in str(parsed["sections"])
    assert parsed["sections"][0]["source_locator"]["resource"] == "OPS/Text/b.xhtml"


@pytest.mark.parametrize(
    "name", ["../outside", "/absolute", "OPS/../../outside", "C:/book", "OPS\\outside"]
)
def test_epub_rejects_unsafe_paths(name: str) -> None:
    with pytest.raises(DomainError, match="不安全路径"):
        epub(epub_bytes(malicious=name))


def test_zip_bomb_and_symlink() -> None:
    for symlink in [False, True]:
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            if symlink:
                entry = zipfile.ZipInfo("link")
                entry.create_system = 3
                entry.external_attr = 0o120777 << 16
                archive.writestr(entry, "/tmp/escape")
            else:
                archive.writestr("bomb", b"a" * 2_000_000)
        with zipfile.ZipFile(stream) as archive, pytest.raises(DomainError):
            inspect_zip(archive)


def test_epub_entity_and_missing_spine_resource() -> None:
    for old, new in [
        (b"<!DOCTYPE html>", b'<!DOCTYPE html [<!ENTITY leak SYSTEM "file:///etc/passwd">]>'),
        (b'<itemref idref="b"/>', b'<itemref idref="missing"/>'),
    ]:
        source = zipfile.ZipFile(io.BytesIO(epub_bytes()))
        stream = io.BytesIO()
        with source, zipfile.ZipFile(stream, "w") as target:
            for name in source.namelist():
                target.writestr(name, source.read(name).replace(old, new))
        with pytest.raises(DomainError):
            epub(stream.getvalue())


def test_epub_preview_confirm_and_original_bytes(domain: Domain) -> None:
    raw = epub_bytes()
    operation = import_file(domain, "story.epub", raw)
    assert operation.status == "completed", operation.message
    assert operation.preview
    assert not domain.book_list(c.Empty()).books
    workspace = domain.book_confirm_import(
        c.ConfirmImport(import_id=operation.preview.import_id, title="导入测试")
    )
    assert workspace.origin_type == "imported"
    assert len(workspace.chapters) == 2
    assert (domain.db.directory / "sources" / hashlib.sha256(raw).hexdigest()).read_bytes() == raw


def test_pdf_text_scanned_mixed_and_password(domain: Domain) -> None:
    operation = import_file(domain, "text.pdf", pdf_bytes())
    assert operation.status == "completed", operation.message
    assert operation.preview and "The door opened." in operation.preview.sample
    scanned = import_file(domain, "scanned.pdf", pdf_bytes(blank=True))
    assert scanned.status == "failed" and scanned.error_code == "OCR_REQUIRED"
    mixed = import_file(domain, "mixed.pdf", pdf_bytes(mixed=True))
    assert mixed.preview and mixed.preview.omitted_pages == [2]
    with pytest.raises(DomainError) as exc:
        domain.book_confirm_import(c.ConfirmImport(import_id=mixed.preview.import_id, title="混合"))
    assert exc.value.code == "INCOMPLETE_IMPORT"
    workspace = domain.book_confirm_import(
        c.ConfirmImport(import_id=mixed.preview.import_id, title="混合", accept_incomplete=True)
    )
    assert len(workspace.chapters) == 1
    for password, expected in [
        ("", "PDF_PASSWORD_REQUIRED"),
        ("wrong", "PDF_PASSWORD_INVALID"),
        ("secret", None),
    ]:
        result = import_file(domain, "encrypted.pdf", pdf_bytes(password="secret"), password)
        assert result.error_code == expected, result.message
    assert "secret" not in "".join(p.read_text() for p in domain.files.records.glob("*.json"))
    broken = import_file(domain, "broken.pdf", b"not a pdf")
    assert broken.status == "failed" and broken.error_code == "INVALID_PDF"


def seed_library(domain: Domain) -> c.Workspace:
    workspace = domain.book_create(c.BookCreate(title="空作品也合法"))
    workspace = domain.planning_save(
        c.PlanningSave(
            branch_id=workspace.branch_id,
            expected_snapshot=workspace.snapshot_id,
            entries=[
                c.PlanningEntry(
                    id="secret", kind="lore", title="秘密", text="最后的真相", author_only=True
                )
            ],
        )
    )
    fork = domain.branch_fork(
        c.BranchFork(
            branch_id=workspace.branch_id, expected_snapshot=workspace.snapshot_id, name="支线"
        )
    )
    domain.chapter_save(
        c.ChapterSave(
            branch_id=fork.branch_id,
            chapter_id=fork.chapters[0].id,
            expected_snapshot=fork.snapshot_id,
            text="支线正文😀",
        )
    )
    task = domain.writing_generate(
        c.Generate(
            branch_id=workspace.branch_id,
            chapter_id=workspace.chapters[0].id,
            offset=0,
            expected_snapshot=workspace.snapshot_id,
            intent="写一阵雨",
            context_policy="author_plan",
            provider="demo",
        )
    )
    for _ in range(200):
        domain.tick()
    task = domain.task_get(c.TaskTarget(task_id=task.task_id))
    assert task.generation
    return domain.writing_accept(
        c.Accept(
            generation_id=task.generation.id,
            expected_snapshot=workspace.snapshot_id,
            candidate_revision=task.generation.candidate_revision,
            start=0,
            end=2,
            edited_text="雨停了",
            idempotency_key="test-decision",
        )
    )


def test_full_backup_restores_empty_book_planning_history_decisions_and_sources(
    domain: Domain, tmp_path: Path
) -> None:
    workspace = seed_library(domain)
    domain.book_create(c.BookCreate(title="完全空白"))
    imported = domain.book_preview_import(
        c.PreviewImport(
            filename="original.txt", content_b64=base64.b64encode("正文".encode()).decode()
        )
    )
    domain.book_confirm_import(c.ConfirmImport(import_id=imported.import_id, title="导入书"))
    backup = tmp_path / "backup.narravo"
    create_backup(domain.db.directory, backup, tmp_path / "work", False)
    restored_dir = tmp_path / "restored"
    info = prepare_restore(backup, restored_dir, domain.db.path)
    assert info["book_count"] == 3
    restored = Domain(Storage(restored_dir))
    try:
        actual = restored.branch_get(c.BranchTarget(branch_id=workspace.branch_id))
        assert actual == workspace
        assert len(actual.branches) == 2
        assert actual.planning[0].text == "最后的真相"
        assert len(restored.branch_history(c.BranchTarget(branch_id=actual.branch_id)).entries) >= 2
        with restored.db.transaction() as conn:
            assert conn.exec_driver_sql("SELECT COUNT(*) FROM decisions").scalar() == 1
            assert conn.exec_driver_sql("SELECT COUNT(*) FROM providers").scalar() == 0
        assert not restored.providers.provider_list(c.Empty()).external_enabled
        assert (restored_dir / "sources").is_dir()
    finally:
        restored.db.close()


def test_backup_validated_before_atomic_activation_and_restart(domain: Domain) -> None:
    async def run() -> None:
        domain.book_create(c.BookCreate(title="备份时的作品"))
        created = await wait_operation(domain, domain.files.backup_create(c.BackupCreate()))
        assert created.status == "completed", created.message
        domain.book_create(c.BookCreate(title="当前作品保留"))
        output = domain.files.root / "outbox" / f"{created.operation_id}.narravo"
        preview = await wait_operation(
            domain,
            domain.files.backup_preview_restore(
                c.RestorePreview(content_b64=base64.b64encode(output.read_bytes()).decode())
            ),
        )
        assert preview.status == "completed", preview.message
        assert len(domain.book_list(c.Empty()).books) == 2
        restored = domain.files.backup_activate_restore(
            c.OperationTarget(operation_id=preview.operation_id)
        )
        assert len(restored.books) == 1
        with sqlite3.connect(domain.files.root / "library.db") as conn:
            assert conn.execute("SELECT COUNT(*) FROM books").fetchone()[0] == 2
        restarted = Storage(domain.files.root)
        try:
            assert restarted.directory == domain.db.directory
        finally:
            restarted.close()
        previous = domain.files.backup_return_previous(
            c.OperationTarget(operation_id=preview.operation_id)
        )
        assert len(previous.books) == 2
        restarted = Storage(domain.files.root)
        try:
            assert restarted.directory == domain.files.root
        finally:
            restarted.close()

    asyncio.run(run())


@pytest.mark.parametrize("tamper", ["checksum", "version", "missing", "schema", "reference"])
def test_restore_rejects_corruption_without_touching_current(
    domain: Domain, tmp_path: Path, tamper: str
) -> None:
    seed_library(domain)
    backup = tmp_path / "backup.narravo"
    create_backup(domain.db.directory, backup, tmp_path / "work", False)
    with zipfile.ZipFile(backup) as archive:
        contents = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(contents["manifest.json"])
    if tamper == "checksum":
        contents["library.db"] += b"corrupt"
    elif tamper == "version":
        manifest["version"] = 999
    elif tamper == "missing":
        del contents["library.db"]
    else:
        modified = tmp_path / "modified.db"
        modified.write_bytes(contents["library.db"])
        with sqlite3.connect(modified) as conn:
            if tamper == "schema":
                conn.execute("CREATE TABLE unexpected(id)")
            else:
                snapshot_id, chapters = conn.execute(
                    "SELECT id,chapters FROM snapshots LIMIT 1"
                ).fetchone()
                chapters = json.loads(chapters)
                chapters[0]["revision"] = "missing"
                conn.execute(
                    "UPDATE snapshots SET chapters=? WHERE id=?",
                    (json.dumps(chapters), snapshot_id),
                )
        conn.close()
        contents["library.db"] = modified.read_bytes()
        manifest["files"]["library.db"] = {
            "sha256": hashlib.sha256(contents["library.db"]).hexdigest(),
            "size": len(contents["library.db"]),
        }
    contents["manifest.json"] = json.dumps(manifest).encode()
    corrupt = tmp_path / "corrupt.narravo"
    with zipfile.ZipFile(corrupt, "w") as archive:
        for name, value in contents.items():
            archive.writestr(name, value)
    with pytest.raises(DomainError):
        prepare_restore(corrupt, tmp_path / "restored", domain.db.path)
    assert not (tmp_path / "restored").exists()
    assert len(domain.book_list(c.Empty()).books) == 1
    assert not (domain.files.root / "active-library.json").exists()


def test_cancel_terminates_worker_and_restart_marks_interrupted(
    domain: Domain, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def slow_worker(*args: object, **kwargs: object) -> dict[str, object]:
        await asyncio.sleep(60)
        return {}

    monkeypatch.setattr(domain.files, "worker", slow_worker)

    async def run() -> None:
        operation = domain.files.file_start_import(
            c.PreviewImport(
                filename="slow.epub", content_b64=base64.b64encode(epub_bytes()).decode()
            )
        )
        await asyncio.sleep(0.01)
        cancelled = domain.files.file_cancel(c.OperationTarget(operation_id=operation.operation_id))
        await domain.files.workers[operation.operation_id]
        assert cancelled.status == "cancelled"
        assert not domain.book_list(c.Empty()).books

    asyncio.run(run())
    record = c.FileOperation(operation_id="a" * 32, kind="backup", status="running", stage="test")
    domain.files.store(record)
    reopened = Domain(Storage(domain.files.root))
    try:
        assert (
            reopened.files.file_get(c.OperationTarget(operation_id=record.operation_id)).error_code
            == "INTERRUPTED"
        )
    finally:
        reopened.db.close()


@pytest.mark.parametrize("include_audio", [False, True])
def test_backup_audio_and_private_configuration_exclusion(
    domain: Domain, tmp_path: Path, include_audio: bool
) -> None:
    import wave

    from narravo_engine.providers.models import AudioRead

    workspace = seed_library(domain)
    raw_stream = io.BytesIO()
    with wave.open(raw_stream, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(b"\x00\x00" * 2400)
    raw = raw_stream.getvalue()
    asset_id = "a" * 32
    folder = domain.db.directory / "audio"
    folder.mkdir()
    (folder / f"{asset_id}.wav").write_bytes(raw)
    with domain.db.transaction() as conn:
        domain.insert(
            conn,
            "audio_assets",
            id=asset_id,
            cache_key="cache-test",
            payload={
                "format": "wav",
                "mime_type": "audio/wav",
                "duration": 0.1,
                "checksum": hashlib.sha256(raw).hexdigest(),
            },
        )
        domain.insert(
            conn,
            "providers",
            id="private-provider",
            payload={"base_url": "https://private-endpoint.example", "has_credential": True},
        )
        domain.insert(conn, "preferences", id="network", payload={"enabled": True})
        generations = conn.exec_driver_sql("SELECT id,payload FROM generations").fetchall()
        for generation_id, payload in generations:
            generation = json.loads(payload)
            generation["provider_snapshot"] = {
                "base_url": "https://private-endpoint.example",
                "id": "private-provider",
                "has_credential": True,
                "protocol": "openai_chat",
                "model": "history-model",
            }
            domain.update(conn, "generations", generation_id, payload=generation)
        domain.insert(
            conn,
            "tasks",
            id="running-remote",
            payload={
                "task_id": "running-remote",
                "status": "running",
                "remote": True,
                "seq": 2,
                "generation_id": None,
                "kind": "test",
                "emitted": 0,
            },
        )
    backup = tmp_path / "backup.narravo"
    create_backup(domain.db.directory, backup, tmp_path / "work", include_audio)
    with zipfile.ZipFile(backup) as archive:
        assert "private-endpoint" not in archive.read("library.db").decode("utf-8", errors="ignore")
        assert (f"audio/{asset_id}.wav" in archive.namelist()) is include_audio
    restored_dir = tmp_path / "restored"
    prepare_restore(backup, restored_dir, domain.db.path)
    restored = Domain(Storage(restored_dir))
    try:
        assert restored.branch_get(c.BranchTarget(branch_id=workspace.branch_id)) == workspace
        assert not restored.providers.provider_list(c.Empty()).providers
        task = restored.task_get(c.TaskTarget(task_id="running-remote"))
        assert task.status == "failed" and task.error_code == "UNKNOWN_OUTCOME"
        if include_audio:
            assert (
                base64.b64decode(
                    restored.providers.audio_read(AudioRead(asset_id=asset_id)).content_b64
                )
                == raw
            )
        else:
            with pytest.raises(DomainError):
                restored.providers.audio_read(AudioRead(asset_id=asset_id))
    finally:
        restored.db.close()


def test_missing_asset_and_backup_failure_leave_live_library(
    domain: Domain, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from narravo_engine import backup as module

    seed_library(domain)
    before = domain.book_list(c.Empty())
    original_write = zipfile.ZipFile.write

    def disk_full(*args: object, **kwargs: object) -> None:
        raise OSError("injected disk full")

    monkeypatch.setattr(module.zipfile.ZipFile, "write", disk_full)
    with pytest.raises(OSError):
        create_backup(domain.db.directory, tmp_path / "failed.narravo", tmp_path / "work", False)
    assert not (tmp_path / "failed.narravo").exists()
    assert not (tmp_path / "failed.tmp").exists()
    assert domain.book_list(c.Empty()) == before
    monkeypatch.setattr(module.zipfile.ZipFile, "write", original_write)
    with domain.db.transaction() as conn:
        domain.insert(
            conn, "audio_assets", id="a" * 32, cache_key="missing", payload={"format": "wav"}
        )
    with pytest.raises(DomainError) as exc:
        create_backup(domain.db.directory, tmp_path / "missing.narravo", tmp_path / "work", True)
    assert exc.value.code == "BACKUP_MISSING_ASSET"


def test_pdf_failed_page_and_optional_margin_normalization(
    domain: Domain, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_worker(params: dict[str, object], timeout: int = 30) -> dict[str, object]:
        if params["action"] == "pdf_count":
            return {"pages": 4}
        if params["page"] == 1:
            raise DomainError("PDF_PAGE_FAILED", "injected bad page")
        return {
            "title": f"第 {int(str(params['page'])) + 1} 页",
            "text": f"共同页眉\n第{params['page']}页的正文\n共同页脚",
            "source_locator": {"page": int(str(params["page"])) + 1},
        }

    monkeypatch.setattr(domain.files, "worker", fake_worker)

    async def run() -> None:
        for remove in [False, True]:
            operation = domain.files.new("import")
            result = await domain.files.parse_pdf(operation, Path("unused"), "", remove)
            assert result["omitted_pages"] == [2]
            assert ("共同页眉" in result["sections"][0]["text"]) is not remove
            assert "第0页的正文" in result["sections"][0]["text"]

    asyncio.run(run())


def test_activation_failure_before_pointer_commit_preserves_current_library(
    domain: Domain, monkeypatch: pytest.MonkeyPatch
) -> None:
    from narravo_engine import files as module

    async def run() -> None:
        domain.book_create(c.BookCreate(title="旧书库"))
        created = await wait_operation(domain, domain.files.backup_create(c.BackupCreate()))
        assert created.status == "completed", created.message
        raw = (domain.files.root / "outbox" / f"{created.operation_id}.narravo").read_bytes()
        restored = await wait_operation(
            domain,
            domain.files.backup_preview_restore(
                c.RestorePreview(content_b64=base64.b64encode(raw).decode())
            ),
        )
        assert restored.status == "completed", restored.message
        before = domain.db
        original = module.atomic_json

        def fail_pointer(path: Path, data: dict[str, object]) -> None:
            if path.name == "active-library.json":
                raise OSError("injected full disk")
            original(path, data)

        monkeypatch.setattr(module, "atomic_json", fail_pointer)
        with pytest.raises(OSError):
            domain.files.backup_activate_restore(
                c.OperationTarget(operation_id=restored.operation_id)
            )
        assert domain.db is before and len(domain.book_list(c.Empty()).books) == 1
        assert not (domain.files.root / "active-library.json").exists()

    asyncio.run(run())


def test_highly_compressible_source_is_restorable(domain: Domain, tmp_path: Path) -> None:
    raw = b"a" * 2_000_000
    preview = domain.book_preview_import(
        c.PreviewImport(filename="repeated.txt", content_b64=base64.b64encode(raw).decode())
    )
    domain.book_confirm_import(c.ConfirmImport(import_id=preview.import_id, title="高压缩比源文件"))
    backup = tmp_path / "compressed.narravo"
    create_backup(domain.db.directory, backup, tmp_path / "work", False)
    prepare_restore(backup, tmp_path / "restored", domain.db.path)
    assert (tmp_path / "restored" / "sources" / hashlib.sha256(raw).hexdigest()).read_bytes() == raw


def test_cancellation_reaps_real_parser_subprocess(
    domain: Domain, monkeypatch: pytest.MonkeyPatch
) -> None:
    processes: list[asyncio.subprocess.Process] = []
    original = asyncio.create_subprocess_exec

    async def track(*args: object, **kwargs: object) -> asyncio.subprocess.Process:
        process = await original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", track)

    async def run() -> None:
        operation = domain.files.file_start_import(
            c.PreviewImport(
                filename="cancel.epub", content_b64=base64.b64encode(epub_bytes()).decode()
            )
        )
        async with asyncio.timeout(5):
            while not processes:
                await asyncio.sleep(0.001)
        domain.files.file_cancel(c.OperationTarget(operation_id=operation.operation_id))
        await domain.files.workers[operation.operation_id]
        assert all(process.returncode is not None for process in processes)
        assert not domain.book_list(c.Empty()).books

    asyncio.run(run())
