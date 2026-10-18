import asyncio
import base64
import io
import json
import sqlite3
import wave
from pathlib import Path
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from pydantic import ValidationError

from narravo_engine import contracts as c
from narravo_engine.domain import Domain, DomainError
from narravo_engine.providers.llm import generate
from narravo_engine.providers.models import (
    AudioRead,
    NarrationRequest,
    NetworkSet,
    ProviderConfig,
    ProviderSave,
)
from narravo_engine.providers.speech import split_text, synthesize, validate_audio
from narravo_engine.providers.transport import ProviderError, Transport
from narravo_engine.storage import Storage


def config(protocol: str = "openai_chat", **overrides: Any) -> ProviderConfig:
    return ProviderConfig.model_validate(
        {
            "id": "a" * 32,
            "name": "测试服务",
            "kind": "tts"
            if protocol in {"openai_speech", "minimax_speech", "elevenlabs"}
            else "llm",
            "protocol": protocol,
            "base_url": "https://provider.example/v1",
            "model": "test-model",
            "voice": "test-voice",
            **overrides,
        }
    )


def sse_response(events: list[dict[str, Any] | str]) -> httpx.Response:
    content = "".join(
        "data: "
        + (event if isinstance(event, str) else json.dumps(event, ensure_ascii=False))
        + "\n\n"
        for event in events
    )
    return httpx.Response(
        200, content=content.encode(), headers={"content-type": "text/event-stream"}
    )


def wav() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(b"\x00\x00" * 2400)
    return output.getvalue()


