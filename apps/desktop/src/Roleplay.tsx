import { useEffect, useRef, useState, type ReactNode } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import {
  MessageCircle,
  Plus,
  X,
  ArrowLeft,
  Square,
  Users,
  Download,
  Settings2,
} from 'lucide-react';
import type {
  Budget,
  Character,
  ChatContext,
  ChatView,
  Member,
  Memory,
  Persona,
  ProviderList,
  RoleplayLibrary,
  Voice,
  Message,
} from '../../../packages/contracts';
import { connected, exportChat, rpc } from './rpc';
import { message as errorMessage } from './store';
import { ChatAudio } from './ChatAudio';
import { stopAudioFocus } from './audioPlayback';

const key = () => crypto.randomUUID();
const blankVoice = (): Voice => ({
  config_id: null,
  voice: '',
  emotion: 'auto',
  locked: true,
  speed: null,
});
const blankPersona = (): Persona => ({
  name: '',
  introduction: '',
  identity: '',
  appearance: '',
  background: '',
  personality: '',
  motivation: '',
  relationships: '',
  style: '',
  opening: '',
  examples: '',
  private_knowledge: '',
  voice_preference: '',
  freeform: false,
  voice: blankVoice(),
});
const initialBudget = (): Budget => ({
  max_requests: 24,
  max_tokens: 65536,
  max_characters: 10000,
  max_cost: null,
  currency: 'CNY',
  input_per_million: null,
  output_per_million: null,
  speech_per_million: null,
  price_source: '',
  price_date: '',
});
const req = (view: ChatView) => ({
  conversation_id: view.id,
  expected_snapshot: view.snapshot_id,
  idempotency_key: key(),
});
const fields = [
  ['introduction', '公开简介'],
  ['identity', '身份 / 物种'],
  ['appearance', '外观'],
  ['background', '背景'],
  ['personality', '性格'],
  ['motivation', '动机、目标、价值观与限制'],
  ['relationships', '关系（外部人物请明确描述）'],
  ['style', '称呼、口头禅与表达风格'],
  ['opening', '预设开场白'],
  ['examples', '示例对白（不作为历史）'],
  ['private_knowledge', '私有知识（只注入本角色请求）'],
  ['voice_preference', '声音偏好描述'],
] as const;

