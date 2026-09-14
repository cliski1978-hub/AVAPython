import type { DocumentContent } from "../model";

/** The small AVA-facing capability surface of a rich-text editor. */
export interface EditorAdapter {
  getContent(): DocumentContent;
  setContent(content: DocumentContent): void;
  focus(): void;
  isEditable(): boolean;
}
