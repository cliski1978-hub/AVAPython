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

describe("conversation:replaceMessage", () => {
  it("reconciles a placeholder in place without changing thread order", () => {
    let state = conversationReducer(emptyState, { type: "conversation:create" });
    const conversationId = state.activeConversationId!;
    state = conversationReducer(state, { type: "conversation:addAssistantMessage", conversationId, messageId: "local", sourceUserMessageId: undefined });
    state = conversationReducer(state, { type: "conversation:replaceMessage", conversationId, placeholderId: "local", message: { id: "backend", role: "assistant", status: "complete", content: "done", createdAt: "2026-01-01T00:00:00Z" } });
    const messages = state.conversations[0].messages;
    expect(messages).toHaveLength(1);
    expect(messages[0]).toMatchObject({ id: "backend", content: "done", status: "complete" });
  });
});

describe("conversation:associateAssistantMessage", () => {
  it("rekeys the existing streaming bubble to the durable backend message id", () => {
    let state = conversationReducer(emptyState, { type: "conversation:create" });
    const conversationId = state.activeConversationId!;
    state = conversationReducer(state, {
      type: "conversation:addAssistantMessage", conversationId,
      messageId: "local", sourceUserMessageId: "user",
    });
    state = conversationReducer(state, {
      type: "conversation:associateAssistantMessage", conversationId,
      placeholderId: "local", messageId: "durable",
    });
    expect(state.conversations[0].messages).toEqual([
      expect.objectContaining({ id: "durable", sourceUserMessageId: "user" }),
    ]);
  });
});

describe("conversation:rename", () => {
  it("replaces the title of the named conversation only", () => {
    let state = conversationReducer(emptyState, { type: "conversation:create" });
    const id = state.activeConversationId!;
    state = conversationReducer(state, { type: "conversation:rename", conversationId: id, title: "Backend Title" });
    expect(state.conversations[0].title).toBe("Backend Title");
  });

  it("does not change the active selection when renaming a non-active conversation", () => {
    let state = conversationReducer(emptyState, { type: "conversation:create" });
    const activeId = state.activeConversationId!;
    state = conversationReducer(state, { type: "conversation:create" });
    const targetId = state.activeConversationId!;

    state = conversationReducer(state, { type: "conversation:select", id: activeId });
    state = conversationReducer(state, { type: "conversation:rename", conversationId: targetId, title: "Renamed" });

    expect(state.activeConversationId).toBe(activeId);
    expect(state.conversations.find((c) => c.id === targetId)!.title).toBe("Renamed");
  });

  it("preserves messages and leaves other conversations untouched", () => {
    let state = conversationReducer(emptyState, { type: "conversation:create" });
    const a = state.activeConversationId!;
    state = conversationReducer(state, { type: "conversation:create" });
    const b = state.activeConversationId!;
    state = conversationReducer(state, { type: "conversation:addUserMessage", conversationId: b, content: "Keep me", createdMessageId: "b1" });
    const bBefore = state.conversations.find((c) => c.id === b);

    state = conversationReducer(state, { type: "conversation:rename", conversationId: a, title: "Renamed A" });

    expect(state.conversations.find((c) => c.id === a)!.title).toBe("Renamed A");
    expect(state.conversations.find((c) => c.id === a)!.messages).toEqual([]);
    expect(state.conversations.find((c) => c.id === b)).toBe(bBefore);
  });

  it("keeps state identical when the title is unchanged", () => {
    let state = conversationReducer(emptyState, { type: "conversation:create" });
    const id = state.activeConversationId!;
    const title = state.conversations[0].title;
    const next = conversationReducer(state, { type: "conversation:rename", conversationId: id, title });
    expect(next).toBe(state);
  });
});

