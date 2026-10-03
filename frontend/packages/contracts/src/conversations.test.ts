import { describe, expect, it } from "vitest";

import type {
  CreateConversationRequest,
  ConversationListResponse,
  ConversationResponse,
} from "./conversations";
import { CONTRACT_VERSION } from "./version";

/** A conversation as the backend serializes it for a freshly created row. */
function conversation(
  overrides: Partial<ConversationResponse> = {},
): ConversationResponse {
  return {
    conversation_id: "conversation-1",
    title: "Original",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    is_pinned: false,
    is_archived: false,
    folder_id: null,
    project_id: null,
    contract_version: CONTRACT_VERSION,
    ...overrides,
  };
}

describe("conversations contract", () => {
  it("allows folder-aware creation without adding Project inference", () => {
    const request: CreateConversationRequest = { folder_id: "folder-7" };
    expect(request).toEqual({ folder_id: "folder-7" });
    expect(request).not.toHaveProperty("project_id");
  });

  it("exposes the organization metadata fields", () => {
    const response = conversation();

    expect(response.is_pinned).toBe(false);
    expect(response.is_archived).toBe(false);
    expect(response.folder_id).toBeNull();
    expect(response.project_id).toBeNull();
  });

  it("represents an explicitly organized conversation", () => {
    const response = conversation({
      is_pinned: true,
      is_archived: true,
      folder_id: "folder-7",
      project_id: "project-5",
    });

    expect(response.is_pinned).toBe(true);
    expect(response.is_archived).toBe(true);
    expect(response.folder_id).toBe("folder-7");
    expect(response.project_id).toBe("project-5");
  });

  it("allows Project membership independently from Folder membership", () => {
    const projectOnly = conversation({ project_id: "project-5" });
    const folderAndProject = conversation({ folder_id: "folder-7", project_id: "project-5" });
    expect(projectOnly).toMatchObject({ folder_id: null, project_id: "project-5" });
    expect(folderAndProject).toMatchObject({ folder_id: "folder-7", project_id: "project-5" });
  });

  it("keeps pin and archive independent", () => {
    const pinned = conversation({ is_pinned: true });
    const archived = conversation({ is_archived: true });

    expect([pinned.is_pinned, pinned.is_archived]).toEqual([true, false]);
    expect([archived.is_pinned, archived.is_archived]).toEqual([false, true]);
  });

  it("requires the organization fields so a read contract is never partial", () => {
    // The backend always emits these, so omitting them is a contract error
    // rather than an implicit default.
    // @ts-expect-error is_pinned is required
    const missing: ConversationResponse = {
      conversation_id: "conversation-1",
      title: "Original",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
      contract_version: CONTRACT_VERSION,
    };

    expect(missing.conversation_id).toBe("conversation-1");
  });

  it("carries organization fields inside the list envelope without filtering", () => {
    const list: ConversationListResponse = {
      conversations: [conversation(), conversation({ title: "Second" })],
      contract_version: CONTRACT_VERSION,
    };

    // Ordering is unchanged and no conversation is hidden, even though an
    // archived conversation is representable.
    expect(list.conversations.map((item) => item.title)).toEqual([
      "Original",
      "Second",
    ]);
  });
});
