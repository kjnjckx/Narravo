"""Portable, checksummed library snapshots. Restoration never replaces a live library."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import zipfile
from contextlib import closing
from pathlib import Path
from typing import Any

from .archive import inspect_zip, read_entry
from .domain import DomainError, require

FORMAT = "narravo-library"
VERSION = 1
MAX_BACKUP = 1024**3
SOURCE = re.compile(r"sources/[a-f0-9]{64}\Z")
AUDIO = re.compile(r"audio/[a-f0-9]{32}\.(wav|mp3)\Z")


def digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024**2), b""):
            checksum.update(block)
    return checksum.hexdigest()


def schema(conn: sqlite3.Connection) -> list[tuple[str, str, str, str]]:
    return conn.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()


def clean_snapshot(path: Path, include_audio: bool) -> list[str]:
    with closing(sqlite3.connect(path)) as conn:
        # Service configurations can contain personal endpoints; keychain credentials never enter SQLite.
        conn.execute("DELETE FROM providers")
        conn.execute("DELETE FROM preferences")
        if not include_audio:
            conn.execute("DELETE FROM audio_assets")
        for generation_id, payload in conn.execute("SELECT id,payload FROM generations").fetchall():
            data = json.loads(payload)
            if "provider_snapshot" in data:
                snapshot = data.pop("provider_snapshot")
                data["provider_provenance"] = {
                    key: value
                    for key, value in snapshot.items()
                    if key not in {"id", "name", "base_url", "has_credential", "allow_local"}
                }
                conn.execute(
                    "UPDATE generations SET payload=? WHERE id=?",
                    (json.dumps(data, ensure_ascii=False), generation_id),
                )
        for task_id, payload in conn.execute("SELECT id,payload FROM tasks").fetchall():
            data = json.loads(payload)
            if data.get("status") == "running":
                data.update(
                    status="failed",
                    error_code="UNKNOWN_OUTCOME" if data.get("remote") else "INTERRUPTED",
                    message="备份时任务未完成；恢复后不会自动重新请求。",
                    seq=data.get("seq", 0) + 1,
                )
            if not include_audio:
                data["audio"] = None
            conn.execute(
                "UPDATE tasks SET payload=? WHERE id=?",
                (json.dumps(data, ensure_ascii=False), task_id),
            )
        from .roleplay.backup import clean as clean_roleplay

        clean_roleplay(conn, include_audio)
        sources = [
            row[0]
            for row in conn.execute("SELECT source_hash FROM books WHERE source_hash IS NOT NULL")
        ]
        # Retain unconfirmed previews too: their source manifests remain recoverable.
        sources += [
            json.loads(row[0])["source_hash"] for row in conn.execute("SELECT payload FROM imports")
        ]
        files = [f"sources/{value}" for value in set(sources)]
        if include_audio:
            for asset_id, payload in conn.execute("SELECT id,payload FROM audio_assets"):
                data = json.loads(payload)
                files.append(f"audio/{asset_id}.{data['format']}")
        conn.commit()
        conn.execute("VACUUM")
    return files


def create_backup(directory: Path, output: Path, work: Path, include_audio: bool) -> dict[str, Any]:
    work.mkdir(parents=True, exist_ok=False)
    snapshot = work / "library.db"
    try:
        with (
            closing(sqlite3.connect(directory / "library.db")) as source,
            closing(sqlite3.connect(snapshot)) as target,
        ):
            source.backup(target)
            target.execute("PRAGMA journal_mode=DELETE")
        files = clean_snapshot(snapshot, include_audio)
        with closing(sqlite3.connect(snapshot)) as conn:
            schema_version = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            books = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
        manifest: dict[str, Any] = {
            "format": FORMAT,
            "version": VERSION,
            "schema_version": schema_version,
            "include_audio": include_audio,
            "book_count": books,
            "files": {},
        }
        total = 0
        for name in ["library.db", *sorted(files)]:
            require(
                name == "library.db" or bool(SOURCE.fullmatch(name) or AUDIO.fullmatch(name)),
                "BACKUP_INVALID_ASSET",
                "资产标识无效，无法创建备份。",
            )
            path = snapshot if name == "library.db" else directory / name
            require(
                path.is_file() and not path.is_symlink() and not path.parent.is_symlink(),
                "BACKUP_MISSING_ASSET",
                "备份所需的原文件或音频缺失，请检查磁盘。",
            )
            checksum = digest(path)
            if name.startswith("sources/"):
                require(
                    checksum == name.split("/")[1],
                    "SOURCE_CORRUPT",
                    "原文件副本校验失败，备份已停止。",
                )
            manifest["files"][name] = {"sha256": checksum, "size": path.stat().st_size}
            total += path.stat().st_size
        require(total <= MAX_BACKUP, "BACKUP_LIMIT", "备份解压内容超过 1 GiB；请不含音频重试。")
        validate_database(snapshot, directory / "library.db", manifest, directory)
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(".tmp")
        try:
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
                for name in manifest["files"]:
                    archive.write(snapshot if name == "library.db" else directory / name, name)
            temporary.replace(output)
        finally:
            temporary.unlink(missing_ok=True)
        return {"book_count": books, "include_audio": include_audio, "size": output.stat().st_size}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def prepare_restore(source: Path, destination: Path, template: Path) -> dict[str, Any]:
    destination.mkdir(parents=True, exist_ok=False)
    try:
        require(source.stat().st_size <= MAX_BACKUP, "BACKUP_LIMIT", "备份文件超过 1 GiB。")
        with zipfile.ZipFile(source) as archive:
            entries = inspect_zip(
                archive,
                total_limit=MAX_BACKUP,
                entry_limit=MAX_BACKUP,
                count_limit=20_000,
                ratio_limit=None,
            )
            manifest = json.loads(read_entry(archive, "manifest.json", 4 * 1024**2))
            require(
                manifest.get("format") == FORMAT and manifest.get("version") == VERSION,
                "BACKUP_VERSION",
                "备份格式版本不兼容，请使用对应版本的叙声。",
            )
            files = manifest.get("files", {})
            require(
                isinstance(files, dict)
                and "library.db" in files
                and set(entries) == {*files, "manifest.json"},
                "BACKUP_INVALID",
                "备份清单与文件不一致。",
            )
            for name, expected in files.items():
                require(
                    name == "library.db" or bool(SOURCE.fullmatch(name) or AUDIO.fullmatch(name)),
                    "BACKUP_INVALID",
                    "备份包含非书库资产。",
                )
                require(
                    isinstance(expected, dict) and entries[name].file_size == expected.get("size"),
                    "BACKUP_CHECKSUM",
                    "备份文件大小校验失败。",
                )
                target = destination / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as inp, target.open("xb") as out:
                    shutil.copyfileobj(inp, out, length=1024**2)
                require(
                    digest(target) == expected.get("sha256"),
                    "BACKUP_CHECKSUM",
                    "备份校验和不匹配，未切换书库。",
                )
                if name.startswith("sources/"):
                    require(
                        digest(target) == name.split("/")[1],
                        "BACKUP_CHECKSUM",
                        "备份源文件标识不匹配。",
                    )
        validate_database(destination / "library.db", template, manifest, destination)
        return {
            "book_count": manifest["book_count"],
            "include_audio": manifest["include_audio"],
            "size": source.stat().st_size,
        }
    except DomainError:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(destination, ignore_errors=True)
        raise DomainError("BACKUP_INVALID", "备份损坏或结构不受支持，当前书库未改动。") from exc


def validate_database(
    path: Path, template: Path, manifest: dict[str, Any], directory: Path
) -> None:
    with closing(sqlite3.connect(template)) as reference, closing(sqlite3.connect(path)) as conn:
        conn.execute("PRAGMA trusted_schema=OFF")
        require(
            schema(conn) == schema(reference), "BACKUP_SCHEMA", "备份数据库结构与当前版本不兼容。"
        )
        version = conn.execute("SELECT version_num FROM alembic_version").fetchall()
        require(
            version == reference.execute("SELECT version_num FROM alembic_version").fetchall()
            and len(version) == 1
            and version[0][0] == manifest.get("schema_version"),
            "BACKUP_SCHEMA",
            "备份数据库版本不兼容。",
        )
        require(
            conn.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
            and not conn.execute("PRAGMA foreign_key_check").fetchall(),
            "BACKUP_DATABASE",
            "备份数据库完整性检查失败。",
        )
        require(
            conn.execute("SELECT COUNT(*) FROM providers").fetchone()[0] == 0
            and conn.execute("SELECT COUNT(*) FROM preferences").fetchone()[0] == 0,
            "BACKUP_PRIVATE_CONFIG",
            "备份含服务配置，不符合当前可移植备份格式。",
        )
        require(
            isinstance(manifest.get("include_audio"), bool)
            and isinstance(manifest.get("book_count"), int),
            "BACKUP_INVALID",
            "备份清单类型无效。",
        )
        require(
            conn.execute("SELECT COUNT(*) FROM books").fetchone()[0] == manifest.get("book_count"),
            "BACKUP_INVALID",
            "备份作品数量与清单不一致。",
        )
        rows = {
            table: {row[0]: row for row in conn.execute(f'SELECT * FROM "{table}"')}
            for table in (
                "books",
                "branches",
                "revisions",
                "planning",
                "snapshots",
                "generations",
                "imports",
            )
        }
        from .contracts import Accept, ChapterMeta, Generation, PlanningEntry, Task
        from .domain import count

        for row in rows["planning"].values():
            for entry in json.loads(row[1]):
                PlanningEntry.model_validate(entry)
        for row in rows["snapshots"].values():
            chapters = json.loads(row[4])
            for chapter in chapters:
                ChapterMeta.model_validate(chapter)
                require(
                    chapter["revision"] in rows["revisions"],
                    "BACKUP_REFERENCE",
                    "备份章节修订引用缺失。",
                )
                require(
                    chapter["word_count"] == count(rows["revisions"][chapter["revision"]][1]),
                    "BACKUP_REFERENCE",
                    "备份章节字数与正文不一致。",
                )
            require(
                len({chapter["id"] for chapter in chapters}) == len(chapters),
                "BACKUP_REFERENCE",
                "备份章节标识重复。",
            )
            if row[2]:
                require(
                    rows["snapshots"][row[2]][1] == row[1],
                    "BACKUP_REFERENCE",
                    "备份历史跨作品引用。",
                )
        for row in rows["books"].values():
            if row[4] is not None:
                require(
                    f"sources/{row[4]}" in manifest["files"], "BACKUP_REFERENCE", "备份缺失原文件。"
                )
        for row in rows["branches"].values():
            require(
                rows["snapshots"][row[4]][1] == row[1],
                "BACKUP_REFERENCE",
                "备份分支引用了其他作品。",
            )
            if row[3]:
                require(
                    rows["branches"][row[3]][1] == row[1],
                    "BACKUP_REFERENCE",
                    "备份分支父节点跨作品引用。",
                )
        for generation_id, payload in rows["generations"].values():
            generation = json.loads(payload)
            require(
                "provider_snapshot" not in generation,
                "BACKUP_PRIVATE_CONFIG",
                "备份含未脱敏的服务配置快照。",
            )
            Generation.model_validate(
                {key: generation[key] for key in Generation.model_fields if key in generation}
            )
            require(
                generation["id"] == generation_id
                and generation["branch_id"] in rows["branches"]
                and generation["base_snapshot"] in rows["snapshots"],
                "BACKUP_REFERENCE",
                "备份候选依赖缺失。",
            )
            snapshot = rows["snapshots"][generation["base_snapshot"]]
            require(
                snapshot[1] == rows["branches"][generation["branch_id"]][1]
                and any(
                    chapter["id"] == generation["chapter_id"] for chapter in json.loads(snapshot[4])
                ),
                "BACKUP_REFERENCE",
                "备份候选目标章节无效。",
            )
        for import_id, payload in rows["imports"].values():
            imported = json.loads(payload)
            require(
                f"sources/{imported['source_hash']}" in manifest["files"],
                "BACKUP_REFERENCE",
                "备份导入预览缺失原文件。",
            )
            require(
                not imported["book_branch"] or imported["book_branch"] in rows["branches"],
                "BACKUP_REFERENCE",
                "备份导入清单分支引用缺失。",
            )
        for decision_id, generation_id, payload in conn.execute(
            "SELECT id,generation_id,payload FROM decisions"
        ):
            decision = json.loads(payload)
            request = Accept.model_validate(decision["request"])
            require(
                request.generation_id == generation_id
                and request.idempotency_key == decision_id
                and decision["target_revision"] in rows["revisions"]
                and decision["target_snapshot"] in rows["snapshots"],
                "BACKUP_REFERENCE",
                "备份接纳决策引用缺失。",
            )
        for task_id, payload in conn.execute("SELECT id,payload FROM tasks"):
            task = json.loads(payload)
            Task.model_validate({key: task[key] for key in Task.model_fields if key in task})
            require(
                task["task_id"] == task_id
                and (not task.get("generation_id") or task["generation_id"] in rows["generations"]),
                "BACKUP_REFERENCE",
                "备份任务候选引用缺失。",
            )
            require(
                task.get("status") != "running",
                "BACKUP_RUNNING_TASK",
                "备份包含未冻结的活动任务。",
            )
        from .roleplay.backup import validate as validate_roleplay

        validate_roleplay(conn, manifest["include_audio"])
        for asset_id, payload in conn.execute("SELECT id,payload FROM audio_assets"):
            data = json.loads(payload)
            name = f"audio/{asset_id}.{data['format']}"
            require(
                bool(AUDIO.fullmatch(name)) and manifest.get("include_audio") is True,
                "BACKUP_REFERENCE",
                "备份音频清单无效。",
            )
            require(
                name in manifest["files"] and digest(directory / name) == data["checksum"],
                "BACKUP_REFERENCE",
                "备份音频引用或校验和无效。",
            )
            from .providers.speech import validate_audio

            extension, mime, duration = validate_audio((directory / name).read_bytes())
            require(
                extension == data["format"]
                and mime == data["mime_type"]
                and abs(duration - data["duration"]) < 0.1,
                "BACKUP_AUDIO",
                "备份音频格式校验失败。",
            )
