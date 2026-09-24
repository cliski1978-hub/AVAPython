import type {
  CreateDocumentRequest,
  DocumentListResponse,
  DocumentResponse,
  DocumentRevisionListResponse,
  DocumentRevisionResponse,
  UpdateDocumentRequest,
} from "@ava/contracts";

import { ApiClient } from "./client";

const path = (id: string) => `/documents/${encodeURIComponent(id)}`;

export async function listDocuments(client: ApiClient): Promise<DocumentListResponse> {
  return (await client.request("/documents")).json();
}

export async function getDocument(client: ApiClient, documentId: string): Promise<DocumentResponse> {
  return (await client.request(path(documentId))).json();
}

export async function createDocument(
  client: ApiClient,
  request: CreateDocumentRequest,
): Promise<DocumentResponse> {
  return (await client.request("/documents", { method: "POST", body: JSON.stringify(request) })).json();
}

export async function updateDocument(
  client: ApiClient,
  documentId: string,
  request: UpdateDocumentRequest,
): Promise<DocumentResponse> {
  return (await client.request(path(documentId), { method: "PATCH", body: JSON.stringify(request) })).json();
}

export async function listDocumentRevisions(
  client: ApiClient,
  documentId: string,
): Promise<DocumentRevisionListResponse> {
  return (await client.request(`${path(documentId)}/revisions`)).json();
}

export async function getDocumentRevision(
  client: ApiClient,
  documentId: string,
  revisionId: string,
): Promise<DocumentRevisionResponse> {
  return (await client.request(`${path(documentId)}/revisions/${encodeURIComponent(revisionId)}`)).json();
}
