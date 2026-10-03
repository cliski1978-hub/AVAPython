import { describe, expect, it } from "vitest";
import { selectActiveConversations, selectArchivedConversations } from "./conversationSelectors";
import type { Conversation } from "../types";

const conversation = (id: string, isArchived: boolean): Conversation => ({
  id,
  title: id,
  createdAt: id,
  isPinned: false,
  isArchived,
  folderId: null,
  projectId: null,
  messages: [],
});

describe("conversation archive selectors", () => {
  it("splits one canonical collection without reordering or copying records", () => {
    const active = conversation("active", false);
    const archived = conversation("archived", true);
    const conversations = [active, archived];

    expect(selectActiveConversations(conversations)).toEqual([active]);
    expect(selectArchivedConversations(conversations)).toEqual([archived]);
    expect(selectActiveConversations(conversations)[0]).toBe(active);
    expect(selectArchivedConversations(conversations)[0]).toBe(archived);
  });
});
