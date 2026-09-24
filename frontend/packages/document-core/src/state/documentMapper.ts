import type { DocumentResponse, DocumentRevisionResponse } from "@ava/contracts";

import type { AvaDocument, AvaDocumentRevision } from "../model";

/** Converts a backend document snapshot into document-core's editor-neutral model. */
export function mapDocumentResponse(document: DocumentResponse): AvaDocument {
  return {
    id: document.document_id,
    title: document.title,
    content: { format: document.content_format, value: document.content },
    createdAt: document.created_at,
    updatedAt: document.updated_at,
    isDirty: false,
  };
}

/** Converts a backend revision snapshot into a frontend-domain revision, preserving order. */
export function mapDocumentRevisionResponse(response: DocumentRevisionResponse): AvaDocumentRevision {
  return {
    revisionId: response.revision_id,
    documentId: response.document_id,
    revisionNumber: response.revision_number,
    title: response.title,
    content: { format: response.content_format, value: response.content },
    createdAt: response.created_at,
  };
}
