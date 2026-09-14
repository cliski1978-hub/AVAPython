import { describe, expect, it } from "vitest";

import type { ConversationState } from "./conversationReducer";
import {
  conversationReducer,
  createEntityId,
  deriveTitle,
  getActiveConversation,
  DEFAULT_CONVERSATION_TITLE,
} from "./conversationReducer";

const emptyState: ConversationState = {
  conversations: [],
  activeConversationId: null,
};

describe("deriveTitle", () => {
  it("keeps short prompts as-is after trimming", () => {
    expect(deriveTitle("  Hello AVA  ")).toBe("Hello AVA");
  });

  it("truncates long prompts and appends an ellipsis", () => {
    const long = "a".repeat(60);
    expect(deriveTitle(long)).toBe(`${"a".repeat(40)}…`);
  });

  it("normalizes internal whitespace to a single line", () => {
    expect(deriveTitle("line one\nline two\u00a0 \u00a0tail")).toBe(
      "line one line two tail",
    );
  });
});

describe("conversationReducer", () => {
  it("creates a conversation that becomes active and is empty", () => {
    const state = conversationReducer(emptyState, {
      type: "conversation:create",
    });
    expect(state.conversations).toHaveLength(1);
    expect(state.activeConversationId).toBe(state.conversations[0].id);
    expect(state.conversations[0].title).toBe(DEFAULT_CONVERSATION_TITLE);
    expect(state.conversations[0].messages).toEqual([]);
    expect(typeof state.conversations[0].createdAt).toBe("string");
  });

  it("keeps newest conversations first", () => {
    let state = conversationReducer(emptyState, { type: "conversation:create" });
    state = conversationReducer(state, { type: "conversation:create" });
    expect(state.conversations).toHaveLength(2);
    expect(state.activeConversationId).toBe(state.conversations[0].id);
  });

  it("selects a known conversation and becomes active", () => {
    let state = conversationReducer(emptyState, { type: "conversation:create" });
    const first = state.conversations[0].id;
    state = conversationReducer(state, { type: "conversation:create" });
    state = conversationReducer(state, { type: "conversation:select", id: first });
    expect(state.activeConversationId).toBe(first);
  });

  it("ignores selecting an unknown conversation id", () => {
    const state = conversationReducer(emptyState, {
      type: "conversation:select",
      id: "missing",
    });
    expect(state).toBe(emptyState);
    expect(state.activeConversationId).toBeNull();
  });

  it("adds a user message to an existing conversation", () => {
    let state = conversationReducer(emptyState, { type: "conversation:create" });
    const id = state.conversations[0].id;
    state = conversationReducer(state, {
      type: "conversation:addUserMessage",
      conversationId: id,
      content: "Hello there",
    });
    const [message] = state.conversations[0].messages;
    expect(message.role).toBe("user");
    expect(message.status).toBe("complete");
    expect(message.content).toBe("Hello there");
    expect(message.id.length).toBeGreaterThan(0);
    expect(typeof message.createdAt).toBe("string");
  });

  it("uses the createdMessageId when provided for deterministic ids", () => {
    const state = conversationReducer(emptyState, {
      type: "conversation:addUserMessage",
      conversationId: null,
      content: "Hello",
      createdConversationId: "fixed-conv",
      createdMessageId: "fixed-msg",
    });
    expect(state.conversations[0].messages[0].id).toBe("fixed-msg");
    expect(state.activeConversationId).toBe("fixed-conv");
  });

  it("derives the title from the first user message", () => {
    let state = conversationReducer(emptyState, { type: "conversation:create" });
    const id = state.conversations[0].id;
    state = conversationReducer(state, {
      type: "conversation:addUserMessage",
      conversationId: id,
      content: "Explain how robot zoning works in AVA",
    });
    expect(state.conversations[0].title).toBe(
      "Explain how robot zoning works in AVA",
    );
  });

  it("does not replace the title on later messages", () => {
    let state = conversationReducer(emptyState, { type: "conversation:create" });
    const id = state.conversations[0].id;
    state = conversationReducer(state, {
      type: "conversation:addUserMessage",
      conversationId: id,
      content: "First message",
    });
    state = conversationReducer(state, {
      type: "conversation:addUserMessage",
      conversationId: id,
      content: "Completely different second message",
    });
    expect(state.conversations[0].title).toBe("First message");
    expect(state.conversations[0].messages).toHaveLength(2);
  });

  it("auto-creates an active conversation when submitting with none", () => {
    const state = conversationReducer(emptyState, {
      type: "conversation:addUserMessage",
      conversationId: null,
      content: "Brand new topic",
    });
    expect(state.conversations).toHaveLength(1);
    expect(state.activeConversationId).toBe(state.conversations[0].id);
    expect(state.conversations[0].title).toBe("Brand new topic");
    expect(state.conversations[0].messages).toHaveLength(1);
  });

  it("ignores submission of whitespace-only content", () => {
    const state = conversationReducer(emptyState, {
      type: "conversation:addUserMessage",
      conversationId: null,
      content: "   \n  ",
    });
    expect(state).toEqual(emptyState);
  });

  it("preserves messages across conversations when switching", () => {
    let state = conversationReducer(emptyState, { type: "conversation:create" });
    const a = state.conversations[0].id;
    state = conversationReducer(state, {
      type: "conversation:addUserMessage",
      conversationId: a,
      content: "Message A1",
    });
    state = conversationReducer(state, { type: "conversation:create" });
    const b = state.conversations[0].id;
    state = conversationReducer(state, {
      type: "conversation:addUserMessage",
      conversationId: b,
      content: "Message B1",
    });
    state = conversationReducer(state, {
      type: "conversation:addUserMessage",
      conversationId: b,
      content: "Message B2",
    });
    state = conversationReducer(state, { type: "conversation:select", id: a });
    const aMessages = state.conversations
      .find((c) => c.id === a)!
      .messages.map((m) => m.content);
    expect(aMessages).toEqual(["Message A1"]);
    state = conversationReducer(state, { type: "conversation:select", id: b });
    const bMessages = state.conversations
      .find((c) => c.id === b)!
      .messages.map((m) => m.content);
    expect(bMessages).toEqual(["Message B1", "Message B2"]);
  });

  it("recovers gracefully when submitting to an unavailable conversation id", () => {
    const state = conversationReducer(emptyState, {
      type: "conversation:addUserMessage",
      conversationId: "ghost",
      content: "Recovered prompt",
    });
    expect(state.conversations).toHaveLength(1);
    expect(state.conversations[0].title).toBe("Recovered prompt");
    expect(state.activeConversationId).toBe(state.conversations[0].id);
  });
});

