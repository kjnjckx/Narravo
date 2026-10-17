/* Generated from Python contracts. Do not edit. */

export type SchemaVersion = 1;
export type EngineVersion = string;
export type Provider = "unconfigured" | "configured";
export type ExternalEnabled = boolean;
export type Id = string;
export type Revision = string;
export type Kind = "character" | "user";
export type Archived = boolean;
export type Avatar = string;
export type Name = string;
export type Introduction = string;
export type Identity = string;
export type Appearance = string;
export type Background = string;
export type Personality = string;
export type Motivation = string;
export type Relationships = string;
export type Style = string;
export type Opening = string;
export type Examples = string;
export type PrivateKnowledge = string;
export type VoicePreference = string;
export type Freeform = boolean;
export type ConfigId = string | null;
export type Voice1 = string;
export type Emotion = "auto" | "neutral" | "happy" | "sad" | "angry" | "tense" | "surprised" | "gentle" | "whisper";
export type Locked = boolean;
export type Speed = number | null;
export type Source = string | null;
export type Characters = Character[];
export type Id1 = string;
export type Title = string;
export type SnapshotId = string;
export type MemberCount = number;
export type Active = boolean;
export type Conversations = ChatSummary[];
export type Id2 = string;
export type Revision1 = string | null;
export type ConversationId = string;
export type ExpectedSnapshot = string;
export type IdempotencyKey = string;
export type Text = string;
export type Id3 = string;
export type Title1 = string;
export type SnapshotId1 = string;
export type Id4 = string;
export type CharacterId = string;
export type PersonaRevision = string;
export type Name1 = string;
export type JoinedSeq = number;
export type Muted = boolean;
export type Removed = boolean;
export type Members = Member[];
export type UserCharacterId = string | null;
export type UserPersonaRevision = string | null;
export type Scene = string;
export type Id5 = string;
export type Revision2 = string;
export type ConversationId1 = string;
export type MemberId = string | null;
export type Speaker = string;
export type Role = "user" | "assistant" | "preset";
export type Text1 = string;
export type Status = "complete" | "interrupted" | "streaming" | "preset";
export type Sequence = number;
export type TurnId = string | null;
export type InputSnapshot = string | null;
export type VisibleTo = string[];
export type Kind1 = "dialogue" | "action";
export type Messages = Message[];
export type Variants = Message[];
export type Id6 = string;
export type Text2 = string;
/**
 * @minItems 1
 * @maxItems 100
 */
export type SourceRevisions = string[];
/**
 * @maxItems 8
 */
export type RecipientIds = string[];
export type Kind2 = "fact" | "inference";
export type Locked1 = boolean;
export type Memories = Memory[];
export type SnapshotId2 = string;
export type ParentId = string | null;
export type MessageCount = number;
export type ConversationSnapshotHistory = ChatHistory[];
export type ConversationId2 = string;
export type SnapshotId3 = string;
export type MemberId1 = string;
export type ContextPolicy = "chat_scoped";
export type Messages1 = {
  [k: string]: string;
}[];
export type SourceRevisions1 = string[];
export type MemoryIds = string[];
export type TrimmedRevisions = string[];
export type EstimatedTokens = number;
export type OutputReserve = number;
export type Warning = string;
export type Contexts = ChatContext[];
export type Id7 = string;
export type TaskId = string;
export type ConversationId3 = string;
export type BaseSnapshot = string;
export type ExpectedSnapshot1 = string;
export type Status1 = "running" | "completed" | "cancelled" | "failed";
export type Seq = number;
export type Queue = string[];
export type CompletedMembers = string[];
export type SkippedMembers = string[];
export type Messages2 = Message[];
export type Id8 = string;
export type Revision3 = string;
export type ConversationId4 = string;
export type TurnId1 = string;
export type MessageId = string;
export type VariantRevision = string;
export type Start = number;
export type End = number;
export type Text3 = string;
export type TextHash = string;
export type RequestedEmotion = string;
export type ProviderFingerprint = string;
export type EffectiveEmotion = string;
export type EffectiveSpeed = number;
export type Warning1 = string;
export type Kind3 = "dialogue" | "action";
export type Status2 = "pending" | "synthesizing" | "ready" | "played" | "failed" | "stopped";
export type AssetId = string | null;
export type Error = string | null;
export type CacheHit = boolean;
export type Epoch = number;
export type Speech = SpeechItem[];
export type Id9 = string;
export type Kind4 = "selection" | "reply" | "speech";
export type InputTokens = number;
export type OutputTokens = number;
export type Characters1 = number;
export type ReservedCost = number | null;
export type Status3 = "reserved" | "settled" | "unknown";
export type ActualModel = string | null;
export type Charges = Charge[];
export type MaxRequests = number;
export type MaxTokens = number;
export type MaxCharacters = number;
export type MaxCost = number | null;
export type Currency = string;
export type InputPerMillion = number | null;
export type OutputPerMillion = number | null;
export type SpeechPerMillion = number | null;
export type PriceSource = string;
export type PriceDate = string;
export type PlaybackEpoch = number;
export type SpeechStopped = boolean;
export type TextFinished = boolean;
export type AutoSpeech = boolean;
export type RetryRevision = string | null;
export type ErrorCode = string | null;
export type Notice = string;
export type Turns = Turn[];
export type PlaybackEpoch1 = number;
export type SnapshotSequence = number;
export type EventSequence = number;
export type Id10 = string | null;
export type ExpectedRevision = string | null;
export type Kind5 = "character" | "user";
export type Archived1 = boolean;
export type Title2 = string;
/**
 * @minItems 1
 * @maxItems 8
 */
