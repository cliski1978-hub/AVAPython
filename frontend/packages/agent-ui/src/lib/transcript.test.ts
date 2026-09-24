import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../types";
import {
  associateAssistantMessages,
  selectTranscriptMessages,
} from "./transcript";

function user(id: string, content: string, sourceUserMessageId?: string): ConversationMessage {
  return { id, role: "user", status: "complete", content, sourceUserMessageId };
}

function assistant(id: string, content: string, sourceUserMessageId?: string): ConversationMessage {
  return { id, role: "assistant", status: "complete", content, sourceUserMessageId };
}

describe("selectTranscriptMessages", () => {
  it("keeps a single user/assistant turn unchanged", () => {
    const messages = [user("u1", "Hello"), assistant("a1", "A1")];
    expect(selectTranscriptMessages(messages)).toEqual(messages);
  });

  it("replaces the older assistant response when a regeneration exists (U1 A1 A2 -> U1 A2)", () => {
    const messages = [
      user("u1", "Hello"),
      assistant("a1", "A1"),
      assistant("a2", "A2"),
    ];
    const visible = selectTranscriptMessages(messages);
    expect(visible.map((m) => m.id)).toEqual(["u1", "a2"]);
  });

  it("keeps only the latest of every regenerated turn (U1 A1 A2 A3 -> U1 A3)", () => {
    const messages = [
      user("u1", "Hello"),
      assistant("a1", "A1"),
      assistant("a2", "A2"),
      assistant("a3", "A3"),
    ];
    const visible = selectTranscriptMessages(messages);
    expect(visible.map((m) => m.id)).toEqual(["u1", "a3"]);
    expect(visible[1].content).toBe("A3");
  });

  it("derives the active response per turn across multiple turns", () => {
    const messages = [
      user("u1", "First"),
      assistant("a1", "A1"),
      assistant("a2", "A2"),
      user("u2", "Second"),
      assistant("b1", "B1"),
      assistant("b2", "B2"),
    ];
    const visible = selectTranscriptMessages(messages);
    expect(visible.map((m) => m.id)).toEqual(["u1", "a2", "u2", "b2"]);
  });

  it("never hides user messages", () => {
    const messages = [
      user("u1", "Hello"),
      assistant("a1", "A1"),
      user("u2", "Follow-up"),
      assistant("a2", "A2"),
    ];
    const visible = selectTranscriptMessages(messages);
    expect(visible.map((m) => m.id)).toEqual(["u1", "a1", "u2", "a2"]);
  });

  it("deduplicates by position and identity, not by message text", () => {
    const messages = [
      user("u1", "Same text"),
      assistant("a1", "Same text"),
      assistant("a2", "Same text"),
    ];
    const visible = selectTranscriptMessages(messages);
    expect(visible.map((m) => m.id)).toEqual(["u1", "a2"]);
    expect(visible).toHaveLength(2);
  });
});

describe("associateAssistantMessages", () => {
  it("backs an assistant response into the nearest preceding user message by id", () => {
    const messages = [
      { id: "u1", role: "user" as const, content: "Hello" },
      { id: "a1", role: "assistant" as const, content: "A1" },
    ];
    const associated = associateAssistantMessages(messages);
    expect(associated).not.toBe(messages);
    expect(associated[1].sourceUserMessageId).toBe("u1");
  });

  it("maps each regenerated response to the same originating user message", () => {
    const messages = [
      { id: "u1", role: "user" as const, content: "Hello" },
      { id: "a1", role: "assistant" as const, content: "A1" },
      { id: "a2", role: "assistant" as const, content: "A2" },
    ];
    const associated = associateAssistantMessages(messages);
    expect(associated[1].sourceUserMessageId).toBe("u1");
    expect(associated[2].sourceUserMessageId).toBe("u1");
  });

  it("keeps an existing association and the surrounding structure", () => {
    const messages = [
      user("u1", "Hello"),
      assistant("a1", "A1", "u1"),
      assistant("a2", "A2"),
    ];
    const associated = associateAssistantMessages(messages);
    expect(associated[1].sourceUserMessageId).toBe("u1");
    expect(associated[2].sourceUserMessageId).toBe("u1");
  });

  it("returns the same array when every assistant is already associated", () => {
    const messages = [
      user("u1", "Hello"),
      assistant("a1", "A1", "u1"),
    ];
    expect(associateAssistantMessages(messages)).toBe(messages);
  });

  it("does not associate assistant messages that precede any user message", () => {
    const messages = [{ id: "a1", role: "assistant" as const, content: "A1" }];
    const associated = associateAssistantMessages(messages);
    expect(associated).toBe(messages);
  });
});