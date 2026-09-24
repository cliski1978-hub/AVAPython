import type { ContractVersion } from "./version";

/** AVA entities an attachment may be associated with (backend AttachmentOwnerType).
 *
 * Backend vocabulary only; the client never invents owner types.
 */
export type AttachmentOwnerType = "document" | "conversation" | "message";

/** AVA attachment lifecycle status (backend AttachmentStatus).
 *
 * ``available`` is the only content-bearing state: the backend only serves
 * bytes for available attachments.
 */
export type AttachmentStatus = "pending" | "available" | "failed";

/** Backend-authoritative attachment snapshot returned by the Attachments API.
 *
 * Mirrors the backend ``AttachmentResponse`` wire contract exactly. The
 * physical ``storage_key`` is an internal content reference and is
 * deliberately absent from the public shape; bytes are fetched exclusively
 * through the content endpoint (``GET /attachments/{id}/content``).
 */
export interface AttachmentResponse {
  attachment_id: string;
  file_name: string;
  media_type: string;
  size_bytes: number;
  owner_type: AttachmentOwnerType | null;
  owner_id: string | null;
  status: AttachmentStatus;
  created_at: string;
  contract_version: ContractVersion;
}

/** Owner-scoped attachment collection (backend AttachmentListResponse).
 *
 * Attachments are listed only for a concrete owner pair; there is no global
 * list and no unassociated-attachment list. The backend preserves insertion
 * order; the client never re-sorts.
 */
export interface AttachmentListResponse {
  contract_version: ContractVersion;
  owner_type: AttachmentOwnerType;
  owner_id: string;
  attachments: AttachmentResponse[];
}