export type CharacterIds = string[];
export type UserCharacterId1 = string | null;
export type Scene1 = string;
export type ConversationId5 = string;
export type SnapshotId4 = string | null;
export type ConversationId6 = string;
export type ExpectedSnapshot2 = string;
export type IdempotencyKey1 = string;
export type UserPersonaRevision1 = string | null;
export type Title3 = string;
/**
 * @minItems 1
 * @maxItems 500
 */
export type Members1 = Member[];
/**
 * @maxItems 8
 */
export type AddCharacterIds = string[];
export type UserCharacterId2 = string | null;
export type Scene2 = string;
export type ConversationId7 = string;
export type SnapshotId5 = string | null;
export type MemberId2 = string;
export type ConfigId1 = string | null;
export type ConversationId8 = string;
export type ExpectedSnapshot3 = string;
export type IdempotencyKey2 = string;
export type Remove = boolean;
export type ConversationId9 = string;
export type ExpectedSnapshot4 = string;
export type IdempotencyKey3 = string;
export type Kind6 = ("dialogue" | "action") | null;
export type Revision4 = string;
export type Action = "edit" | "select" | "use_interrupted" | "restore";
export type Text4 = string;
export type Filename = string;
export type Content = string;
/**
 * @minItems 1
 * @maxItems 2
 */
export type Fields = ("introduction" | "background")[];
export type BranchId = string;
export type ExpectedSnapshot5 = string;
export type ChapterId = string;
export type Offset = number;
export type PlanningId = string;
export type IncludeAuthor = boolean;
export type Confirm = boolean;
export type Source1 = string;
export type Warning2 = string;
export type ConversationId10 = string;
export type ExpectedSnapshot6 = string;
export type IdempotencyKey4 = string;
export type IncludeActions = boolean;
export type Text5 = string;
export type ConfigId2 = string;
export type Mode = "mention" | "round_robin" | "all" | "situation";
/**
 * @maxItems 8
 */
export type MemberIds = string[];
export type ContinueTurn = boolean;
export type RetryRevision1 = string | null;
export type AutoSpeech1 = boolean;
export type SpeechScope = "all" | "first";
export type TtsConfigId = string | null;
export type TurnId2 = string;
export type TurnId3 = string;
export type Action1 = "stop_speech" | "stop_turn" | "skip" | "played";
export type MemberId3 = string | null;
export type SegmentId = string | null;
export type PlaybackEpoch2 = number | null;
export type ConversationId11 = string;
export type ExpectedSnapshot7 = string;
export type IdempotencyKey5 = string;
export type IncludeActions1 = boolean;
export type SourceSegmentId = string | null;
export type MessageRevision = string;
export type TtsConfigId1 = string;
export type TurnId4 = string;
export type SegmentId1 = string | null;
export type ConfigId3 = string;
export type PlaybackEpoch3 = number;
export type Id11 = string;
export type Name2 = string;
export type Kind7 = "llm" | "tts";
export type Protocol =
  "openai_chat" | "openai_responses" | "anthropic" | "openai_speech" | "minimax_speech" | "elevenlabs";
export type BaseUrl = string;
export type Region = string;
export type Model = string;
export type Voice2 = string;
export type Note = string;
export type TokenParameter = "max_tokens" | "max_completion_tokens";
export type Templates = ProviderTemplate[];
export type CheckedOn = string;
export type Id12 = string;
export type Name3 = string;
export type Kind8 = "llm" | "tts";
export type Protocol1 =
  "openai_chat" | "openai_responses" | "anthropic" | "openai_speech" | "minimax_speech" | "elevenlabs";
export type BaseUrl1 = string;
export type Model1 = string;
export type Region1 = string;
export type Voice3 = string;
export type ContextLimit = number;
export type MaxOutputTokens = number;
export type TokenParameter1 = "max_tokens" | "max_completion_tokens";
export type IncludeUsage = boolean;
export type SendTemperature = boolean;
export type Temperature = number;
export type SpeechExpression = boolean;
export type AllowLocal = boolean;
export type RequiresKey = boolean;
export type HasCredential = boolean;
export type Providers = ProviderRecord[];
export type ExternalEnabled1 = boolean;
export type ConfigId4 = string;
export type Id13 = string;
export type Name4 = string;
export type Kind9 = "llm" | "tts";
export type Protocol2 =
  "openai_chat" | "openai_responses" | "anthropic" | "openai_speech" | "minimax_speech" | "elevenlabs";