describe("conversation:addAssistantMessage", () => {
  it("appends a pending assistant message to the conversation", () => {
    let state = conversationReducer(emptyState, { type: "conversation:create" });
    const id = state.conversations[0].id;
    state = conversationReducer(state, {
      type: "conversation:addAssistantMessage",
      conversationId: id,
      messageId: "asm-1",
    });
    const [message] = state.conversations[0].messages;
    expect(message.id).toBe("asm-1");
    expect(message.role).toBe("assistant");
    expect(message.status).toBe("pending");
    expect(message.content).toBe("");
    expect(typeof message.createdAt).toBe("string");
    expect(message.sourceUserMessageId).toBeUndefined();
  });

  it("stores the sourceUserMessageId when provided", () => {
    let state = conversationReducer(emptyState, { type: "conversation:create" });
    const id = state.conversations[0].id;
    state = conversationReducer(state, {
      type: "conversation:addAssistantMessage",
      conversationId: id,
      messageId: "asm-1",
      sourceUserMessageId: "user-msg-1",
    });
    const [message] = state.conversations[0].messages;
    expect(message.sourceUserMessageId).toBe("user-msg-1");
  });

  it("is a no-op when the message id already exists (stable ids)", () => {
    let state = conversationReducer(emptyState, { type: "conversation:create" });
    const id = state.conversations[0].id;
    state = conversationReducer(state, {
      type: "conversation:addAssistantMessage",
      conversationId: id,
      messageId: "asm-1",
    });
    const before = state.conversations[0];
    state = conversationReducer(state, {
      type: "conversation:addAssistantMessage",
      conversationId: id,
      messageId: "asm-1",
    });
    expect(state.conversations[0]).toBe(before);
    expect(state.conversations[0].messages).toHaveLength(1);
  });

  it("ignores unknown conversations", () => {
    const state = conversationReducer(emptyState, {
      type: "conversation:addAssistantMessage",
      conversationId: "nope",
      messageId: "asm-1",
    });
    expect(state).toBe(emptyState);
  });
});

