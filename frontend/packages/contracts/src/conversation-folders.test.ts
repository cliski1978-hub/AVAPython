import { describe, expect, it } from "vitest";

import type {
  ConversationFolder,
  CreateConversationFolderRequest,
  UpdateConversationFolderRequest,
} from "./index";
import { CONTRACT_VERSION } from "./version";

describe("conversation folder contracts", () => {
  it("mirrors the backend folder response fields", () => {
    const folder: ConversationFolder = {
      id: "folder-1",
      name: "Planning",
      created_at: "2026-10-01T00:00:00Z",
      updated_at: "2026-10-02T00:00:00Z",
      contract_version: CONTRACT_VERSION,
    };

    expect(Object.keys(folder).sort()).toEqual([
      "contract_version",
      "created_at",
      "id",
      "name",
      "updated_at",
    ]);
  });

  it("keeps identity and timestamps out of write requests", () => {
    const create: CreateConversationFolderRequest = { name: "Planning" };
    const update: UpdateConversationFolderRequest = { name: "Research" };

    expect(create).toEqual({ name: "Planning" });
    expect(update).toEqual({ name: "Research" });
  });
});