export type BaseUrl2 = string;
export type Model2 = string;
export type Region2 = string;
export type Voice4 = string;
export type ContextLimit1 = number;
export type MaxOutputTokens1 = number;
export type TokenParameter2 = "max_tokens" | "max_completion_tokens";
export type IncludeUsage1 = boolean;
export type SendTemperature1 = boolean;
export type Temperature1 = number;
export type SpeechExpression1 = boolean;
export type AllowLocal1 = boolean;
export type RequiresKey1 = boolean;
export type TaskId1 = string;
export type Status4 = "running" | "completed" | "cancelled" | "failed";
export type Kind10 = "writing" | "test" | "narration" | "roleplay" | "chat_speech";
export type Message1 = string | null;
export type InputTokens1 = number | null;
export type OutputTokens1 = number | null;
export type InputCharacters = number;
export type RequestsSubmitted = number;
export type CostStatus = "unknown" | "local_demo";
export type ActualModel1 = string | null;
export type BranchId1 = string | null;
export type ChapterId1 = string | null;
export type Revision5 = string | null;
export type Text6 = string;
export type AssetId1 = string;
export type Start1 = number;
export type End1 = number;
export type Duration = number;
export type MimeType = "audio/wav" | "audio/mpeg";
export type CacheHit1 = boolean;
export type Segments = AudioSegment[];
export type TotalSegments = number;
export type Seq1 = number;
export type Id14 = string;
export type ArtifactKind = "prose";
export type CandidateRevision = string;
export type Text7 = string;
export type Accepted = boolean;
export type ErrorCode1 = string | null;
export type Enabled = boolean;
export type ConfigId5 = string;
export type BranchId2 = string;
export type ChapterId2 = string;
export type ExpectedSnapshot8 = string;
export type MaxCharacters1 = number;
export type AssetId2 = string;
export type AssetId3 = string;
export type MimeType1 = "audio/wav" | "audio/mpeg";
export type ContentB64 = string;
export type BookId = string;
export type Title4 = string;
export type OriginType = "original" | "imported";
export type BranchId3 = string;
export type WordCount = number;
export type ChapterCount = number;
export type UpdatedAt = string;
export type Books = BookSummary[];
export type Title5 = string;
export type BookId1 = string;
export type Title6 = string;
export type OriginType1 = "original" | "imported";
export type BranchId4 = string;
export type SnapshotId6 = string;
export type PlanningRevision = string;
export type Id15 = string;
export type Name5 = string;
export type ParentId1 = string | null;
export type Branches = BranchInfo[];
export type Id16 = string;
export type Title7 = string;
export type Status5 = "draft" | "revising" | "done";
export type Revision6 = string;
export type Anchor = string;
export type WordCount1 = number;
export type Chapters = ChapterMeta[];
export type Id17 = string;
export type Kind11 = "brief" | "character" | "lore" | "outline";
export type Title8 = string;
export type Text8 = string;
export type ContextRole = "setting" | "planned_event";
export type AuthorOnly = boolean;
export type VisibleFrom = string | null;
export type Locked2 = boolean;
export type Planning = PlanningEntry[];
export type WordCount2 = number;
export type Filename1 = string;
export type ContentB641 = string;
export type AssetId4 = string | null;
export type Password = string;
export type RemovePdfMargins = boolean;
export type Encoding = "auto" | "utf-8" | "utf-16" | "gb18030";
export type ImportId = string;
export type Filename2 = string;
export type Encoding1 = string;
export type Warnings = string[];
export type Chapters1 = string[];
export type Sample = string;
export type OmittedPages = number[];
export type OperationId = string;
export type Kind12 = "import" | "backup" | "restore";
export type Status6 = "running" | "completed" | "failed" | "cancelled";
export type Stage = string;
export type BookCount = number | null;
export type IncludeAudio = boolean;
export type Size = number;
export type ErrorCode2 = string | null;
export type Message2 = string;
export type Activated = boolean;
export type PreviousLibraryId = string | null;
export type OperationId1 = string;
export type IncludeAudio1 = boolean;
export type AssetId5 = string | null;
export type ContentB642 = string;
export type ImportId1 = string;
export type AcceptIncomplete = boolean;
export type Title9 = string;
export type BranchId5 = string;
export type Format = "txt" | "md";
export type BranchId6 = string;
export type BranchId7 = string;
export type ExpectedSnapshot9 = string;
export type Name6 = string;
export type SnapshotId7 = string;
export type WordCount3 = number;
export type ChapterCount1 = number;
export type PlanningCount = number;
export type Entries = HistoryEntry[];
export type BranchId8 = string;
export type ExpectedSnapshot10 = string;
export type SnapshotId8 = string;
export type BranchId9 = string;
export type ChapterId3 = string;
export type ChapterId4 = string;
export type Revision7 = string;
export type Text9 = string;
export type Anchor1 = string;
export type BranchId10 = string;
export type ExpectedSnapshot11 = string;
export type ChapterId5 = string;
export type Text10 = string;
export type BranchId11 = string;
export type ExpectedSnapshot12 = string;
export type Title10 = string;
export type BranchId12 = string;
export type ExpectedSnapshot13 = string;
export type ChapterId6 = string;
export type Title11 = string;
export type Status7 = "draft" | "revising" | "done";
export type BranchId13 = string;
export type ExpectedSnapshot14 = string;
export type OrderedIds = string[];
export type BranchId14 = string;
export type ExpectedSnapshot15 = string;
export type ChapterId7 = string;
export type BranchId15 = string;
export type ExpectedSnapshot16 = string;
/**
 * @maxItems 500
 */
