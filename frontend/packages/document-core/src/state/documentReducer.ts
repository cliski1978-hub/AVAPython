import type { AvaDocument, DocumentContent } from "../model";

export interface DocumentState {
  documents: AvaDocument[];
  activeDocumentId: string | null;
}

export type DocumentAction =
  | { type: "create"; document: AvaDocument }
  | { type: "setActiveDocument"; documentId: string }
  | { type: "updateContent"; documentId: string; content: DocumentContent; updatedAt: string }
  | { type: "rename"; documentId: string; title: string; updatedAt: string }
  | { type: "markClean"; documentId: string; updatedAt: string }
  | { type: "close"; documentId: string };

export function getDocumentById(state: DocumentState, documentId: string | null): AvaDocument | null {
  return documentId == null ? null : state.documents.find((document) => document.id === documentId) ?? null;
}

export function getActiveDocument(state: DocumentState): AvaDocument | null {
  return getDocumentById(state, state.activeDocumentId);
}

export function documentReducer(state: DocumentState, action: DocumentAction): DocumentState {
  if (action.type === "create") {
    return { documents: [...state.documents, action.document], activeDocumentId: action.document.id };
  }
  if (action.type === "setActiveDocument") {
    return getDocumentById(state, action.documentId) == null ? state : { ...state, activeDocumentId: action.documentId };
  }
  const existing = getDocumentById(state, action.documentId);
  if (existing == null) return state;
  if (action.type === "close") {
    const index = state.documents.findIndex((item) => item.id === action.documentId);
    const documents = state.documents.filter((item) => item.id !== action.documentId);
    const activeDocumentId = state.activeDocumentId === action.documentId
      ? (documents[index]?.id ?? documents[index - 1]?.id ?? null)
      : state.activeDocumentId;
    return { documents, activeDocumentId };
  }
  const document = action.type === "updateContent"
    ? { ...existing, content: action.content, updatedAt: action.updatedAt, isDirty: true }
    : action.type === "rename"
      ? { ...existing, title: action.title, updatedAt: action.updatedAt, isDirty: true }
      : { ...existing, updatedAt: action.updatedAt, isDirty: false };
  return { ...state, documents: state.documents.map((item) => item.id === document.id ? document : item) };
}