describe("conversation:updateMessage", () => {
  it("patches content, status, and error immutably", () => {
    let state = conversationReducer(emptyState, { type: "conversation:create" });
    const id = state.conversations[0].id;
    state = conversationReducer(state, {
      type: "conversation:addAssistantMessage",
      conversationId: id,
      messageId: "asm-1",
    });
    state = conversationReducer(state, {
      type: "conversation:updateMessage",
      conversationId: id,
      messageId: "asm-1",
      patch: { content: "Hello AVA", status: "complete", error: undefined },
    });
    const updated = state.conversations[0].messages[0];
    expect(updated.content).toBe("Hello AVA");
    expect(updated.status).toBe("complete");

    state = conversationReducer(state, {
      type: "conversation:updateMessage",
      conversationId: id,
      messageId: "asm-1",
      patch: { status: "failed", error: "Backend unavailable" },
    });
    expect(state.conversations[0].messages[0].status).toBe("failed");
    expect(state.conversations[0].messages[0].error).toBe("Backend unavailable");
  });

  it("ignores unknown message ids", () => {
    let state = conversationReducer(emptyState, { type: "conversation:create" });
    const id = state.conversations[0].id;
    const before = state.conversations[0];
    state = conversationReducer(state, {
      type: "conversation:updateMessage",
      conversationId: id,
      messageId: "missing",
      patch: { content: "x" },
    });
    expect(state.conversations[0]).toBe(before);
  });

  it("ignores unknown conversations", () => {
    const state = conversationReducer(emptyState, {
      type: "conversation:updateMessage",
      conversationId: "nope",
      messageId: "asm-1",
      patch: { status: "failed" },
    });
    expect(state).toBe(emptyState);
  });
});

describe("conversation:setRunState", () => {
  it("merges partial run state onto a conversation", () => {
    let state = conversationReducer(emptyState, { type: "conversation:create" });
    const id = state.conversations[0].id;
    state = conversationReducer(state, {
      type: "conversation:setRunState",
      conversationId: id,
      update: { backendStatus: "running", uiPhase: "starting", pendingMessageId: "asm-1" },
    });
    state = conversationReducer(state, {
      type: "conversation:setRunState",
      conversationId: id,
      update: { runId: "run-001", uiPhase: "running" },
    });
    const run = state.conversations[0].run!;
    expect(run.backendStatus).toBe("running");
    expect(run.uiPhase).toBe("running");
    expect(run.pendingMessageId).toBe("asm-1");
    expect(run.runId).toBe("run-001");
    expect(run.runError).toBeNull();
  });

  it("keeps other conversations' run state untouched", () => {
    let state = conversationReducer(emptyState, { type: "conversation:create" });
    const a = state.conversations[0].id;
    state = conversationReducer(state, { type: "conversation:create" });
    const b = state.conversations[0].id;
    state = conversationReducer(state, {
      type: "conversation:setRunState",
      conversationId: a,
      update: { backendStatus: "running", uiPhase: "running" },
    });
    expect(state.conversations.find((c) => c.id === a)!.run!.backendStatus).toBe(
      "running",
    );
    expect(state.conversations.find((c) => c.id === a)!.run!.uiPhase).toBe(
      "running",
    );
    expect(state.conversations.find((c) => c.id === b)!.run!.backendStatus).toBeNull();
    expect(state.conversations.find((c) => c.id === b)!.run!.uiPhase).toBe("idle");
    expect(state.conversations.find((c) => c.id === b)!.run!.runId).toBeNull();
  });

  it("ignores unknown conversations", () => {
    const state = conversationReducer(emptyState, {
      type: "conversation:setRunState",
      conversationId: "nope",
      update: { backendStatus: "failed", uiPhase: "failed" },
    });
    expect(state).toBe(emptyState);
  });
});

describe("conversation:addUserMessage with createdConversationId", () => {
  it("uses the provided id when auto-creating a conversation", () => {
    const state = conversationReducer(emptyState, {
      type: "conversation:addUserMessage",
      conversationId: null,
      content: "Deterministic topic",
      createdConversationId: "fixed-id",
    });
    expect(state.conversations[0].id).toBe("fixed-id");
    expect(state.activeConversationId).toBe("fixed-id");
  });
});

describe("getActiveConversation", () => {
  it("returns null when nothing is active", () => {
    expect(getActiveConversation(emptyState)).toBeNull();
  });

  it("returns the active conversation", () => {
    let state = conversationReducer(emptyState, { type: "conversation:create" });
    state = conversationReducer(state, {
      type: "conversation:addUserMessage",
      conversationId: null,
      content: "topic",
    });
    const active = getActiveConversation(state);
    expect(active?.id).toBe(state.activeConversationId);
  });

  it("fails gracefully when the active id no longer resolves", () => {
    const state: ConversationState = {
      conversations: [],
      activeConversationId: "removed-in-the-future",
    };
    expect(getActiveConversation(state)).toBeNull();
  });
});

describe("createEntityId", () => {
  it("produces unique ids", () => {
    const ids = new Set([createEntityId(), createEntityId(), createEntityId()]);
    expect(ids.size).toBe(3);
  });
});