@pytest.mark.parametrize("protocol", ["openai_chat", "anthropic", "openai_responses"])
def test_text_protocol_stream_and_usage(protocol: str) -> None:
    seen = []

    def reply(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        if protocol == "anthropic":
            assert (
                request.headers["x-api-key"] == "fake-only"
                and request.headers["anthropic-version"] == "2023-06-01"
            )
            assert request.url.path == "/v1/messages" and body["system"] == "system"
            return sse_response(
                [
                    {
                        "type": "message_start",
                        "message": {"model": "actual-v1", "usage": {"input_tokens": 12}},
                    },
                    {
                        "type": "content_block_delta",
                        "delta": {"type": "thinking_delta", "thinking": "do not expose"},
                    },
                    {
                        "type": "content_block_delta",
                        "delta": {"type": "text_delta", "text": "国王😀"},
                    },
                    {"type": "message_delta", "usage": {"output_tokens": 3}},
                    {"type": "message_stop"},
                ]
            )
        if protocol == "openai_responses":
            assert request.url.path == "/v1/responses" and body["store"] is False
            return sse_response(
                [
                    {"type": "response.output_text.delta", "delta": "国王😀"},
                    {
                        "type": "response.completed",
                        "response": {
                            "model": "actual-v1",
                            "usage": {"input_tokens": 12, "output_tokens": 3},
                        },
                    },
                ]
            )
        assert request.headers["authorization"] == "Bearer fake-only"
        assert (
            request.url.path == "/v1/chat/completions"
            and "temperature" not in body
            and "stream_options" not in body
        )
        return sse_response(
            [
                {
                    "model": "actual-v1",
                    "choices": [
                        {"delta": {"reasoning_content": "do not expose", "content": "国王😀"}}
                    ],
                },
                {
                    "choices": [{"delta": {}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 12, "completion_tokens": 3},
                },
                "[DONE]",
            ]
        )

    async def run() -> list[dict[str, Any]]:
        return [
            event
            async for event in generate(
                config(protocol),
                "fake-only",
                [{"role": "system", "content": "system"}, {"role": "user", "content": "intent"}],
                Transport(httpx.MockTransport(reply)),
            )
        ]

    events = asyncio.run(run())
    assert "".join(event.get("delta", "") for event in events) == "国王😀"
    assert any(event.get("usage") for event in events)
    assert "fake-only" not in json.dumps(seen)


@pytest.mark.parametrize("protocol", ["openai_speech", "minimax_speech", "elevenlabs"])
def test_speech_protocols_return_validated_audio(protocol: str) -> None:
    raw = wav()

    def reply(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if protocol == "minimax_speech":
            assert (
                body["output_format"] == "hex" and body["voice_setting"]["voice_id"] == "test-voice"
            )
            return httpx.Response(
                200, json={"base_resp": {"status_code": 0}, "data": {"audio": raw.hex()}}
            )
        if protocol == "elevenlabs":
            assert request.headers["xi-api-key"] == "fake-only" and request.url.path.endswith(
                "/text-to-speech/test-voice"
            )
        else:
            assert body["input"] == "你好😀" and body["response_format"] == "wav"
        return httpx.Response(200, content=raw)

    result, _ = asyncio.run(
        synthesize(config(protocol), "fake-only", "你好😀", Transport(httpx.MockTransport(reply)))
    )
    assert result == raw and validate_audio(result) == ("wav", "audio/wav", 0.1)
    with pytest.raises(ProviderError):
        validate_audio(raw[:45])
    with pytest.raises(ProviderError):
        validate_audio(b'{"error":"not audio"}')


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "AUTH_FAILED"),
        (402, "QUOTA_EXCEEDED"),
        (429, "RATE_LIMITED"),
        (307, "REDIRECT_BLOCKED"),
    ],
)
def test_errors_redacted_no_retries_or_redirects(status: int, code: str) -> None:
    count = 0

    def reply(request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        return httpx.Response(
            status,
            headers={"location": "http://127.0.0.1/private"},
            text="fake-secret PRIVATE_NOVEL",
        )

    async def run() -> None:
        async for _ in generate(config(), "fake-secret", [], Transport(httpx.MockTransport(reply))):
            pass

    with pytest.raises(ProviderError) as error:
        asyncio.run(run())
    assert error.value.code == code and count == 1
    assert "fake-secret" not in str(error.value) and "PRIVATE_NOVEL" not in str(error.value)


def setup(domain: Domain, protocol: str = "openai_chat", **kwargs: Any) -> ProviderConfig:
    item = config(protocol, **kwargs)
    domain.providers.save(ProviderSave(config=item), False)
    domain.providers.network_set(NetworkSet(enabled=True))
    return item


def writing_request(domain: Domain, item: ProviderConfig) -> tuple[c.Workspace, c.Generate]:
    workspace = domain.book_create(c.BookCreate(title="国王"))
    workspace = domain.chapter_save(
        c.ChapterSave(
            branch_id=workspace.branch_id,
            expected_snapshot=workspace.snapshot_id,
            chapter_id=workspace.chapters[0].id,
            text="很久以前，有一个国王。",
        )
    )
    return workspace, c.Generate(
        branch_id=workspace.branch_id,
        chapter_id=workspace.chapters[0].id,
        offset=len("很久以前，有一个国王。"),
        context_policy="author_plan",
        intent="描写王冠失踪",
        expected_snapshot=workspace.snapshot_id,
        provider="configured",
        config_id=item.id,
    )


async def finish(domain: Domain, task: c.Task) -> c.Task:
    await asyncio.gather(*list(domain.providers.workers.values()))
    return domain.task_get(c.TaskTarget(task_id=task.task_id))


@pytest.mark.parametrize("intent", ["描写王冠失踪", "", " \n "])
def test_real_task_uses_saved_context_keeps_candidate_and_records_usage(
    domain: Domain, intent: str
) -> None:
    captured = []

    def reply(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return sse_response(
            [
                {
                    "choices": [{"delta": {"content": "王冠不见了。😀"}}],
                    "model": "provider-version-1",
                },
                {
                    "choices": [{"delta": {}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 20, "completion_tokens": 8},
                },
                "[DONE]",
            ]
        )

    item = setup(domain)
    workspace, request = writing_request(domain, item)
    request = request.model_copy(update={"intent": intent})
    domain.providers.transport = Transport(httpx.MockTransport(reply))

    async def run() -> c.Task:
        task = domain.providers.start_writing(request, "fake-only")
        # Saving stays usable while the network task exists.
        assert domain.branch_get(c.BranchTarget(branch_id=workspace.branch_id)).word_count > 0
        return await finish(domain, task)

    result = asyncio.run(run())
    assert (
        result.status == "completed"
        and result.generation
        and result.generation.text == "王冠不见了。😀"
    )
    assert (
        "很久以前" in captured[0]["messages"][1]["content"]
        and ("描写王冠失踪" if intent.strip() else "从末尾自然续写")
        in captured[0]["messages"][1]["content"]
    )
    assert (
        result.usage
        and result.usage.actual_model == "provider-version-1"
        and result.usage.output_tokens == 8
    )
    assert (
        domain.chapter_get(
            c.ChapterTarget(branch_id=workspace.branch_id, chapter_id=workspace.chapters[0].id)
        ).text
        == "很久以前，有一个国王。"
    )
    with domain.db.transaction() as conn:
        for name in ["providers", "tasks", "generations"]:
            rows = conn.execute(sa.select(domain.db.tables[name])).mappings().all()
            assert "fake-only" not in json.dumps([dict(row) for row in rows], ensure_ascii=False)


def test_disabled_service_empty_intent_and_endpoint_change_do_not_request(domain: Domain) -> None:
    item = setup(domain)
    _, request = writing_request(domain, item)
    domain.providers.network_set(NetworkSet(enabled=False))
    with pytest.raises(DomainError) as error:
        domain.providers.start_writing(request, "fake-only")
    assert error.value.code == "EXTERNAL_DISABLED"
    domain.providers.network_set(NetworkSet(enabled=True))
    with pytest.raises(DomainError):
        domain.dispatch(
            "writing.generate",
            request.model_dump(),
            secret="fake-only",
            credential_endpoint="https://another.example/v1",
        )
    with pytest.raises(DomainError) as error:
        # Existing text after the insertion point is not eligible continuation context.
        domain.providers.start_writing(
            request.model_copy(update={"intent": " ", "offset": 0}), "fake-only"
        )
    assert error.value.code == "EMPTY_INTENT"
    assert not domain.providers.workers


def test_unicode_split_full_coverage_and_cached_narration(domain: Domain) -> None:
    text = ("国王😀走进大厅。\n" * 50) + "结束"
    pieces = split_text(text)
    assert "".join(piece[2] for piece in pieces) == text
    assert all(text[start:end] == part for start, end, part in pieces)
    assert all(pieces[i][1] == pieces[i + 1][0] for i in range(len(pieces) - 1))
    item = setup(domain, "openai_speech")
    w = domain.book_create(c.BookCreate())
    w = domain.chapter_save(
        c.ChapterSave(
            branch_id=w.branch_id,
            expected_snapshot=w.snapshot_id,
            chapter_id=w.chapters[0].id,
            text=text,
        )
    )
    calls = []

    def reply(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content)["input"])
        return httpx.Response(200, content=wav())

    domain.providers.transport = Transport(httpx.MockTransport(reply))
    request = NarrationRequest(
        config_id=item.id,
        branch_id=w.branch_id,
        chapter_id=w.chapters[0].id,
        expected_snapshot=w.snapshot_id,
    )

    async def run() -> tuple[c.Task, c.Task]:
        first = await finish(domain, domain.providers.start_narration(request, "fake-only"))
        second = await finish(domain, domain.providers.start_narration(request, "fake-only"))
        return first, second

    first, second = asyncio.run(run())
    assert first.status == second.status == "completed" and first.audio and second.audio
    assert len(calls) == len(pieces) and "".join(calls) == text
    assert all(segment.cache_hit for segment in second.audio.segments)
    assert second.usage and second.usage.requests_submitted == 0
    data = domain.providers.audio_read(AudioRead(asset_id=second.audio.segments[0].asset_id))
    assert base64.b64decode(data.content_b64) == wav()
    assert second.audio.revision == w.chapters[0].revision


def test_remote_running_tasks_become_unknown_after_restart_without_replay(
    domain: Domain, tmp_path: Path
) -> None:
    with domain.db.transaction() as conn:
        domain.insert(
            conn,
            "tasks",
            id="remote-one",
            payload={
                "task_id": "remote-one",
                "remote": True,
                "status": "running",
                "seq": 3,
                "generation_id": None,
                "emitted": 0,
            },
        )
    reopened = Domain(Storage(tmp_path))
    task = reopened.task_get(c.TaskTarget(task_id="remote-one"))
    assert task.status == "failed" and task.error_code == "UNKNOWN_OUTCOME"
    assert not reopened.providers.workers
    reopened.db.close()


def test_migration_backs_up_existing_0001_library_and_preserves_data(tmp_path: Path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'library.db'}")
    cfg = Config()
    cfg.set_main_option(
        "script_location", str(Path(__file__).parents[1] / "src/narravo_engine/migrations")
    )
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "0001")
        conn.exec_driver_sql(
            "INSERT INTO books VALUES ('old','旧书','original',NULL,NULL,'not_applicable','2026-10-16')"
        )
    engine.dispose()
    storage = Storage(tmp_path)
    with sqlite3.connect(tmp_path / "pre-migration.db") as old:
        assert old.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0001"
        assert old.execute("SELECT title FROM books").fetchone()[0] == "旧书"
    with storage.engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT version_num FROM alembic_version").scalar() == "0004"
        assert conn.exec_driver_sql("SELECT title FROM books").scalar() == "旧书"
    storage.close()


def test_config_validation_rejects_embedded_secrets_and_wrong_protocol() -> None:
    for override in [
        {"base_url": "https://user:password@example.com/v1"},
        {"base_url": "https://example.com/v1?key=secret"},
        {"base_url": "http://localhost:1234/v1"},
        {"kind": "tts", "voice": ""},
    ]:
        with pytest.raises(ValidationError):
            config(**override)


class PausedStream(httpx.AsyncByteStream):
    def __init__(self, release: asyncio.Event, fail: bool = False):
        self.release = release
        self.fail = fail

    async def __aiter__(self):  # type: ignore[no-untyped-def]
        yield b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
        await self.release.wait()
        if self.fail:
            raise httpx.ReadError("fake-secret PRIVATE_NOVEL")
        yield b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'


def test_cancel_stops_stream_retains_partial_and_never_replays(domain: Domain) -> None:
    item = setup(domain)
    _, request = writing_request(domain, item)

    async def run() -> c.Task:
        release = asyncio.Event()
        count = 0

        def reply(req: httpx.Request) -> httpx.Response:
            nonlocal count
            count += 1
            return httpx.Response(200, stream=PausedStream(release))

        domain.providers.transport = Transport(httpx.MockTransport(reply))
        task = domain.providers.start_writing(request, "fake-only")
        for _ in range(100):
            await asyncio.sleep(0.001)
            value = domain.task_get(c.TaskTarget(task_id=task.task_id))
            if value.generation and value.generation.text:
                break
        domain.task_cancel(c.TaskTarget(task_id=task.task_id))
        release.set()
        result = await finish(domain, task)
        assert count == 1
        return result

    value = asyncio.run(run())
    assert value.status == "cancelled" and value.generation and value.generation.text == "partial"


def test_stream_failure_is_unknown_and_partial_remains_reviewable(domain: Domain) -> None:
    item = setup(domain)
    _, request = writing_request(domain, item)

    async def run() -> c.Task:
        release = asyncio.Event()
        release.set()
        domain.providers.transport = Transport(
            httpx.MockTransport(lambda req: httpx.Response(200, stream=PausedStream(release, True)))
        )
        return await finish(domain, domain.providers.start_writing(request, "fake-only"))

    value = asyncio.run(run())
    assert value.status == "failed" and value.error_code == "UNKNOWN_OUTCOME"
    assert value.generation and value.generation.text == "partial"
    assert "fake-secret" not in value.model_dump_json()


def test_disable_network_cancels_without_starting_further_speech_segments(domain: Domain) -> None:
    item = setup(domain, "openai_speech")
    w = domain.book_create(c.BookCreate())
    w = domain.chapter_save(
        c.ChapterSave(
            branch_id=w.branch_id,
            chapter_id=w.chapters[0].id,
            expected_snapshot=w.snapshot_id,
            text="很长的正文。" * 200,
        )
    )

    async def run() -> c.Task:
        entered = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def reply(req: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            entered.set()
            await release.wait()
            return httpx.Response(200, content=wav())

        domain.providers.transport = Transport(httpx.MockTransport(reply))
        task = domain.providers.start_narration(
            NarrationRequest(
                config_id=item.id,
                branch_id=w.branch_id,
                chapter_id=w.chapters[0].id,
                expected_snapshot=w.snapshot_id,
            ),
            "fake-only",
        )
        await asyncio.wait_for(entered.wait(), 2)
        domain.providers.network_set(NetworkSet(enabled=False))
        release.set()
        result = await finish(domain, task)
        assert calls == 1
        return result

    assert asyncio.run(run()).status == "cancelled"


def test_failed_migration_rolls_back_ddl_and_keeps_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'library.db'}")
    cfg = Config()
    cfg.set_main_option(
        "script_location", str(Path(__file__).parents[1] / "src/narravo_engine/migrations")
    )
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "0001")
    engine.dispose()

    def fail(config: Config, revision: str) -> None:
        config.attributes["connection"].exec_driver_sql("CREATE TABLE accidental (id TEXT)")
        raise RuntimeError("injected migration failure")

    with monkeypatch.context() as patch:
        patch.setattr(command, "upgrade", fail)
        with pytest.raises(RuntimeError):
            Storage(tmp_path)
    with sqlite3.connect(tmp_path / "library.db") as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0001"
        assert not conn.execute("SELECT name FROM sqlite_master WHERE name='accidental'").fetchone()
    assert (tmp_path / "pre-migration.db").exists()