function Sheet({
  title,
  close,
  children,
  error,
}: {
  title: string;
  close: () => void;
  children: ReactNode;
  error?: string;
}) {
  return (
    <Dialog.Root
      open
      onOpenChange={(open) => {
        if (!open) close();
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="modal-overlay" />
        <Dialog.Content className="modal rp-modal">
          <div className="modal-header">
            <Dialog.Title>{title}</Dialog.Title>
            <Dialog.Close aria-label="关闭" className="icon-button">
              <X size={19} />
            </Dialog.Close>
          </div>
          <Dialog.Description className="small muted">
            修改会保存于本机；生成时才将所选资料发给模型。
          </Dialog.Description>
          {error && (
            <div className="error-banner" role="alert">
              {error}
            </div>
          )}
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function VoiceFields({
  value,
  onChange,
  providers,
}: {
  value: Voice;
  onChange: (voice: Voice) => void;
  providers: ProviderList;
}) {
  return (
    <div className="rp-voice-fields">
      <label>
        语音服务
        <select
          value={value.config_id ?? ''}
          onChange={(e) => {
            const config = providers.providers.find((p) => p.id === e.target.value);
            onChange({ ...value, config_id: config?.id ?? null, voice: config?.voice ?? '' });
          }}
        >
          <option value="">使用发送时预选的默认声音</option>
          {providers.providers
            .filter((p) => p.kind === 'tts')
            .map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} · {p.model} / {p.region}
              </option>
            ))}
        </select>
      </label>
      <label>
        固定音色 ID
        <input
          value={value.voice}
          pattern="[\w.\-]*"
          onChange={(e) => onChange({ ...value, voice: e.target.value })}
          placeholder="留空使用所选服务的预选声音"
        />
      </label>
      <label>
        语气覆盖
        <select
          value={value.emotion}
          onChange={(e) => onChange({ ...value, emotion: e.target.value as Voice['emotion'] })}
        >
          {Object.entries({
            auto: '结合人设与场景建议',
            neutral: '普通',
            happy: '开心',
            sad: '悲伤',
            angry: '生气',
            tense: '紧张',
            surprised: '惊讶',
            gentle: '温柔',
            whisper: '低声',
          }).map(([id, label]) => (
            <option key={id} value={id}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <label>
        合成语速覆盖（留空按场景建议）
        <input
          aria-label="合成语速覆盖"
          type="number"
          min="0.5"
          max="2"
          step="0.05"
          value={value.speed ?? ''}
          onChange={(e) =>
            onChange({ ...value, speed: e.target.value ? Number(e.target.value) : null })
          }
        />
      </label>
      <label className="check-row">
        <input
          type="checkbox"
          checked={value.locked}
          onChange={(e) => onChange({ ...value, locked: e.target.checked })}
        />
        锁定人工声音绑定
      </label>
      <small>
        语气建议结合可见对话、人设与场景在本地计算。设置中可按具体配置启用 MiniMax 2.6
        表达能力；不支持时明确回退普通语气，不更换服务或音色。
      </small>
    </div>
  );
}

export function Roleplay({
  providers,
  llmId,
  ttsId,
  setLlmId,
  setTtsId,
  openSettings,
  openBackup,
}: {
  providers: ProviderList;
  llmId: string;
  ttsId: string;
  setLlmId: (id: string) => void;
  setTtsId: (id: string) => void;
  openSettings: (kind: 'llm' | 'tts') => void;
  openBackup: () => void;
}) {
  const [library, setLibrary] = useState<RoleplayLibrary>({ characters: [], conversations: [] });
  const [view, setView] = useState<ChatView | null>(null);
  const latest = useRef<ChatView | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState('');
  const [mode, setMode] = useState<'mention' | 'round_robin' | 'all' | 'situation'>('mention');
  const [mentions, setMentions] = useState<string[]>([]);
  const [autoSpeech, setAutoSpeech] = useState(false);
  const [speechScope, setSpeechScope] = useState<'all' | 'first'>('all');
  const [userRevision, setUserRevision] = useState<string | null>(null);
  const [segmentEmotions, setSegmentEmotions] = useState<Record<string, Voice['emotion']>>({});
  const [budget, setBudget] = useState<Budget>(initialBudget);
  const [playTurnId, setPlayTurnId] = useState<string | null>(null);
  const requestedSpeech = useRef('');
  const generation = useRef(0);
  const [sheet, setSheet] = useState<
    'character' | 'create' | 'members' | 'context' | 'memory' | 'history' | 'copy' | null
  >(null);
  const [editing, setEditing] = useState<Character | null>(null);
  const [persona, setPersona] = useState<Persona>(blankPersona);
  const [kind, setKind] = useState<'character' | 'user'>('character');
  const [title, setTitle] = useState('新的会话');
  const [scene, setScene] = useState('');
  const [userId, setUserId] = useState('');
  const [selectedChars, setSelectedChars] = useState<string[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [comparison, setComparison] = useState<{
    memberId: string;
    old: Character;
    next: Character;
  } | null>(null);
  const [context, setContext] = useState<ChatContext | null>(null);
  const [contextMember, setContextMember] = useState('');
  const [editMessage, setEditMessage] = useState<Message | null>(null);
  const [editText, setEditText] = useState('');
  const [editKind, setEditKind] = useState<'dialogue' | 'action'>('dialogue');
  const [includeActions, setIncludeActions] = useState(false);
  const [memoryText, setMemoryText] = useState('');
  const [memorySources, setMemorySources] = useState<string[]>([]);
  const [memoryRecipients, setMemoryRecipients] = useState<string[]>([]);
  const [memoryKind, setMemoryKind] = useState<'fact' | 'inference'>('fact');
  const [memoryLocked, setMemoryLocked] = useState(true);
  const [copyPreview, setCopyPreview] = useState<Awaited<ReturnType<typeof loadCopy>> | null>(null);
  const [copyBranch, setCopyBranch] = useState('');
  const [copyWorkspace, setCopyWorkspace] = useState<Awaited<
    ReturnType<typeof loadCopyWorkspace>
  > | null>(null);
  const [copyChapter, setCopyChapter] = useState('');
  const [copyPlanning, setCopyPlanning] = useState('');
  const [copyAuthor, setCopyAuthor] = useState(false);
  const [copyFields, setCopyFields] = useState<('introduction' | 'background')[]>(['background']);
  const [copyOffset, setCopyOffset] = useState(0);
  const [copyPosition, setCopyPosition] = useState('start');
  const [copyBooks, setCopyBooks] = useState<Awaited<ReturnType<typeof loadBooks>>>([]);
  const refreshLibrary = async () => setLibrary(await rpc('roleplay.library', {}));
  function apply(next: ChatView) {
    if (latest.current?.id !== next.id) return;
    const current = latest.current;
    if (
      current &&
      (next.playback_epoch < current.playback_epoch ||
        (next.playback_epoch === current.playback_epoch &&
          (next.snapshot_sequence < current.snapshot_sequence ||
            (next.snapshot_sequence === current.snapshot_sequence &&
              next.event_sequence < current.event_sequence))))
    )
      return;
    latest.current = next;
    setView(next);
  }
  async function act(fn: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      await fn();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    if (connected()) void refreshLibrary().catch((e) => setError(errorMessage(e)));
  }, []);
  useEffect(() => {
    const id = view?.id;
    if (!id) return;
    const epoch = ++generation.current;
    let pending = false;
    const timer = setInterval(async () => {
      if (pending || latest.current?.id !== id) return;
      pending = true;
      try {
        const next = await rpc('roleplay.get', { conversation_id: id });
        if (generation.current === epoch && latest.current?.id === id) apply(next);
      } catch (e) {
        if (generation.current === epoch) setError(errorMessage(e));
      } finally {
        pending = false;
      }
    }, 240);
    return () => {
      generation.current++;
      clearInterval(timer);
    };
  }, [view?.id]);
  useEffect(
    () => () => {
      generation.current++;
      stopAudioFocus();
      const id = latest.current?.id;
      latest.current = null;
      if (id) void rpc('roleplay.silence', { conversation_id: id }).catch(() => {});
    },
    [],
  );
  const playback = view?.turns.find((t) => t.id === playTurnId);
  useEffect(() => {
    const turn = playback;
    if (!turn || !view || turn.speech_stopped || turn.playback_epoch !== view.playback_epoch)
      return;
    if ((turn.speech ?? []).some((s) => s.status === 'failed' || s.status === 'synthesizing'))
      return;
    if ((turn.speech ?? []).filter((s) => s.status === 'ready').length >= 3) return;
    const next = (turn.speech ?? []).find((s) => s.status === 'pending');
    if (!next || !next.segment.voice.config_id || requestedSpeech.current === next.segment.id)
      return;
    requestedSpeech.current = next.segment.id;
    const conversation = view.id;
    void rpc('roleplay.synthesize', {
      turn_id: turn.id,
      config_id: next.segment.voice.config_id,
      playback_epoch: turn.playback_epoch,
      segment_id: next.segment.id,
    }).catch((e) => {
      if (latest.current?.id === conversation) setError(errorMessage(e));
    });
  }, [playback, view?.playback_epoch]);
  async function openConversation(id: string) {
    stopAudioFocus();
    setPlayTurnId(null);
    requestedSpeech.current = '';
    if (latest.current) await rpc('roleplay.silence', { conversation_id: latest.current.id });
    const next = await rpc('roleplay.get', { conversation_id: id });
    latest.current = next;
    setView(next);
    setDraft('');
    setMentions([]);
    setMode('mention');
    setError('');
  }
  async function leave() {
    stopAudioFocus();
    setPlayTurnId(null);
    if (latest.current) await rpc('roleplay.silence', { conversation_id: latest.current.id });
    latest.current = null;
    setView(null);
    setDraft('');
    await refreshLibrary();
  }
  function newCharacter(character?: Character, copy = false) {
    setEditing(copy ? null : (character ?? null));
    setKind(character?.kind ?? 'character');
    setPersona(
      character
        ? { ...character.persona, name: character.persona.name + (copy ? '（副本）' : '') }
        : blankPersona(),
    );
    setSheet('character');
  }
  async function send(text = draft, continueTurn = false, retryRevision?: string) {
    const current = latest.current;
    if (!current) return;
    stopAudioFocus();
    setPlayTurnId(null);
    const llm = providers.providers.find((p) => p.id === llmId && p.kind === 'llm');
    if (!llm) {
      if (continueTurn || retryRevision)
        throw new Error('请先在模型设置中配置并选择 LLM；本地消息仍可保存。');
      apply(await rpc('roleplay.local_message', { ...req(current), text }));
      setDraft('');
      setNotice('消息已保存。尚未配置 LLM，请前往模型设置后显式继续。');
      return;
    }
    const turn = await rpc('roleplay.send', {
      ...req(current),
      text,
      config_id: llm.id,
      mode,
      member_ids: mentions,
      continue_turn: continueTurn,
      retry_revision: retryRevision ?? null,
      auto_speech: autoSpeech,
      include_actions: includeActions,
      speech_scope: speechScope,
      tts_config_id: ttsId || null,
      budget,
    });
    if (autoSpeech && !retryRevision) setPlayTurnId(turn.id);
    requestedSpeech.current = '';
    if (!retryRevision && !continueTurn) setDraft('');
    apply(await rpc('roleplay.get', { conversation_id: current.id }));
  }
  async function stop(text: boolean) {
    const current = latest.current;
    if (!current) return;
    stopAudioFocus();
    setPlayTurnId(null);
    const active =
      [...current.turns].reverse().find((t) => t.status === 'running') ?? current.turns.at(-1);
    if (active)
      await rpc('roleplay.control', {
        turn_id: active.id,
        action: text ? 'stop_turn' : 'stop_speech',
      });
    else await rpc('roleplay.silence', { conversation_id: current.id });
    apply(await rpc('roleplay.get', { conversation_id: current.id }));
  }
  async function replay(message: Message) {
    const binding = view?.members.find((m) => m.id === message.member_id)?.voice ?? blankVoice();
    const speechId = binding.config_id || ttsId;
    if (!view || !speechId) {
      openSettings('tts');
      return;
    }
    stopAudioFocus();
    requestedSpeech.current = '';
    const turn = await rpc('roleplay.playback', {
      ...req(view),
      message_revision: message.revision,
      tts_config_id: speechId,
      voice: binding,
      include_actions: includeActions,
      budget,
    });
    setPlayTurnId(turn.id);
    apply(await rpc('roleplay.get', { conversation_id: view.id }));
  }
  function configureMembers() {
    if (!view) return;
    setTitle(view.title);
    setScene(view.scene);
    setUserId(view.user_character_id ?? '');
    setUserRevision(view.user_persona_revision ?? null);
    setMembers(view.members);
    setSelectedChars([]);
    setComparison(null);
    setSheet('members');
  }
  async function loadCopyWorkspace(branch: string) {
    return rpc('branch.get', { branch_id: branch });
  }
  async function loadBooks() {
    return (await rpc('book.list', {})).books;
  }
  async function loadCopy(confirm = false) {
    if (!copyWorkspace) throw new Error('请先选择作品。');
    return rpc('roleplay.copy_book_character', {
      branch_id: copyWorkspace.branch_id,
      expected_snapshot: copyWorkspace.snapshot_id,
      chapter_id: copyChapter,
      offset: copyOffset,
      fields: copyFields,
      planning_id: copyPlanning,
      include_author: copyAuthor,
      confirm,
    });
  }
  const activeTurn = [...(view?.turns ?? [])].reverse().find((t) => t.status === 'running');
  const recentTurn = view?.turns.at(-1);
  const drafts =
    view?.turns
      .flatMap((t) =>
        (t.messages ?? []).filter(
          (m) => m.status !== 'complete' && !view.messages.some((v) => v.revision === m.revision),
        ),
      )
      .slice(-8) ?? [];
  const sharedForm = (
    <>
      <label>
        会话名称
        <input value={title} onChange={(e) => setTitle(e.target.value)} required maxLength={120} />
      </label>
      <label>
        用户身份
        <select
          aria-label="用户身份"
          value={userId}
          onChange={(e) => {
            setUserId(e.target.value);
            setUserRevision(null);
          }}
        >
          <option value="">普通用户（不填写身份）</option>
          {library.characters
            .filter((c) => c.kind === 'user' && !c.archived)
            .map((c) => (
              <option key={c.id} value={c.id}>
                {c.persona.name} · {c.id.slice(0, 6)}
              </option>
            ))}
        </select>
      </label>
      <label>
        共享场景
        <textarea value={scene} onChange={(e) => setScene(e.target.value)} maxLength={8000} />
      </label>
    </>
  );
  return (
    <main className="roleplay-workspace">
      <div className="rp-heading">
        <div>
          <div className="eyebrow">CHARACTERS & CONVERSATIONS</div>
          <h1>{view ? view.title : '遇见故事里的人。'}</h1>
          <p>独立于作品的虚构会话 · 人设与聊天保存在本机</p>
        </div>
        <div className="rp-actions">
          {view && (
            <button className="outline-button" onClick={() => void act(leave)}>
              <ArrowLeft size={16} />
              角色库与会话
            </button>
          )}
          <button className="outline-button" onClick={openBackup}>
            备份与恢复
          </button>
          <button className="outline-button" onClick={() => openSettings('llm')}>
            <Settings2 size={16} />
            模型设置
          </button>
        </div>
      </div>
      {error && (
        <div className="error-banner" role="alert">
          {error}
          <button aria-label="关闭聊天错误" onClick={() => setError('')}>
            <X size={16} />
          </button>
        </div>
      )}
      {notice && (
        <p className="rp-notice" role="status">
          {notice}
          <button aria-label="关闭聊天提示" onClick={() => setNotice('')}>
            ×
          </button>
        </p>
      )}
      {!view ? (
        <>
          <div className="rp-actions">
            <button
              className="primary-button"
              disabled={!connected() || busy}
              onClick={() => newCharacter()}
            >
              <Plus size={16} />
              新建角色 / 用户身份
            </button>
            <button
              className="outline-button"
              disabled={
                !connected() ||
                busy ||
                !library.characters.some((c) => c.kind === 'character' && !c.archived)
              }
              onClick={() => {
                setTitle('新的会话');
                setScene('');
                setUserId('');
                setSelectedChars([]);
                setSheet('create');
              }}
            >
              <MessageCircle size={16} />
              新建单聊 / 群聊
            </button>
            <button
              className="outline-button"
              disabled={!connected()}
              onClick={() =>
                void act(async () => {
                  setCopyBooks(await loadBooks());
                  setCopyWorkspace(null);
                  setCopyPreview(null);
                  setSheet('copy');
                })
              }
            >
              从作品复制人物
            </button>
          </div>
          <div className="rp-columns">
            <section>
              <h2>角色与身份</h2>
              <p className="muted small">允许同名，使用独立编号；无需小说或模型即可保存。</p>
              <div className="rp-cards">
                {library.characters.map((character) => (
                  <article key={character.id} className="rp-card">
                    <span className="rp-initial">
                      {character.persona.avatar ? (
                        <img className="rp-avatar" src={character.persona.avatar} alt="" />
                      ) : (
                        character.persona.name.slice(0, 1)
                      )}
                    </span>
                    <h3>{character.persona.name}</h3>
                    <small>
                      {character.kind === 'user' ? '用户身份' : '扮演角色'} ·{' '}
                      {character.id.slice(0, 6)}
                      {character.archived ? ' · 已归档' : ''}
                    </small>
                    <p>{character.persona.introduction || '尚无公开简介'}</p>
                    <div className="rp-actions">
                      <button onClick={() => newCharacter(character)}>编辑人设</button>
                      <button onClick={() => newCharacter(character, true)}>复制</button>
                      <button
                        onClick={() =>
                          void act(async () => {
                            await rpc('roleplay.character_save', {
                              id: character.id,
                              expected_revision: character.revision,
                              kind: character.kind,
                              persona: character.persona,
                              archived: !character.archived,
                            });
                            await refreshLibrary();
                          })
                        }
                      >
                        {character.archived ? '取消归档' : '归档'}
                      </button>
                    </div>
                  </article>
                ))}
                {!library.characters.length && (
                  <p className="rp-empty">创建第一个角色，保存背景、性格、表达方式与声音偏好。</p>
                )}
              </div>
            </section>
            <section>
              <h2>已保存会话</h2>
              <div className="rp-conversations">
                {library.conversations.map((chat) => (
                  <button
                    className="rp-card"
                    key={chat.id}
                    disabled={busy}
                    onClick={() => void act(() => openConversation(chat.id))}
                  >
                    <h3>{chat.title}</h3>
                    <p>
                      {chat.member_count} 位角色{chat.active ? ' · 文字生成中' : ' · 本地历史'}
                    </p>
                  </button>
                ))}
                {!library.conversations.length && (
                  <p className="rp-empty">从一个问候开始，也可以让多位角色加入场景。</p>
                )}
              </div>
            </section>
          </div>
        </>
      ) : (
        <>
          <div className="rp-chat-toolbar">
            <button className="outline-button" onClick={configureMembers}>
              <Users size={16} />
              成员、人设与声音
            </button>
            <button
              className="outline-button"
              onClick={() => {
                setContext(null);
                setContextMember(view.members.find((m) => !m.removed)?.id ?? '');
                setSheet('context');
              }}
            >
              上下文预览
            </button>
            <button
              className="outline-button"
              onClick={() => {
                setMemoryText('');
                setMemorySources([]);
                setMemoryRecipients([]);
                setSheet('memory');
              }}
            >
              会话记忆
            </button>
            <button className="outline-button" onClick={() => setSheet('history')}>
              历史路径
            </button>
            <button
              className="outline-button"
              onClick={() =>
                void act(async () => {
                  await exportChat(view.id);
                })
              }
            >
              <Download size={15} />
              导出聊天
            </button>
          </div>
          <div className="rp-chat-layout">
            <div className="rp-chat-main">
              <section className="rp-messages" aria-label="所选聊天历史" aria-live="off">
                {!view.messages.length && !drafts.length && (
                  <p className="rp-empty">
                    会话已保存。发送消息开始聊天；尚未配置模型时可先保存本地消息。
                  </p>
                )}
                {view.messages.map((m) => (
                  <article
                    className={`rp-message ${m.role === 'user' ? 'rp-user' : ''}`}
                    key={m.revision}
                  >
                    <div className="rp-message-heading">
                      <strong>{m.speaker}</strong>
                      <small>
                        {m.role === 'preset'
                          ? '预设开场白 · 未调用模型'
                          : m.role === 'user'
                            ? '用户消息 · 已保存'
                            : '完整回复 · 已自动保存'}
                        {m.member_id ? ` · ${m.member_id.slice(0, 6)}` : ''}
                      </small>
                    </div>
                    {m.kind === 'action' && <small>动作 / 环境段 · 默认不朗读</small>}
                    <p>{m.text}</p>
                    <div className="rp-actions">
                      <button
                        aria-label={`编辑消息 ${m.speaker} ${m.revision.slice(0, 6)}`}
                        onClick={() => {
                          setEditMessage(m);
                          setEditText(m.text);
                          setEditKind(m.kind ?? 'dialogue');
                        }}
                      >
                        编辑
                      </button>
                      {m.role === 'assistant' && (
                        <>
                          <button onClick={() => void act(() => send('', false, m.revision))}>
                            生成另一变体
                          </button>
                          <button onClick={() => void act(() => replay(m))}>播放 / 重播此条</button>
                        </>
                      )}
                      {view.variants.some((v) => v.id === m.id) && (
                        <label>
                          选择版本
                          <select
                            aria-label={`回复变体 ${m.id.slice(0, 6)}`}
                            value={m.revision}
                            onChange={(e) =>
                              void act(async () => {
                                stopAudioFocus();
                                setPlayTurnId(null);
                                apply(
                                  await rpc('roleplay.change_history', {
                                    ...req(view),
                                    revision: e.target.value,
                                    action: 'select',
                                  }),
                                );
                              })
                            }
                          >
                            {[
                              m,
                              ...view.variants.filter(
                                (v) => v.id === m.id && v.status === 'complete',
                              ),
                            ].map((v, i) => (
                              <option key={v.revision} value={v.revision}>
                                {i === 0 ? '当前版本' : '备选版本'} · {v.text.slice(0, 24)}
                              </option>
                            ))}
                          </select>
                        </label>
                      )}
                    </div>
                  </article>
                ))}
                {drafts.map((m) => (
                  <article key={m.revision} className="rp-message rp-partial">
                    <div className="rp-message-heading">
                      <strong>{m.speaker}</strong>
                      <small>
                        {m.status === 'streaming'
                          ? '流式回复中 · 尚未成为完整历史'
                          : '中断回复 · 未进入后续上下文'}
                      </small>
                    </div>
                    <p>{m.text || '等待首段文字…'}</p>
                    {m.status === 'interrupted' && (
                      <div className="rp-actions">
                        <button
                          onClick={() =>
                            void act(async () => {
                              apply(
                                await rpc('roleplay.change_history', {
                                  ...req(view),
                                  revision: m.revision,
                                  action: 'use_interrupted',
                                }),
                              );
                            })
                          }
                        >
                          使用这段继续
                        </button>
                        <button onClick={() => void act(() => send('', false, m.revision))}>
                          重试此回复
                        </button>
                      </div>
                    )}
                  </article>
                ))}
              </section>
              <div className="rp-composer">
                <div className="rp-actions">
                  <label>
                    发言模式
                    <select
                      aria-label="发言模式"
                      value={mode}
                      onChange={(e) => {
                        setMode(e.target.value as typeof mode);
                        setMentions([]);
                      }}
                    >
                      <option value="mention">@指定</option>
                      <option value="round_robin">轮流（每次一人）</option>
                      <option value="all">全员（串行）</option>
                      <option value="situation">情境（1–3 人，另计一次调用）</option>
                    </select>
                  </label>
                  <label>
                    文本模型
                    <select
                      aria-label="聊天文本模型"
                      value={llmId}
                      onChange={(e) => setLlmId(e.target.value)}
                    >
                      <option value="demo">未选择模型</option>
                      {providers.providers
                        .filter((p) => p.kind === 'llm')
                        .map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.name} · {p.model}
                          </option>
                        ))}
                    </select>
                  </label>
                </div>
                <p className="small muted">
                  本次
                  {mentions.length
                    ? `按指定顺序 ${mentions.length} 人`
                    : mode === 'all'
                      ? `最多 ${view.members.filter((m) => !m.removed && !m.muted).length} 人依次发言`
                      : mode === 'situation'
                        ? '选择 1–3 人，另计一次选择调用'
                        : mode === 'round_robin'
                          ? '下一位未禁言成员发言'
                          : '仅 @ 指定成员发言'}
                  ；达到队列上限即停。未填写价格时费用未知。
                </p>
                <fieldset className="rp-mentions">
                  <legend>@指定成员（指定优先于情境选择）</legend>
                  {view.members
                    .filter((m) => !m.removed)
                    .map((m) => (
                      <label className="check-row" key={m.id}>
                        <input
                          type="checkbox"
                          disabled={m.muted}
                          checked={mentions.includes(m.id)}
                          onChange={(e) =>
                            setMentions(
                              e.target.checked
                                ? [...mentions, m.id]
                                : mentions.filter((id) => id !== m.id),
                            )
                          }
                        />
                        {m.name} · {m.id.slice(0, 6)}
                        {m.muted ? '（禁言）' : ''}
                      </label>
                    ))}
                </fieldset>
                <label className="sr-only" htmlFor="chat-message">
                  聊天消息
                </label>
                <textarea
                  id="chat-message"
                  placeholder="发给角色的消息… Ctrl / ⌘ + Enter 发送"
                  value={draft}
                  maxLength={20000}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && draft.trim() && !busy) {
                      e.preventDefault();
                      void act(() => send());
                    }
                  }}
                />
                <div className="rp-actions">
                  <button
                    className="primary-button"
                    disabled={busy || !draft.trim()}
                    onClick={() => void act(() => send())}
                  >
                    {activeTurn
                      ? '停止旧轮并发送'
                      : providers.providers.some((p) => p.id === llmId && p.kind === 'llm')
                        ? '发送消息'
                        : '保存本地消息'}
                  </button>
                  <button
                    className="outline-button"
                    disabled={busy || !!activeTurn}
                    onClick={() => void act(() => send('', true))}
                  >
                    继续当前场景
                  </button>
                  <button
                    className="outline-button"
                    onClick={() => {
                      stopAudioFocus();
                      setPlayTurnId(null);
                      void act(() => stop(false));
                    }}
                  >
                    <Square size={13} />
                    停止语音
                  </button>
                  <button
                    className="outline-button"
                    disabled={!activeTurn}
                    onClick={() => {
                      stopAudioFocus();
                      setPlayTurnId(null);
                      void act(() => stop(true));
                    }}
                  >
                    <Square size={13} />
                    停止本轮
                  </button>
                </div>
                <small role="status">
                  {activeTurn ? '本轮文字生成中；完整回复自动进入聊天历史。' : '等待用户输入。'}
                  聊天不会写入小说正文；切换会话会停止自动发声。
                </small>
              </div>
            </div>
            <aside className="rp-chat-side">
              <h3>本轮与语音</h3>
              <label className="check-row">
                <input
                  type="checkbox"
                  checked={autoSpeech}
                  onChange={(e) => {
                    setAutoSpeech(e.target.checked);
                    if (!e.target.checked) {
                      stopAudioFocus();
                      setPlayTurnId(null);
                      void act(() => stop(false));
                    }
                  }}
                />
                发送后自动朗读（可能计费）
              </label>
              <label className="check-row">
                <input
                  type="checkbox"
                  checked={includeActions}
                  onChange={(e) => setIncludeActions(e.target.checked)}
                />
                朗读已明确标记的动作 / 环境
              </label>
              <label>
                朗读范围
                <select
                  aria-label="聊天朗读范围"
                  value={speechScope}
                  onChange={(e) => setSpeechScope(e.target.value as typeof speechScope)}
                >
                  <option value="all">本轮全部角色</option>
                  <option value="first">仅本轮首位发言者</option>
                </select>
              </label>
              <label>
                默认语音服务
                <select
                  aria-label="聊天语音服务"
                  value={ttsId}
                  onChange={(e) => setTtsId(e.target.value)}
                >
                  <option value="">仅文字</option>
                  {providers.providers
                    .filter((p) => p.kind === 'tts')
                    .map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name} · {p.voice}
                      </option>
                    ))}
                </select>
              </label>
              <button className="context-link" onClick={() => openSettings('tts')}>
                管理语音服务
              </button>
              <p className="small muted">
                音色由成员绑定或发送时预选的默认声音决定。语气能力不足时使用普通语气，不静默切换。
              </p>
              <ChatAudio
                turn={playback}
                epoch={view.playback_epoch}
                onError={setError}
                onPlayed={(turn, segmentId) => {
                  void rpc('roleplay.control', {
                    turn_id: turn.id,
                    action: 'played',
                    segment_id: segmentId,
                    playback_epoch: turn.playback_epoch,
                  })
                    .then(() => rpc('roleplay.get', { conversation_id: view.id }))
                    .then(apply)
                    .catch((e) => setError(errorMessage(e)));
                }}
              />
              {playback && (
                <div className="rp-speech-status">
                  <p>
                    {(playback.speech ?? []).filter((s) => s.status === 'ready').length}/3 段待播 ·{' '}
                    {(playback.speech ?? []).filter((s) => s.status === 'pending').length}{' '}
                    段等待合成
                  </p>
                  {(playback.speech ?? []).some((s) => s.status === 'ready') && (
                    <small>积压达到三段时暂停合成，文字继续保存。</small>
                  )}
                  {(playback.speech ?? [])
                    .filter((s) => s.status === 'failed')
                    .map((s) => (
                      <div key={s.segment.id}>
                        <p>{s.error}</p>
                        <button
                          onClick={() =>
                            void act(async () => {
                              requestedSpeech.current = '';
                              await rpc('roleplay.synthesize', {
                                turn_id: playback.id,
                                config_id: s.segment.voice.config_id ?? ttsId,
                                segment_id: s.segment.id,
                                playback_epoch: playback.playback_epoch,
                              });
                            })
                          }
                        >
                          重试此语音片段（可能重复计费）
                        </button>
                      </div>
                    ))}
                  <details>
                    <summary>逐句语气覆盖与重播</summary>
                    {(playback.speech ?? []).map((item) => (
                      <div key={item.segment.id} className="rp-sentence">
                        <p>{item.segment.text}</p>
                        <small>
                          建议 {item.segment.requested_emotion} → 实际{' '}
                          {item.segment.effective_emotion} · 速度{' '}
                          {item.segment.effective_speed ?? 1}
                        </small>
                        <label>
                          单句语气
                          <select
                            aria-label={`单句语气 ${item.segment.id.slice(0, 6)}`}
                            value={
                              segmentEmotions[item.segment.id] ??
                              item.segment.voice.emotion ??
                              'auto'
                            }
                            onChange={(e) =>
                              setSegmentEmotions({
                                ...segmentEmotions,
                                [item.segment.id]: e.target.value as Voice['emotion'],
                              })
                            }
                          >
                            {['auto', 'neutral', 'happy', 'sad', 'angry', 'gentle', 'whisper'].map(
                              (v) => (
                                <option key={v} value={v}>
                                  {v}
                                </option>
                              ),
                            )}
                          </select>
                        </label>
                        <button
                          disabled={
                            busy ||
                            !!activeTurn ||
                            !view.messages.some((m) => m.revision === item.segment.variant_revision)
                          }
                          onClick={() =>
                            void act(async () => {
                              const configId = item.segment.voice.config_id || ttsId;
                              if (!configId) {
                                openSettings('tts');
                                return;
                              }
                              stopAudioFocus();
                              requestedSpeech.current = '';
                              const turn = await rpc('roleplay.playback', {
                                ...req(view),
                                message_revision: item.segment.variant_revision,
                                source_segment_id: item.segment.id,
                                tts_config_id: configId,
                                include_actions: includeActions,
                                voice: {
                                  ...item.segment.voice,
                                  emotion:
                                    segmentEmotions[item.segment.id] ?? item.segment.voice.emotion,
                                },
                                budget,
                              });
                              setPlayTurnId(turn.id);
                              apply(await rpc('roleplay.get', { conversation_id: view.id }));
                            })
                          }
                        >
                          按此语气重播这句
                        </button>
                      </div>
                    ))}
                  </details>
                  {(playback.speech ?? [])[0] && (
                    <small>{(playback.speech ?? [])[0].segment.warning}</small>
                  )}
                </div>
              )}
              {recentTurn && (
                <>
                  <p className="small" role="status">
                    {recentTurn.status === 'failed'
                      ? `本轮停止：${recentTurn.error_code}`
                      : recentTurn.status === 'cancelled'
                        ? '本轮已停止'
                        : recentTurn.status === 'completed'
                          ? '本轮已完成'
                          : '本轮进行中'}{' '}
                    · 已提交 {(recentTurn.charges ?? []).length} 次请求
                  </p>
                  <p className="small muted">{recentTurn.notice}</p>
                  <ol className="rp-queue">
                    {(recentTurn.queue ?? []).map((id) => (
                      <li key={id}>
                        {view.members.find((m) => m.id === id)?.name ?? id} · {id.slice(0, 6)}
                        {(recentTurn.completed_members ?? []).includes(id)
                          ? ' · 已完成'
                          : (recentTurn.skipped_members ?? []).includes(id)
                            ? ' · 已跳过'
                            : ''}
                        {recentTurn.status === 'running' &&
                          !(recentTurn.messages ?? []).some((m) => m.member_id === id) &&
                          !(recentTurn.skipped_members ?? []).includes(id) && (
                            <button
                              onClick={() =>
                                void act(async () => {
                                  await rpc('roleplay.control', {
                                    turn_id: recentTurn.id,
                                    action: 'skip',
                                    member_id: id,
                                  });
                                })
                              }
                            >
                              跳过
                            </button>
                          )}
                      </li>
                    ))}
                  </ol>
                  <p className="small">
                    token 计入 / 预留：
                    {(recentTurn.charges ?? []).reduce(
                      (n, v) => n + (v.input_tokens ?? 0) + (v.output_tokens ?? 0),
                      0,
                    )}{' '}
                    · 语音字符：
                    {(recentTurn.charges ?? []).reduce((n, v) => n + (v.characters ?? 0), 0)}
                  </p>
                  <p className="small">
                    {(recentTurn.charges ?? []).some((v) => v.reserved_cost === null)
                      ? '费用未知'
                      : `估算 / 预留 ${(recentTurn.charges ?? []).reduce((n, v) => n + (v.reserved_cost ?? 0), 0).toFixed(6)} ${recentTurn.budget.currency}`}
                    （非厂商账单）
                  </p>
                </>
              )}
              <details className="rp-budget">
                <summary>下一轮累计预算</summary>
                {(
                  [
                    ['max_requests', '请求次数上限'],
                    ['max_tokens', 'token 上限'],
                    ['max_characters', '语音字符上限'],
                  ] as const
                ).map(([field, label]) => (
                  <label key={field}>
                    {label}
                    <input
                      type="number"
                      min={field === 'max_characters' ? 0 : 1}
                      value={budget[field]}
                      onChange={(e) => setBudget({ ...budget, [field]: Number(e.target.value) })}
                    />
                  </label>
                ))}
                <label>
                  金额上限（可选）
                  <input
                    type="number"
                    min="0.000001"
                    step="any"
                    value={budget.max_cost ?? ''}
                    onChange={(e) =>
                      setBudget({
                        ...budget,
                        max_cost: e.target.value ? Number(e.target.value) : null,
                      })
                    }
                  />
                </label>
                <label>
                  币种
                  <input
                    value={budget.currency}
                    onChange={(e) => setBudget({ ...budget, currency: e.target.value })}
                  />
                </label>
                {(
                  [
                    ['input_per_million', '每百万输入 token 单价'],
                    ['output_per_million', '每百万输出 token 单价'],
                    ['speech_per_million', '每百万语音字符单价'],
                  ] as const
                ).map(([field, label]) => (
                  <label key={field}>
                    {label}
                    <input
                      type="number"
                      min="0"
                      step="any"
                      value={budget[field] ?? ''}
                      onChange={(e) =>
                        setBudget({
                          ...budget,
                          [field]: e.target.value ? Number(e.target.value) : null,
                        })
                      }
                    />
                  </label>
                ))}
                <label>
                  价格来源
                  <input
                    value={budget.price_source}
                    onChange={(e) => setBudget({ ...budget, price_source: e.target.value })}
                  />
                </label>
                <label>
                  价格核对日期
                  <input
                    type="date"
                    value={budget.price_date}
                    onChange={(e) => setBudget({ ...budget, price_date: e.target.value })}
                  />
                </label>
                <small>
                  金额按用户填写的本轮统一单价估算；不同服务价格须先核对。不知道价格时仅约束请求、token
                  与字符，显示费用未知。
                </small>
              </details>
            </aside>
          </div>
        </>
      )}
      {sheet === 'character' && (
        <Sheet
          error={error}
          title={editing ? '编辑角色 / 身份' : '新建角色 / 身份'}
          close={() => setSheet(null)}
        >
          <form
            className="rp-form"
            onSubmit={(e) => {
              e.preventDefault();
              void act(async () => {
                await rpc('roleplay.character_save', {
                  id: editing?.id ?? null,
                  expected_revision: editing?.revision ?? null,
                  kind,
                  archived: editing?.archived ?? false,
                  persona,
                });
                await refreshLibrary();
                setSheet(null);
                setNotice('人设已保存为新修订；既有会话继续引用原修订。');
              });
            }}
          >
            <label>
              类型
              <select
                aria-label="角色类型"
                value={kind}
                disabled={!!editing}
                onChange={(e) => setKind(e.target.value as typeof kind)}
              >
                <option value="character">扮演角色</option>
                <option value="user">用户身份</option>
              </select>
            </label>
            <label>
              名称
              <input
                required
                aria-label="角色名称"
                maxLength={120}
                value={persona.name}
                onChange={(e) => setPersona({ ...persona, name: e.target.value })}
              />
            </label>
            <label>
              本地头像（PNG，128 KiB 内，最长边 512 像素）
              <input
                type="file"
                accept="image/png"
                aria-label="本地头像"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (!file) return;
                  void act(async () => {
                    if (file.size > 128 * 1024) throw new Error('头像需小于 128 KiB。');
                    const bytes = new Uint8Array(await file.arrayBuffer());
                    let binary = '';
                    for (const byte of bytes) binary += String.fromCharCode(byte);
                    setPersona({ ...persona, avatar: 'data:image/png;base64,' + btoa(binary) });
                  });
                }}
              />
            </label>
            {persona.avatar && (
              <div className="rp-actions">
                <img className="rp-avatar" src={persona.avatar} alt="本地头像预览" />
                <button type="button" onClick={() => setPersona({ ...persona, avatar: '' })}>
                  移除头像
                </button>
              </div>
            )}
            {fields.map(([field, label]) => (
              <label key={field}>
                {label}
                <textarea
                  maxLength={
                    ['background', 'examples', 'private_knowledge'].includes(field)
                      ? 8000
                      : ['introduction', 'identity', 'appearance', 'voice_preference'].includes(
                            field,
                          )
                        ? 2000
                        : 4000
                  }
                  value={persona[field]}
                  onChange={(e) => setPersona({ ...persona, [field]: e.target.value })}
                />
              </label>
            ))}
            <label className="check-row">
              <input
                type="checkbox"
                checked={persona.freeform}
                onChange={(e) => setPersona({ ...persona, freeform: e.target.checked })}
              />
              明确使用自由角色（无核心描述时仍允许生成）
            </label>
            <VoiceFields
              value={persona.voice ?? blankVoice()}
              onChange={(voice) => setPersona({ ...persona, voice })}
              providers={providers}
            />
            <button className="primary-button" disabled={busy}>
              保存人设
            </button>
          </form>
        </Sheet>
      )}
      {sheet === 'create' && (
        <Sheet error={error} title="新建单聊 / 群聊" close={() => setSheet(null)}>
          <form
            className="rp-form"
            onSubmit={(e) => {
              e.preventDefault();
              void act(async () => {
                const next = await rpc('roleplay.create', {
                  title,
                  character_ids: selectedChars,
                  user_character_id: userId || null,
                  scene,
                });
                latest.current = next;
                setView(next);
                setSheet(null);
                await refreshLibrary();
              });
            }}
          >
            {sharedForm}
            <fieldset>
              <legend>选择 1–8 位角色</legend>
              {library.characters
                .filter((c) => c.kind === 'character' && !c.archived)
                .map((c) => (
                  <label className="check-row" key={c.id}>
                    <input
                      type="checkbox"
                      checked={selectedChars.includes(c.id)}
                      disabled={!selectedChars.includes(c.id) && selectedChars.length >= 8}
                      onChange={(e) =>
                        setSelectedChars(
                          e.target.checked
                            ? [...selectedChars, c.id]
                            : selectedChars.filter((id) => id !== c.id),
                        )
                      }
                    />
                    {c.persona.name} · {c.id.slice(0, 6)}
                  </label>
                ))}
            </fieldset>
            <button className="primary-button" disabled={busy || !selectedChars.length}>
              创建会话
            </button>
          </form>
        </Sheet>
      )}
      {sheet === 'members' && view && (
        <Sheet error={error} title="成员、人设与声音快照" close={() => setSheet(null)}>
          <form
            className="rp-form"
            onSubmit={(e) => {
              e.preventDefault();
              void act(async () => {
                stopAudioFocus();
                setPlayTurnId(null);
                apply(
                  await rpc('roleplay.configure', {
                    ...req(view),
                    title,
                    scene,
                    members,
                    add_character_ids: selectedChars,
                    user_character_id: userId || null,
                    user_persona_revision: userRevision,
                  }),
                );
                setSheet(null);
              });
            }}
          >
            {sharedForm}
            <p>
              保存会先停止旧轮。新成员仅见加入后的消息；修改不会覆盖旧历史。人物关系使用文字描述，未建立自动角色
              ID 关系图。
            </p>
            {userId &&
              library.characters.some((c) => c.id === userId && c.revision !== userRevision) && (
                <button
                  type="button"
                  onClick={() =>
                    void act(async () => {
                      const next = library.characters.find((c) => c.id === userId)!;
                      const old = userRevision
                        ? await rpc('roleplay.character_get', {
                            id: userId,
                            revision: userRevision,
                          })
                        : next;
                      setComparison({ memberId: '__user__', old, next });
                    })
                  }
                >
                  比较用户身份新版
                </button>
              )}
            {members.map((m, index) => (
              <fieldset key={m.id}>
                <legend>
                  {m.name} · {m.id.slice(0, 6)}
                </legend>
                <small>固定人设修订：{m.persona_revision.slice(0, 8)}</small>
                <label className="check-row">
                  <input
                    type="checkbox"
                    checked={m.muted}
                    onChange={(e) =>
                      setMembers(
                        members.map((v) => (v.id === m.id ? { ...v, muted: e.target.checked } : v)),
                      )
                    }
                  />
                  禁言
                </label>
                <label className="check-row">
                  <input
                    type="checkbox"
                    checked={m.removed}
                    onChange={(e) =>
                      setMembers(
                        members.map((v) =>
                          v.id === m.id ? { ...v, removed: e.target.checked } : v,
                        ),
                      )
                    }
                  />
                  移出（保留历史）
                </label>
                <div className="rp-actions">
                  <button
                    type="button"
                    disabled={index === 0}
                    onClick={() => {
                      const next = [...members];
                      [next[index - 1], next[index]] = [next[index], next[index - 1]];
                      setMembers(next);
                    }}
                  >
                    向前排序
                  </button>
                  <button
                    type="button"
                    disabled={index + 1 === members.length}
                    onClick={() => {
                      const next = [...members];
                      [next[index + 1], next[index]] = [next[index], next[index + 1]];
                      setMembers(next);
                    }}
                  >
                    向后排序
                  </button>
                  {library.characters.some(
                    (c) => c.id === m.character_id && c.revision !== m.persona_revision,
                  ) && (
                    <button
                      type="button"
                      onClick={() =>
                        void act(async () => {
                          const old = await rpc('roleplay.character_get', {
                            id: m.character_id,
                            revision: m.persona_revision,
                          });
                          const next = library.characters.find((c) => c.id === m.character_id)!;
                          setComparison({ memberId: m.id, old, next });
                        })
                      }
                    >
                      比较角色库新版
                    </button>
                  )}
                </div>
                <VoiceFields
                  value={m.voice ?? blankVoice()}
                  onChange={(voice) =>
                    setMembers(members.map((v) => (v.id === m.id ? { ...v, voice } : v)))
                  }
                  providers={providers}
                />
              </fieldset>
            ))}
            {comparison && (
              <div className="rp-comparison">
                <h3>应用新修订前比较</h3>
                <div className="rp-columns">
                  <pre>{JSON.stringify(comparison.old.persona, null, 2)}</pre>
                  <pre>{JSON.stringify(comparison.next.persona, null, 2)}</pre>
                </div>
                <button
                  type="button"
                  onClick={() => {
                    if (comparison.memberId === '__user__')
                      setUserRevision(comparison.next.revision);
                    else
                      setMembers(
                        members.map((m) =>
                          m.id === comparison.memberId
                            ? {
                                ...m,
                                persona_revision: comparison.next.revision,
                                name: comparison.next.persona.name,
                              }
                            : m,
                        ),
                      );
                    setComparison(null);
                  }}
                >
                  采用这份人设（声音保留人工绑定）
                </button>
              </div>
            )}
            <fieldset>
              <legend>新增成员（上限 8 人）</legend>
              {library.characters
                .filter(
                  (c) =>
                    c.kind === 'character' &&
                    !c.archived &&
                    !members.some((m) => !m.removed && m.character_id === c.id),
                )
                .map((c) => (
                  <label className="check-row" key={c.id}>
                    <input
                      type="checkbox"
                      checked={selectedChars.includes(c.id)}
                      onChange={(e) =>
                        setSelectedChars(
                          e.target.checked
                            ? [...selectedChars, c.id]
                            : selectedChars.filter((id) => id !== c.id),
                        )
                      }
                    />
                    {c.persona.name} · {c.id.slice(0, 6)}
                  </label>
                ))}
            </fieldset>
            <button className="primary-button" disabled={busy}>
              停止旧轮并保存配置
            </button>
          </form>
        </Sheet>
      )}
      {sheet === 'context' && view && (
        <Sheet error={error} title="逐角色上下文预览" close={() => setSheet(null)}>
          <div className="rp-form">
            <label>
              接收角色
              <select value={contextMember} onChange={(e) => setContextMember(e.target.value)}>
                {view.members
                  .filter((m) => !m.removed)
                  .map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.name} · {m.id.slice(0, 6)}
                    </option>
                  ))}
              </select>
            </label>
            <button
              className="primary-button"
              disabled={busy}
              onClick={() =>
                void act(async () => {
                  setContext(
                    await rpc('roleplay.preview_context', {
                      conversation_id: view.id,
                      member_id: contextMember,
                      config_id: providers.providers.some((p) => p.id === llmId) ? llmId : null,
                    }),
                  );
                })
              }
            >
              预览实际上下文
            </button>
            {context && (
              <>
                <p>
                  chat_scoped · 估算输入 {context.estimated_tokens} token · 输出预留{' '}
                  {context.output_reserve} · 裁剪 {context.trimmed_revisions.length} 条历史
                </p>
                <p>{context.warning}</p>
                <pre className="rp-context">{JSON.stringify(context.messages, null, 2)}</pre>
              </>
            )}
            {recentTurn?.contexts?.length ? (
              <details>
                <summary>本轮实际请求快照（{(recentTurn.contexts ?? []).length}）</summary>
                {(recentTurn.contexts ?? []).map((ctx, i) => (
                  <div key={i}>
                    <p>
                      接收成员 {ctx.member_id} · 来源 {ctx.source_revisions.length} 条
                    </p>
                    <pre className="rp-context">{JSON.stringify(ctx.messages, null, 2)}</pre>
                  </div>
                ))}
              </details>
            ) : null}
          </div>
        </Sheet>
      )}
      {sheet === 'memory' && view && (
        <Sheet error={error} title="有来源的会话记忆" close={() => setSheet(null)}>
          <form
            className="rp-form"
            onSubmit={(e) => {
              e.preventDefault();
              void act(async () => {
                const memory: Memory = {
                  id: key(),
                  text: memoryText,
                  source_revisions: memorySources,
                  recipient_ids: memoryRecipients,
                  kind: memoryKind,
                  locked: memoryLocked,
                };
                apply(await rpc('roleplay.memory_save', { ...req(view), memory }));
                setMemoryText('');
                setMemorySources([]);
              });
            }}
          >
            <p>
              只在本会话和所选路径使用。编辑或换变体后，失效来源不再注入；新成员不会通过记忆读取加入前消息。
            </p>
            {view.memories.map((memory) => (
              <div key={memory.id} className="rp-card">
                <p>{memory.text}</p>
                <small>
                  {memory.kind === 'fact' ? '用户确认事实' : '推测'} ·{' '}
                  {memory.locked ? '锁定' : '可裁剪'}
                </small>
                <button
                  type="button"
                  onClick={() =>
                    void act(async () => {
                      apply(
                        await rpc('roleplay.memory_save', { ...req(view), memory, remove: true }),
                      );
                    })
                  }
                >
                  移除记忆
                </button>
              </div>
            ))}
            <label>
              记忆内容
              <textarea
                required
                maxLength={4000}
                value={memoryText}
                onChange={(e) => setMemoryText(e.target.value)}
              />
            </label>
            <fieldset>
              <legend>来源消息（至少一条）</legend>
              {view.messages.map((m) => (
                <label className="check-row" key={m.revision}>
                  <input
                    type="checkbox"
                    checked={memorySources.includes(m.revision)}
                    onChange={(e) =>
                      setMemorySources(
                        e.target.checked
                          ? [...memorySources, m.revision]
                          : memorySources.filter((id) => id !== m.revision),
                      )
                    }
                  />
                  {m.speaker}：{m.text.slice(0, 90)}
                </label>
              ))}
            </fieldset>
            <fieldset>
              <legend>接收者（留空为全部当前成员）</legend>
              {view.members
                .filter((m) => !m.removed)
                .map((m) => (
                  <label className="check-row" key={m.id}>
                    <input
                      type="checkbox"
                      checked={memoryRecipients.includes(m.id)}
                      onChange={(e) =>
                        setMemoryRecipients(
                          e.target.checked
                            ? [...memoryRecipients, m.id]
                            : memoryRecipients.filter((id) => id !== m.id),
                        )
                      }
                    />
                    {m.name} · {m.id.slice(0, 6)}
                  </label>
                ))}
            </fieldset>
            <label>
              类型
              <select
                value={memoryKind}
                onChange={(e) => setMemoryKind(e.target.value as typeof memoryKind)}
              >
                <option value="fact">用户确认事实</option>
                <option value="inference">推测</option>
              </select>
            </label>
            <label className="check-row">
              <input
                type="checkbox"
                checked={memoryLocked}
                onChange={(e) => setMemoryLocked(e.target.checked)}
              />
              锁定（不被裁剪或自动改写）
            </label>
            <button className="primary-button" disabled={busy || !memorySources.length}>
              保存记忆
            </button>
          </form>
        </Sheet>
      )}
      {sheet === 'history' && view && (
        <Sheet error={error} title="保留的历史路径" close={() => setSheet(null)}>
          <p className="small">恢复会派生新快照，保留所有原路径，并停止旧轮及语音。</p>
          <div className="rp-history">
            {view.history.map((h) => (
              <button
                key={h.snapshot_id}
                disabled={busy || h.snapshot_id === view.snapshot_id}
                onClick={() =>
                  void act(async () => {
                    stopAudioFocus();
                    setPlayTurnId(null);
                    apply(
                      await rpc('roleplay.change_history', {
                        ...req(view),
                        revision: h.snapshot_id,
                        action: 'restore',
                      }),
                    );
                    setSheet(null);
                  })
                }
              >
                {h.snapshot_id.slice(0, 8)} · {h.message_count} 条消息
                {h.snapshot_id === view.snapshot_id ? ' · 当前' : ''}
              </button>
            ))}
          </div>
        </Sheet>
      )}
      {editMessage && view && (
        <Sheet error={error} title="编辑历史消息并派生新路径" close={() => setEditMessage(null)}>
          <form
            className="rp-form"
            onSubmit={(e) => {
              e.preventDefault();
              void act(async () => {
                stopAudioFocus();
                setPlayTurnId(null);
                apply(
                  await rpc('roleplay.change_history', {
                    ...req(view),
                    revision: editMessage.revision,
                    action: 'edit',
                    text: editText,
                    kind: editKind,
                  }),
                );
                setEditMessage(null);
              });
            }}
          >
            <p>此消息之后的回复保留在旧路径，不沿用到新上下文。</p>
            <label>
              段落类型
              <select
                aria-label="消息段落类型"
                value={editKind}
                onChange={(e) => setEditKind(e.target.value as typeof editKind)}
              >
                <option value="dialogue">对白 / 未结构化可见文字</option>
                <option value="action">明确的动作 / 环境段</option>
              </select>
            </label>
            <label>
              编辑消息
              <textarea
                required
                aria-label="编辑消息"
                value={editText}
                maxLength={20000}
                onChange={(e) => setEditText(e.target.value)}
              />
            </label>
            <button className="primary-button" disabled={busy}>
              保存为新历史路径
            </button>
          </form>
        </Sheet>
      )}
      {sheet === 'copy' && (
        <Sheet error={error} title="从作品明确复制人物资料" close={() => setSheet(null)}>
          <div className="rp-form">
            <label>
              作品
              <select
                value={copyBranch}
                onChange={(e) => {
                  setCopyBranch(e.target.value);
                  setCopyPreview(null);
                  void act(async () => {
                    const workspace = await loadCopyWorkspace(e.target.value);
                    setCopyWorkspace(workspace);
                    setCopyChapter(workspace.chapters[0]?.id ?? '');
                    setCopyOffset(0);
                    setCopyPosition('start');
                    setCopyPlanning(
                      workspace.planning.find((p) => p.kind === 'character')?.id ?? '',
                    );
                  });
                }}
              >
                <option value="">选择作品</option>
                {copyBooks.map((b) => (
                  <option key={b.branch_id} value={b.branch_id}>
                    {b.title}（主分支）
                  </option>
                ))}
              </select>
            </label>
            {copyWorkspace && (
              <>
                <label>
                  可见章节
                  <select
                    value={copyChapter}
                    onChange={(e) => {
                      setCopyChapter(e.target.value);
                      setCopyPosition('start');
                      setCopyOffset(0);
                      setCopyPreview(null);
                    }}
                  >
                    {copyWorkspace.chapters.map((ch) => (
                      <option key={ch.id} value={ch.id}>
                        {ch.title}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  人物字段
                  <select
                    value={copyPlanning}
                    onChange={(e) => {
                      setCopyPlanning(e.target.value);
                      setCopyPreview(null);
                    }}
                  >
                    {copyWorkspace.planning
                      .filter((p) => p.kind === 'character')
                      .map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.title}
                        </option>
                      ))}
                  </select>
                </label>
                <label>
                  阅读位置
                  <select
                    aria-label="复制人物阅读位置"
                    value={copyPosition}
                    onChange={(e) => {
                      const position = e.target.value;
                      setCopyPosition(position);
                      setCopyPreview(null);
                      if (position === 'start') setCopyOffset(0);
                      else
                        void act(async () => {
                          const chapter = await rpc('chapter.get', {
                            branch_id: copyWorkspace.branch_id,
                            chapter_id: copyChapter,
                          });
                          setCopyOffset(Array.from(chapter.text).length);
                        });
                    }}
                  >
                    <option value="start">本章开头</option>
                    <option value="end">已读完本章</option>
                  </select>
                </label>
                <label>
                  分支
                  <select
                    aria-label="复制人物分支"
                    value={copyWorkspace.branch_id}
                    onChange={(e) =>
                      void act(async () => {
                        const workspace = await loadCopyWorkspace(e.target.value);
                        setCopyWorkspace(workspace);
                        setCopyChapter(workspace.chapters[0]?.id ?? '');
                        setCopyPlanning(
                          workspace.planning.find((p) => p.kind === 'character')?.id ?? '',
                        );
                        setCopyPreview(null);
                        setCopyOffset(0);
                        setCopyPosition('start');
                      })
                    }
                  >
                    {copyWorkspace.branches.map((branch) => (
                      <option key={branch.id} value={branch.id}>
                        {branch.name}
                      </option>
                    ))}
                  </select>
                </label>
                <fieldset>
                  <legend>明确选择复制字段（名称会显示给会话成员）</legend>
                  {(['introduction', 'background'] as const).map((field) => (
                    <label className="check-row" key={field}>
                      <input
                        type="checkbox"
                        checked={copyFields.includes(field)}
                        disabled={copyAuthor && field === 'introduction'}
                        onChange={(e) => {
                          setCopyFields(
                            e.target.checked
                              ? [...copyFields, field]
                              : copyFields.filter((v) => v !== field),
                          );
                          setCopyPreview(null);
                        }}
                      />
                      {field === 'introduction'
                        ? '公开简介（其他成员可见）'
                        : '背景（仅注入本角色请求）'}
                    </label>
                  ))}
                </fieldset>
                <label className="check-row">
                  <input
                    type="checkbox"
                    checked={copyAuthor}
                    onChange={(e) => {
                      setCopyAuthor(e.target.checked);
                      if (e.target.checked) setCopyFields(['background']);
                      setCopyPreview(null);
                    }}
                  />
                  明确选入作者资料（会在聊天生成时发送给模型）
                </label>
                <button
                  disabled={!copyPlanning || !copyFields.length || busy}
                  onClick={() =>
                    void act(async () => {
                      setCopyPreview(await loadCopy());
                    })
                  }
                >
                  预览所选资料
                </button>
              </>
            )}
            {copyPreview && (
              <>
                <p>{copyPreview.warning}</p>
                <pre className="rp-context">{JSON.stringify(copyPreview.persona, null, 2)}</pre>
                <button
                  className="primary-button"
                  disabled={busy}
                  onClick={() =>
                    void act(async () => {
                      await loadCopy(true);
                      await refreshLibrary();
                      setSheet(null);
                    })
                  }
                >
                  确认复制为独立角色
                </button>
              </>
            )}
          </div>
        </Sheet>
      )}
    </main>
  );
}
