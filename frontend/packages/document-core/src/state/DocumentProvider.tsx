import { createContext, useContext, useMemo, useReducer, type ReactNode } from "react";
import { createAvaDocument, htmlContent, type AvaDocument, type DocumentContent } from "../model";
import { documentReducer, getActiveDocument, type DocumentState } from "./documentReducer";
import { INITIAL_DOCUMENT } from "../editor/initialDocument";

interface DocumentsContextValue {
  state: DocumentState;
  activeDocument: AvaDocument | null;
  updateDocumentContent: (documentId: string, content: DocumentContent) => void;
  createDocument: () => void;
  selectDocument: (documentId: string) => void;
  renameDocument: (documentId: string, title: string) => void;
  saveDocument: (documentId: string) => void;
  closeDocument: (documentId: string) => void;
}

const DocumentsContext = createContext<DocumentsContextValue | null>(null);

export function DocumentProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(documentReducer, undefined, () => {
    const document = createAvaDocument(htmlContent(INITIAL_DOCUMENT));
    return { documents: [document], activeDocumentId: document.id };
  });
  const value = useMemo<DocumentsContextValue>(() => ({
    state,
    activeDocument: getActiveDocument(state),
    updateDocumentContent: (documentId, content) => dispatch({ type: "updateContent", documentId, content, updatedAt: new Date().toISOString() }),
    createDocument: () => {
      let number = 1;
      while (state.documents.some((item) => item.title === (number === 1 ? "Untitled Document" : `Untitled Document ${number}`))) number += 1;
      const title = number === 1 ? "Untitled Document" : `Untitled Document ${number}`;
      const document = { ...createAvaDocument(htmlContent("<p></p>")), title };
      dispatch({ type: "create", document });
    },
    selectDocument: (documentId) => dispatch({ type: "setActiveDocument", documentId }),
    renameDocument: (documentId, title) => {
      const normalized = title.trim();
      if (normalized) dispatch({ type: "rename", documentId, title: normalized, updatedAt: new Date().toISOString() });
    },
    saveDocument: (documentId) => dispatch({ type: "markClean", documentId, updatedAt: new Date().toISOString() }),
    closeDocument: (documentId) => dispatch({ type: "close", documentId }),
  }), [state]);
  return <DocumentsContext.Provider value={value}>{children}</DocumentsContext.Provider>;
}

export function useDocuments(): DocumentsContextValue {
  const value = useContext(DocumentsContext);
  if (value == null) throw new Error("useDocuments must be used within a DocumentProvider");
  return value;
}
