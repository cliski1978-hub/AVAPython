import { createDocument as createBackendDocument, listDocumentRevisions, listDocuments, updateDocument, type ApiClient } from "@ava/api-client";
import { createContext, useContext, useEffect, useMemo, useReducer, useRef, type ReactNode } from "react";
import { type AvaDocument, type AvaDocumentRevision, type DocumentContent } from "../model";
import { documentReducer, getActiveDocument, getDocumentById, type DocumentState } from "./documentReducer";
import { mapDocumentResponse, mapDocumentRevisionResponse } from "./documentMapper";

interface DocumentsContextValue {
  state: DocumentState;
  activeDocument: AvaDocument | null;
  updateDocumentContent: (documentId: string, content: DocumentContent) => void;
  createDocument: () => Promise<void>;
  selectDocument: (documentId: string) => void;
  renameDocument: (documentId: string, title: string) => Promise<void>;
  saveDocument: (documentId: string) => Promise<void>;
  closeDocument: (documentId: string) => void;
  loadRevisions: (documentId: string) => Promise<AvaDocumentRevision[]>;
}

const DocumentsContext = createContext<DocumentsContextValue | null>(null);

export function DocumentProvider({ client, children }: { client: ApiClient; children: ReactNode }) {
  const [state, dispatch] = useReducer(documentReducer, {
    documents: [], activeDocumentId: null, loading: true, isCreating: false, isSaving: false, error: null,
  });
  const stateRef = useRef(state);
  const creatingRef = useRef(false);
  const savingRef = useRef(false);
  stateRef.current = state;

  useEffect(() => {
    let cancelled = false;
    listDocuments(client)
      .then((response) => {
        if (!cancelled) dispatch({ type: "hydrate", documents: response.documents.map(mapDocumentResponse) });
      })
      .catch((error: unknown) => {
        if (!cancelled) dispatch({ type: "hydrateFailure", error: error instanceof Error ? error : new Error(String(error)) });
      });
    return () => { cancelled = true; };
  }, [client]);
  const value = useMemo<DocumentsContextValue>(() => ({
    state,
    activeDocument: getActiveDocument(state),
    updateDocumentContent: (documentId, content) => dispatch({ type: "updateContent", documentId, content, updatedAt: new Date().toISOString() }),
    createDocument: async () => {
      if (creatingRef.current) return;
      creatingRef.current = true;
      dispatch({ type: "createStart" });
      let number = 1;
      while (state.documents.some((item) => item.title === (number === 1 ? "Untitled Document" : `Untitled Document ${number}`))) number += 1;
      const title = number === 1 ? "Untitled Document" : `Untitled Document ${number}`;
      try {
        const saved = await createBackendDocument(client, {
          title,
          content: "<p></p>",
          content_format: "html",
        });
        dispatch({ type: "create", document: mapDocumentResponse(saved) });
      } catch (error: unknown) {
        dispatch({ type: "createFailure", error: error instanceof Error ? error : new Error(String(error)) });
      } finally {
        creatingRef.current = false;
      }
    },
    selectDocument: (documentId) => dispatch({ type: "setActiveDocument", documentId }),
    renameDocument: async (documentId, title) => {
      const normalized = title.trim();
      if (!normalized) return;
      dispatch({ type: "rename", documentId, title: normalized, updatedAt: new Date().toISOString() });
      try {
        const saved = await updateDocument(client, documentId, { title: normalized });
        const persisted = mapDocumentResponse(saved);
        const current = getDocumentById(stateRef.current, documentId);
        const contentUntouched = current != null
          && current.content.format === persisted.content.format
          && current.content.value === persisted.content.value;
        dispatch({
          type: "reconcile",
          documentId,
          document: contentUntouched ? persisted : { ...persisted, content: current!.content, isDirty: true },
        });
      } catch (error: unknown) {
        dispatch({ type: "operationFailure", error: error instanceof Error ? error : new Error(String(error)) });
      }
    },
    saveDocument: async (documentId) => {
      if (savingRef.current) return;
      const snapshot = getDocumentById(stateRef.current, documentId);
      if (snapshot == null) return;
      savingRef.current = true;
      dispatch({ type: "saveStart" });
      try {
        const saved = await updateDocument(client, documentId, {
          title: snapshot.title,
          content: snapshot.content.value,
          content_format: snapshot.content.format,
        });
        const current = getDocumentById(stateRef.current, documentId);
        if (current != null && documentMatchesSnapshot(current, snapshot)) {
          dispatch({ type: "reconcile", documentId, document: mapDocumentResponse(saved) });
        } else {
          dispatch({ type: "saveComplete" });
        }
      } catch (error: unknown) {
        dispatch({ type: "saveFailure", error: error instanceof Error ? error : new Error(String(error)) });
      } finally {
        savingRef.current = false;
      }
    },
    closeDocument: (documentId) => dispatch({ type: "close", documentId }),
    loadRevisions: async (documentId) => {
      const response = await listDocumentRevisions(client, documentId);
      return response.revisions.map(mapDocumentRevisionResponse);
    },
  }), [state]);
  return <DocumentsContext.Provider value={value}>{children}</DocumentsContext.Provider>;
}

function documentMatchesSnapshot(current: AvaDocument, snapshot: AvaDocument): boolean {
  return current.title === snapshot.title
    && current.content.format === snapshot.content.format
    && current.content.value === snapshot.content.value;
}

export function useDocuments(): DocumentsContextValue {
  const value = useContext(DocumentsContext);
  if (value == null) throw new Error("useDocuments must be used within a DocumentProvider");
  return value;
}
