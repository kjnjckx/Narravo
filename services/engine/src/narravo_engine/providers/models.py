from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

Protocol = Literal[
    "openai_chat", "openai_responses", "anthropic", "openai_speech", "minimax_speech", "elevenlabs"
]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProviderConfig(Model):
    id: str = Field(pattern=r"^[a-f0-9]{32}$")
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["llm", "tts"]
    protocol: Protocol
    base_url: str = Field(min_length=8, max_length=500)
    model: str = Field(min_length=1, max_length=160)
    region: str = Field(default="custom", max_length=80)
    voice: str = Field(default="", max_length=160, pattern=r"^[\w.\-]*$")
    context_limit: int = Field(default=16384, ge=2048, le=2_000_000)
    max_output_tokens: int = Field(default=2048, ge=16, le=32768)
    token_parameter: Literal["max_tokens", "max_completion_tokens"] = "max_tokens"
    include_usage: bool = False
    send_temperature: bool = False
    temperature: float = Field(default=0.8, ge=0, le=2)
    speech_expression: bool = False
    allow_local: bool = False
    requires_key: bool = True

    @model_validator(mode="after")
    def validate_provider(self) -> "ProviderConfig":
        parsed = urlsplit(self.base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Use a base URL without credentials, query or fragment")
        if parsed.scheme == "http" and not self.allow_local:
            raise ValueError("HTTP is allowed only for explicitly configured local services")
        if self.base_url.endswith(
            ("/chat/completions", "/messages", "/audio/speech", "/t2a_v2", "/responses")
        ):
            raise ValueError("Use the API base URL, not the full method path")
        if (self.kind == "tts") != (
            self.protocol in {"openai_speech", "minimax_speech", "elevenlabs"}
        ):
            raise ValueError("Provider kind and protocol do not match")
        if self.kind == "tts" and not self.voice.strip():
            raise ValueError("TTS requires an explicit voice")
        if self.max_output_tokens + 512 >= self.context_limit:
            raise ValueError("Output reserve must fit context limit")
        return self


class ProviderRecord(ProviderConfig):
    has_credential: bool = False


class ProviderSave(Model):
    config: ProviderConfig


class ProviderTarget(Model):
    config_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class ProviderList(Model):
    providers: list[ProviderRecord]
    external_enabled: bool


class ProviderTemplate(Model):
    id: str
    name: str
    kind: Literal["llm", "tts"]
    protocol: Protocol
    base_url: str
    region: str = "custom"
    model: str = ""
    voice: str = ""
    note: str = "使用 API 平台的密钥和模型 ID；账号权限需自行测试。"
    token_parameter: Literal["max_tokens", "max_completion_tokens"] = "max_tokens"


class ProviderCatalog(Model):
    templates: list[ProviderTemplate]
    checked_on: str = "2026-10-16"


class NetworkSet(Model):
    enabled: bool


class NarrationRequest(Model):
    config_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    branch_id: str
    chapter_id: str
    expected_snapshot: str
    max_characters: int = Field(default=10000, ge=1, le=10000)


class Usage(Model):
    input_tokens: int | None = None
    output_tokens: int | None = None
    input_characters: int = 0
    requests_submitted: int = 0
    cost_status: Literal["unknown", "local_demo"] = "unknown"
    actual_model: str | None = None


class AudioSegment(Model):
    asset_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    start: int
    end: int
    duration: float
    mime_type: Literal["audio/wav", "audio/mpeg"]
    cache_hit: bool = False


class AudioPlan(Model):
    branch_id: str | None = None
    chapter_id: str | None = None
    revision: str | None = None
    text: str
    segments: list[AudioSegment]
    total_segments: int


class AudioRead(Model):
    asset_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class AudioData(Model):
    asset_id: str
    mime_type: Literal["audio/wav", "audio/mpeg"]
    content_b64: str
