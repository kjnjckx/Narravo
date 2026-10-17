import { useEffect } from 'react';
import { useEditor, EditorContent } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import { Undo2, Redo2 } from 'lucide-react';
import { useWork } from './store';
const document = (text: string) => ({
  type: 'doc',
  content: text
    .split('\n')
    .map((line) => ({ type: 'paragraph', content: line ? [{ type: 'text', text: line }] : [] })),
});
export function Editor({ disabled }: { disabled: boolean }) {
  const { text, setText } = useWork();
  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: false,
        bulletList: false,
        orderedList: false,
        blockquote: false,
        codeBlock: false,
        horizontalRule: false,
        bold: false,
        italic: false,
        strike: false,
        code: false,
        link: false,
        underline: false,
      }),
    ],
    content: document(text),
    editorProps: {
      attributes: {
        'aria-label': '章节正文',
        role: 'textbox',
        'aria-multiline': 'true',
        class: 'prose-editor',
      },
    },
    onUpdate: ({ editor }) => setText(editor.getText({ blockSeparator: '\n' })),
  });
  useEffect(() => {
    if (editor && editor.getText({ blockSeparator: '\n' }) !== text)
      editor.commands.setContent(document(text), { emitUpdate: false });
  }, [text, editor]);
  useEffect(() => {
    editor?.setEditable(!disabled, false);
  }, [disabled, editor]);
  return (
    <>
      <div className="editor-tools">
        <span>正文</span>
        <span className="tool-divider" />
        <button
          aria-label="撤销输入"
          onClick={() => editor?.chain().focus().undo().run()}
          disabled={disabled}
        >
          <Undo2 size={15} />
        </button>
        <button
          aria-label="重做输入"
          onClick={() => editor?.chain().focus().redo().run()}
          disabled={disabled}
        >
          <Redo2 size={15} />
        </button>
        <span className="tools-note">每一个故事，都从一句话开始</span>
      </div>
      <EditorContent editor={editor} />
      {!text && (
        <div className="editor-placeholder" aria-hidden="true">
          在这里，写下故事的第一句话……
          <br />
          <small>可以直接手写，也可以在右侧描述灵感。</small>
        </div>
      )}
    </>
  );
}
