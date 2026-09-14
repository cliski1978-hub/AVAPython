import type { DocumentContent } from "./documentContent";

export interface AvaDocument {
  id: string;
  title: string;
  content: DocumentContent;
  createdAt: string;
  updatedAt: string;
  isDirty: boolean;
}

export function createAvaDocument(
  content: DocumentContent,
  now = new Date().toISOString(),
): AvaDocument {
  return {
    id: createDocumentId(),
    title: "Untitled Document",
    content,
    createdAt: now,
    updatedAt: now,
    isDirty: false,
  };
}

function createDocumentId(): string {
  return typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `ava-document-${Math.random().toString(36).slice(2)}`;
}
