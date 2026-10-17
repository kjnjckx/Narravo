"""Cancellable local file jobs. Binary assets cross stdio by opaque staged IDs."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import sqlalchemy as sa

from . import contracts as c
from .domain import DomainError, require, uid
from .storage import Storage

if TYPE_CHECKING:
    from .domain import Domain


def atomic_json(path: Path, data: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    if os.name != "nt":
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


class FileService:
    def __init__(self, domain: Domain):
        self.domain = domain
        self.root = domain.db.root_directory
        self.records = self.root / "operations"
        self.records.mkdir(exist_ok=True)
        self.workers: dict[str, asyncio.Task[None]] = {}
        self.activating = False
        for path in self.records.glob("*.json"):
            try:
                operation = c.FileOperation.model_validate_json(path.read_text())
                if operation.status == "running":
                    operation.status = "failed"
                    operation.error_code = "INTERRUPTED"
                    operation.message = "上次文件处理已中断，请重新选择文件；不会自动重跑。"
                    self.store(operation)
                    if operation.kind == "restore":
                        shutil.rmtree(
                            self.root / "libraries" / operation.operation_id, ignore_errors=True
                        )
                    shutil.rmtree(self.root / f"work-{operation.operation_id}", ignore_errors=True)
                    (self.root / "outbox" / f"{operation.operation_id}.tmp").unlink(missing_ok=True)
            except (ValueError, OSError):
                continue
        inbox = self.root / "inbox"
        if inbox.is_dir() and not inbox.is_symlink():
            for staged in inbox.iterdir():
                if re.fullmatch(r"[a-f0-9]{32}", staged.name) and staged.is_file():
                    staged.unlink(missing_ok=True)

    def ensure_idle(self) -> None:
        require(
            not any(not task.done() for task in self.workers.values()),
            "FILE_BUSY",
            "已有文件处理任务，请等待完成或取消。",
        )

    def store(self, operation: c.FileOperation) -> None:
        atomic_json(self.records / f"{operation.operation_id}.json", operation.model_dump())

    def file_get(self, p: c.OperationTarget) -> c.FileOperation:
        path = self.records / f"{p.operation_id}.json"
        require(path.is_file(), "NOT_FOUND", "文件处理记录不存在，请重新选择文件。")
        operation = c.FileOperation.model_validate_json(path.read_text())
        if (
            operation.kind == "restore"
            and operation.status == "completed"
            and self.domain.db.directory == self.root / "libraries" / p.operation_id
        ):
            operation.activated = True
            operation.stage = "已切换至恢复书库；原书库仍保留在本机"
        return operation

    def new(self, kind: Literal["import", "backup", "restore"]) -> c.FileOperation:
        require(
            not any(not task.done() for task in self.workers.values()),
            "FILE_BUSY",
            "已有文件处理任务，请等待完成或取消。",
        )
        operation = c.FileOperation(
            operation_id=uid(), kind=kind, status="running", stage="准备文件"
        )
        self.store(operation)
        return operation

    def input_path(self, asset_id: str, maximum: int) -> Path:
        folder = self.root / "inbox"
        path = folder / asset_id
        require(
            not folder.is_symlink() and not path.is_symlink() and path.is_file(),
            "FILE_MISSING",
            "所选文件已失效，请重新选择。",
        )
        require(path.stat().st_size <= maximum, "FILE_TOO_LARGE", "文件超过大小限制。")
        return path

    def file_start_import(self, p: c.PreviewImport) -> c.FileOperation:
        self.ensure_idle()
        extension = Path(p.filename).suffix.lower()
        require(
            extension in {".txt", ".epub", ".pdf"},
            "UNSUPPORTED_FORMAT",
            "请选择 TXT、EPUB 或文本型 PDF。",
        )
        maximum = 10 * 1024**2 if extension == ".txt" else 100 * 1024**2
        if p.asset_id:
            require(not p.content_b64, "INVALID_ARGUMENT", "文件来源重复，请重新选择。")
            path = self.input_path(p.asset_id, maximum)
        else:
            raw = base64.b64decode(p.content_b64, validate=True)
            require(len(raw) <= maximum, "FILE_TOO_LARGE", "文件超过大小限制。")
            folder = self.root / "inbox"
            folder.mkdir(exist_ok=True)
            require(not folder.is_symlink(), "UNSAFE_DIRECTORY", "暂存目录不允许符号链接。")
            path = folder / uid()
            path.write_bytes(raw)
        operation = self.new("import")
        self.workers[operation.operation_id] = asyncio.create_task(
            self.run_import(operation, p, path)
        )
        self.workers[operation.operation_id].add_done_callback(
            lambda _: path.unlink(missing_ok=True)
        )
        return operation

    def backup_create(self, p: c.BackupCreate) -> c.FileOperation:
        operation = self.new("backup")
        self.workers[operation.operation_id] = asyncio.create_task(self.run_backup(operation, p))
        return operation

    def backup_preview_restore(self, p: c.RestorePreview) -> c.FileOperation:
        self.ensure_idle()
        if p.asset_id:
            require(not p.content_b64, "INVALID_ARGUMENT", "文件来源重复。")
            path = self.input_path(p.asset_id, 1024**3)
        else:
            raw = base64.b64decode(p.content_b64, validate=True)
            require(bool(raw), "INVALID_ARGUMENT", "请选择备份文件。")
            folder = self.root / "inbox"
            folder.mkdir(exist_ok=True)
            require(not folder.is_symlink(), "UNSAFE_DIRECTORY", "暂存目录不允许符号链接。")
            path = folder / uid()
            path.write_bytes(raw)
        operation = self.new("restore")
        self.workers[operation.operation_id] = asyncio.create_task(
            self.run_restore(operation, path)
        )
        self.workers[operation.operation_id].add_done_callback(
            lambda _: path.unlink(missing_ok=True)
        )
        return operation

    def file_cancel(self, p: c.OperationTarget) -> c.FileOperation:
        operation = self.file_get(p)
        if operation.status == "running":
            worker = self.workers.get(p.operation_id)
            if worker:
                worker.cancel()
            operation.status = "cancelled"
            operation.stage = "已取消"
            operation.message = "文件处理已取消，当前书库未切换。"
            self.store(operation)
        return operation

    async def worker(self, params: dict[str, Any], timeout: float = 30) -> dict[str, Any]:
        args = [sys.executable]
        if not getattr(sys, "frozen", False):
            args += ["-m", "narravo_engine"]
        args += ["--file-worker"]
        process = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            assert process.stdin and process.stdout
            process.stdin.write(json.dumps(params).encode())
            await process.stdin.drain()
            process.stdin.close()
            async with asyncio.timeout(timeout):
                raw = await process.stdout.read(12 * 1024**2 + 1)
                require(len(raw) <= 12 * 1024**2, "FILE_RESULT_LIMIT", "文件提取结果过大。")
                # StreamReader.read can return partial output; read until EOF within the bound.
                while block := await process.stdout.read(64 * 1024):
                    raw += block
                    require(len(raw) <= 12 * 1024**2, "FILE_RESULT_LIMIT", "文件提取结果过大。")
                await process.wait()
            require(
                process.returncode == 0,
                "FILE_WORKER_FAILED",
                "文件解析进程超出资源限制或异常退出。",
            )
            result = json.loads(raw)
            if "error" in result:
                raise DomainError(result["error"]["code"], result["error"]["message"])
            return dict(result["result"])
        except TimeoutError as exc:
            raise DomainError("FILE_TIMEOUT", "文件或页面解析超时，已停止解析。") from exc
        finally:
            if process.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
                await process.wait()

    def stage(self, operation: c.FileOperation, label: str) -> None:
        operation.stage = label
        self.store(operation)

    def fail(self, operation: c.FileOperation, exc: Exception) -> None:
        operation.status = "failed"
        operation.stage = "处理失败"
        operation.error_code = exc.code if isinstance(exc, DomainError) else "FILE_FAILED"
        operation.message = (
            exc.message
            if isinstance(exc, DomainError)
            else "本地文件处理未完成，请检查磁盘空间并重试。"
        )
        if isinstance(exc, TimeoutError):
            operation.error_code = "FILE_TIMEOUT"
            operation.message = "整份文件处理超时，请拆分文件或先转换为 TXT。"
        self.store(operation)

    async def run_import(self, operation: c.FileOperation, p: c.PreviewImport, path: Path) -> None:
        try:
            self.stage(operation, "解析与规范化正文")
            extension = Path(p.filename).suffix.lower()
            if extension == ".txt":
                preview = self.domain.book_preview_import(
                    c.PreviewImport(
                        filename=p.filename,
                        content_b64=base64.b64encode(path.read_bytes()).decode(),
                        encoding=p.encoding,
                    )
                )
            else:
                if extension == ".epub":
                    result = await self.worker({"action": "epub", "path": str(path)})
                else:
                    result = await self.parse_pdf(operation, path, p.password, p.remove_pdf_margins)
                preview = self.domain.persist_import(
                    p.filename,
                    path.read_bytes(),
                    result["encoding"],
                    result["sections"],
                    result["warnings"],
                    result["omitted_pages"],
                    result.get("metadata"),
                )
            operation.preview = preview
            operation.status = "completed"
            operation.stage = "预览已准备，请确认导入"
            self.store(operation)
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001 - sanitize file job failures
            self.fail(operation, exc)
        finally:
            path.unlink(missing_ok=True)

    async def parse_pdf(
        self, operation: c.FileOperation, path: Path, password: str, remove_margins: bool = False
    ) -> dict[str, Any]:
        params = {"path": str(path), "password": password}
        total = (await self.worker({"action": "pdf_count", **params}, 10))["pages"]
        sections, omitted = [], []
        size = 0
        async with asyncio.timeout(180):
            for page in range(total):
                self.stage(operation, f"逐页提取 PDF：{page + 1}/{total}")
                try:
                    section = await self.worker({"action": "pdf_page", "page": page, **params}, 8)
                    sections.append(section)
                    size += len(section["text"].encode())
                    require(size <= 8 * 1024**2, "TEXT_LIMIT", "提取正文超过 8 MiB，请拆分 PDF。")
                except DomainError as exc:
                    if exc.code not in {
                        "OCR_REQUIRED",
                        "PDF_PAGE_FAILED",
                        "PDF_PAGE_LIMIT",
                        "FILE_TIMEOUT",
                        "FILE_WORKER_FAILED",
                        "FILE_RESULT_LIMIT",
                    }:
                        raise
                    omitted.append(page + 1)
        require(
            bool(sections),
            "OCR_REQUIRED",
            "PDF 没有可可靠提取的文本；可能是扫描件、坏页或解析超时。请先 OCR 或转换为 TXT。",
        )
        warnings = ["PDF 按页导入；多栏、竖排和特殊排版可能顺序错误，请检查预览。"]
        if remove_margins and len(sections) >= 3:
            from collections import Counter

            margins = Counter(
                line
                for section in sections
                for line in {
                    section["text"].splitlines()[0].strip(),
                    section["text"].splitlines()[-1].strip(),
                }
                if line
            )
            repeated = {
                line
                for line, occurrences in margins.items()
                if occurrences >= max(3, (len(sections) * 3 + 4) // 5)
            }
            changed = 0
            for section in sections:
                lines = section["text"].splitlines()
                if lines and lines[0].strip() in repeated:
                    lines.pop(0)
                    changed += 1
                if lines and lines[-1].strip() in repeated:
                    lines.pop()
                    changed += 1
                # Keep the original text if this heuristic would erase an entire page.
                if "\n".join(lines).strip():
                    section["text"] = "\n".join(lines).strip()
            if changed:
                warnings.append(f"尝试移除了 {changed} 处重复页眉/页脚；请核对正文，原文件未改动。")
        if omitted:
            warnings.append("部分页面缺失，请核对遗漏页码并明确接受后导入。")
        return {
            "sections": sections,
            "omitted_pages": omitted,
            "encoding": "pdf",
            "warnings": warnings,
        }

    async def run_backup(self, operation: c.FileOperation, p: c.BackupCreate) -> None:
        work = self.root / f"work-{operation.operation_id}"
        output = self.root / "outbox" / f"{operation.operation_id}.narravo"
        try:
            self.stage(operation, "创建一致性快照并校验资产")
            result = await self.worker(
                {
                    "action": "backup",
                    "directory": str(self.domain.db.directory),
                    "output": str(output),
                    "work": str(work),
                    "include_audio": p.include_audio,
                },
                120,
            )
            operation.book_count = result["book_count"]
            operation.size = result["size"]
            operation.include_audio = p.include_audio
            operation.status = "completed"
            operation.stage = "备份已准备，可保存文件"
            self.store(operation)
        except asyncio.CancelledError:
            output.unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001 - sanitize file job failures
            self.fail(operation, exc)
        finally:
            shutil.rmtree(work, ignore_errors=True)
            output.with_suffix(".tmp").unlink(missing_ok=True)

    async def run_restore(self, operation: c.FileOperation, path: Path) -> None:
        destination = self.root / "libraries" / operation.operation_id
        try:
            self.stage(operation, "校验清单、版本、数据库与全部资产")
            destination.parent.mkdir(exist_ok=True)
            require(
                not destination.parent.is_symlink(), "UNSAFE_DIRECTORY", "恢复目录不允许符号链接。"
            )
            result = await self.worker(
                {
                    "action": "restore",
                    "path": str(path),
                    "destination": str(destination),
                    "template": str(self.domain.db.path),
                },
                120,
            )
            operation.book_count = result["book_count"]
            operation.size = result["size"]
            operation.include_audio = result["include_audio"]
            operation.status = "completed"
            operation.stage = "校验通过，等待恢复为独立书库"
            self.store(operation)
        except asyncio.CancelledError:
            shutil.rmtree(destination, ignore_errors=True)
        except Exception as exc:  # noqa: BLE001 - sanitize file job failures
            shutil.rmtree(destination, ignore_errors=True)
            self.fail(operation, exc)
        finally:
            path.unlink(missing_ok=True)

    def backup_activate_restore(self, p: c.OperationTarget) -> c.Library:
        operation = self.file_get(p)
        require(
            operation.kind == "restore" and operation.status == "completed",
            "RESTORE_NOT_READY",
            "请先选择备份并等待校验完成。",
        )
        require(
            not any(not task.done() for task in self.workers.values()),
            "FILE_BUSY",
            "请等待文件任务结束后恢复。",
        )
        require(
            not any(not task.done() for task in self.domain.providers.workers.values()),
            "TASK_BUSY",
            "请先停止模型或语音任务，再恢复书库。",
        )
        with self.domain.db.transaction() as conn:
            tasks = conn.execute(sa.select(self.domain.db.tables["tasks"].c.payload)).scalars()
            require(
                not any(task["status"] == "running" for task in tasks),
                "TASK_BUSY",
                "请先停止正在运行的任务，再恢复书库。",
            )
        if not operation.activated:
            operation.previous_library_id = (
                self.domain.db.directory.name
                if self.domain.db.directory != self.root
                else "original"
            )
        self.store(operation)
        self.switch_library(p.operation_id)
        operation.activated = True
        operation.stage = "已切换至恢复书库；原书库仍保留在本机"
        self.store(operation)
        return self.domain.book_list(c.Empty())

    def backup_return_previous(self, p: c.OperationTarget) -> c.Library:
        operation = self.file_get(p)
        require(
            operation.activated and operation.previous_library_id is not None,
            "RESTORE_NOT_READY",
            "此恢复记录没有可切回的书库。",
        )
        require(
            not any(not task.done() for task in self.workers.values())
            and not any(not task.done() for task in self.domain.providers.workers.values()),
            "TASK_BUSY",
            "请先停止正在运行的任务。",
        )
        with self.domain.db.transaction() as conn:
            tasks = conn.execute(sa.select(self.domain.db.tables["tasks"].c.payload)).scalars()
            require(
                not any(task["status"] == "running" for task in tasks),
                "TASK_BUSY",
                "请先停止正在运行的任务。",
            )
        assert operation.previous_library_id is not None
        self.switch_library(operation.previous_library_id)
        return self.domain.book_list(c.Empty())

    def switch_library(self, library_id: str) -> None:
        self.activating = True
        replacement: Storage | None = None
        try:
            require(
                library_id == "original" or bool(re.fullmatch(r"[a-f0-9]{32}", library_id)),
                "INVALID_ARGUMENT",
                "书库标识无效。",
            )
            directory = (
                self.root if library_id == "original" else self.root / "libraries" / library_id
            )
            require((directory / "library.db").is_file(), "LIBRARY_MISSING", "原书库文件已不可用。")
            require(
                not directory.is_symlink() and not directory.parent.is_symlink(),
                "UNSAFE_DIRECTORY",
                "书库目录不允许符号链接。",
            )
            replacement = Storage(directory, follow_pointer=False)
            replacement.root_directory = self.root
            # No await between durable pointer commit and in-memory switch.
            atomic_json(self.root / "active-library.json", {"library_id": library_id})
            old = self.domain.db
            self.domain.db = replacement
            replacement = None
            old.close()
            self.domain.providers.recover()
            self.domain.roleplay.recover()
        finally:
            if replacement:
                replacement.close()
            self.activating = False

    async def close(self) -> None:
        for operation_id, task in self.workers.items():
            if not task.done():
                self.file_cancel(c.OperationTarget(operation_id=operation_id))
        await asyncio.gather(*self.workers.values(), return_exceptions=True)
