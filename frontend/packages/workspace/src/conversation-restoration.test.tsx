// @vitest-environment jsdom
import { ApiClient } from "@ava/api-client";
import { ConversationProvider, useConversationState, type ConversationManager } from "@ava/agent-ui";
import { act, render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const key = "ava.activeConversationId";
const response = (body: unknown) => new Response(JSON.stringify(body));
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}
function setup(extra = {}, pendingList?: Promise<Response>, pendingFolders?: Promise<Response>) {
  const conversations = ["B", "A"].map((id) => ({ conversation_id: id, title: id,
    created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", contract_version: "v1",
    ...(id === "A" ? extra : {}),
  }));
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/conversations")) return pendingList ?? response({ conversations });
    if (url.endsWith("/conversation-folders")) return pendingFolders ?? response({ folders: [] });
    return response({ messages: [] });
  });
  const client = new ApiClient({ baseUrl: "http://ava.test", fetchImpl: fetchMock as typeof fetch });
  let manager!: ConversationManager;
  function Probe() { manager = useConversationState(); return null; }
  const mount = () => render(<ConversationProvider client={client}><Probe /></ConversationProvider>);
  return { mount, current: () => manager, fetchMock, conversations };
}

beforeEach(() => sessionStorage.clear());
describe("conversation restoration", () => {
  it.each([{}, { folder_id: "folder-1" }, { project_id: "project-1" }, { is_archived: true }])(
    "preserves a selected conversation across reconstruction (%j)", async (metadata) => {
      const app = setup(metadata);
      let view = app.mount();
      await waitFor(() => expect(app.current().state.loading).toBe(false));
      await act(() => app.current().selectConversation("A"));
      view.unmount();
      view = app.mount();
      await waitFor(() => expect(app.current().state.loading).toBe(false));
      expect(app.current().state.activeConversationId).toBe("A");
      view.unmount();
    },
  );
  it("retains restoration while the collection and folders arrive later without duplicate detail loads", async () => {
    sessionStorage.setItem(key, "A");
    const list = deferred<Response>();
    const folders = deferred<Response>();
    const app = setup({ folder_id: "folder-1" }, list.promise, folders.promise);
    app.mount();
    expect(app.current().state.activeConversationId).toBe("A");
    await act(async () => list.resolve(response({ conversations: app.conversations })));
    expect(app.current().state.activeConversationId).toBe("A");
    await act(async () => folders.resolve(response({ folders: [] })));
    expect(app.current().state.activeConversationId).toBe("A");
    expect(app.fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/A/messages"))).toHaveLength(1);
  });
  it("ignores a stale B detail response after returning to restored A", async () => {
    sessionStorage.setItem(key, "A");
    const app = setup(); app.mount();
    await waitFor(() => expect(app.current().state.loading).toBe(false));
    const stale = deferred<Response>();
    app.fetchMock.mockImplementationOnce(() => stale.promise);
    let selectingB!: Promise<void>;
    act(() => { selectingB = app.current().selectConversation("B"); });
    await act(() => app.current().selectConversation("A"));
    await act(async () => {
      stale.resolve(response({ messages: [{ message_id: "stale", role: "assistant", content: "B transcript" }] }));
      await selectingB;
    });
    expect(app.current().state.activeConversationId).toBe("A");
    expect(app.current().activeConversation?.messages).toEqual([]);
    expect(sessionStorage.getItem(key)).toBe("A");
  });
  it("clears a missing selection only after a successful empty collection load", async () => {
    sessionStorage.setItem(key, "A");
    const app = setup({}, Promise.resolve(response({ conversations: [] }))); app.mount();
    await waitFor(() => expect(app.current().state.loading).toBe(false));
    expect(app.current().state.activeConversationId).toBeNull();
    expect(sessionStorage.getItem(key)).toBeNull();
  });
  it("retains the remembered identity after a failed load and restores it on retry", async () => {
    sessionStorage.setItem(key, "A");
    const app = setup();
    app.fetchMock.mockImplementationOnce(async () => new Response("unavailable", { status: 503 }));
    app.mount();
    await waitFor(() => expect(app.current().state.loadError).toBeTruthy());
    expect(sessionStorage.getItem(key)).toBe("A");
    await act(() => app.current().reloadConversations());
    expect(app.current().state.activeConversationId).toBe("A");
  });
  it("falls back when the remembered identity is missing", async () => {
    sessionStorage.setItem(key, "missing");
    const app = setup(); app.mount();
    await waitFor(() => expect(app.current().state.loading).toBe(false));
    expect(app.current().state.activeConversationId).toBe("B");
    expect(sessionStorage.getItem(key)).toBe("B");
  });
  it("keeps a Project conversation selected after safe Project deletion", async () => {
    const app = setup({ project_id: "project-a" }); app.mount();
    await waitFor(() => expect(app.current().state.loading).toBe(false));
    await act(() => app.current().selectConversation("A"));
    act(() => app.current().reconcileDeletedProject("project-a"));
    expect(app.current().state.activeConversationId).toBe("A");
    expect(app.current().conversations.find((item) => item.id === "A")?.projectId).toBeNull();
  });
  it("selects a valid fallback when Project deletion removes the active conversation", async () => {
    const app = setup({ project_id: "project-a" }); app.mount();
    await waitFor(() => expect(app.current().state.loading).toBe(false));
    await act(() => app.current().selectConversation("A"));
    act(() => app.current().reconcileDeletedProject("project-a", ["A"]));
    expect(app.current().state.activeConversationId).toBe("B");
    expect(app.current().conversations.some((item) => item.id === "A")).toBe(false);
  });
});
