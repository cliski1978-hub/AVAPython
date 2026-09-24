/**
 * AVA document workspace foundation.
 *
 * AVA owns document data and state. Tiptap is an internal editor adapter.
 */

export { DocumentWorkspace } from "./editor/DocumentWorkspace";
export { type EditorAdapter } from "./editor/EditorAdapter";
export { type AvaDocument, type AvaDocumentRevision, type DocumentContent, createAvaDocument, htmlContent } from "./model";
export { DocumentProvider, useDocuments } from "./state/DocumentProvider";
export { getActiveDocument, getDocumentById, type DocumentState } from "./state/documentReducer";
