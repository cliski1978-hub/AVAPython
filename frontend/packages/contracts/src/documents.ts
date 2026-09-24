import type { ContractVersion } from "./version";

/** The canonical serialized document format accepted by the backend. */
export type DocumentContentFormat = "html";

/** Backend-authoritative document snapshot returned by the Documents API. */
export interface DocumentResponse {
  document_id: string;
  title: string;
  content: string;
  content_format: DocumentContentFormat;
  created_at: string;
  updated_at: string;
  contract_version: ContractVersion;
}

export interface DocumentListResponse {
  documents: DocumentResponse[];
  contract_version: ContractVersion;
}

/**
 * Immutable snapshot of a document at a point in time, returned by the
 * revisions API. Mirrors the backend wire contract exactly: no surrogates,
 * no author/source/restore metadata.
 */
export interface DocumentRevisionResponse {
  revision_id: string;
  document_id: string;
  /** Per-document history sequence (1, 2, 3, …); independent of contract_version. */
  revision_number: number;
  title: string;
  content: string;
  content_format: DocumentContentFormat;
  created_at: string;
  contract_version: ContractVersion;
}

/**
 * Revision-history collection for one document, ordered by revision_number
 * ascending as the backend returns it. The client never re-sorts.
 */
export interface DocumentRevisionListResponse {
  document_id: string;
  revisions: DocumentRevisionResponse[];
  contract_version: ContractVersion;
}

/** Payload for POST /documents; durable identity and timestamps are server-owned. */
export interface CreateDocumentRequest {
  title?: string | null;
  content: string;
  content_format?: DocumentContentFormat;
  contract_version?: ContractVersion;
}

/** Payload for PATCH /documents/{document_id}; the backend requires one mutable field. */
export interface UpdateDocumentRequest {
  title?: string | null;
  content?: string | null;
  content_format?: DocumentContentFormat | null;
  contract_version?: ContractVersion;
}
