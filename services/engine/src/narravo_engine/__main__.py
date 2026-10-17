import argparse
import asyncio
import json
import sys
import threading
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .contracts import RpcRequest
from .domain import Domain, DomainError
from .storage import Storage

MAX_LINE = 16 * 1024 * 1024


def respond(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> None:
    if sys.argv[1:] == ["--file-worker"]:
        from .file_worker import main as worker_main

        worker_main()
        return
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(serve(args.data_dir))


async def serve(directory: Path) -> None:
    storage = Storage(directory)
    domain = Domain(storage)
    incoming: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=32)
    loop = asyncio.get_running_loop()

    def read() -> None:
        while True:
            line = sys.stdin.buffer.readline(MAX_LINE + 1)
            if not line:
                asyncio.run_coroutine_threadsafe(incoming.put(None), loop).result()
                return
            asyncio.run_coroutine_threadsafe(incoming.put(line), loop).result()
            if len(line) > MAX_LINE:
                asyncio.run_coroutine_threadsafe(incoming.put(None), loop).result()
                return

    threading.Thread(target=read, daemon=True).start()
    try:
        while True:
            try:
                line = await asyncio.wait_for(incoming.get(), timeout=0.04)
            except TimeoutError:
                for event in domain.tick():
                    respond(event)
                continue
            if line is None:
                break
            request_id = None
            try:
                if len(line) > MAX_LINE:
                    raise DomainError("REQUEST_TOO_LARGE", "请求内容过大，请缩小范围。")
                payload = json.loads(line)
                if isinstance(payload, dict) and isinstance(payload.get("id"), str):
                    request_id = payload["id"]
                request = RpcRequest.model_validate(payload)
                secret = request.params.pop("_credential", "")
                present = request.params.pop("_credential_present", False)
                endpoint = request.params.pop("_credential_endpoint", "")
                result = domain.dispatch(
                    request.method,
                    request.params,
                    secret=secret if isinstance(secret, str) else "",
                    credential_present=present is True,
                    credential_endpoint=endpoint if isinstance(endpoint, str) else "",
                )
                respond(
                    {
                        "jsonrpc": "2.0",
                        "schema_version": 1,
                        "id": request.id,
                        "result": result.model_dump(),
                    }
                )
            except DomainError as exc:
                respond(
                    {
                        "jsonrpc": "2.0",
                        "schema_version": 1,
                        "id": request_id,
                        "error": {
                            "code": -32000,
                            "data": {"code": exc.code},
                            "message": exc.message,
                        },
                    }
                )
            except (ValidationError, ValueError, UnicodeError):
                respond(
                    {
                        "jsonrpc": "2.0",
                        "schema_version": 1,
                        "id": request_id,
                        "error": {
                            "code": -32602,
                            "data": {"code": "INVALID_ARGUMENT"},
                            "message": "请求格式或版本无效，请更新应用后重试。",
                        },
                    }
                )
            except Exception:  # noqa: BLE001 - sanitize the top-level RPC boundary
                # Never serialize arbitrary exception strings: they may contain text or paths.
                respond(
                    {
                        "jsonrpc": "2.0",
                        "schema_version": 1,
                        "id": request_id,
                        "error": {
                            "code": -32603,
                            "data": {"code": "ENGINE_ERROR"},
                            "message": "本地操作未完成，请保留输入并重试。",
                        },
                    }
                )
    finally:
        await domain.files.close()
        await domain.providers.close()
        domain.db.close()


if __name__ == "__main__":
    main()