def test_concurrent_narration_reuses_one_synthesis_and_unique_cache_key(domain: Domain) -> None:
    item = setup(domain, "openai_speech")
    w = domain.book_create(c.BookCreate())
    w = domain.chapter_save(
        c.ChapterSave(
            branch_id=w.branch_id,
            chapter_id=w.chapters[0].id,
            expected_snapshot=w.snapshot_id,
            text="同一段正文😀",
        )
    )
    calls = 0

    async def reply(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return httpx.Response(200, content=wav())

    domain.providers.transport = Transport(httpx.MockTransport(reply))
    request = NarrationRequest(
        config_id=item.id,
        branch_id=w.branch_id,
        chapter_id=w.chapters[0].id,
        expected_snapshot=w.snapshot_id,
    )

    async def run() -> tuple[c.Task, c.Task]:
        first = domain.providers.start_narration(request, "fake-only")
        second = domain.providers.start_narration(request, "fake-only")
        await asyncio.gather(*list(domain.providers.workers.values()))
        return domain.task_get(c.TaskTarget(task_id=first.task_id)), domain.task_get(
            c.TaskTarget(task_id=second.task_id)
        )

    first, second = asyncio.run(run())
    assert first.status == second.status == "completed" and calls == 1
    assert second.audio and second.audio.segments[0].cache_hit
    with domain.db.transaction() as conn:
        assert (
            conn.execute(
                sa.select(sa.func.count()).select_from(domain.db.tables["audio_assets"])
            ).scalar()
            == 1
        )
