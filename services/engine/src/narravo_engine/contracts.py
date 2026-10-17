from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from . import roleplay_models as r
from .providers.models import (
    AudioData,
    AudioPlan,
    AudioRead,
    NarrationRequest,
    NetworkSet,
    ProviderCatalog,
    ProviderList,
    ProviderRecord,
    ProviderSave,
    ProviderTarget,
    Usage,
)

VERSION = 1


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Empty(Model):
    pass


class BookCreate(Model):
    title: str = Field(default="未命名作品", max_length=120)


class BranchTarget(Model):
    branch_id: str


class Expected(BranchTarget):
    expected_snapshot: str


class RestoreSnapshot(Expected):
    snapshot_id: str


class HistoryEntry(Model):
    snapshot_id: str
    word_count: int
    chapter_count: int
    planning_count: int


class History(Model):
    entries: list[HistoryEntry]


class ChapterTarget(BranchTarget):
    chapter_id: str


class ChapterSave(Expected):
    chapter_id: str
    text: str = Field(max_length=1_000_000)


class ChapterCreate(Expected):
    title: str = Field(default="新章节", max_length=120)


class ChapterUpdate(Expected):
    chapter_id: str
    title: str = Field(min_length=1, max_length=120)
    status: Literal["draft", "revising", "done"] = "draft"


class ChapterReorder(Expected):
    ordered_ids: list[str]


class ChapterRemove(Expected):
    chapter_id: str


class BranchFork(Expected):
    name: str = Field(default="新的可能", min_length=1, max_length=80)


class PlanningEntry(Model):
    id: str
    kind: Literal["brief", "character", "lore", "outline"]
    title: str = Field(min_length=1, max_length=120)
    text: str = Field(max_length=20000)
    context_role: Literal["setting", "planned_event"] = "setting"
    author_only: bool = False
    visible_from: str | None = None
    locked: bool = True


class PlanningSave(Expected):
    entries: list[PlanningEntry] = Field(max_length=500)


class ContextRequest(ChapterTarget):
    offset: int = Field(ge=0)
    context_policy: Literal["reader_safe", "author_plan", "full_rewrite"]
    selected_planning_ids: list[str] = Field(default_factory=list)
    rewrite_chapter_ids: list[str] = Field(default_factory=list)
    config_id: str | None = None


class Generate(ContextRequest):
    expected_snapshot: str
    intent: str = Field(max_length=2000)
    provider: Literal["demo", "configured"]


class Accept(Model):
    generation_id: str
    expected_snapshot: str
    candidate_revision: str
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    edited_text: str = Field(min_length=1, max_length=100000)
    idempotency_key: str = Field(min_length=1, max_length=100)


class TaskTarget(Model):
    task_id: str


class PreviewImport(Model):
    filename: str = Field(max_length=255)
    content_b64: str = Field(default="", max_length=14_000_000)
    asset_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    password: str = Field(default="", max_length=256)
    remove_pdf_margins: bool = False
    encoding: Literal["auto", "utf-8", "utf-16", "gb18030"] = "auto"


class ConfirmImport(Model):
    import_id: str
    accept_incomplete: bool = False
    title: str = Field(min_length=1, max_length=120)


class Export(BranchTarget):
    format: Literal["txt", "md"] = "txt"


class ChapterMeta(Model):
    id: str
    title: str
    status: Literal["draft", "revising", "done"]
    revision: str
    anchor: str
    word_count: int


class BranchInfo(Model):
    id: str
    name: str
    parent_id: str | None


class Workspace(Model):
    book_id: str
    title: str
    origin_type: Literal["original", "imported"]
    branch_id: str
    snapshot_id: str
    planning_revision: str
    branches: list[BranchInfo]
    chapters: list[ChapterMeta]
    planning: list[PlanningEntry]
    word_count: int


class BookSummary(Model):
    book_id: str
    title: str
    origin_type: Literal["original", "imported"]
    branch_id: str
    word_count: int
    chapter_count: int
    updated_at: str


class Library(Model):
    books: list[BookSummary]


class ChapterText(Model):
    chapter_id: str
    revision: str
    text: str
    anchor: str


class ContextPreview(Model):
    context_policy: str
    preceding_text: str
    planning: list[PlanningEntry]
    missing_chapter_ids: list[str]
    estimated_tokens: int
    token_estimation: Literal["estimated"] = "estimated"
    warning: str


class Generation(Model):
    id: str
    artifact_kind: Literal["prose"] = "prose"
    candidate_revision: str
    text: str
    accepted: bool = False


class Task(Model):
    task_id: str
    status: Literal["running", "completed", "cancelled", "failed"]
    kind: Literal["writing", "test", "narration", "roleplay", "chat_speech"] = "writing"
    message: str | None = None
    usage: Usage | None = None
    audio: AudioPlan | None = None
    seq: int
    generation: Generation | None = None
    error_code: str | None = None


class TaskSummary(Model):
    task_id: str
    status: str
    branch_id: str
    chapter_id: str
    title: str
    kind: Literal["writing", "test", "narration", "roleplay", "chat_speech"] = "writing"