export type Entries1 = PlanningEntry[];
export type BranchId16 = string;
export type ChapterId8 = string;
export type Offset1 = number;
export type ContextPolicy1 = "reader_safe" | "author_plan" | "full_rewrite";
export type SelectedPlanningIds = string[];
export type RewriteChapterIds = string[];
export type ConfigId6 = string | null;
export type ContextPolicy2 = string;
export type PrecedingText = string;
export type Planning1 = PlanningEntry[];
export type MissingChapterIds = string[];
export type EstimatedTokens1 = number;
export type TokenEstimation = "estimated";
export type Warning3 = string;
export type BranchId17 = string;
export type ChapterId9 = string;
export type Offset2 = number;
export type ContextPolicy3 = "reader_safe" | "author_plan" | "full_rewrite";
export type SelectedPlanningIds1 = string[];
export type RewriteChapterIds1 = string[];
export type ConfigId7 = string | null;
export type ExpectedSnapshot17 = string;
export type Intent = string;
export type Provider1 = "demo" | "configured";
export type GenerationId = string;
export type ExpectedSnapshot18 = string;
export type CandidateRevision1 = string;
export type Start2 = number;
export type End2 = number;
export type EditedText = string;
export type IdempotencyKey6 = string;
export type TaskId2 = string;
export type TaskId3 = string;
export type Status8 = string;
export type BranchId18 = string;
export type ChapterId10 = string;
export type Title12 = string;
export type Kind13 = "writing" | "test" | "narration" | "roleplay" | "chat_speech";
export type Tasks = TaskSummary[];