describe("conversation:messagesHydrate merging", () => {
  const ts = "2026-01-01T00:00:00Z";

  function hydratedUser(id: string, content: string) {
    return { id, role: "user" as const, status: "complete" as const, content, createdAt: ts };
  }

  function hydratedAssistant(id: string, content: string) {
    return { id, role: "assistant" as const, status: "complete" as const, content, createdAt: ts };
  }

  it("keeps local-only messages when the server snapshot lags in-flight persistence", () => {
    let state = conversationReducer(emptyState, { type: "conversation:create" });
    const id = state.activeConversationId!;
    state = conversationReducer(state, { type: "conversation:addUserMessage", conversationId: id, content: "Question", createdMessageId: "u1" });
    state = conversationReducer(state, { type: "conversation:addAssistantMessage", conversationId: id, messageId: "local-asst", sourceUserMessageId: "u1" });
    state = conversationReducer(state, { type: "conversation:updateMessage", conversationId: id, messageId: "local-asst", patch: { content: "Answer A", status: "complete" } });

    state = conversationReducer(state, { type: "conversation:messagesHydrate", conversationId: id, messages: [hydratedUser("u1", "Question")] });

    const messages = state.conversations[0].messages;
    expect(messages.map((m) => m.id)).toEqual(["u1", "local-asst"]);
    expect(messages[0]).toMatchObject({ id: "u1", role: "user", content: "Question" });
    expect(messages[1]).toMatchObject({ id: "local-asst", role: "assistant", content: "Answer A", status: "complete" });
  });

  it("replaces same-id messages with the authoritative server copy", () => {
    let state = conversationReducer(emptyState, { type: "conversation:create" });
    const id = state.activeConversationId!;
    state = conversationReducer(state, { type: "conversation:addUserMessage", conversationId: id, content: "Local user", createdMessageId: "u1" });
    state = conversationReducer(state, { type: "conversation:addAssistantMessage", conversationId: id, messageId: "a1", sourceUserMessageId: "u1" });
    state = conversationReducer(state, { type: "conversation:updateMessage", conversationId: id, messageId: "a1", patch: { content: "Local draft", status: "complete" } });

    state = conversationReducer(state, {
      type: "conversation:messagesHydrate",
      conversationId: id,
      messages: [hydratedUser("u1", "Server user"), hydratedAssistant("a1", "Server Answer")],
    });

    const messages = state.conversations[0].messages;
    expect(messages).toHaveLength(2);
    expect(messages[0]).toMatchObject({ id: "u1", content: "Server user" });
    expect(messages[1]).toMatchObject({ id: "a1", content: "Server Answer", status: "complete" });
  });

  it("appends server-only messages in server order", () => {
    let state = conversationReducer(emptyState, { type: "conversation:create" });
    const id = state.activeConversationId!;
    state = conversationReducer(state, { type: "conversation:addUserMessage", conversationId: id, content: "Question", createdMessageId: "u1" });

    state = conversationReducer(state, {
      type: "conversation:messagesHydrate",
      conversationId: id,
      messages: [hydratedUser("u1", "Question"), hydratedAssistant("a1", "Answer"), hydratedUser("u2", "Follow-up")],
    });

    const messages = state.conversations[0].messages;
    expect(messages.map((m) => m.id)).toEqual(["u1", "a1", "u2"]);
    expect(messages[1].role).toBe("assistant");
  });

  it("is idempotent when re-hydrated with the same snapshot", () => {
    let state = conversationReducer(emptyState, { type: "conversation:create" });
    const id = state.activeConversationId!;
    state = conversationReducer(state, { type: "conversation:addUserMessage", conversationId: id, content: "Question", createdMessageId: "u1" });
    state = conversationReducer(state, { type: "conversation:addAssistantMessage", conversationId: id, messageId: "local-asst", sourceUserMessageId: "u1" });
    const snapshot = [hydratedUser("u1", "Question")];

    state = conversationReducer(state, { type: "conversation:messagesHydrate", conversationId: id, messages: snapshot });
    const once = state.conversations[0].messages.map((m) => m.id).join(",");
    state = conversationReducer(state, { type: "conversation:messagesHydrate", conversationId: id, messages: snapshot });
    const twice = state.conversations[0].messages.map((m) => m.id).join(",");

    expect(twice).toBe(once);
    expect(state.conversations[0].messages).toHaveLength(2);
  });

  it("leaves other conversations untouched", () => {
    let state = conversationReducer(emptyState, { type: "conversation:create" });
    const a = state.activeConversationId!;
    state = conversationReducer(state, { type: "conversation:create" });
    const b = state.activeConversationId!;
    state = conversationReducer(state, { type: "conversation:addUserMessage", conversationId: b, content: "For B", createdMessageId: "b1" });
    const bBefore = state.conversations.find((c) => c.id === b);

    state = conversationReducer(state, { type: "conversation:messagesHydrate", conversationId: a, messages: [hydratedUser("a1", "For A")] });

    expect(state.conversations.find((c) => c.id === b)).toBe(bBefore);
    expect(state.conversations.find((c) => c.id === b)!.messages.map((m) => m.id)).toEqual(["b1"]);
    expect(state.conversations.find((c) => c.id === a)!.messages.map((m) => m.id)).toEqual(["a1"]);
  });

  it("re-hydrating a regenerated turn yields the server's authoritative order (U1 A1 A2)", () => {
    let state = conversationReducer(emptyState, { type: "conversation:create" });
    const id = state.activeConversationId!;
    // Local conversation after a successful regenerate: the old assistant row
    // (a1) was replaced in place by the regenerated response (a2).
    state = conversationReducer(state, { type: "conversation:addUserMessage", conversationId: id, content: "Question", createdMessageId: "u1" });
    state = conversationReducer(state, { type: "conversation:addAssistantMessage", conversationId: id, messageId: "a2", sourceUserMessageId: "u1" });
    state = conversationReducer(state, { type: "conversation:updateMessage", conversationId: id, messageId: "a2", patch: { content: "Regenerated", status: "complete" } });

    // Server (append-order) snapshot still contains the superseded A1 row.
    state = conversationReducer(state, {
      type: "conversation:messagesHydrate",
      conversationId: id,
      messages: [hydratedUser("u1", "Question"), hydratedAssistant("a1", "Original"), hydratedAssistant("a2", "Regenerated")],
    });

    const messages = state.conversations[0].messages;
    expect(messages.map((m) => m.id)).toEqual(["u1", "a1", "a2"]);
    expect(messages[1].content).toBe("Original");
    expect(messages[2].content).toBe("Regenerated");
  });

  it("re-hydration never duplicates a message by id, even when local and server overlap", () => {
    let state = conversationReducer(emptyState, { type: "conversation:create" });
    const id = state.activeConversationId!;
    state = conversationReducer(state, { type: "conversation:addUserMessage", conversationId: id, content: "Question", createdMessageId: "u1" });
    state = conversationReducer(state, { type: "conversation:addAssistantMessage", conversationId: id, messageId: "a2", sourceUserMessageId: "u1" });

    state = conversationReducer(state, {
      type: "conversation:messagesHydrate",
      conversationId: id,
      messages: [hydratedUser("u1", "Question"), hydratedAssistant("a1", "Original"), hydratedAssistant("a2", "Regenerated")],
    });
    state = conversationReducer(state, {
      type: "conversation:messagesHydrate",
      conversationId: id,
      messages: [hydratedUser("u1", "Question"), hydratedAssistant("a1", "Original"), hydratedAssistant("a2", "Regenerated")],
    });

    const ids = state.conversations[0].messages.map((m) => m.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(ids).toEqual(["u1", "a1", "a2"]);
  });
});

describe("failure codes survive hydration", () => {
  const ts = "2026-01-01T00:00:00Z";

  /** Refresh must not flatten a specific failure back to the generic one. */
  it.each([
    "model_unavailable",
    "provider_connection_unavailable",
    "provider_timeout",
    "provider_rate_limited",
    "provider_authentication_failed",
    "provider_response_invalid",
    "runtime_unavailable",
    "credential_unavailable",
    "context_window_exceeded",
    "execution_interrupted",
    "agent_failed",
  ])("keeps %s after a reload", (code) => {
    const state = conversationReducer(emptyState, {
      type: "conversation:hydrate",
      conversations: [
        {
          id: "c1",
          title: "Chat",
          messages: [
            { id: "u1", role: "user", status: "complete", content: "Question", createdAt: ts },
            {
              id: "a1",
              role: "assistant",
              status: "failed",
              content: "The provider rejected the request.",
              errorCode: code,
              createdAt: ts,
            },
          ],
        },
      ],
    });

    expect(state.conversations[0].messages[1]).toMatchObject({ status: "failed", errorCode: code });
  });

  it("keeps partial streamed content alongside the failure code", () => {
    const state = conversationReducer(emptyState, {
      type: "conversation:hydrate",
      conversations: [
        {
          id: "c1",
          title: "Chat",
          messages: [
            {
              id: "a1",
              role: "assistant",
              status: "failed",
              content: "Here is what I found so far",
              errorCode: "provider_timeout",
              createdAt: ts,
            },
          ],
        },
      ],
    });

    expect(state.conversations[0].messages[0]).toMatchObject({
      content: "Here is what I found so far",
      errorCode: "provider_timeout",
    });
  });

  it("leaves a successful message without a failure code", () => {
    const state = conversationReducer(emptyState, {
      type: "conversation:hydrate",
      conversations: [
        {
          id: "c1",
          title: "Chat",
          messages: [{ id: "a1", role: "assistant", status: "complete", content: "Answer", createdAt: ts }],
        },
      ],
    });

    expect(state.conversations[0].messages[0].errorCode).toBeUndefined();
  });
});
