"""Roleplay wire contracts; this module contains no provider SDK types."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Voice(Model):
    config_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    voice: str = Field(default="", max_length=160, pattern=r"^[\w.\-]*$")
    emotion: Literal[
        "auto", "neutral", "happy", "sad", "angry", "tense", "surprised", "gentle", "whisper"
    ] = "auto"
    locked: bool = True
    speed: float | None = Field(default=None, ge=0.5, le=2)


class Persona(Model):
    avatar: str = Field(default="", max_length=180000)

    @field_validator("avatar")
    @classmethod
    def validate_avatar(cls, value: str) -> str:
        from .roleplay.avatar import validate

        return validate(value)

    name: str = Field(min_length=1, max_length=120)
    introduction: str = Field(default="", max_length=2000)
    identity: str = Field(default="", max_length=2000)
    appearance: str = Field(default="", max_length=2000)
    background: str = Field(default="", max_length=8000)
    personality: str = Field(default="", max_length=4000)
    motivation: str = Field(default="", max_length=4000)
    relationships: str = Field(default="", max_length=4000)
    style: str = Field(default="", max_length=4000)
    opening: str = Field(default="", max_length=4000)
    examples: str = Field(default="", max_length=8000)
    private_knowledge: str = Field(default="", max_length=8000)
    voice_preference: str = Field(default="", max_length=2000)
    freeform: bool = False
    voice: Voice = Field(default_factory=Voice)


class Character(Model):
    id: str
    revision: str
    kind: Literal["character", "user"] = "character"
    archived: bool = False
    persona: Persona
    source: str | None = None


class CharacterSave(Model):
    id: str | None = None
    expected_revision: str | None = None
    kind: Literal["character", "user"] = "character"
    archived: bool = False
    persona: Persona


class CharacterTarget(Model):
    id: str
    revision: str | None = None


class ChatTarget(Model):
    conversation_id: str
    snapshot_id: str | None = None


class ChatExpected(Model):
    conversation_id: str
    expected_snapshot: str
    idempotency_key: str = Field(min_length=1, max_length=100)


class LocalMessage(ChatExpected):
    text: str = Field(min_length=1, max_length=20000)


class Member(Model):
    id: str
    character_id: str
    persona_revision: str
    name: str
    joined_seq: int = 0
    muted: bool = False
    removed: bool = False
    voice: Voice = Field(default_factory=Voice)


class ChatCreate(Model):
    title: str = Field(default="新的会话", min_length=1, max_length=120)
    character_ids: list[str] = Field(min_length=1, max_length=8)
    user_character_id: str | None = None
    scene: str = Field(default="", max_length=8000)


class ChatConfigure(ChatExpected):
    user_persona_revision: str | None = None
    title: str = Field(min_length=1, max_length=120)
    members: list[Member] = Field(min_length=1, max_length=500)
    add_character_ids: list[str] = Field(default_factory=list, max_length=8)
    user_character_id: str | None = None
    scene: str = Field(default="", max_length=8000)


class Budget(Model):
    max_requests: int = Field(default=24, ge=1, le=40)
    max_tokens: int = Field(default=65536, ge=512, le=500000)
    max_characters: int = Field(default=10000, ge=0, le=50000)
    max_cost: float | None = Field(default=None, gt=0, le=10000)
    currency: str = Field(default="CNY", min_length=1, max_length=8)
    input_per_million: float | None = Field(default=None, ge=0, le=100000)
    output_per_million: float | None = Field(default=None, ge=0, le=100000)
    speech_per_million: float | None = Field(default=None, ge=0, le=100000)
    price_source: str = Field(default="", max_length=500)
    price_date: str = Field(default="", max_length=40)


class ChatSend(ChatExpected):
    include_actions: bool = False
    text: str = Field(default="", max_length=20000)
    config_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    mode: Literal["mention", "round_robin", "all", "situation"] = "mention"
    member_ids: list[str] = Field(default_factory=list, max_length=8)
    continue_turn: bool = False
    retry_revision: str | None = None
    budget: Budget = Field(default_factory=Budget)
    auto_speech: bool = False
    speech_scope: Literal["all", "first"] = "all"
    tts_config_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")


class ChatContextRequest(ChatTarget):
    member_id: str
    config_id: str | None = None


class ChatContext(Model):
    conversation_id: str
    snapshot_id: str
    member_id: str
    context_policy: Literal["chat_scoped"] = "chat_scoped"
    messages: list[dict[str, str]]
    source_revisions: list[str]
    memory_ids: list[str]
    trimmed_revisions: list[str]
    estimated_tokens: int
    output_reserve: int
    warning: str = "token 数为保守估算；私有人设只向本角色注入，模型仍可能在公开回复中说出。"


class Message(Model):
    id: str
    revision: str
    conversation_id: str
    member_id: str | None = None
    speaker: str
    role: Literal["user", "assistant", "preset"]
    text: str
    status: Literal["complete", "interrupted", "streaming", "preset"]
    sequence: int
    turn_id: str | None = None
    input_snapshot: str | None = None
    visible_to: list[str] = Field(default_factory=list)
    kind: Literal["dialogue", "action"] = "dialogue"


class Memory(Model):
    id: str
    text: str = Field(min_length=1, max_length=4000)
    source_revisions: list[str] = Field(min_length=1, max_length=100)
    recipient_ids: list[str] = Field(default_factory=list, max_length=8)
    kind: Literal["fact", "inference"] = "fact"
    locked: bool = True


class MemorySave(ChatExpected):
    memory: Memory
    remove: bool = False


class HistoryChange(ChatExpected):
    kind: Literal["dialogue", "action"] | None = None
    revision: str
    action: Literal["edit", "select", "use_interrupted", "restore"]
    text: str = Field(default="", max_length=20000)


class Charge(Model):
    id: str
    kind: Literal["selection", "reply", "speech"]
    input_tokens: int = 0
    output_tokens: int = 0
    characters: int = 0
    reserved_cost: float | None = None
    status: Literal["reserved", "settled", "unknown"] = "reserved"
    actual_model: str | None = None


class SpeechSegment(Model):
    id: str
    revision: str
    conversation_id: str
    turn_id: str
    message_id: str
    variant_revision: str
    start: int
    end: int
    text: str
    text_hash: str
    voice: Voice
    requested_emotion: str
    provider_fingerprint: str = ""
    effective_emotion: str = "neutral"
    effective_speed: float = 1
    warning: str = "此配置未声明表达能力，使用普通语气；音色保持所选绑定。"
    kind: Literal["dialogue", "action"] = "dialogue"


class SpeechItem(Model):
    segment: SpeechSegment
    status: Literal["pending", "synthesizing", "ready", "played", "failed", "stopped"] = "pending"
    asset_id: str | None = None
    error: str | None = None
    cache_hit: bool = False
    epoch: int


class Turn(Model):
    model_config = ConfigDict(extra="ignore")
    contexts: list[ChatContext] = Field(default_factory=list)
    id: str
    task_id: str
    conversation_id: str
    base_snapshot: str
    expected_snapshot: str
    status: Literal["running", "completed", "cancelled", "failed"] = "running"
    seq: int = 0
    queue: list[str] = Field(default_factory=list)
    completed_members: list[str] = Field(default_factory=list)
    skipped_members: list[str] = Field(default_factory=list)
    messages: list[Message] = Field(default_factory=list)
    speech: list[SpeechItem] = Field(default_factory=list)
    charges: list[Charge] = Field(default_factory=list)
    budget: Budget
    playback_epoch: int
    speech_stopped: bool = False
    text_finished: bool = False
    auto_speech: bool = False
    retry_revision: str | None = None
    error_code: str | None = None
    notice: str = "费用未知；已提交的请求可能计费，未知结果不会自动重发。"


class TurnTarget(Model):
    turn_id: str


class TurnControl(TurnTarget):
    action: Literal["stop_speech", "stop_turn", "skip", "played"]
    member_id: str | None = None
    segment_id: str | None = None
    playback_epoch: int | None = None


class SpeechRequest(TurnTarget):
    segment_id: str | None = None
    config_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    playback_epoch: int


class ChatPlayback(ChatExpected):
    include_actions: bool = False
    source_segment_id: str | None = None
    message_revision: str
    tts_config_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    voice: Voice = Field(default_factory=Voice)
    budget: Budget = Field(default_factory=Budget)


class ChatSummary(Model):
    id: str
    title: str
    snapshot_id: str
    member_count: int
    active: bool = False


class RoleplayLibrary(Model):
    characters: list[Character]
    conversations: list[ChatSummary]


class ChatHistory(Model):
    snapshot_id: str
    parent_id: str | None
    message_count: int


class ChatView(Model):
    id: str
    title: str
    snapshot_id: str
    members: list[Member]
    user_character_id: str | None = None
    user_persona_revision: str | None = None
    scene: str
    messages: list[Message]
    variants: list[Message]
    memories: list[Memory]
    history: list[ChatHistory] = Field(title="Conversation snapshot history")
    turns: list[Turn]
    playback_epoch: int
    snapshot_sequence: int
    event_sequence: int


def default_copy_fields() -> list[Literal["introduction", "background"]]:
    return ["background"]


class BookCharacterCopy(Model):
    fields: list[Literal["introduction", "background"]] = Field(
        default_factory=default_copy_fields, min_length=1, max_length=2
    )
    branch_id: str
    expected_snapshot: str
    chapter_id: str
    offset: int = Field(ge=0)
    planning_id: str
    include_author: bool = False
    confirm: bool = False


class CopyPreview(Model):
    persona: Persona
    source: str
    warning: str
    character: Character | None = None
