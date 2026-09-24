import type { DocumentContent } from "./documentContent";

/** Immutable snapshot of a document's durable state at one point in its history. */
export interface AvaDocumentRevision {
  revisionId: string;
  documentId: string;
  revisionNumber: number;
  title: string;
  content: DocumentContent;
  createdAt: string;
}