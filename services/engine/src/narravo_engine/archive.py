"""Bounded ZIP reads shared by EPUB and portable backups; never extractall."""

from __future__ import annotations

import stat
import zipfile
from pathlib import PurePosixPath

from .domain import require


def safe_name(name: str) -> bool:
    path = PurePosixPath(name)
    return (
        bool(name)
        and not path.is_absolute()
        and not any(part in {"..", "."} for part in name.split("/"))
        and "\\" not in name
        and ":" not in name
        and "\x00" not in name
    )


def inspect_zip(
    archive: zipfile.ZipFile,
    *,
    total_limit: int = 500 * 1024**2,
    entry_limit: int = 50 * 1024**2,
    count_limit: int = 10_000,
    ratio_limit: int | None = 1000,
) -> dict[str, zipfile.ZipInfo]:
    entries = archive.infolist()
    require(len(entries) <= count_limit, "ARCHIVE_LIMIT", "压缩包条目过多，请拆分文件。")
    result: dict[str, zipfile.ZipInfo] = {}
    total = 0
    for entry in entries:
        name = entry.filename.rstrip("/")
        mode = entry.external_attr >> 16
        require(safe_name(name), "UNSAFE_ARCHIVE", "压缩包含不安全路径，已停止读取。")
        require(not stat.S_ISLNK(mode), "UNSAFE_ARCHIVE", "压缩包不允许符号链接。")
        require(name not in result, "UNSAFE_ARCHIVE", "压缩包存在重复路径。")
        require(not entry.flag_bits & 1, "ENCRYPTED_ARCHIVE", "暂不支持加密压缩包。")
        require(entry.file_size <= entry_limit, "ARCHIVE_LIMIT", "压缩包单条目超过限制。")
        total += entry.file_size
        require(total <= total_limit, "ARCHIVE_LIMIT", "压缩包解压总量超过限制。")
        require(
            ratio_limit is None or entry.file_size <= max(1, entry.compress_size) * ratio_limit,
            "ARCHIVE_LIMIT",
            "压缩比过高，已停止读取。",
        )
        result[name] = entry
    return result


def read_entry(archive: zipfile.ZipFile, name: str, limit: int = 50 * 1024**2) -> bytes:
    with archive.open(name) as stream:
        raw = stream.read(limit + 1)
    require(len(raw) <= limit, "ARCHIVE_LIMIT", "压缩包条目超过读取限制。")
    return raw
