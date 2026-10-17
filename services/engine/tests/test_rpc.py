import json
import os
import subprocess
import sys
from pathlib import Path


def test_stdio_rejects_versions_redacts_errors_and_exits_on_eof(tmp_path: Path) -> None:
    requests = [
        {"jsonrpc": "2.0", "schema_version": 1, "id": "1", "method": "system.health", "params": {}},
        {
            "jsonrpc": "2.0",
            "schema_version": 99,
            "id": "2",
            "method": "book.create",
            "params": {"title": "SECRET_TEXT"},
        },
        {"jsonrpc": "2.0", "schema_version": 1, "id": "3", "method": "not.allowed", "params": {}},
    ]
    process = subprocess.run(
        [sys.executable, "-m", "narravo_engine", "--data-dir", str(tmp_path)],
        input="\n".join(json.dumps(r) for r in requests) + "\n",
        text=True,
        capture_output=True,
        timeout=10,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        check=True,
    )
    replies = [json.loads(line) for line in process.stdout.splitlines()]
    assert len(replies) == 3 and replies[0]["result"]["schema_version"] == 1
    assert replies[1]["error"]["data"]["code"] == "INVALID_ARGUMENT"
    assert replies[2]["error"]["data"]["code"] == "METHOD_NOT_FOUND"
    assert "SECRET_TEXT" not in process.stdout + process.stderr
    assert str(tmp_path) not in process.stdout + process.stderr