export interface Contracts {
  Empty: Empty;
  Health: Health;
  RoleplayLibrary: RoleplayLibrary;
  CharacterTarget: CharacterTarget;
  Character: Character;
  LocalMessage: LocalMessage;
  ChatView: ChatView;
  CharacterSave: CharacterSave;
  ChatCreate: ChatCreate;
  ChatTarget: ChatTarget;
  ChatConfigure: ChatConfigure;
  ChatContextRequest: ChatContextRequest;
  ChatContext: ChatContext;
  MemorySave: MemorySave;
  HistoryChange: HistoryChange;
  ExportResult: ExportResult;
  BookCharacterCopy: BookCharacterCopy;
  CopyPreview: CopyPreview;
  ChatSend: ChatSend;
  Turn: Turn;
  TurnTarget: TurnTarget;
  TurnControl: TurnControl;
  ChatPlayback: ChatPlayback;
  SpeechRequest: SpeechRequest;
  ProviderCatalog: ProviderCatalog;
  ProviderList: ProviderList;
  ProviderTarget: ProviderTarget;
  ProviderRecord: ProviderRecord;
  ProviderSave: ProviderSave;
  Task: Task;
  NetworkSet: NetworkSet;
  NarrationRequest: NarrationRequest;
  AudioRead: AudioRead;
  AudioData: AudioData;
  Library: Library;
  BookCreate: BookCreate;
  Workspace: Workspace;
  PreviewImport: PreviewImport;
  ImportPreview: ImportPreview;
  FileOperation: FileOperation;
  OperationTarget: OperationTarget;
  BackupCreate: BackupCreate;
  RestorePreview: RestorePreview;
  ConfirmImport: ConfirmImport;
  Export: Export;
  BranchTarget: BranchTarget;
  BranchFork: BranchFork;
  History: History;
  RestoreSnapshot: RestoreSnapshot;
  ChapterTarget: ChapterTarget;
  ChapterText: ChapterText;
  ChapterSave: ChapterSave;
  ChapterCreate: ChapterCreate;
  ChapterUpdate: ChapterUpdate;
  ChapterReorder: ChapterReorder;
  ChapterRemove: ChapterRemove;
  PlanningSave: PlanningSave;
  ContextRequest: ContextRequest;
  ContextPreview: ContextPreview;
  Generate: Generate;
  Accept: Accept;
  TaskTarget: TaskTarget;
  TaskList: TaskList;
}
export interface Empty {}
export interface Health {
  schema_version?: SchemaVersion;
  engine_version?: EngineVersion;
  provider?: Provider;
  external_enabled?: ExternalEnabled;
}
export interface RoleplayLibrary {
  characters: Characters;
  conversations: Conversations;
}
export interface Character {
  id: Id;
  revision: Revision;
  kind?: Kind;
  archived?: Archived;
  persona: Persona;
  source?: Source;
}
export interface Persona {
  avatar?: Avatar;
  name: Name;
  introduction?: Introduction;
  identity?: Identity;
  appearance?: Appearance;
  background?: Background;
  personality?: Personality;
  motivation?: Motivation;
  relationships?: Relationships;
  style?: Style;
  opening?: Opening;
  examples?: Examples;
  private_knowledge?: PrivateKnowledge;
  voice_preference?: VoicePreference;
  freeform?: Freeform;
  voice?: Voice;
}
export interface Voice {
  config_id?: ConfigId;
  voice?: Voice1;
  emotion?: Emotion;
  locked?: Locked;
  speed?: Speed;
}
export interface ChatSummary {
  id: Id1;
  title: Title;
  snapshot_id: SnapshotId;
  member_count: MemberCount;
  active?: Active;
}
export interface CharacterTarget {
  id: Id2;
  revision?: Revision1;
}
export interface LocalMessage {
  conversation_id: ConversationId;
  expected_snapshot: ExpectedSnapshot;
  idempotency_key: IdempotencyKey;
  text: Text;
}
export interface ChatView {
  id: Id3;
  title: Title1;
  snapshot_id: SnapshotId1;
  members: Members;
  user_character_id?: UserCharacterId;
  user_persona_revision?: UserPersonaRevision;
  scene: Scene;
  messages: Messages;
  variants: Variants;
  memories: Memories;
  history: ConversationSnapshotHistory;
  turns: Turns;
  playback_epoch: PlaybackEpoch1;
  snapshot_sequence: SnapshotSequence;
  event_sequence: EventSequence;
}
export interface Member {
  id: Id4;
  character_id: CharacterId;
  persona_revision: PersonaRevision;
  name: Name1;
  joined_seq?: JoinedSeq;
  muted?: Muted;
  removed?: Removed;
  voice?: Voice;
}
export interface Message {
  id: Id5;
  revision: Revision2;
  conversation_id: ConversationId1;
  member_id?: MemberId;
  speaker: Speaker;
  role: Role;
  text: Text1;
  status: Status;
  sequence: Sequence;
  turn_id?: TurnId;
  input_snapshot?: InputSnapshot;
  visible_to?: VisibleTo;
  kind?: Kind1;
}
export interface Memory {
  id: Id6;
  text: Text2;
  source_revisions: SourceRevisions;
  recipient_ids?: RecipientIds;
  kind?: Kind2;
  locked?: Locked1;
}
export interface ChatHistory {
  snapshot_id: SnapshotId2;
  parent_id: ParentId;
  message_count: MessageCount;
}
export interface Turn {
  contexts?: Contexts;
  id: Id7;
  task_id: TaskId;
  conversation_id: ConversationId3;
  base_snapshot: BaseSnapshot;
  expected_snapshot: ExpectedSnapshot1;
  status?: Status1;
  seq?: Seq;
  queue?: Queue;
  completed_members?: CompletedMembers;
  skipped_members?: SkippedMembers;
  messages?: Messages2;
  speech?: Speech;
  charges?: Charges;
  budget: Budget;
  playback_epoch: PlaybackEpoch;
  speech_stopped?: SpeechStopped;
  text_finished?: TextFinished;
  auto_speech?: AutoSpeech;
  retry_revision?: RetryRevision;
  error_code?: ErrorCode;
  notice?: Notice;
}
export interface ChatContext {
  conversation_id: ConversationId2;
  snapshot_id: SnapshotId3;
  member_id: MemberId1;
  context_policy?: ContextPolicy;
  messages: Messages1;
  source_revisions: SourceRevisions1;
  memory_ids: MemoryIds;
  trimmed_revisions: TrimmedRevisions;
  estimated_tokens: EstimatedTokens;
  output_reserve: OutputReserve;
  warning?: Warning;
}
export interface SpeechItem {
  segment: SpeechSegment;
  status?: Status2;
  asset_id?: AssetId;
  error?: Error;
  cache_hit?: CacheHit;
  epoch: Epoch;
}
export interface SpeechSegment {
  id: Id8;
  revision: Revision3;
  conversation_id: ConversationId4;
  turn_id: TurnId1;
  message_id: MessageId;
  variant_revision: VariantRevision;
  start: Start;
  end: End;
  text: Text3;
  text_hash: TextHash;
  voice: Voice;
  requested_emotion: RequestedEmotion;
  provider_fingerprint?: ProviderFingerprint;
  effective_emotion?: EffectiveEmotion;
  effective_speed?: EffectiveSpeed;
  warning?: Warning1;
  kind?: Kind3;
}
export interface Charge {
  id: Id9;
  kind: Kind4;
  input_tokens?: InputTokens;
  output_tokens?: OutputTokens;
  characters?: Characters1;
  reserved_cost?: ReservedCost;
  status?: Status3;
  actual_model?: ActualModel;
}
export interface Budget {
  max_requests?: MaxRequests;
  max_tokens?: MaxTokens;
  max_characters?: MaxCharacters;
  max_cost?: MaxCost;
  currency?: Currency;
  input_per_million?: InputPerMillion;
  output_per_million?: OutputPerMillion;
  speech_per_million?: SpeechPerMillion;
  price_source?: PriceSource;
  price_date?: PriceDate;
}
export interface CharacterSave {
  id?: Id10;
  expected_revision?: ExpectedRevision;
  kind?: Kind5;
  archived?: Archived1;
  persona: Persona;
}
export interface ChatCreate {
  title?: Title2;
  character_ids: CharacterIds;
  user_character_id?: UserCharacterId1;
  scene?: Scene1;
}
export interface ChatTarget {
  conversation_id: ConversationId5;
  snapshot_id?: SnapshotId4;
}
export interface ChatConfigure {
  conversation_id: ConversationId6;
  expected_snapshot: ExpectedSnapshot2;
  idempotency_key: IdempotencyKey1;
  user_persona_revision?: UserPersonaRevision1;
  title: Title3;
  members: Members1;
  add_character_ids?: AddCharacterIds;
  user_character_id?: UserCharacterId2;
  scene?: Scene2;
}
export interface ChatContextRequest {
  conversation_id: ConversationId7;
  snapshot_id?: SnapshotId5;
  member_id: MemberId2;
  config_id?: ConfigId1;
}
export interface MemorySave {
  conversation_id: ConversationId8;
  expected_snapshot: ExpectedSnapshot3;
  idempotency_key: IdempotencyKey2;
  memory: Memory;
  remove?: Remove;
}
export interface HistoryChange {
  conversation_id: ConversationId9;
  expected_snapshot: ExpectedSnapshot4;
  idempotency_key: IdempotencyKey3;
  kind?: Kind6;
  revision: Revision4;
  action: Action;
  text?: Text4;
}
export interface ExportResult {
  filename: Filename;
  content: Content;
}
export interface BookCharacterCopy {
  fields?: Fields;
  branch_id: BranchId;
  expected_snapshot: ExpectedSnapshot5;
  chapter_id: ChapterId;
  offset: Offset;
  planning_id: PlanningId;
  include_author?: IncludeAuthor;
  confirm?: Confirm;
}
export interface CopyPreview {
  persona: Persona;
  source: Source1;
  warning: Warning2;
  character?: Character | null;
}
export interface ChatSend {
  conversation_id: ConversationId10;
  expected_snapshot: ExpectedSnapshot6;
  idempotency_key: IdempotencyKey4;
  include_actions?: IncludeActions;
  text?: Text5;
  config_id: ConfigId2;
  mode?: Mode;
  member_ids?: MemberIds;
  continue_turn?: ContinueTurn;
  retry_revision?: RetryRevision1;
  budget?: Budget;
  auto_speech?: AutoSpeech1;
  speech_scope?: SpeechScope;
  tts_config_id?: TtsConfigId;
}
export interface TurnTarget {
  turn_id: TurnId2;
}
export interface TurnControl {
  turn_id: TurnId3;
  action: Action1;
  member_id?: MemberId3;
  segment_id?: SegmentId;
  playback_epoch?: PlaybackEpoch2;
}
export interface ChatPlayback {
  conversation_id: ConversationId11;
  expected_snapshot: ExpectedSnapshot7;
  idempotency_key: IdempotencyKey5;
  include_actions?: IncludeActions1;
  source_segment_id?: SourceSegmentId;
  message_revision: MessageRevision;
  tts_config_id: TtsConfigId1;
  voice?: Voice;
  budget?: Budget;
}
export interface SpeechRequest {
  turn_id: TurnId4;
  segment_id?: SegmentId1;
  config_id: ConfigId3;
  playback_epoch: PlaybackEpoch3;
}
export interface ProviderCatalog {
  templates: Templates;
  checked_on?: CheckedOn;
}
export interface ProviderTemplate {
  id: Id11;
  name: Name2;
  kind: Kind7;
  protocol: Protocol;
  base_url: BaseUrl;
  region?: Region;
  model?: Model;
  voice?: Voice2;
  note?: Note;
  token_parameter?: TokenParameter;
}
export interface ProviderList {
  providers: Providers;
  external_enabled: ExternalEnabled1;
}
export interface ProviderRecord {
  id: Id12;
  name: Name3;
  kind: Kind8;
  protocol: Protocol1;
  base_url: BaseUrl1;
  model: Model1;
  region?: Region1;
  voice?: Voice3;
  context_limit?: ContextLimit;
  max_output_tokens?: MaxOutputTokens;
  token_parameter?: TokenParameter1;
  include_usage?: IncludeUsage;
  send_temperature?: SendTemperature;
  temperature?: Temperature;
  speech_expression?: SpeechExpression;
  allow_local?: AllowLocal;
  requires_key?: RequiresKey;
  has_credential?: HasCredential;
}
export interface ProviderTarget {
  config_id: ConfigId4;
}
export interface ProviderSave {
  config: ProviderConfig;
}
export interface ProviderConfig {
  id: Id13;
  name: Name4;
  kind: Kind9;
  protocol: Protocol2;
  base_url: BaseUrl2;
  model: Model2;
  region?: Region2;
  voice?: Voice4;
  context_limit?: ContextLimit1;
  max_output_tokens?: MaxOutputTokens1;
  token_parameter?: TokenParameter2;
  include_usage?: IncludeUsage1;
  send_temperature?: SendTemperature1;
  temperature?: Temperature1;
  speech_expression?: SpeechExpression1;
  allow_local?: AllowLocal1;
  requires_key?: RequiresKey1;
}
export interface Task {
  task_id: TaskId1;
  status: Status4;
  kind?: Kind10;
  message?: Message1;
  usage?: Usage | null;
  audio?: AudioPlan | null;
  seq: Seq1;
  generation?: Generation | null;
  error_code?: ErrorCode1;
}
export interface Usage {
  input_tokens?: InputTokens1;
  output_tokens?: OutputTokens1;
  input_characters?: InputCharacters;
  requests_submitted?: RequestsSubmitted;
  cost_status?: CostStatus;
  actual_model?: ActualModel1;
}
export interface AudioPlan {
  branch_id?: BranchId1;
  chapter_id?: ChapterId1;
  revision?: Revision5;
  text: Text6;
  segments: Segments;
  total_segments: TotalSegments;
}
export interface AudioSegment {
  asset_id: AssetId1;
  start: Start1;
  end: End1;
  duration: Duration;
  mime_type: MimeType;
  cache_hit?: CacheHit1;
}
export interface Generation {
  id: Id14;
  artifact_kind?: ArtifactKind;
  candidate_revision: CandidateRevision;
  text: Text7;
  accepted?: Accepted;
}
export interface NetworkSet {
  enabled: Enabled;
}
export interface NarrationRequest {
  config_id: ConfigId5;
  branch_id: BranchId2;
  chapter_id: ChapterId2;
  expected_snapshot: ExpectedSnapshot8;
  max_characters?: MaxCharacters1;
}
export interface AudioRead {
  asset_id: AssetId2;
}
export interface AudioData {
  asset_id: AssetId3;
  mime_type: MimeType1;
  content_b64: ContentB64;
}
export interface Library {
  books: Books;
}
export interface BookSummary {
  book_id: BookId;
  title: Title4;
  origin_type: OriginType;
  branch_id: BranchId3;
  word_count: WordCount;
  chapter_count: ChapterCount;
  updated_at: UpdatedAt;
}
export interface BookCreate {
  title?: Title5;
}
export interface Workspace {
  book_id: BookId1;
  title: Title6;
  origin_type: OriginType1;
  branch_id: BranchId4;
  snapshot_id: SnapshotId6;
  planning_revision: PlanningRevision;
  branches: Branches;
  chapters: Chapters;
  planning: Planning;
  word_count: WordCount2;
}
export interface BranchInfo {
  id: Id15;
  name: Name5;
  parent_id: ParentId1;
}
export interface ChapterMeta {
  id: Id16;
  title: Title7;
  status: Status5;
  revision: Revision6;
  anchor: Anchor;
  word_count: WordCount1;
}
export interface PlanningEntry {
  id: Id17;
  kind: Kind11;
  title: Title8;
  text: Text8;
  context_role?: ContextRole;
  author_only?: AuthorOnly;
  visible_from?: VisibleFrom;
  locked?: Locked2;
}
export interface PreviewImport {
  filename: Filename1;
  content_b64?: ContentB641;
  asset_id?: AssetId4;
  password?: Password;
  remove_pdf_margins?: RemovePdfMargins;
  encoding?: Encoding;
}
export interface ImportPreview {
  import_id: ImportId;
  filename: Filename2;
  encoding: Encoding1;
  warnings: Warnings;
  chapters: Chapters1;
  sample: Sample;
  omitted_pages?: OmittedPages;
  metadata?: Metadata;
}
export interface Metadata {
  [k: string]: string;
}
export interface FileOperation {
  operation_id: OperationId;
  kind: Kind12;
  status: Status6;
  stage: Stage;
  preview?: ImportPreview | null;
  book_count?: BookCount;
  include_audio?: IncludeAudio;
  size?: Size;
  error_code?: ErrorCode2;
  message?: Message2;
  activated?: Activated;
  previous_library_id?: PreviousLibraryId;
}
export interface OperationTarget {
  operation_id: OperationId1;
}
export interface BackupCreate {
  include_audio?: IncludeAudio1;
}
export interface RestorePreview {
  asset_id?: AssetId5;
  content_b64?: ContentB642;
}
export interface ConfirmImport {
  import_id: ImportId1;
  accept_incomplete?: AcceptIncomplete;
  title: Title9;
}
export interface Export {
  branch_id: BranchId5;
  format?: Format;
}
export interface BranchTarget {
  branch_id: BranchId6;
}
export interface BranchFork {
  branch_id: BranchId7;
  expected_snapshot: ExpectedSnapshot9;
  name?: Name6;
}
export interface History {
  entries: Entries;
}
export interface HistoryEntry {
  snapshot_id: SnapshotId7;
  word_count: WordCount3;
  chapter_count: ChapterCount1;
  planning_count: PlanningCount;
}
export interface RestoreSnapshot {
  branch_id: BranchId8;
  expected_snapshot: ExpectedSnapshot10;
  snapshot_id: SnapshotId8;
}
export interface ChapterTarget {
  branch_id: BranchId9;
  chapter_id: ChapterId3;
}
export interface ChapterText {
  chapter_id: ChapterId4;
  revision: Revision7;
  text: Text9;
  anchor: Anchor1;
}
export interface ChapterSave {
  branch_id: BranchId10;
  expected_snapshot: ExpectedSnapshot11;
  chapter_id: ChapterId5;
  text: Text10;
}
export interface ChapterCreate {
  branch_id: BranchId11;
  expected_snapshot: ExpectedSnapshot12;
  title?: Title10;
}
export interface ChapterUpdate {
  branch_id: BranchId12;
  expected_snapshot: ExpectedSnapshot13;
  chapter_id: ChapterId6;
  title: Title11;
  status?: Status7;
}
export interface ChapterReorder {
  branch_id: BranchId13;
  expected_snapshot: ExpectedSnapshot14;
  ordered_ids: OrderedIds;
}
export interface ChapterRemove {
  branch_id: BranchId14;
  expected_snapshot: ExpectedSnapshot15;
  chapter_id: ChapterId7;
}
export interface PlanningSave {
  branch_id: BranchId15;
  expected_snapshot: ExpectedSnapshot16;
  entries: Entries1;
}
export interface ContextRequest {
  branch_id: BranchId16;
  chapter_id: ChapterId8;
  offset: Offset1;
  context_policy: ContextPolicy1;
  selected_planning_ids?: SelectedPlanningIds;
  rewrite_chapter_ids?: RewriteChapterIds;
  config_id?: ConfigId6;
}
export interface ContextPreview {
  context_policy: ContextPolicy2;
  preceding_text: PrecedingText;
  planning: Planning1;
  missing_chapter_ids: MissingChapterIds;
  estimated_tokens: EstimatedTokens1;
  token_estimation?: TokenEstimation;
  warning: Warning3;
}
export interface Generate {
  branch_id: BranchId17;
  chapter_id: ChapterId9;
  offset: Offset2;
  context_policy: ContextPolicy3;
  selected_planning_ids?: SelectedPlanningIds1;
  rewrite_chapter_ids?: RewriteChapterIds1;
  config_id?: ConfigId7;
  expected_snapshot: ExpectedSnapshot17;
  intent: Intent;
  provider: Provider1;
}
export interface Accept {
  generation_id: GenerationId;
  expected_snapshot: ExpectedSnapshot18;
  candidate_revision: CandidateRevision1;
  start: Start2;
  end: End2;
  edited_text: EditedText;
  idempotency_key: IdempotencyKey6;
}
export interface TaskTarget {
  task_id: TaskId2;
}
export interface TaskList {
  tasks: Tasks;
}
export interface TaskSummary {
  task_id: TaskId3;
  status: Status8;
  branch_id: BranchId18;
  chapter_id: ChapterId10;
  title: Title12;
  kind?: Kind13;
}

