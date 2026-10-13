import type {
  AttachmentListResponse,
  AttachmentOwnerType,
  AttachmentResponse,
} from "@ava/contracts";

import { ApiClient } from "./client";

const path = (id: string) => `/attachments/${encodeURIComponent(id)}`;

/** Client-side input for POST /attachments.
 *
 * `file` is uploaded as multipart display metadata: when the input carries a
 * real `File`-like source its own name is used, otherwise `fileName` must be
 * provided. The client never manufactures a path-like name from local state.
 * `ownerType`/`ownerId` form a pair: both set or both absent.
 */
export interface CreateAttachmentInput {
  file: Blob | File;
  fileName?: string;
  ownerType?: AttachmentOwnerType | null;
  ownerId?: string | null;
}

/** A client-side argument error, rejected before any network request. */
export class AttachmentInputError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AttachmentInputError";
  }
}

/**
 * Upload attachment content (POST /attachments).
 *
 * Builds a `FormData` payload with the file and, when associated, the owner
 * pair. Identity, status, size, and timestamps stay server-owned and are
 * never sent. The runtime generates the multipart boundary; this client never
 * sets a multipart Content-Type. The backend derives the media type from the
 * multipart file metadata.
 */
export async function createAttachment(
  client: ApiClient,
  input: CreateAttachmentInput,
): Promise<AttachmentResponse> {
  if ((input.ownerType == null) !== (input.ownerId == null)) {
    throw new AttachmentInputError(
      "ownerType and ownerId must be both set or both absent to create an attachment",
    );
  }

  const formData = new FormData();
  formData.append("file", input.file, resolveFileName(input));
  if (input.ownerType != null && input.ownerId != null) {
    formData.append("owner_type", input.ownerType);
    formData.append("owner_id", input.ownerId);
  }

  return (await client.request("/attachments", { method: "POST", body: formData })).json();
}

/** Upload a file directly into a conversation's attachment collection. */
export async function uploadConversationAttachment(
  client: ApiClient,
  conversationId: string,
  file: File,
): Promise<AttachmentResponse> {
  const formData = new FormData();
  formData.append("file", file, file.name);
  return (await client.request(`/conversations/${encodeURIComponent(conversationId)}/attachments`, {
    method: "POST",
    body: formData,
  })).json();
}

/** Remove one attachment, scoped to the conversation that owns it. */
export async function deleteConversationAttachment(
  client: ApiClient,
  conversationId: string,
  attachmentId: string,
): Promise<void> {
  await client.request(
    `/conversations/${encodeURIComponent(conversationId)}/attachments/${encodeURIComponent(attachmentId)}`,
    { method: "DELETE" },
  );
}

/** Return one attachment's metadata (GET /attachments/{attachment_id}). */
export async function getAttachment(
  client: ApiClient,
  attachmentId: string,
): Promise<AttachmentResponse> {
  return (await client.request(path(attachmentId))).json();
}

/**
 * List one owner's attachments (GET /attachments?owner_type=...&owner_id=...).
 *
 * Owner-scoped only: both values are required at the boundary and are query-
 * encoded safely (space/slash/query/unicode safe). Backend insertion order is
 * preserved; the client never sorts and never fabricates an empty list on
 * error.
 */
export async function listAttachments(
  client: ApiClient,
  ownerType: AttachmentOwnerType,
  ownerId: string,
): Promise<AttachmentListResponse> {
  const query = new URLSearchParams({ owner_type: ownerType, owner_id: ownerId });
  return (await client.request(`/attachments?${query.toString()}`)).json();
}

/** List attachments belonging to a conversation (never its Project). */
export async function listConversationAttachments(
  client: ApiClient,
  conversationId: string,
): Promise<AttachmentListResponse> {
  return (await client.request(`/conversations/${encodeURIComponent(conversationId)}/attachments`)).json();
}

/**
 * Download attachment content as binary (GET /attachments/{attachment_id}/content).
 *
 * Returns a `Blob` (the standard fetch body type, available across the Web,
 * Desktop, and Node test runtimes from the shared `Response`) — never a
 * Base64 string. Non-2xx responses (404/409/500) are surfaced as `ApiError`
 * with the backend JSON error body, not as binary.
 */
export async function getAttachmentContent(client: ApiClient, attachmentId: string): Promise<Blob> {
  return client.requestBlob(`${path(attachmentId)}/content`);
}

function resolveFileName(input: CreateAttachmentInput): string {
  const fileLike = input.file as { name?: unknown };
  const name = typeof fileLike.name === "string" && fileLike.name !== ""
    ? input.fileName ?? fileLike.name
    : input.fileName;
  if (name === undefined || name.length === 0) {
    throw new AttachmentInputError("attachment upload requires a non-empty file name");
  }
  return name;
}
