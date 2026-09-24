import { describe, expect, it } from "vitest";

import type {
  AttachmentListResponse,
  AttachmentOwnerType,
  AttachmentResponse,
  AttachmentStatus,
} from "./index";
import { CONTRACT_VERSION } from "./version";

function response(overrides: Partial<AttachmentResponse> = {}): AttachmentResponse {
  return {
    attachment_id: "attachment-1",
    file_name: "report.pdf",
    media_type: "application/pdf",
    size_bytes: 12,
    owner_type: "document",
    owner_id: "doc-1",
    status: "available",
    created_at: "2026-09-20T00:00:00Z",
    contract_version: CONTRACT_VERSION,
    ...overrides,
  };
}

describe("attachment contracts", () => {
  it("mirrors the backend AttachmentResponse wire shape exactly", () => {
    const snapshot = response();

    expect(Object.keys(snapshot).sort()).toEqual([
      "attachment_id",
      "contract_version",
      "created_at",
      "file_name",
      "media_type",
      "owner_id",
      "owner_type",
      "size_bytes",
      "status",
    ]);
    expect(snapshot.contract_version).toBe(CONTRACT_VERSION);
  });

  it("never exposes storage_key or other storage internals on the wire", () => {
    const snapshot = response();

    expect("storage_key" in snapshot).toBeFalsy();
    expect("absolute_path" in snapshot).toBeFalsy();
    expect("storage_backend" in snapshot).toBeFalsy();
    expect("root" in snapshot).toBeFalsy();
    expect("checksum" in snapshot).toBeFalsy();
    expect("download_url" in snapshot).toBeFalsy();
    expect("provider" in snapshot).toBeFalsy();
    expect("path" in snapshot).toBeFalsy();
  });

  it("pins the exact owner vocabulary", () => {
    const owners: AttachmentOwnerType[] = ["document", "conversation", "message"];

    expect(owners).toEqual(["document", "conversation", "message"]);
    expect(response().owner_type).toBe("document");
    expect(response({ owner_type: "conversation" }).owner_type).toBe("conversation");
    expect(response({ owner_type: "message" }).owner_type).toBe("message");
  });

  it("pins the exact lifecycle status vocabulary", () => {
    const statuses: AttachmentStatus[] = ["pending", "available", "failed"];

    expect(statuses).toEqual(["pending", "available", "failed"]);
    expect(response().status).toBe("available");
    expect(response({ status: "pending" }).status).toBe("pending");
    expect(response({ status: "failed" }).status).toBe("failed");
  });

  it("allows an unassociated (null/null) owner pair and a backend timestamp", () => {
    const unassociated = response({ owner_type: null, owner_id: null });

    expect(unassociated.owner_type).toBeNull();
    expect(unassociated.owner_id).toBeNull();
    expect(typeof unassociated.created_at).toBe("string");
    expect(unassociated.size_bytes).toBe(12);
  });

  it("mirrors the backend AttachmentListResponse shape and stays owner-scoped", () => {
    const list: AttachmentListResponse = {
      contract_version: CONTRACT_VERSION,
      owner_type: "document",
      owner_id: "doc-1",
      attachments: [response()],
    };

    expect(Object.keys(list).sort()).toEqual([
      "attachments",
      "contract_version",
      "owner_id",
      "owner_type",
    ]);
    expect(list.owner_type).toBe("document");
    expect(list.owner_id).toBe("doc-1");
    expect(list.attachments).toEqual([response()]);
    expect(list.contract_version).toBe(CONTRACT_VERSION);
  });
});