class TaskList(Model):
    tasks: list[TaskSummary]


class ImportPreview(Model):
    import_id: str
    filename: str
    encoding: str
    warnings: list[str]
    chapters: list[str]
    sample: str
    omitted_pages: list[int] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)


class BackupCreate(Model):
    include_audio: bool = False


class RestorePreview(Model):
    asset_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    content_b64: str = Field(default="", max_length=14_000_000)


class OperationTarget(Model):
    operation_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class FileOperation(Model):
    operation_id: str
    kind: Literal["import", "backup", "restore"]
    status: Literal["running", "completed", "failed", "cancelled"]
    stage: str
    preview: ImportPreview | None = None
    book_count: int | None = None
    include_audio: bool = False
    size: int = 0
    error_code: str | None = None
    message: str = ""
    activated: bool = False
    previous_library_id: str | None = None


class ExportResult(Model):
    filename: str
    content: str


class Health(Model):
    schema_version: Literal[1] = 1
    engine_version: str = "0.1.0"
    provider: Literal["unconfigured", "configured"] = "unconfigured"
    external_enabled: bool = False


# This registry generates the JSON Schema, TypeScript method map and Rust allowlist.
METHODS: dict[str, tuple[type[BaseModel], type[BaseModel]]] = {
    "system.health": (Empty, Health),
    "roleplay.library": (Empty, r.RoleplayLibrary),
    "roleplay.character_get": (r.CharacterTarget, r.Character),
    "roleplay.local_message": (r.LocalMessage, r.ChatView),
    "roleplay.character_save": (r.CharacterSave, r.Character),
    "roleplay.create": (r.ChatCreate, r.ChatView),
    "roleplay.get": (r.ChatTarget, r.ChatView),
    "roleplay.configure": (r.ChatConfigure, r.ChatView),
    "roleplay.preview_context": (r.ChatContextRequest, r.ChatContext),
    "roleplay.memory_save": (r.MemorySave, r.ChatView),
    "roleplay.change_history": (r.HistoryChange, r.ChatView),
    "roleplay.export": (r.ChatTarget, ExportResult),
    "roleplay.copy_book_character": (r.BookCharacterCopy, r.CopyPreview),
    "roleplay.send": (r.ChatSend, r.Turn),
    "roleplay.turn_get": (r.TurnTarget, r.Turn),
    "roleplay.control": (r.TurnControl, r.Turn),
    "roleplay.silence": (r.ChatTarget, r.ChatView),
    "roleplay.playback": (r.ChatPlayback, r.Turn),
    "roleplay.synthesize": (r.SpeechRequest, r.Turn),
    "provider.catalog": (Empty, ProviderCatalog),
    "provider.list": (Empty, ProviderList),
    "provider.get": (ProviderTarget, ProviderRecord),
    "provider.validate": (ProviderSave, ProviderRecord),
    "provider.save": (ProviderSave, ProviderRecord),
    "provider.test": (ProviderTarget, Task),
    "network.set": (NetworkSet, ProviderList),
    "narration.synthesize": (NarrationRequest, Task),
    "audio.read": (AudioRead, AudioData),
    "book.list": (Empty, Library),
    "book.create": (BookCreate, Workspace),
    "book.preview_import": (PreviewImport, ImportPreview),
    "file.start_import": (PreviewImport, FileOperation),
    "file.get": (OperationTarget, FileOperation),
    "file.cancel": (OperationTarget, FileOperation),
    "backup.create": (BackupCreate, FileOperation),
    "backup.preview_restore": (RestorePreview, FileOperation),
    "backup.activate_restore": (OperationTarget, Library),
    "backup.return_previous": (OperationTarget, Library),
    "book.confirm_import": (ConfirmImport, Workspace),
    "book.export": (Export, ExportResult),
    "branch.get": (BranchTarget, Workspace),
    "branch.fork": (BranchFork, Workspace),
    "branch.history": (BranchTarget, History),
    "branch.restore": (RestoreSnapshot, Workspace),
    "chapter.get": (ChapterTarget, ChapterText),
    "chapter.save": (ChapterSave, Workspace),
    "chapter.create": (ChapterCreate, Workspace),
    "chapter.update": (ChapterUpdate, Workspace),
    "chapter.reorder": (ChapterReorder, Workspace),
    "chapter.remove": (ChapterRemove, Workspace),
    "planning.save": (PlanningSave, Workspace),
    "writing.preview_context": (ContextRequest, ContextPreview),
    "writing.generate": (Generate, Task),
    "writing.accept": (Accept, Workspace),
    "task.get": (TaskTarget, Task),
    "task.list": (Empty, TaskList),
    "task.cancel": (TaskTarget, Task),
}


class RpcRequest(Model):
    jsonrpc: Literal["2.0"]
    schema_version: Literal[1]
    id: str = Field(min_length=1, max_length=100)
    method: str
    params: dict[str, Any] = Field(default_factory=dict)
