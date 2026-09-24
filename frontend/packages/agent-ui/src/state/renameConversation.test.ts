import { describe, expect, it, vi } from "vitest";
import { createRenameConversationCommand } from "./renameConversation";
describe("createRenameConversationCommand", () => {
  it("uses the backend conversation", async () => {
    const request = vi.fn(async () => new Response(JSON.stringify({ conversation_id: "conversation-a", title: "Backend Normalized Title", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-02T00:00:00Z" })));
    const onSuccess = vi.fn(); const command = createRenameConversationCommand({ client: { request } as never, onSuccess, onError: vi.fn() });
    await command("conversation-a", "Requested Title");
    expect(request).toHaveBeenCalledWith("/conversations/conversation-a", { method: "PATCH", body: JSON.stringify({ title: "Requested Title" }) });
    expect(onSuccess).toHaveBeenCalledWith(expect.objectContaining({ title: "Backend Normalized Title", createdAt: "2026-01-01T00:00:00Z" }));
  });
  it("reports and rethrows failures", async () => {
    const onError = vi.fn(); const command = createRenameConversationCommand({ client: { request: vi.fn(async () => { throw new Error("no"); }) } as never, onSuccess: vi.fn(), onError });
    await expect(command("conversation-a", "Title")).rejects.toThrow("no"); expect(onError).toHaveBeenCalledTimes(1);
  });
});
