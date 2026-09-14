import type { Editor } from "@tiptap/core";
import { htmlContent, type DocumentContent } from "../model";
import type { EditorAdapter } from "./EditorAdapter";

/** Tiptap-only conversion boundary; never export its native editor instance. */
export function createTiptapEditorAdapter(editor: Editor): EditorAdapter {
  return {
    getContent: () => htmlContent(editor.getHTML()),
    setContent: (content: DocumentContent) => editor.commands.setContent(content.value, { emitUpdate: false }),
    focus: () => editor.commands.focus(),
    isEditable: () => editor.isEditable,
  };
}
