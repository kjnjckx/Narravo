import { create } from 'zustand';
import { rpc } from './rpc';
import type { Workspace, ChapterText, BookSummary } from '../../../packages/contracts';

interface State {
  books: BookSummary[];
  workspace: Workspace | null;
  chapter: ChapterText | null;
  text: string;
  dirty: boolean;
  saving: boolean;
  error: string | null;
  setText: (text: string) => void;
}
export const useWork = create<State>((set) => ({
  books: [],
  workspace: null,
  chapter: null,
  text: '',
  dirty: false,
  saving: false,
  error: null,
  setText: (text) => set({ text, dirty: true, error: null }),
}));
let savePromise: Promise<void> | null = null;
export async function flush(): Promise<void> {
  if (savePromise) {
    await savePromise;
    if (useWork.getState().dirty) return flush();
    return;
  }
  const state = useWork.getState();
  if (!state.dirty || !state.workspace || !state.chapter) return;
  const { workspace, chapter, text } = state;
  useWork.setState({ saving: true });
  savePromise = (async () => {
    try {
      const next = await rpc('chapter.save', {
        branch_id: workspace.branch_id,
        chapter_id: chapter.chapter_id,
        text,
        expected_snapshot: workspace.snapshot_id,
      });
      useWork.setState((latest) => ({
        workspace: next,
        dirty: latest.text !== text,
        error: null,
        chapter: {
          ...chapter,
          revision: next.chapters.find((c) => c.id === chapter.chapter_id)!.revision,
        },
      }));
    } catch (e) {
      useWork.setState({ error: message(e) });
      throw e;
    } finally {
      useWork.setState({ saving: false });
      savePromise = null;
    }
  })();
  await savePromise;
  if (useWork.getState().dirty) return flush();
}
export async function loadLibrary() {
  const { books } = await rpc('book.list', {});
  useWork.setState({ books });
}
export async function openWorkspace(workspace: Workspace, chapterId?: string) {
  const id = chapterId ?? workspace.chapters[0].id;
  const chapter = await rpc('chapter.get', { branch_id: workspace.branch_id, chapter_id: id });
  useWork.setState({ workspace, chapter, text: chapter.text, dirty: false, error: null });
}
export function message(e: unknown): string {
  return e instanceof Error
    ? e.message
    : typeof e === 'string'
      ? e
      : '操作未完成，请保留输入并重试。';
}
export const wordCount = (text: string) => [...text].filter((char) => !/\s/u.test(char)).length;
export const toCodePoint = (text: string, utf16: number) => [...text.slice(0, utf16)].length;
