import { useEffect, useRef, useState, type ReactNode } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { invoke, isTauri } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';
import {
  AudioLines,
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  BookOpen,
  Check,
  ChevronRight,
  CircleHelp,
  Download,
  Feather,
  FolderOpen,
  GitBranch,
  Headphones,
  MessageCircle,
  LayoutGrid,
  LoaderCircle,
  Plus,
  Search,
  Settings2,
  Sparkles,
  Square,
  X,
} from 'lucide-react';
import type {
  ContextPreview,
  HistoryEntry,
  ImportPreview,
  FileOperation,
  PlanningEntry,
  Task,
  TaskSummary,
  Workspace,
} from '../../../packages/contracts';
import { connected, exportBook, pickImport, pickRestore, saveBackup, rpc } from './rpc';
import {
  flush,
  loadLibrary,
  message,
  openWorkspace,
  toCodePoint,
  useWork,
  wordCount,
} from './store';
import { Editor } from './Editor';
import { ProviderSettings } from './ProviderSettings';
import { AudioPlayer } from './AudioPlayer';
import { Roleplay } from './Roleplay';
import { stopAudioFocus } from './audioPlayback';
import type { ProviderList } from '../../../packages/contracts';

function Modal({
  title,
  children,
  close,
}: {
  title: string;
  children: ReactNode;
  close: () => void;
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
        <Dialog.Content className="modal">
          <div className="modal-header">
            <Dialog.Title>{title}</Dialog.Title>
            <Dialog.Close className="icon-button" aria-label="关闭">
              <X size={19} />
            </Dialog.Close>
          </div>
          <Dialog.Description className="sr-only">{title}，按 Escape 关闭。</Dialog.Description>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
const kindNames = { brief: '创作简报', character: '人物卡', lore: '世界观', outline: '章节大纲' };
const newPlan = (): PlanningEntry => ({
  id: crypto.randomUUID(),
  kind: 'brief',
  title: '',
  text: '',
  context_role: 'setting',
  author_only: false,
  visible_from: null,
  locked: true,
});

export function App() {
  const [surface, setSurface] = useState<'books' | 'roleplay'>('books');
  const { books, workspace: w, chapter, text, dirty, saving, error } = useWork();
  const [providerState, setProviderState] = useState<ProviderList>({
    providers: [],
    external_enabled: false,
  });
  const [llmId, setLlmId] = useState(() => localStorage.getItem('narravo.llm') ?? 'demo');
  const [ttsId, setTtsId] = useState(() => localStorage.getItem('narravo.tts') ?? '');
  const [settingsKind, setSettingsKind] = useState<'llm' | 'tts'>('llm');
  function openSettings(kind: 'llm' | 'tts') {
    setSettingsKind(kind);
    setModal('settings');
  }
  const [audioTask, setAudioTask] = useState<Task | null>(null);
  const [showNarrationConfirm, setShowNarrationConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [modal, setModal] = useState<
    | 'create'
    | 'import'
    | 'backup'
    | 'settings'
    | 'fork'
    | 'chapter'
    | 'plan'
    | 'context'
    | 'tasks'
    | 'history'
    | null
  >(null);
  const [tab, setTab] = useState<'writing' | 'planning'>('writing');
  const [title, setTitle] = useState('');
  const [exportFormat, setExportFormat] = useState<'txt' | 'md'>('txt');
  const [search, setSearch] = useState('');
  const [intent, setIntent] = useState('');
  const [task, setTask] = useState<Task | null>(null);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [recentTasks, setRecentTasks] = useState<TaskSummary[]>([]);
  const [acceptText, setAcceptText] = useState('');
  const [selection, setSelection] = useState<[number, number]>([0, 0]);
  const [policy, setPolicy] = useState<'reader_safe' | 'author_plan' | 'full_rewrite'>(
    'author_plan',
  );
  const [selectedPlans, setSelectedPlans] = useState<string[]>([]);
  const [rewriteIds, setRewriteIds] = useState<string[]>([]);
  const [context, setContext] = useState<ContextPreview | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [encoding, setEncoding] = useState('auto');
  const [pdfPassword, setPdfPassword] = useState('');
  const [removePdfMargins, setRemovePdfMargins] = useState(false);
  const [acceptIncomplete, setAcceptIncomplete] = useState(false);
  const [includeAudio, setIncludeAudio] = useState(false);
  const [fileOp, setFileOp] = useState<FileOperation | null>(null);
  const fileRunning = fileOp?.status === 'running';
  useEffect(() => {
    const id = localStorage.getItem('narravo.file-operation');
    if (id && connected())
      rpc('file.get', { operation_id: id })
        .then(setFileOp)
        .catch(() => {});
  }, []);
  useEffect(() => {
    if (!fileOp) return;
    localStorage.setItem('narravo.file-operation', fileOp.operation_id);
    if (fileOp.status === 'completed' && fileOp.preview) {
      setPreview(fileOp.preview);
      setTitle(
        fileOp.preview.metadata?.title || fileOp.preview.filename.replace(/\.(txt|epub|pdf)$/i, ''),
      );
      setAcceptIncomplete(false);
    }
    if (fileOp.status !== 'running') return;
    let pending = false;
    const interval = setInterval(async () => {
      if (pending) return;
      pending = true;
      try {
        setFileOp(await rpc('file.get', { operation_id: fileOp.operation_id }));
      } catch (e) {
        useWork.setState({ error: message(e) });
      } finally {
        pending = false;
      }
    }, 300);
    return () => clearInterval(interval);
  }, [fileOp?.operation_id, fileOp?.status]);
  async function closeFileModal() {
    if (fileOp?.status === 'running')
      await rpc('file.cancel', { operation_id: fileOp.operation_id }).then(setFileOp);
    setModal(null);
  }
  async function readBrowserFile(file: File) {
    if (file.size > 10 * 1024 * 1024)
      throw new Error('浏览器测试桥接上限 10 MiB；大文件请在桌面版中选择。');
    const bytes = new Uint8Array(await file.arrayBuffer());
    let binary = '';
    for (const byte of bytes) binary += String.fromCharCode(byte);
    return btoa(binary);
  }
  const [plan, setPlan] = useState<PlanningEntry>(newPlan);
  const [notice, setNotice] = useState('');
  const polling = useRef(false);
  const initializedTask = useRef('');
  const taskRunning = task?.status === 'running';
  const ready = connected();

  async function refreshProviders() {
    setProviderState(await rpc('provider.list', {}));
  }
  useEffect(() => {
    if (connected()) refreshProviders().catch((e) => useWork.setState({ error: message(e) }));
  }, []);
  useEffect(() => {
    localStorage.setItem('narravo.llm', llmId);
  }, [llmId]);
  useEffect(() => {
    localStorage.setItem('narravo.tts', ttsId);
  }, [ttsId]);
  useEffect(() => {
    if (audioTask?.status !== 'running') return;
    let pending = false;
    const id = setInterval(async () => {
      if (pending) return;
      pending = true;
      try {
        setAudioTask(await rpc('task.get', { task_id: audioTask.task_id }));
      } catch (e) {
        useWork.setState({ error: message(e) });
      } finally {
        pending = false;
      }
    }, 250);
    return () => clearInterval(id);
  }, [audioTask?.task_id, audioTask?.status]);
  async function prepareNarration() {
    await flush();
    const current = useWork.getState();
    if (!current.text.trim()) {
      setNotice('暂无正文可播放，不会创建语音任务。');
      return;
    }
    if (!ttsId) {
      openSettings('tts');
      return;
    }
    setShowNarrationConfirm(true);
  }
  const llmConfig = providerState.providers.find((p) => p.id === llmId && p.kind === 'llm');
  const ttsConfig = providerState.providers.find((p) => p.id === ttsId && p.kind === 'tts');
  useEffect(() => {
    const plan = audioTask?.audio;
    if (
      audioTask?.status === 'running' &&
      plan &&
      (plan.branch_id !== w?.branch_id ||
        plan.chapter_id !== chapter?.chapter_id ||
        plan.revision !== w?.chapters.find((item) => item.id === chapter?.chapter_id)?.revision ||
        dirty)
    ) {
      const id = audioTask.task_id;
      rpc('task.cancel', { task_id: id })
        .then((next) => setAudioTask((current) => (current?.task_id === id ? next : current)))
        .catch((e) => useWork.setState({ error: message(e) }));
    }
  }, [w?.branch_id, chapter?.chapter_id, w?.snapshot_id, dirty, audioTask?.task_id]);
  async function action(fn: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    useWork.setState({ error: null });
    try {
      await fn();
    } catch (e) {
      useWork.setState({ error: message(e) });
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    if (!isTauri()) return;
    const unlisten = listen('app:close-requested', () => {
      void flush()
        .then(() => invoke('exit_app'))
        .catch((e) => useWork.setState({ error: message(e) }));
    });
    return () => {
      void unlisten.then((fn) => fn());
    };
  }, []);
  useEffect(() => {
    if (modal === 'tasks' && connected())
      rpc('task.list', {})
        .then((result) => setRecentTasks(result.tasks))
        .catch((e) => useWork.setState({ error: message(e) }));
  }, [modal]);
  useEffect(() => {
    if (connected()) loadLibrary().catch((e) => useWork.setState({ error: message(e) }));
  }, []);
  useEffect(() => {
    if (!dirty || error) return;
    const timeout = setTimeout(() => {
      void flush().catch(() => {});
    }, 500);
    return () => clearTimeout(timeout);
  }, [text, dirty, error]);
  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (useWork.getState().dirty) {
        e.preventDefault();
      }
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, []);
  useEffect(() => {
    if (!notice) return;
    const id = setTimeout(() => setNotice(''), 5000);
    return () => clearTimeout(id);
  }, [notice]);
  useEffect(() => {
    if (!taskRunning || !task) return;
    const interval = setInterval(async () => {
      if (polling.current) return;
      polling.current = true;
      try {
        const next = await rpc('task.get', { task_id: task.task_id });
        setTask((old) => (old?.task_id === next.task_id && next.seq >= old.seq ? next : old));
      } catch (e) {
        useWork.setState({ error: message(e) });
      } finally {
        polling.current = false;
      }
    }, 150);
    return () => clearInterval(interval);
  }, [task?.task_id, taskRunning]);
  useEffect(() => {
    if (task && !taskRunning && task.generation && initializedTask.current !== task.task_id) {
      initializedTask.current = task.task_id;
      setAcceptText(task.generation.text);
      setSelection([0, [...task.generation.text].length]);
    }
  }, [task, taskRunning]);

  async function enter(next: Workspace, chapterId?: string) {
    await openWorkspace(next, chapterId);
    setTask(null);
    setAudioTask(null);
    setIntent('');
    setSelectedPlans([]);
    setRewriteIds([]);
    setPolicy(next.origin_type === 'original' ? 'author_plan' : 'reader_safe');
  }
  async function back() {
    setSurface('books');
    stopAudioFocus();
    await flush();
    if (taskRunning && task) await rpc('task.cancel', { task_id: task.task_id });
    await loadLibrary();
    useWork.setState({ workspace: null, chapter: null });
    setTask(null);
  }
  async function mutate(fn: (current: Workspace) => Promise<Workspace>, targetId?: string) {
    await flush();
    const current = useWork.getState().workspace!;
    const next = await fn(current);
    await openWorkspace(next, targetId ?? chapter?.chapter_id);
  }
  async function createBook() {
    const next = await rpc('book.create', { title: title.trim() || '未命名作品' });
    await enter(next);
    setModal(null);
  }
  async function chooseFile() {
    if (isTauri()) {
      const next = await pickImport(encoding, pdfPassword, removePdfMargins);
      if (next) {
        setPreview(null);
        setPdfPassword('');
        setFileOp(next);
      }
    }
  }
  const currentMeta = w?.chapters.find((c) => c.id === chapter?.chapter_id);
  const target = () => ({
    branch_id: useWork.getState().workspace!.branch_id,
    chapter_id: useWork.getState().chapter!.chapter_id,
    offset: [...useWork.getState().text].length,
    context_policy: policy,
    selected_planning_ids: selectedPlans,
    rewrite_chapter_ids: rewriteIds,
    config_id: llmId === 'demo' ? null : llmId,
  });
  async function generate() {
    await flush();
    const current = useWork.getState().workspace!;
    const next = await rpc('writing.generate', {
      ...target(),
      expected_snapshot: current.snapshot_id,
      intent,
      provider: llmId === 'demo' ? 'demo' : 'configured',
    });
    setTask(next);
    setAcceptText('');
    setSelection([0, 0]);
  }
  async function accept() {
    if (!task?.generation || !w) return;
    await flush();
    const next = await rpc('writing.accept', {
      generation_id: task.generation.id,
      candidate_revision: task.generation.candidate_revision,
      expected_snapshot: useWork.getState().workspace!.snapshot_id,
      start: selection[0],
      end: selection[1],
      edited_text: acceptText,
      idempotency_key: crypto.randomUUID(),
    });
    await openWorkspace(next, chapter!.chapter_id);
    setTask({ ...task, generation: { ...task.generation, accepted: true } });
    setNotice('候选已接纳为新修订');
  }
  function downloadDraft() {
    const a = document.createElement('a');
    const url = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }));
    a.href = url;
    a.download = '未保存草稿.txt';
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="app-shell">
      <nav className="rail" aria-label="主导航">
        <button className="brand-mark" onClick={() => void action(back)} aria-label="叙声作品库">
          <AudioLines size={27} />
        </button>
        <div className="rail-links">
          <button
            className={surface === 'books' && !w ? 'rail-link active' : 'rail-link'}
            onClick={() => void action(back)}
            disabled={busy}
            title="作品库"
            aria-label="作品库"
          >
            <LayoutGrid size={21} />
            <span>作品</span>
          </button>
          <button
            className={surface === 'books' && w ? 'rail-link active' : 'rail-link'}
            disabled={!w || busy}
            onClick={() => {
              setSurface('books');
              setTab('writing');
            }}
            aria-label="创作"
          >
            <Feather size={21} />
            <span>创作</span>
          </button>
          <button
            className={surface === 'roleplay' ? 'rail-link active' : 'rail-link'}
            aria-label="角色扮演"
            onClick={() =>
              void action(async () => {
                await flush();
                stopAudioFocus();
                if (audioTask?.status === 'running')
                  setAudioTask(await rpc('task.cancel', { task_id: audioTask.task_id }));
                setSurface('roleplay');
              })
            }
          >
            <MessageCircle size={21} />
            <span>角色</span>
          </button>
          <button className="rail-link" onClick={() => setModal('tasks')} aria-label="任务中心">
            <LoaderCircle size={21} />
            <span>任务</span>
            {taskRunning && <i />}
          </button>
        </div>
        <div className="rail-bottom">
          <button className="rail-link" onClick={() => openSettings('llm')} aria-label="模型设置">
            <Settings2 size={21} />
            <span>设置</span>
          </button>
          <div className="avatar">叙</div>
        </div>
      </nav>
      <div className="main-shell">
        <header className="topbar">
          <div className="wordmark">
            叙声 <span>NARRAVO</span>
          </div>
          <div className="breadcrumb">
            {w ? (
              <>
                <span>作品库</span>
                <ChevronRight size={13} />
                <span>{w.title}</span>
              </>
            ) : (
              <>故事的另一种可能</>
            )}
          </div>
          <div className="top-status">
            <span className={ready ? 'status-dot' : 'status-dot off'} />
            {ready ? '本地工作台' : '界面预览'}
            <span className="version">v0.1 · 开发版</span>
          </div>
        </header>
        {!ready && (
          <div className="preview-banner">
            当前为浏览器界面预览。创建和保存作品请启动桌面版；浏览器不会写入正式书库。
          </div>
        )}
        {error && (
          <div className="error-banner" role="alert">
            <span>{error}</span>
            {dirty && <button onClick={downloadDraft}>下载未保存草稿</button>}
            <button aria-label="关闭错误提示" onClick={() => useWork.setState({ error: null })}>
              <X size={16} />
            </button>
          </div>
        )}
        {notice && (
          <div className="toast" role="status">
            <Check size={16} />
            {notice}
          </div>
        )}
        {surface === 'roleplay' ? (
          <Roleplay
            providers={providerState}
            llmId={llmId}
            ttsId={ttsId}
            setLlmId={setLlmId}
            setTtsId={setTtsId}
            openSettings={openSettings}
            openBackup={() => {
              stopAudioFocus();
              setSurface('books');
              setModal('backup');
            }}
          />
        ) : !w ? (
          <main className="library">
            <div className="library-intro">
              <div>
                <div className="eyebrow">YOUR STORY STARTS HERE</div>
                <h1>
                  让故事，<em>有声有色。</em>
                </h1>
                <p>
                  从一个灵感出发，或重逢一本好书。
                  <br />
                  在叙声，把文字写成属于你的世界。
                </p>
              </div>
              <div className="intro-art" aria-hidden="true">
                <div className="art-orbit orbit-one" />
                <div className="art-orbit orbit-two" />
                <div className="art-book">
                  <span>叙</span>
                  <i />
                  <small>
                    A WORLD
                    <br />
                    IN WORDS.
                  </small>
                </div>
                <div className="art-note">
                  <AudioLines size={32} />
                </div>
                <span className="art-star">✦</span>
              </div>
            </div>
            <div className="entry-grid">
              <button
                className="entry-card create-card"
                disabled={!ready || busy}
                onClick={() => {
                  setTitle('');
                  setModal('create');
                }}
              >
                <span className="entry-icon">
                  <Feather size={24} />
                </span>
                <div>
                  <span className="entry-kicker">从零开始</span>
                  <h2>写下一个新世界</h2>
                  <p>空白手写、一句灵感，让故事从这里生长。</p>
                </div>
                <span className="round-arrow">
                  <Plus size={20} />
                </span>
              </button>
              <button
                className="entry-card import-card"
                disabled={!ready || busy}
                onClick={() => {
                  if (!fileRunning) setPreview(null);
                  setTitle('');
                  setModal('import');
                }}
              >
                <span className="entry-icon">
                  <FolderOpen size={24} />
                </span>
                <div>
                  <span className="entry-kicker">继续一段旅程</span>
                  <h2>导入你的小说</h2>
                  <p>导入 TXT、EPUB、PDF，与故事再次相遇。</p>
                </div>
                <span className="round-arrow">
                  <ArrowRight size={20} />
                </span>
              </button>
            </div>
            <button
              className="outline-button"
              disabled={!ready || busy}
              onClick={() => setModal('backup')}
            >
              <Download size={16} /> 备份与恢复
            </button>
            <section className="books-section">
              <div className="section-heading">
                <h2>
                  我的作品 <span>{books.length.toString().padStart(2, '0')}</span>
                </h2>
                <label className="search">
                  <Search size={16} />
                  <input
                    placeholder="搜索作品名称"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                  />
                </label>
              </div>
              {books.length === 0 ? (
                <div className="empty-library">
                  <div className="empty-icon">
                    <BookOpen size={30} />
                  </div>
                  <h3>这里，等着你的第一个故事</h3>
                  <p>新建一部作品，或导入一本小说。无需配置模型即可开始写作。</p>
                  <span>文字会被珍藏，故事会有回声。</span>
                </div>
              ) : (
                <div className="book-grid">
                  {books
                    .filter((b) => b.title.toLowerCase().includes(search.toLowerCase()))
                    .map((book, i) => (
                      <button
                        key={book.book_id}
                        className="book-card"
                        disabled={busy}
                        onClick={() =>
                          void action(async () => {
                            await enter(await rpc('branch.get', { branch_id: book.branch_id }));
                          })
                        }
                      >
                        <div className={`book-cover cover-${i % 3}`}>
                          <span className="cover-number">
                            N° {(i + 1).toString().padStart(2, '0')}
                          </span>
                          <strong>{book.title}</strong>
                          <Feather size={26} />
                          <small>NARRAVO · 叙声</small>
                        </div>
                        <h3>{book.title}</h3>
                        <p>
                          <span className="source-tag">
                            {book.origin_type === 'original' ? '原创' : '导入'}
                          </span>
                          {book.chapter_count} 章 · {book.word_count.toLocaleString()} 字
                        </p>
                        <small>
                          最近编辑 {new Date(book.updated_at).toLocaleDateString('zh-CN')}
                        </small>
                      </button>
                    ))}
                </div>
              )}
            </section>
            <footer className="library-footer">
              <span>
                <span className="status-dot" /> 本地保存，安心创作
              </span>
              <span>
                {providerState.external_enabled
                  ? '外部服务已启用 · 仅在显式请求时调用'
                  : '外部模型请求已关闭'}
              </span>
            </footer>
          </main>
        ) : (
          <div className="workspace">
            <aside className="chapter-panel">
              <button className="back-link" disabled={busy} onClick={() => void action(back)}>
                <ArrowLeft size={15} />
                返回作品库
              </button>
              <div className="work-title">
                <span className="source-tag">
                  {w.origin_type === 'original' ? '原创作品' : '导入作品'}
                </span>
                <h2>{w.title}</h2>
                <p>
                  {w.chapters.length} 章 <span>·</span> {w.word_count.toLocaleString()} 字
                </p>
              </div>
              <div className="branch-control">
                <GitBranch size={15} />
                <select
                  aria-label="当前分支"
                  value={w.branch_id}
                  disabled={busy || taskRunning}
                  onChange={(e) =>
                    void action(async () => {
                      await flush();
                      await enter(await rpc('branch.get', { branch_id: e.target.value }));
                    })
                  }
                >
                  {w.branches.map((b) => (
                    <option key={b.id} value={b.id}>
                      {b.name}
                    </option>
                  ))}
                </select>
                <button
                  aria-label="创建分支"
                  disabled={busy || taskRunning}
                  onClick={() => {
                    setTitle('新的可能');
                    setModal('fork');
                  }}
                >
                  <Plus size={15} />
                </button>
              </div>
              <div className="chapter-heading">
                <span>章节目录</span>
                <button
                  aria-label="新建章节"
                  disabled={busy || taskRunning}
                  onClick={() =>
                    void action(async () => {
                      await flush();
                      const current = useWork.getState().workspace!;
                      const next = await rpc('chapter.create', {
                        branch_id: current.branch_id,
                        expected_snapshot: current.snapshot_id,
                        title: `第${current.chapters.length + 1}章`,
                      });
                      await openWorkspace(next, next.chapters.at(-1)!.id);
                      setTask(null);
                    })
                  }
                >
                  <Plus size={17} />
                </button>
              </div>
              <div className="chapter-list">
                {w.chapters.map((ch, i) => (
                  <button
                    className={`chapter-link ${chapter?.chapter_id === ch.id ? 'selected' : ''}`}
                    key={ch.id}
                    disabled={busy || taskRunning}
                    onClick={() =>
                      void action(async () => {
                        await flush();
                        await openWorkspace(useWork.getState().workspace!, ch.id);
                        setTask(null);
                      })
                    }
                  >
                    <span className="chapter-number">{(i + 1).toString().padStart(2, '0')}</span>
                    <span>
                      <strong>{ch.title}</strong>
                      <small>
                        {ch.word_count} 字 ·{' '}
                        {ch.status === 'draft'
                          ? '草稿'
                          : ch.status === 'revising'
                            ? '修订中'
                            : '已完成'}
                      </small>
                    </span>
                    {chapter?.chapter_id === ch.id && <span className="chapter-dot" />}
                  </button>
                ))}
              </div>
              <div className="sidebar-note">
                <Feather size={17} />
                <p>
                  不必等故事完整，
                  <br />
                  先写下你想写的一页。
                </p>
              </div>
            </aside>
            <main className="writing-main">
              <div className="document-header">
                <div>
                  <span className="eyebrow">WRITING STUDIO</span>
                  <h1>{currentMeta?.title}</h1>
                </div>
                <div className="document-actions">
                  <span className="save-state" role="status">
                    {saving ? (
                      <>
                        <LoaderCircle size={13} />
                        保存中
                      </>
                    ) : dirty ? (
                      '待保存'
                    ) : (
                      <>
                        <Check size={13} />
                        已保存到本地
                      </>
                    )}
                  </span>
                  <button
                    className="subtle-button"
                    disabled={busy || taskRunning}
                    onClick={() =>
                      void action(async () => {
                        await flush();
                        setHistory(
                          (await rpc('branch.history', { branch_id: w.branch_id })).entries,
                        );
                        setModal('history');
                      })
                    }
                  >
                    版本历史
                  </button>
                  <button
                    className="subtle-button"
                    disabled={busy || taskRunning}
                    onClick={() => {
                      setTitle(currentMeta?.title ?? '');
                      setModal('chapter');
                    }}
                  >
                    章节管理
                  </button>
                  <select
                    className="export-format"
                    aria-label="导出格式"
                    value={exportFormat}
                    onChange={(e) => setExportFormat(e.target.value as 'txt' | 'md')}
                  >
                    <option value="txt">TXT</option>
                    <option value="md">Markdown</option>
                  </select>
                  <button
                    className="subtle-button"
                    disabled={busy}
                    onClick={() =>
                      void action(async () => {
                        await flush();
                        if (await exportBook(w.branch_id, exportFormat))
                          setNotice('正文已导出，不含设定与候选');
                      })
                    }
                  >
                    <Download size={15} />
                    导出
                  </button>
                </div>
              </div>
              <div className="document-paper">
                <Editor key={`${w.branch_id}:${chapter?.chapter_id}`} disabled={busy} />
              </div>
              <div className="document-footer">
                <span>
                  {wordCount(text).toLocaleString()} 字 <span>·</span> 当前章节
                </span>
                <button onClick={() => void action(prepareNarration)}>
                  <Headphones size={15} />
                  试听本章
                </button>
                <span>正文修订独立保存</span>
              </div>
            </main>
            <aside className="inspector">
              <div className="inspector-tabs">
                <button
                  className={tab === 'writing' ? 'active' : ''}
                  onClick={() => setTab('writing')}
                >
                  <Sparkles size={15} />
                  写作助手
                </button>
                <button
                  className={tab === 'planning' ? 'active' : ''}
                  onClick={() => setTab('planning')}
                >
                  <BookOpen size={15} />
                  故事设定
                </button>
              </div>
              {tab === 'planning' ? (
                <div className="inspector-body">
                  <div className="panel-title">
                    <h3>让世界逐渐清晰</h3>
                    <button
                      aria-label="添加设定"
                      onClick={() => {
                        setPlan(newPlan());
                        setModal('plan');
                      }}
                    >
                      <Plus size={18} />
                    </button>
                  </div>
                  <p className="muted small">
                    可随时跳过规划，直接写作。设定与正文分别保存，分支间互不覆盖。
                  </p>
                  {w.planning.length === 0 ? (
                    <div className="plan-empty">
                      <Feather size={26} />
                      <p>
                        主角是谁？世界是什么模样？
                        <br />
                        把散落的想法留在这里。
                      </p>
                      <button
                        className="outline-button"
                        onClick={() => {
                          setPlan(newPlan());
                          setModal('plan');
                        }}
                      >
                        添加第一个设定
                      </button>
                    </div>
                  ) : (
                    w.planning.map((entry) => (
                      <button
                        className="plan-card"
                        key={entry.id}
                        onClick={() => {
                          setPlan({ ...entry });
                          setModal('plan');
                        }}
                      >
                        <span>
                          {kindNames[entry.kind]}
                          {entry.author_only ? ' · 作者秘密' : ''}
                        </span>
                        <h4>{entry.title}</h4>
                        <p>{entry.text}</p>
                        <small>
                          {entry.context_role === 'planned_event' ? '未来计划 · 尚未发生' : '设定'}{' '}
                          · 人工锁定
                        </small>
                      </button>
                    ))
                  )}
                </div>
              ) : (
                <div className="inspector-body">
                  <div className="demo-label">
                    <span className="status-dot" />{' '}
                    {llmId === 'demo'
                      ? '本地演示模式 · 无网络调用'
                      : llmConfig
                        ? `${llmConfig.name} · ${llmConfig.model}`
                        : '请先配置所选模型'}
                  </div>
                  <h3>下一段故事，往哪里去？</h3>
                  <p className="muted small">
                    {llmId === 'demo'
                      ? '描述开篇或本章目标。演示会返回固定样文，用于体验候选流程。'
                      : '将依据已保存正文、创作意图和明确选中的设定生成候选。'}
                  </p>
                  <label className="field-label" htmlFor="llm-config">
                    本次文本模型
                  </label>
                  <select
                    id="llm-config"
                    className="field-select"
                    value={llmId}
                    disabled={taskRunning || busy}
                    onChange={(e) => setLlmId(e.target.value)}
                  >
                    <option value="demo">本地演示 · 固定样文</option>
                    {providerState.providers
                      .filter((p) => p.kind === 'llm')
                      .map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name} · {p.model}
                        </option>
                      ))}
                  </select>
                  <button className="context-link" onClick={() => openSettings('llm')}>
                    管理 LLM 配置
                  </button>
                  <label className="field-label" htmlFor="intent">
                    本次创作意图
                  </label>
                  <textarea
                    id="intent"
                    className="intent-input"
                    placeholder="例如：一名修钟匠发现，全城的人每天都少活一分钟……"
                    value={intent}
                    onChange={(e) => setIntent(e.target.value)}
                    disabled={taskRunning || busy}
                    maxLength={2000}
                  />
                  <label className="field-label" htmlFor="policy">
                    上下文策略
                  </label>
                  <select
                    id="policy"
                    className="field-select"
                    value={policy}
                    disabled={taskRunning || busy}
                    onChange={(e) => setPolicy(e.target.value as typeof policy)}
                  >
                    <option value="author_plan">作者规划 · 使用所选设定</option>
                    <option value="reader_safe">读者无剧透 · 仅可见内容</option>
                    <option value="full_rewrite">完整改写 · 明确选择范围</option>
                  </select>
                  {policy === 'full_rewrite' && (
                    <div className="check-list">
                      {w.chapters.map((ch) => (
                        <label key={ch.id}>
                          <input
                            type="checkbox"
                            checked={rewriteIds.includes(ch.id)}
                            onChange={(e) =>
                              setRewriteIds((old) =>
                                e.target.checked
                                  ? [...old, ch.id]
                                  : old.filter((id) => id !== ch.id),
                              )
                            }
                          />
                          {ch.title}
                        </label>
                      ))}
                    </div>
                  )}
                  {w.planning.length > 0 && (
                    <details className="planning-select">
                      <summary>选择本次参考设定（{selectedPlans.length}）</summary>
                      {w.planning.map((entry) => (
                        <label key={entry.id}>
                          <input
                            type="checkbox"
                            checked={selectedPlans.includes(entry.id)}
                            disabled={taskRunning || busy}
                            onChange={(e) =>
                              setSelectedPlans((old) =>
                                e.target.checked
                                  ? [...old, entry.id]
                                  : old.filter((id) => id !== entry.id),
                              )
                            }
                          />
                          <span>
                            {entry.title}
                            {entry.author_only ? ' · 作者秘密' : ''}
                          </span>
                        </label>
                      ))}
                    </details>
                  )}
                  <button
                    className="context-link"
                    disabled={busy}
                    onClick={() =>
                      void action(async () => {
                        await flush();
                        setContext(await rpc('writing.preview_context', target()));
                        setModal('context');
                      })
                    }
                  >
                    查看本次上下文 <ArrowRight size={13} />
                  </button>
                  <button
                    className="primary-button generate-button"
                    disabled={busy || (!taskRunning && !intent.trim())}
                    onClick={() =>
                      void action(async () => {
                        if (taskRunning && task)
                          setTask(await rpc('task.cancel', { task_id: task.task_id }));
                        else await generate();
                      })
                    }
                  >
                    {taskRunning ? (
                      <>
                        <Square size={15} />
                        停止生成
                      </>
                    ) : (
                      <>
                        <Sparkles size={16} />
                        {llmId === 'demo' ? '生成演示候选' : '生成候选'}
                      </>
                    )}
                  </button>
                  <p className="privacy-note">
                    写作位置：当前章节末尾
                    <br />
                    {llmId === 'demo'
                      ? '演示不产生费用。'
                      : `将发送已保存正文与所选规划至 ${llmConfig?.base_url ?? '所选服务'}；费用未知，以平台账单为准。`}
                    {llmId !== 'demo' && !providerState.external_enabled && (
                      <>
                        <br />
                        外部服务已关闭，请在模型设置中启用。
                      </>
                    )}
                  </p>
                  {task && (
                    <section className="candidate">
                      <div className="candidate-header">
                        <h4>
                          {task.generation?.accepted
                            ? '候选 · 已接纳到正文'
                            : '候选 · 尚未写入正文'}
                        </h4>
                        <span>
                          {taskRunning
                            ? '生成中'
                            : task.status === 'cancelled'
                              ? '已停止'
                              : task.status === 'failed'
                                ? '失败（保留已收到内容）'
                                : '已完成'}
                        </span>
                      </div>
                      {task.message && (
                        <p
                          className={task.status === 'failed' ? 'warning' : 'small muted'}
                          role={task.status === 'failed' ? 'alert' : undefined}
                        >
                          {task.message}
                        </p>
                      )}
                      {task.usage && (
                        <p className="small muted">
                          已提交 {task.usage.requests_submitted} 次 · 输入{' '}
                          {task.usage.input_tokens ?? '未知'} / 输出{' '}
                          {task.usage.output_tokens ?? '未知'} tokens · 费用未知
                        </p>
                      )}
                      <textarea
                        aria-label="生成候选"
                        readOnly
                        value={task.generation?.text ?? ''}
                        onSelect={(e) => {
                          if (taskRunning) return;
                          const el = e.currentTarget;
                          if (el.selectionEnd > el.selectionStart) {
                            setSelection([
                              toCodePoint(el.value, el.selectionStart),
                              toCodePoint(el.value, el.selectionEnd),
                            ]);
                            setAcceptText(el.value.slice(el.selectionStart, el.selectionEnd));
                          }
                        }}
                      />
                      {!taskRunning && task.generation && !task.generation.accepted && (
                        <>
                          <p className="small muted">可在上方选择片段，再编辑要接纳的文字。</p>
                          <label className="field-label" htmlFor="accept-text">
                            接纳内容（可编辑）
                          </label>
                          <textarea
                            id="accept-text"
                            value={acceptText}
                            onChange={(e) => setAcceptText(e.target.value)}
                          />
                          <button
                            className="primary-button"
                            disabled={busy || !acceptText.trim() || selection[1] <= selection[0]}
                            onClick={() => void action(accept)}
                          >
                            <Check size={15} />
                            {selection[1] - selection[0] < [...task.generation.text].length
                              ? '接纳选中片段'
                              : '接纳候选'}
                          </button>
                        </>
                      )}
                      {task.generation?.accepted && (
                        <p className="accepted-label">
                          <Check size={15} />
                          已接纳，正文已保存为新修订
                        </p>
                      )}
                    </section>
                  )}
                </div>
              )}
              <div className="narration-panel">
                <h4>
                  <Headphones size={15} />
                  普通朗读
                </h4>
                <label className="field-label" htmlFor="tts-config">
                  语音服务与音色
                </label>
                <select
                  id="tts-config"
                  className="field-select"
                  value={ttsId}
                  disabled={audioTask?.status === 'running'}
                  onChange={(e) => {
                    setTtsId(e.target.value);
                    setAudioTask(null);
                  }}
                >
                  <option value="">选择 TTS 配置</option>
                  {providerState.providers
                    .filter((p) => p.kind === 'tts')
                    .map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name} · {p.voice}
                      </option>
                    ))}
                </select>
                <button className="context-link" onClick={() => openSettings('tts')}>
                  管理 TTS 配置
                </button>
                <button
                  className="outline-button"
                  disabled={busy}
                  onClick={() =>
                    void action(async () => {
                      if (audioTask?.status === 'running')
                        setAudioTask(await rpc('task.cancel', { task_id: audioTask.task_id }));
                      else await prepareNarration();
                    })
                  }
                >
                  {audioTask?.status === 'running' ? '停止合成' : '准备本章语音'}
                </button>
                {audioTask && (
                  <>
                    <p className="small muted">
                      {audioTask.message ?? '准备中…'}
                      <br />
                      本次提交 {audioTask.usage?.requests_submitted ?? 0} 次 · 费用未知
                    </p>
                    {audioTask.audio && audioTask.audio.segments.length > 0 && (
                      <AudioPlayer
                        plan={audioTask.audio}
                        stale={
                          audioTask.audio.branch_id !== w.branch_id ||
                          audioTask.audio.chapter_id !== chapter?.chapter_id ||
                          audioTask.audio.revision !== currentMeta?.revision ||
                          dirty
                        }
                        onError={(value) => useWork.setState({ error: value })}
                      />
                    )}
                  </>
                )}
              </div>
              <div className="inspector-footer">
                <CircleHelp size={14} /> 你的文字，由你决定。
              </div>
            </aside>
          </div>
        )}
      </div>
      {modal === 'create' && (
        <Modal title="新建作品" close={() => setModal(null)}>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void action(createBook);
            }}
          >
            <p className="muted">一张白纸，一个新世界。无需文件、模型或大纲。</p>
            <label className="field-label" htmlFor="book-title">
              作品名称
            </label>
            <input
              id="book-title"
              className="field-input"
              autoFocus
              placeholder="未命名作品"
              maxLength={120}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
            <div className="modal-note">
              <Feather size={18} />
              <span>立即创建第一章。进入后可以手写，也可以补充灵感与设定。</span>
            </div>
            <button className="primary-button" type="submit" disabled={busy}>
              开始创作 <ArrowRight size={16} />
            </button>
          </form>
        </Modal>
      )}
      {modal === 'import' && (
        <Modal title="导入小说" close={() => void action(closeFileModal)}>
          <p className="muted">
            支持 TXT（10 MiB）、无 DRM 的流式 EPUB 和文本型 PDF（100 MiB）。保留原文件；扫描件需先
            OCR。
          </p>
          <label className="field-label" htmlFor="encoding">
            TXT 文本编码
          </label>
          <select
            id="encoding"
            className="field-select"
            value={encoding}
            onChange={(e) => {
              setEncoding(e.target.value);
              setPreview(null);
            }}
          >
            <option value="auto">自动识别</option>
            <option value="utf-8">UTF-8</option>
            <option value="utf-16">UTF-16</option>
            <option value="gb18030">GB18030</option>
          </select>
          <button
            className="outline-button"
            disabled={busy || fileRunning}
            onClick={() => void action(chooseFile)}
          >
            <FolderOpen size={16} />
            选择 TXT / EPUB / PDF 文件
          </button>
          <label className="field-label" htmlFor="pdf-password">
            PDF 密码（仅加密文件需要，不保存）
          </label>
          <input
            id="pdf-password"
            className="field-input"
            type="password"
            autoComplete="off"
            value={pdfPassword}
            onChange={(e) => setPdfPassword(e.target.value)}
          />
          <label className="small">
            <input
              type="checkbox"
              checked={removePdfMargins}
              onChange={(e) => setRemovePdfMargins(e.target.checked)}
              disabled={fileRunning}
            />
            尝试移除重复页眉页脚（PDF，可选）
          </label>
          {fileOp?.kind === 'import' && (
            <div role="status">
              <p>{fileOp.stage}</p>
              {fileOp.message && <p className="warning">{fileOp.message}</p>}
              {fileRunning && (
                <button
                  className="outline-button"
                  onClick={() =>
                    void action(async () =>
                      setFileOp(await rpc('file.cancel', { operation_id: fileOp.operation_id })),
                    )
                  }
                >
                  取消处理
                </button>
              )}
            </div>
          )}
          {!isTauri() && (
            <input
              aria-label="测试导入文件"
              type="file"
              accept=".txt,.epub,.pdf"
              disabled={fileRunning}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (!file) return;
                void action(async () => {
                  const next = await rpc('file.start_import', {
                    filename: file.name,
                    content_b64: await readBrowserFile(file),
                    encoding: encoding as 'auto',
                    password: pdfPassword,
                    remove_pdf_margins: removePdfMargins,
                  });
                  setPreview(null);
                  setPdfPassword('');
                  setFileOp(next);
                });
              }}
            />
          )}
          {preview && (
            <>
              <label className="field-label" htmlFor="import-title">
                作品名称
              </label>
              <input
                id="import-title"
                className="field-input"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
              />
              <p className="small">
                {preview.encoding} · {preview.chapters.length} 章
              </p>
              {preview.warnings.map((v) => (
                <p className="warning" key={v}>
                  {v}
                </p>
              ))}
              <details>
                <summary>章节 / 页面列表与顺序</summary>
                <ol>
                  {preview.chapters.map((name, i) => (
                    <li key={i}>{name}</li>
                  ))}
                </ol>
              </details>
              {!!(preview.omitted_pages ?? []).length && (
                <label className="small">
                  <input
                    type="checkbox"
                    checked={acceptIncomplete}
                    onChange={(e) => setAcceptIncomplete(e.target.checked)}
                  />
                  我已核对遗漏页码（{(preview.omitted_pages ?? []).join('、')}），接受不完整导入
                </label>
              )}
              <pre className="import-sample">{preview.sample}</pre>
              <button
                className="primary-button"
                disabled={
                  busy ||
                  fileRunning ||
                  !title.trim() ||
                  (!!(preview.omitted_pages ?? []).length && !acceptIncomplete)
                }
                onClick={() =>
                  void action(async () => {
                    await enter(
                      await rpc('book.confirm_import', {
                        import_id: preview.import_id,
                        title,
                        accept_incomplete: acceptIncomplete,
                      }),
                    );
                    setModal(null);
                  })
                }
              >
                确认导入 <Check size={16} />
              </button>
            </>
          )}
        </Modal>
      )}
      {modal === 'backup' && (
        <Modal title="备份与恢复" close={() => void action(closeFileModal)}>
          <p className="muted">
            完整备份包括全部作品、原文件、修订历史、分支、设定、大纲及候选接纳记录。可选音频。备份未加密，包含作者秘密；不含模型配置、系统密钥或外部请求授权。
          </p>
          <label className="small">
            <input
              type="checkbox"
              checked={includeAudio}
              onChange={(e) => setIncludeAudio(e.target.checked)}
              disabled={fileRunning}
            />
            包含已有音频缓存
          </label>
          <button
            className="primary-button"
            disabled={busy || fileRunning}
            onClick={() =>
              void action(async () => {
                await flush();
                setFileOp(await rpc('backup.create', { include_audio: includeAudio }));
              })
            }
          >
            创建完整备份
          </button>
          <p className="muted">
            恢复会校验全部文件，在本机创建并切换到独立书库。当前书库保留，不合并或覆盖。恢复的书库默认关闭外部服务。
          </p>
          <button
            className="outline-button"
            disabled={busy || fileRunning}
            onClick={() =>
              void action(async () => {
                if (isTauri()) {
                  const next = await pickRestore();
                  if (next) setFileOp(next);
                }
              })
            }
          >
            选择备份文件
          </button>
          {!isTauri() && (
            <input
              type="file"
              aria-label="测试恢复文件"
              accept=".narravo"
              disabled={fileRunning}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (!file) return;
                void action(async () =>
                  setFileOp(
                    await rpc('backup.preview_restore', {
                      content_b64: await readBrowserFile(file),
                    }),
                  ),
                );
              }}
            />
          )}
          {fileOp && (
            <div role="status">
              <p>{fileOp.stage}</p>
              {fileOp.message && <p className="warning">{fileOp.message}</p>}
              {fileRunning && (
                <button
                  className="outline-button"
                  onClick={() =>
                    void action(async () =>
                      setFileOp(await rpc('file.cancel', { operation_id: fileOp.operation_id })),
                    )
                  }
                >
                  取消处理
                </button>
              )}
              {fileOp.status === 'completed' && fileOp.kind !== 'import' && (
                <p>
                  {fileOp.book_count} 部作品 · {fileOp.include_audio ? '含音频' : '不含音频'} ·{' '}
                  {((fileOp.size ?? 0) / 1024 / 1024).toFixed(2)} MiB
                </p>
              )}
              {fileOp.kind === 'backup' && fileOp.status === 'completed' && (
                <button
                  className="primary-button"
                  disabled={!isTauri() || busy}
                  onClick={() =>
                    void action(async () => {
                      if (await saveBackup(fileOp.operation_id)) setNotice('完整备份已保存。');
                    })
                  }
                >
                  保存备份文件
                </button>
              )}
              {fileOp.kind === 'restore' && fileOp.activated && (
                <button
                  className="outline-button"
                  disabled={busy || fileRunning}
                  onClick={() =>
                    void action(async () => {
                      await rpc('backup.return_previous', { operation_id: fileOp.operation_id });
                      setSurface('books');
                      stopAudioFocus();
                      setTask(null);
                      setAudioTask(null);
                      setLlmId('demo');
                      setTtsId('');
                      await loadLibrary();
                      await refreshProviders();
                      setNotice('已切回恢复前书库，恢复出的书库仍保留在本机。');
                    })
                  }
                >
                  切回恢复前书库
                </button>
              )}
              {fileOp.kind === 'restore' && fileOp.status === 'completed' && (
                <button
                  className="primary-button"
                  disabled={busy}
                  onClick={() =>
                    void action(async () => {
                      await rpc('backup.activate_restore', { operation_id: fileOp.operation_id });
                      setSurface('books');
                      stopAudioFocus();
                      setTask(null);
                      setAudioTask(null);
                      setLlmId('demo');
                      setTtsId('');
                      await loadLibrary();
                      await refreshProviders();
                      setFileOp(await rpc('file.get', { operation_id: fileOp.operation_id }));
                      setNotice('已切换至恢复书库，原书库仍保留在本机。');
                    })
                  }
                >
                  {fileOp.activated ? '切换到恢复书库' : '恢复为独立书库并切换'}
                </button>
              )}
            </div>
          )}
        </Modal>
      )}
      {modal === 'settings' && (
        <Modal
          title="模型与语音设置"
          close={() => {
            setModal(null);
            void refreshProviders();
          }}
        >
          <ProviderSettings
            initialKind={settingsKind}
            state={providerState}
            refresh={refreshProviders}
            onSaved={(config) => {
              if (config.kind === 'llm') setLlmId(config.id);
              else setTtsId(config.id);
            }}
          />
        </Modal>
      )}
      {showNarrationConfirm && w && (
        <Modal title="准备本章语音" close={() => setShowNarrationConfirm(false)}>
          <p className="muted small">
            将发送当前已保存章节的正文给以下语音服务，不发送创作规划、作者秘密或未接纳候选。
          </p>
          <div className="modal-note">
            <span>
              {ttsConfig?.name} · {ttsConfig?.model}
              <br />
              {ttsConfig?.base_url}
              <br />
              音色：{ttsConfig?.voice} · {[...text].length} 字符
            </span>
          </div>
          <p className="warning">
            按最多 280 字符分段，最多约 {Math.ceil([...text].length / 140)}{' '}
            次请求；已有匹配缓存会复用。费用未知，请以服务平台账单为准。单次合成最多一万字符。
          </p>
          <button
            className="primary-button"
            disabled={busy || !ttsConfig || !providerState.external_enabled}
            onClick={() =>
              void action(async () => {
                await flush();
                const current = useWork.getState();
                setAudioTask(
                  await rpc('narration.synthesize', {
                    config_id: ttsId,
                    branch_id: current.workspace!.branch_id,
                    chapter_id: current.chapter!.chapter_id,
                    expected_snapshot: current.workspace!.snapshot_id,
                    max_characters: 10000,
                  }),
                );
                setShowNarrationConfirm(false);
              })
            }
          >
            开始合成（可能计费）
          </button>
          {!providerState.external_enabled && (
            <p className="small muted">请先在模型设置中启用外部服务。</p>
          )}
        </Modal>
      )}
      {modal === 'fork' && w && (
        <Modal title="创建故事分支" close={() => setModal(null)}>
          <p className="muted">从当前快照开始尝试另一种走向，正文、章节和规划独立演进。</p>
          <label className="field-label" htmlFor="branch-name">
            分支名称
          </label>
          <input
            id="branch-name"
            className="field-input"
            value={title}
            maxLength={80}
            onChange={(e) => setTitle(e.target.value)}
          />
          <button
            className="primary-button"
            disabled={busy || !title.trim()}
            onClick={() =>
              void action(async () => {
                await flush();
                const current = useWork.getState().workspace!;
                await enter(
                  await rpc('branch.fork', {
                    branch_id: current.branch_id,
                    expected_snapshot: current.snapshot_id,
                    name: title,
                  }),
                  chapter?.chapter_id,
                );
                setModal(null);
              })
            }
          >
            <GitBranch size={16} />
            创建分支
          </button>
        </Modal>
      )}
      {modal === 'chapter' && w && chapter && (
        <Modal title="章节管理" close={() => setModal(null)}>
          <label className="field-label" htmlFor="chapter-title">
            章节名称
          </label>
          <input
            id="chapter-title"
            className="field-input"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            maxLength={120}
          />
          <button
            className="primary-button"
            disabled={busy || !title.trim()}
            onClick={() =>
              void action(async () => {
                await mutate((cur) =>
                  rpc('chapter.update', {
                    branch_id: cur.branch_id,
                    expected_snapshot: cur.snapshot_id,
                    chapter_id: chapter.chapter_id,
                    title,
                    status: currentMeta?.status ?? 'draft',
                  }),
                );
                setModal(null);
              })
            }
          >
            保存名称
          </button>
          <label className="field-label" htmlFor="chapter-status">
            章节状态（由你管理）
          </label>
          <select
            id="chapter-status"
            className="field-select"
            value={currentMeta?.status}
            onChange={(e) =>
              void action(async () => {
                await mutate((cur) =>
                  rpc('chapter.update', {
                    branch_id: cur.branch_id,
                    expected_snapshot: cur.snapshot_id,
                    chapter_id: chapter.chapter_id,
                    title: currentMeta!.title,
                    status: e.target.value as 'draft' | 'revising' | 'done',
                  }),
                );
              })
            }
          >
            <option value="draft">草稿</option>
            <option value="revising">修订中</option>
            <option value="done">已完成</option>
          </select>
          <div className="inline-actions">
            {[-1, 1].map((direction) => (
              <button
                className="outline-button"
                key={direction}
                disabled={
                  busy ||
                  w.chapters.findIndex((c) => c.id === chapter.chapter_id) + direction < 0 ||
                  w.chapters.findIndex((c) => c.id === chapter.chapter_id) + direction >=
                    w.chapters.length
                }
                onClick={() =>
                  void action(async () => {
                    await mutate((cur) => {
                      const ids = cur.chapters.map((c) => c.id);
                      const index = ids.indexOf(chapter.chapter_id);
                      [ids[index], ids[index + direction]] = [ids[index + direction], ids[index]];
                      return rpc('chapter.reorder', {
                        branch_id: cur.branch_id,
                        expected_snapshot: cur.snapshot_id,
                        ordered_ids: ids,
                      });
                    });
                  })
                }
              >
                {direction === -1 ? <ArrowUp size={15} /> : <ArrowDown size={15} />}向
                {direction === -1 ? '上' : '下'}移动
              </button>
            ))}
          </div>
          <button
            className="text-danger"
            disabled={busy || w.chapters.length < 2}
            onClick={() =>
              void action(async () => {
                await flush();
                const cur = useWork.getState().workspace!;
                const next = await rpc('chapter.remove', {
                  branch_id: cur.branch_id,
                  expected_snapshot: cur.snapshot_id,
                  chapter_id: chapter.chapter_id,
                });
                await openWorkspace(next);
                setModal(null);
              })
            }
          >
            从当前分支移除此章（历史快照保留）
          </button>
        </Modal>
      )}
      {modal === 'plan' && w && (
        <Modal
          title={w.planning.some((p) => p.id === plan.id) ? '编辑故事设定' : '添加故事设定'}
          close={() => setModal(null)}
        >
          <label className="field-label" htmlFor="plan-kind">
            类型
          </label>
          <select
            id="plan-kind"
            className="field-select"
            value={plan.kind}
            onChange={(e) => {
              const kind = e.target.value as PlanningEntry['kind'];
              setPlan({
                ...plan,
                kind,
                context_role: kind === 'outline' ? 'planned_event' : 'setting',
              });
            }}
          >
            {Object.entries(kindNames).map(([key, value]) => (
              <option key={key} value={key}>
                {value}
              </option>
            ))}
          </select>
          <label className="field-label" htmlFor="plan-title">
            标题 / 人物姓名
          </label>
          <input
            id="plan-title"
            className="field-input"
            value={plan.title}
            maxLength={120}
            onChange={(e) => setPlan({ ...plan, title: e.target.value })}
          />
          <label className="field-label" htmlFor="plan-text">
            内容
          </label>
          <textarea
            id="plan-text"
            className="field-input plan-text"
            value={plan.text}
            maxLength={20000}
            onChange={(e) => setPlan({ ...plan, text: e.target.value })}
          />
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={plan.author_only}
              onChange={(e) => setPlan({ ...plan, author_only: e.target.checked })}
            />
            作者秘密（作者规划模式仍可明确选用）
          </label>
          <label className="field-label" htmlFor="visible-from">
            在此章之后对读者可见
          </label>
          <select
            id="visible-from"
            className="field-select"
            value={plan.visible_from ?? ''}
            onChange={(e) => setPlan({ ...plan, visible_from: e.target.value || null })}
          >
            <option value="">尚未披露 · 仅作作者参考</option>
            {w.chapters.map((ch) => (
              <option key={ch.id} value={ch.id}>
                {ch.title}
              </option>
            ))}
          </select>
          <p className="small muted">
            {plan.context_role === 'planned_event'
              ? '此条目是未来计划，不会作为已经发生的事实。'
              : '人工设定会保持锁定，不会被自动分析覆盖。'}
          </p>
          <button
            className="primary-button"
            disabled={busy || !plan.title.trim()}
            onClick={() =>
              void action(async () => {
                await mutate((cur) =>
                  rpc('planning.save', {
                    branch_id: cur.branch_id,
                    expected_snapshot: cur.snapshot_id,
                    entries: [...cur.planning.filter((e) => e.id !== plan.id), plan],
                  }),
                );
                setModal(null);
              })
            }
          >
            保存设定 <Check size={16} />
          </button>
        </Modal>
      )}
      {modal === 'context' && context && (
        <Modal title="本次上下文预览" close={() => setModal(null)}>
          <p className="warning">{context.warning}</p>
          <p className="small">
            估算 {context.estimated_tokens} tokens · 输出预留 {llmConfig?.max_output_tokens ?? 2048}{' '}
            · 余量 512 · 上限 {llmConfig?.context_limit ?? 16384}
          </p>
          {context.missing_chapter_ids.length > 0 && (
            <p className="warning">
              有 {context.missing_chapter_ids.length} 个前置章节尚未写作，没有编造前文摘要。
            </p>
          )}
          <h4>已保存正文</h4>
          <pre className="import-sample">{context.preceding_text || '无前文：从空白开始。'}</pre>
          <h4>明确选中的规划</h4>
          {context.planning.length ? (
            context.planning.map((entry) => (
              <div className="context-entry" key={entry.id}>
                <strong>
                  {entry.title} · {entry.context_role === 'planned_event' ? '未来计划' : '设定'}
                  {entry.author_only ? ' · 作者秘密' : ''}
                </strong>
                <p>{entry.text}</p>
              </div>
            ))
          ) : (
            <p className="muted">没有选中可用规划。</p>
          )}
        </Modal>
      )}
      {modal === 'history' && w && (
        <Modal title="版本历史" close={() => setModal(null)}>
          <p className="muted small">
            恢复会同时恢复当时的正文、章节结构与规划，并保留当前版本。最多展示最近 30 个保存版本。
          </p>
          {history.map((entry, index) => (
            <div className="history-row" key={entry.snapshot_id}>
              <div>
                <strong>{index === 0 ? '当前版本' : `之前的第 ${index} 个版本`}</strong>
                <p>
                  {entry.chapter_count} 章 · {entry.word_count} 字 · {entry.planning_count} 条设定
                </p>
              </div>
              {index > 0 && (
                <button
                  className="outline-button"
                  disabled={busy}
                  onClick={() =>
                    void action(async () => {
                      await flush();
                      const current = useWork.getState().workspace!;
                      const next = await rpc('branch.restore', {
                        branch_id: current.branch_id,
                        expected_snapshot: current.snapshot_id,
                        snapshot_id: entry.snapshot_id,
                      });
                      await enter(next);
                      setModal(null);
                      setNotice('已恢复为新版本，原历史仍保留');
                    })
                  }
                >
                  恢复此版本
                </button>
              )}
            </div>
          ))}
        </Modal>
      )}
      {modal === 'tasks' && (
        <Modal title="任务中心" close={() => setModal(null)}>
          {task ? (
            <div className="settings-section">
              <h3>本地演示 · 正文候选</h3>
              <p>
                状态：
                {task.status === 'running'
                  ? '生成中'
                  : task.status === 'cancelled'
                    ? '已停止'
                    : task.status === 'completed'
                      ? '已完成'
                      : '失败'}{' '}
                · 事件序号 {task.seq}
              </p>
              <p>本地确定性样文，无网络调用。任务进度存入数据库。</p>
              {taskRunning && (
                <button
                  className="outline-button"
                  onClick={() =>
                    void action(async () =>
                      setTask(await rpc('task.cancel', { task_id: task.task_id })),
                    )
                  }
                >
                  停止任务
                </button>
              )}
            </div>
          ) : (
            <div className="plan-empty">
              <LoaderCircle size={28} />
              <p>
                当前没有活动任务。
                <br />
                本地新建与手写不会调用模型。
              </p>
            </div>
          )}
          {recentTasks.length > 0 && (
            <div className="recent-tasks">
              <h4>最近的持久化任务</h4>
              {recentTasks.map((item) => (
                <button
                  className="plan-card"
                  key={item.task_id}
                  disabled={busy}
                  onClick={() =>
                    void action(async () => {
                      await flush();
                      await enter(
                        await rpc('branch.get', { branch_id: item.branch_id }),
                        item.chapter_id,
                      );
                      const recovered = await rpc('task.get', { task_id: item.task_id });
                      if (item.kind === 'narration') setAudioTask(recovered);
                      else setTask(recovered);
                      initializedTask.current = '';
                      setModal(null);
                    })
                  }
                >
                  <strong>{item.title}</strong>
                  <p>
                    {item.status === 'completed'
                      ? '已完成'
                      : item.status === 'running'
                        ? '生成中'
                        : item.status === 'cancelled'
                          ? '已停止'
                          : '失败'}{' '}
                    · {item.kind === 'narration' ? '打开语音' : '打开候选'}
                  </p>
                </button>
              ))}
            </div>
          )}
        </Modal>
      )}
    </div>
  );
}