export interface RpcMethods {
  'system.health': { params: Empty; result: Health };
  'roleplay.library': { params: Empty; result: RoleplayLibrary };
  'roleplay.character_get': { params: CharacterTarget; result: Character };
  'roleplay.local_message': { params: LocalMessage; result: ChatView };
  'roleplay.character_save': { params: CharacterSave; result: Character };
  'roleplay.create': { params: ChatCreate; result: ChatView };
  'roleplay.get': { params: ChatTarget; result: ChatView };
  'roleplay.configure': { params: ChatConfigure; result: ChatView };
  'roleplay.preview_context': { params: ChatContextRequest; result: ChatContext };
  'roleplay.memory_save': { params: MemorySave; result: ChatView };
  'roleplay.change_history': { params: HistoryChange; result: ChatView };
  'roleplay.export': { params: ChatTarget; result: ExportResult };
  'roleplay.copy_book_character': { params: BookCharacterCopy; result: CopyPreview };
  'roleplay.send': { params: ChatSend; result: Turn };
  'roleplay.turn_get': { params: TurnTarget; result: Turn };
  'roleplay.control': { params: TurnControl; result: Turn };
  'roleplay.silence': { params: ChatTarget; result: ChatView };
  'roleplay.playback': { params: ChatPlayback; result: Turn };
  'roleplay.synthesize': { params: SpeechRequest; result: Turn };
  'provider.catalog': { params: Empty; result: ProviderCatalog };
  'provider.list': { params: Empty; result: ProviderList };
  'provider.get': { params: ProviderTarget; result: ProviderRecord };
  'provider.validate': { params: ProviderSave; result: ProviderRecord };
  'provider.save': { params: ProviderSave; result: ProviderRecord };
  'provider.test': { params: ProviderTarget; result: Task };
  'network.set': { params: NetworkSet; result: ProviderList };
  'narration.synthesize': { params: NarrationRequest; result: Task };
  'audio.read': { params: AudioRead; result: AudioData };
  'book.list': { params: Empty; result: Library };
  'book.create': { params: BookCreate; result: Workspace };
  'book.preview_import': { params: PreviewImport; result: ImportPreview };
  'file.start_import': { params: PreviewImport; result: FileOperation };
  'file.get': { params: OperationTarget; result: FileOperation };
  'file.cancel': { params: OperationTarget; result: FileOperation };
  'backup.create': { params: BackupCreate; result: FileOperation };
  'backup.preview_restore': { params: RestorePreview; result: FileOperation };
  'backup.activate_restore': { params: OperationTarget; result: Library };
  'backup.return_previous': { params: OperationTarget; result: Library };
  'book.confirm_import': { params: ConfirmImport; result: Workspace };
  'book.export': { params: Export; result: ExportResult };
  'branch.get': { params: BranchTarget; result: Workspace };
  'branch.fork': { params: BranchFork; result: Workspace };
  'branch.history': { params: BranchTarget; result: History };
  'branch.restore': { params: RestoreSnapshot; result: Workspace };
  'chapter.get': { params: ChapterTarget; result: ChapterText };
  'chapter.save': { params: ChapterSave; result: Workspace };
  'chapter.create': { params: ChapterCreate; result: Workspace };
  'chapter.update': { params: ChapterUpdate; result: Workspace };
  'chapter.reorder': { params: ChapterReorder; result: Workspace };
  'chapter.remove': { params: ChapterRemove; result: Workspace };
  'planning.save': { params: PlanningSave; result: Workspace };
  'writing.preview_context': { params: ContextRequest; result: ContextPreview };
  'writing.generate': { params: Generate; result: Task };
  'writing.accept': { params: Accept; result: Workspace };
  'task.get': { params: TaskTarget; result: Task };
  'task.list': { params: Empty; result: TaskList };
  'task.cancel': { params: TaskTarget; result: Task };
}
