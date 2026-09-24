import { describe, expect, it, vi } from "vitest";
import { createPersistAssistantMessageCommand } from "./persistAssistantMessage";

describe("createPersistAssistantMessageCommand", () => {
  it("persists once and dispatches an authoritative replacement", async () => {
    const request = vi.fn(async () => new Response(JSON.stringify({ message_id: "assistant-backend-1", conversation_id: "conversation-a", role: "assistant", content: "final assistant response", status: "complete", created_at: "2026-01-01T00:00:00Z" }), { status: 200 }));
    const replaceMessage = vi.fn();
    const command = createPersistAssistantMessageCommand({ client: { request } as never, replaceMessage });
    const saved = await command("conversation-a", "assistant-local-1", "final assistant response");
    expect(request).toHaveBeenCalledTimes(1);
    expect(request).toHaveBeenCalledWith("/conversations/conversation-a/messages", { method: "POST", body: JSON.stringify({ role: "assistant", content: "final assistant response" }) });
    expect(saved.message_id).toBe("assistant-backend-1");
    expect(replaceMessage).toHaveBeenCalledWith("conversation-a", "assistant-local-1", expect.objectContaining({ id: "assistant-backend-1", status: "complete" }));
  });
});
