"""Private subprocess entry. No network, model requests, or user-selected executables."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def main() -> None:
    try:
        import resource

        # CPU bounds supplement the parent's wall-clock timeout and cancellation.
        resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
        resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
    except (ImportError, ValueError, OSError):
        pass
    from .domain import DomainError

    try:
        params = json.loads(sys.stdin.buffer.read(16 * 1024))
        action = params["action"]
        result: dict[str, Any]
        if action in {"epub", "pdf_count", "pdf_page"}:
            from . import importers

            path = Path(params["path"])
            raw = path.read_bytes()
            if action == "epub":
                result = importers.epub(raw)
            elif action == "pdf_count":
                result = importers.pdf_count(raw, params.get("password", ""))
            else:
                result = importers.pdf_page(raw, params.get("password", ""), params["page"])
        elif action == "backup":
            from .backup import create_backup

            result = create_backup(
                Path(params["directory"]),
                Path(params["output"]),
                Path(params["work"]),
                params["include_audio"],
            )
        elif action == "restore":
            from .backup import prepare_restore

            result = prepare_restore(
                Path(params["path"]), Path(params["destination"]), Path(params["template"])
            )
        else:
            raise DomainError("INVALID_ARGUMENT", "未知的文件处理类型。")
        print(json.dumps({"result": result}, ensure_ascii=False))
    except DomainError as exc:
        print(json.dumps({"error": {"code": exc.code, "message": exc.message}}, ensure_ascii=False))
    except Exception:  # noqa: BLE001 - private worker must not expose file content
        print(
            json.dumps(
                {
                    "error": {
                        "code": "FILE_PARSE_FAILED",
                        "message": "文件处理失败，请检查文件或换用其他版本。",
                    }
                },
                ensure_ascii=False,
            )
        )
