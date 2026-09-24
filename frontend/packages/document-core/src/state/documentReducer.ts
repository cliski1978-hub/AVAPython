import type { AvaDocument, DocumentContent } from "../model";

export interface DocumentState {
  documents: AvaDocument[];
  activeDocumentId: string | null;
  loading?: boolean;
  isCreating?: boolean;
  isSaving?: boolean;
  error?: Error | null;
}

export type DocumentAction =
  | { type: "hydrate"; documents: AvaDocument[] }
  | { type: "hydrateFailure"; error: Error }
  | { type: "createStart" }
  | { type: "createFailure"; error: Error }
  | { type: "saveStart" }
  | { type: "saveComplete" }
  | { type: "saveFailure"; error: Error }
  | { type: "operationFailure"; error: Error }
  | { type: "create"; document: AvaDocument }
  | { type: "reconcile"; documentId: string; document: AvaDocument }
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
  if (action.type === "hydrate") {
    return {
      ...state,
      documents: action.documents,
      activeDocumentId: action.documents[0]?.id ?? null,
      loading: false,
      error: null,
    };
  }
  if (action.type === "hydrateFailure") {
    return { ...state, documents: [], activeDocumentId: null, loading: false, error: action.error };
  }
  if (action.type === "createStart") {
    return { ...state, isCreating: true };
  }
  if (action.type === "createFailure") {
    return { ...state, isCreating: false, error: action.error };
  }
  if (action.type === "saveStart") {
    return { ...state, isSaving: true };
  }
  if (action.type === "saveComplete") {
    return { ...state, isSaving: false, error: null };
  }
  if (action.type === "saveFailure") {
    return { ...state, isSaving: false, error: action.error };
  }
  if (action.type === "operationFailure") {
    return { ...state, error: action.error };
  }
  if (action.type === "create") {
    return {
      ...state,
      documents: [...state.documents, action.document],
      activeDocumentId: action.document.id,
      isCreating: false,
      error: null,
    };
  }
  if (action.type === "reconcile") {
    return {
      ...state,
      documents: state.documents.map((item) => item.id === action.documentId ? action.document : item),
      activeDocumentId: state.activeDocumentId === action.documentId ? action.document.id : state.activeDocumentId,
      isSaving: false,
      error: null,
    };
  }
  if (action.type === "setActiveDocument") {
    return getDocumentById(state, action.documentId) == null ? state : { ...state, activeDocumentId: action.documentId };
  }
  const existing = getDocumentById(state, action.documentId);
  if (existing == null) return state;
  if (action.type === "close") {
    if (state.activeDocumentId !== action.documentId) return state;
    return { ...state, activeDocumentId: null };
  }
  const document = action.type === "updateContent"
    ? { ...existing, content: action.content, updatedAt: action.updatedAt, isDirty: true }
    : action.type === "rename"
      ? { ...existing, title: action.title, updatedAt: action.updatedAt, isDirty: true }
      : { ...existing, updatedAt: action.updatedAt, isDirty: false };
  return { ...state, documents: state.documents.map((item) => item.id === document.id ? document : item) };
}
