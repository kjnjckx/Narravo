from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
from collections.abc import Callable
from functools import partial
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import sqlalchemy as sa

from .catalog import catalog
from .llm import generate, writing_messages
from .models import (
    AudioData,
    AudioPlan,
    AudioRead,
    AudioSegment,
    NarrationRequest,
    NetworkSet,
    ProviderCatalog,
    ProviderConfig,
    ProviderList,
    ProviderRecord,
    ProviderSave,
    ProviderTarget,
    Usage,
)
from .speech import split_text, synthesize, validate_audio
from .transport import ProviderError, Transport

if TYPE_CHECKING:
    from .. import contracts as c
    from ..domain import Domain


def uid() -> str:
    return uuid4().hex


class ProviderService:
    def __init__(self, domain: Domain, transport: Transport | None = None):
        self.domain = domain
        self.transport = transport or Transport()
        self.workers: dict[str, asyncio.Task[None]] = {}
        self.audio_lock = asyncio.Lock()
        self.recover()

    def recover(self) -> None:
        with self.domain.db.transaction() as conn:
            rows = conn.execute(sa.select(self.domain.db.tables["tasks"])).mappings().all()
            for row in rows:
                data = row["payload"]
                if data.get("remote") and data["status"] == "running":
                    data.update(
                        status="failed",
                        error_code="UNKNOWN_OUTCOME",
                        message="上次请求随应用退出中断，远端可能已计费；不会自动重发。",
                        seq=data["seq"] + 1,
                    )
                    self.domain.update(conn, "tasks", row["id"], payload=data)

    def provider_catalog(self, _: Any) -> ProviderCatalog:
        return catalog()

    def provider_list(self, _: Any) -> ProviderList:
        with self.domain.db.transaction() as conn:
            rows = conn.execute(sa.select(self.domain.db.tables["providers"])).mappings().all()
            pref = (
                conn.execute(
                    sa.select(self.domain.db.tables["preferences"]).where(
                        self.domain.db.tables["preferences"].c.id == "network"
                    )
                )
                .mappings()
                .first()
            )
            return ProviderList(
                providers=[ProviderRecord.model_validate(row["payload"]) for row in rows],
                external_enabled=bool(pref and pref["payload"]["enabled"]),
            )

    def provider_get(self, p: ProviderTarget) -> ProviderRecord:
        with self.domain.db.transaction() as conn:
            return ProviderRecord.model_validate(
                self.domain.row(conn, "providers", p.config_id)["payload"]
            )

    def provider_validate(self, p: ProviderSave) -> ProviderRecord:
        return ProviderRecord(**p.config.model_dump())

    def save(self, p: ProviderSave, credential_present: bool) -> ProviderRecord:
        value = ProviderRecord(**p.config.model_dump(), has_credential=credential_present)
        with self.domain.db.transaction() as conn:
            table = self.domain.db.tables["providers"]
            exists = conn.execute(sa.select(table.c.id).where(table.c.id == value.id)).scalar()
            previous = self.domain.row(conn, "providers", value.id)["payload"] if exists else None
            if exists:
                self.domain.update(conn, "providers", value.id, payload=value.model_dump())
            else:
                self.domain.insert(conn, "providers", id=value.id, payload=value.model_dump())
        relevant = ("kind", "protocol", "base_url", "model", "region", "voice", "speech_expression")
        if previous is None or any(previous.get(key) != getattr(value, key) for key in relevant):
            self.domain.roleplay.provider_changed(value.id)
        return value

    def network_set(self, p: NetworkSet) -> ProviderList:
        with self.domain.db.transaction() as conn:
            table = self.domain.db.tables["preferences"]
            if conn.execute(sa.select(table.c.id).where(table.c.id == "network")).scalar():
                self.domain.update(conn, "preferences", "network", payload={"enabled": p.enabled})
            else:
                self.domain.insert(
                    conn, "preferences", id="network", payload={"enabled": p.enabled}
                )
        if not p.enabled:
            for worker in list(self.workers.values()):
                worker.cancel()
        return self.provider_list(None)

    def config(self, id_: str | None, secret: str, kind: str | None = None) -> ProviderRecord:
        from ..domain import require

        require(
            self.provider_list(None).external_enabled,
            "EXTERNAL_DISABLED",
            "外部服务已关闭，请在模型设置中明确启用。",
        )
        require(bool(id_), "PROVIDER_NOT_CONFIGURED", "请先选择并配置模型服务。")
        value = self.provider_get(ProviderTarget(config_id=id_ or ""))
        require(
            kind is None or value.kind == kind, "INVALID_PROVIDER", "所选配置的模型类型不匹配。"
        )
        require(
            not value.requires_key or bool(secret),
            "CREDENTIAL_REQUIRED",
            "此服务尚未保存密钥，请在模型设置中填写 API Key。",
        )
        require(
            len(self.workers) < 4,
            "CONCURRENCY_LIMIT",
            "已有多个模型任务运行，请等待或停止其中一个。",
        )
        return value

    def add_task(self, data: dict[str, Any], coroutine: Any) -> c.Task:
        from .. import contracts as c

        with self.domain.db.transaction() as conn:
            self.domain.insert(conn, "tasks", id=data["task_id"], payload=data)
        worker = asyncio.create_task(coroutine)
        self.workers[data["task_id"]] = worker
        worker.add_done_callback(lambda _: self.workers.pop(data["task_id"], None))
        return c.Task.model_validate({key: data[key] for key in c.Task.model_fields if key in data})

    @staticmethod
    def new_task(kind: str) -> dict[str, Any]:
        return {
            "task_id": uid(),
            "kind": kind,
            "status": "running",
            "seq": 0,
            "error_code": None,
            "generation_id": None,
            "remote": True,
            "emitted": 0,
            "usage": Usage().model_dump(),
            "message": None,
            "audio": None,
        }

    def start_writing(self, p: c.Generate, secret: str) -> c.Task:
        from ..domain import require

        require(bool(p.intent.strip()), "EMPTY_INTENT", "请先填写本次创作意图。")
        config = self.config(p.config_id, secret, "llm")
        with self.domain.db.transaction() as conn:
            state = self.domain.state(conn, p.branch_id, p.expected_snapshot)
            chapter = self.domain.chapter(state, p.chapter_id)
            context = self.domain.context(conn, p, config.context_limit, config.max_output_tokens)
            messages = writing_messages(context.model_dump(), p.intent)
            estimate = len(json.dumps(messages, ensure_ascii=False).encode("utf-8"))
            require(
                estimate + config.max_output_tokens + 512 <= config.context_limit,
                "CONTEXT_BUDGET_EXCEEDED",
                "正文、意图与所选设定超过上下文预算，请缩小范围或调整配置上限。",
            )
            generation_id = uid()
            self.domain.insert(
                conn,
                "generations",
                id=generation_id,
                payload={
                    "id": generation_id,
                    "artifact_kind": "prose",
                    "candidate_revision": uid(),
                    "text": "",
                    "accepted": False,
                    "branch_id": p.branch_id,
                    "base_snapshot": state["id"],
                    "chapter_id": p.chapter_id,
                    "anchor": chapter["anchor"],
                    "offset": p.offset,
                    "context": context.model_dump(),
                    "messages": messages,
                    "provider": "configured",
                    "provider_snapshot": config.model_dump(),
                    "accepted_ranges": [],
                },
            )
        data = self.new_task("writing")
        data["generation_id"] = generation_id
        return self.add_task(
            data, self.run_text(data["task_id"], config, secret, messages, generation_id)
        )

    def start_test(self, p: ProviderTarget, secret: str) -> c.Task:
        config = self.config(p.config_id, secret)
        data = self.new_task("test")
        if config.kind == "llm":
            config = config.model_copy(update={"max_output_tokens": 64})
            messages = [
                {"role": "system", "content": "只输出一个简短中文问候。"},
                {"role": "user", "content": "你好"},
            ]
            worker = self.run_text(data["task_id"], config, secret, messages, None)
        else:
            plan = AudioPlan(text="你好，这是一段语音测试。", segments=[], total_segments=1)
            data["audio"] = plan.model_dump()
            worker = self.run_speech(
                data["task_id"], config, secret, plan, [(0, len(plan.text), plan.text)]
            )
        return self.add_task(data, worker)

    def start_narration(self, p: NarrationRequest, secret: str) -> c.Task:
        from ..domain import require

        with self.domain.db.transaction() as conn:
            state = self.domain.state(conn, p.branch_id, p.expected_snapshot)
            chapter = self.domain.chapter(state, p.chapter_id)
            text = self.domain.row(conn, "revisions", chapter["revision"])["text"]
        require(bool(text.strip()), "EMPTY_DOCUMENT", "暂无已保存正文可朗读，不会创建语音请求。")
        require(
            len(text) <= p.max_characters,
            "NARRATION_LIMIT",
            "本章超过本次合成字符上限（最多一万字符），请先缩短或拆分章节。",
        )
        config = self.config(p.config_id, secret, "tts")
        pieces = split_text(text)
        plan = AudioPlan(
            branch_id=p.branch_id,
            chapter_id=p.chapter_id,
            revision=chapter["revision"],
            text=text,
            segments=[],
            total_segments=len(pieces),
        )
        data = self.new_task("narration")
        data["audio"] = plan.model_dump()
        return self.add_task(data, self.run_speech(data["task_id"], config, secret, plan, pieces))

    def update_task(self, task_id: str, **patch: Any) -> None:
        with self.domain.db.transaction() as conn:
            data = self.domain.row(conn, "tasks", task_id)["payload"]
            if data["status"] != "running":
                return
            data.update(patch, seq=data["seq"] + 1)
            self.domain.update(conn, "tasks", task_id, payload=data)

    def submitted(self, task_id: str, characters: int = 0) -> None:
        from ..domain import require

        require(
            self.provider_list(None).external_enabled,
            "EXTERNAL_DISABLED",
            "外部服务已关闭，不再发送新的请求。",
        )
        with self.domain.db.transaction() as conn:
            data = self.domain.row(conn, "tasks", task_id)["payload"]
            require(data["status"] == "running", "CANCELLED", "任务已停止。")
            usage = data["usage"]
            usage["requests_submitted"] += 1
            usage["input_characters"] += characters
            data.update(usage=usage)
            self.domain.update(conn, "tasks", task_id, payload=data)

    async def run_text(
        self,
        task_id: str,
        config: ProviderConfig,
        secret: str,
        messages: list[dict[str, str]],
        generation_id: str | None,
    ) -> None:
        text = ""
        usage = Usage()
        try:
            self.submitted(task_id)
            usage.requests_submitted = 1
            async for event in generate(config, secret, messages, self.transport):
                delta = event.get("delta", "")
                if isinstance(delta, str):
                    text += delta
                if len(text) > 100000:
                    raise ProviderError(
                        "OUTPUT_LIMIT", "输出已达应用上限，停止接收并保留已收到内容。"
                    )
                stats = event.get("usage", {})
                usage.input_tokens = stats.get(
                    "input_tokens", stats.get("prompt_tokens", usage.input_tokens)
                )
                usage.output_tokens = stats.get(
                    "output_tokens", stats.get("completion_tokens", usage.output_tokens)
                )
                usage.actual_model = event.get("model") or usage.actual_model
                if generation_id:
                    with self.domain.db.transaction() as conn:
                        data = self.domain.row(conn, "generations", generation_id)["payload"]
                        data.update(text=text, actual_model=usage.actual_model)
                        self.domain.update(conn, "generations", generation_id, payload=data)
                self.update_task(task_id, emitted=len(text), usage=usage.model_dump())
                await asyncio.sleep(0)
            if not text.strip():
                raise ProviderError(
                    "EMPTY_RESPONSE", "模型没有返回可用正文，请检查模型是否需要更大的输出上限。"
                )
            self.update_task(
                task_id,
                status="completed",
                message="生成完成" if generation_id else "测试成功：" + text[:160],
                usage=usage.model_dump(),
            )
        except asyncio.CancelledError:
            self.update_task(
                task_id,
                status="cancelled",
                error_code="CANCELLED",
                message="已停止接收，已提交的远端请求仍可能计费。",
            )
        except Exception as exc:  # noqa: BLE001 - sanitize external errors at task boundary
            self.failed(task_id, exc)

    def failed(self, task_id: str, error: Exception) -> None:
        code = getattr(error, "code", "PROVIDER_ERROR")
        safe = getattr(error, "message", "任务未完成，请检查模型配置后重试。")
        self.update_task(task_id, status="failed", error_code=code, message=safe)

    def cache_key(
        self, config: ProviderConfig, plan: AudioPlan, piece: tuple[int, int, str]
    ) -> str:
        fingerprint = {
            "text": piece[2],
            "revision": plan.revision,
            "range": piece[:2],
            "provider": {
                key: getattr(config, key)
                for key in ("protocol", "base_url", "model", "region", "voice")
            },
            "adapter": "speech-v1",
            "plan": "plain-v1",
            "format": "mp3" if config.protocol == "elevenlabs" else "wav",
        }
        return hashlib.sha256(
            json.dumps(fingerprint, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()

    async def cached_audio(
        self,
        config: ProviderConfig,
        secret: str,
        plan: AudioPlan,
        piece: tuple[int, int, str],
        submit: Callable[[], None],
        expression: tuple[str, float] | None = None,
    ) -> AudioSegment:
        # Caller holds audio_lock; narration and chat share validation, cache and assets.
        folder = self.domain.db.directory / "audio"
        folder.mkdir(exist_ok=True)
        key = self.cache_key(config, plan, piece)
        with self.domain.db.transaction() as conn:
            rows = (
                conn.execute(
                    sa.select(self.domain.db.tables["audio_assets"]).where(
                        self.domain.db.tables["audio_assets"].c.payload["cache_key"].as_string()
                        == key
                    )
                )
                .mappings()
                .all()
            )
        cached = None
        for row in rows:
            value = row["payload"]
            path = folder / (row["id"] + "." + value["format"])
            if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == value["checksum"]:
                cached = AudioSegment(
                    asset_id=row["id"],
                    start=piece[0],
                    end=piece[1],
                    duration=value["duration"],
                    mime_type=value["mime_type"],
                    cache_hit=True,
                )
                break
        if cached is None:
            submit()
            raw, _ = await synthesize(config, secret, piece[2], self.transport, expression)
            extension, mime, duration = validate_audio(raw)
            asset_id = uid()
            temp = folder / (asset_id + ".tmp")
            with temp.open("xb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            temp.replace(folder / (asset_id + "." + extension))
            with self.domain.db.transaction() as conn:
                self.domain.insert(
                    conn,
                    "audio_assets",
                    id=asset_id,
                    cache_key=key,
                    payload={
                        "cache_key": key,
                        "format": extension,
                        "mime_type": mime,
                        "duration": duration,
                        "checksum": hashlib.sha256(raw).hexdigest(),
                    },
                )
            cached = AudioSegment(
                asset_id=asset_id,
                start=piece[0],
                end=piece[1],
                duration=duration,
                mime_type=mime,
            )
        return cached

    async def run_speech(
        self,
        task_id: str,
        config: ProviderConfig,
        secret: str,
        plan: AudioPlan,
        pieces: list[tuple[int, int, str]],
    ) -> None:
        try:
            async with self.audio_lock:
                await self.speech_locked(task_id, config, secret, plan, pieces)
        except asyncio.CancelledError:
            self.update_task(
                task_id,
                status="cancelled",
                error_code="CANCELLED",
                message="语音任务已停止；已提交请求仍可能计费。",
            )

    async def speech_locked(
        self,
        task_id: str,
        config: ProviderConfig,
        secret: str,
        plan: AudioPlan,
        pieces: list[tuple[int, int, str]],
    ) -> None:
        try:
            folder = self.domain.db.directory / "audio"
            folder.mkdir(exist_ok=True)
            for piece in pieces:
                await asyncio.sleep(0)
                cached = await self.cached_audio(
                    config, secret, plan, piece, partial(self.submitted, task_id, len(piece[2]))
                )
                plan.segments.append(cached)
                self.update_task(
                    task_id,
                    audio=plan.model_dump(),
                    message=f"已准备 {len(plan.segments)}/{len(pieces)} 段；声音由 AI 生成。",
                )
            self.update_task(
                task_id,
                status="completed",
                audio=plan.model_dump(),
                message="语音准备完成；声音由 AI 生成。",
            )
        except asyncio.CancelledError:
            self.update_task(
                task_id,
                status="cancelled",
                error_code="CANCELLED",
                message="语音任务已停止；已提交请求仍可能计费。",
            )
        except Exception as exc:  # noqa: BLE001 - sanitize external errors at task boundary
            self.failed(task_id, exc)

    def audio_read(self, p: AudioRead) -> AudioData:
        from ..domain import require

        with self.domain.db.transaction() as conn:
            asset = self.domain.row(conn, "audio_assets", p.asset_id)["payload"]
        path = self.domain.db.directory / "audio" / (p.asset_id + "." + asset["format"])
        require(path.exists(), "AUDIO_MISSING", "音频缓存不存在，请重新准备语音。")
        raw = path.read_bytes()
        require(
            hashlib.sha256(raw).hexdigest() == asset["checksum"],
            "INVALID_AUDIO",
            "音频缓存校验失败，请重新合成。",
        )
        return AudioData(
            asset_id=p.asset_id,
            mime_type=asset["mime_type"],
            content_b64=base64.b64encode(raw).decode(),
        )

    def cancel(self, task_id: str) -> None:
        worker = self.workers.get(task_id)
        if worker:
            worker.cancel()

    async def close(self) -> None:
        workers = list(self.workers.values())
        for worker in workers:
            worker.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
