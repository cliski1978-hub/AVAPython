// @vitest-environment jsdom
import { ApiClient } from "@ava/api-client";
import { ConversationProvider, useConversationState, type ConversationManager } from "@ava/agent-ui";
import { act, render, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const TS = "2026-01-01T00:00:00Z";
const initialFolder = { id: "f1", name: "Engineering", created_at: TS, updated_at: TS, contract_version: "v1" };
const secondFolder = { id: "f2", name: "Personal", created_at: TS, updated_at: TS, contract_version: "v1" };
const initialConversation = {
  conversation_id: "c1", title: "Selected", created_at: TS, updated_at: TS,
  is_pinned: true, is_archived: true, folder_id: "f1", contract_version: "v1",
};
const message = {
  message_id: "m1", conversation_id: "c1", role: "assistant", status: "complete", content: "Transcript retained",
  created_at: TS, updated_at: TS, contract_version: "v1",
};

function response(body: unknown, status = 200): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), { status });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

function renderProvider(fetchImpl: typeof fetch) {
  const client = new ApiClient({ baseUrl: "http://ava.test", fetchImpl });
  let manager: ConversationManager | null = null;
  function Probe() {
    manager = useConversationState();
    return <output data-state>{JSON.stringify({
      folders: manager.folders.map((folder) => folder.id),
      active: manager.state.activeConversationId,
      conversations: manager.conversations.map((conversation) => ({
        id: conversation.id, folderId: conversation.folderId, title: conversation.title,
        messages: conversation.messages.map((item) => item.content), run: conversation.run,
      })),
    })}</output>;
  }
  const result = render(<ConversationProvider client={client}><Probe /></ConversationProvider>);
  const managerNow = () => manager!;
  return { ...result, managerNow };
}

describe("conversation folder state reconciliation", () => {
  it("loads folders independently and moves selected conversation metadata without touching its run or transcript", async () => {
    let serverFolderId: string | null = "f1";
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/conversations") || url.includes("/conversations?search=")) {
        return response({ conversations: [{ ...initialConversation, folder_id: serverFolderId }], contract_version: "v1" });
      }
      if (url === "http://ava.test/conversation-folders") return response({ folders: [initialFolder, secondFolder], contract_version: "v1" });
      if (url.endsWith("/conversations/c1/messages")) return response({ conversation_id: "c1", messages: [message], contract_version: "v1" });
      if (url.endsWith("/conversations/c1/folder") && init?.method === "PATCH") {
        serverFolderId = "f2";
        return response({ ...initialConversation, folder_id: serverFolderId });
      }
      return response({}, 404);
    });
    const view = renderProvider(fetchMock as typeof fetch);
    await waitFor(() => expect(view.managerNow().conversations[0]?.messages[0]?.content).toBe("Transcript retained"));
    act(() => view.managerNow().setRunState("c1", { runId: "run-1", backendStatus: "running", uiPhase: "running" }));
    await act(async () => { await view.managerNow().moveConversation("c1", "f2"); });
    act(() => view.managerNow().updateMessage("c1", "m1", { content: "Streamed after Folder move" }));
    const state = JSON.parse(view.container.querySelector("[data-state]")?.textContent ?? "{}");
    expect(view.managerNow().state.activeConversationId).toBe("c1");
    expect(view.managerNow().conversations[0]).toMatchObject({ folderId: "f2", isPinned: true, isArchived: true });
    expect(view.managerNow().conversations[0].messages[0].content).toBe("Streamed after Folder move");
    expect(view.managerNow().conversations[0].run).toMatchObject({ runId: "run-1", uiPhase: "running" });
    expect(state.conversations[0].folderId).toBe("f2");
    expect(fetchMock.mock.calls.some(([url, init]) => String(url).endsWith("/conversations/c1/folder") && init?.method === "PATCH")).toBe(true);
  });

  it("serializes rapid Folder moves so a late earlier response cannot overwrite the latest destination", async () => {
    const first = deferred<Response>();
    const second = deferred<Response>();
    const targets: Array<string | null> = [];
    const projectConversation = { ...initialConversation, project_id: "project-a", folder_id: null };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/conversations") && init?.method !== "PATCH") {
        return response({ conversations: [projectConversation], contract_version: "v1" });
      }
      if (url === "http://ava.test/conversation-folders") return response({ folders: [initialFolder, secondFolder], contract_version: "v1" });
      if (url.endsWith("/conversations/c1/messages")) return response({ conversation_id: "c1", messages: [message], contract_version: "v1" });
      if (url.endsWith("/conversations/c2/messages")) return response({ conversation_id: "c2", messages: [], contract_version: "v1" });
      if (url.endsWith("/conversations/c1/folder") && init?.method === "PATCH") {
        const folderId = JSON.parse(String(init.body)).folder_id as string | null;
        targets.push(folderId);
        return folderId === "f1" ? first.promise : second.promise;
      }
      return response({}, 404);
    });
    const view = renderProvider(fetchMock as typeof fetch);
    await waitFor(() => expect(view.managerNow().conversations[0]?.messages).toHaveLength(1));
    act(() => view.managerNow().setRunState("c1", { runId: "run-active", backendStatus: "running", uiPhase: "running" }));

    let firstMove!: Promise<void>;
    let secondMove!: Promise<void>;
    act(() => { firstMove = view.managerNow().moveConversation("c1", "f1"); });
    await waitFor(() => expect(targets).toEqual(["f1"]));
    act(() => { secondMove = view.managerNow().moveConversation("c1", "f2"); });
    expect(targets).toEqual(["f1"]); // one conversation has at most one mutation in flight

    first.resolve(response({ ...projectConversation, folder_id: "f1" }));
    await waitFor(() => expect(targets).toEqual(["f1", "f2"]));
    expect(view.managerNow().conversations[0].folderId).toBeNull(); // stale intermediate response is not published
    second.resolve(response({ ...projectConversation, folder_id: "f2" }));
    await act(async () => { await Promise.all([firstMove, secondMove]); });

    expect(view.managerNow().conversations[0]).toMatchObject({ folderId: "f2", projectId: "project-a" });
    expect(view.managerNow().conversations[0].messages[0].content).toBe("Transcript retained");
    expect(view.managerNow().conversations[0].run).toMatchObject({ runId: "run-active", uiPhase: "running" });
    expect(view.managerNow().state.activeConversationId).toBe("c1");
  });

  it("keeps moves for different conversations independent", async () => {
    const c1Move = deferred<Response>();
    const c2Move = deferred<Response>();
    const requests: string[] = [];
    const secondConversation = { ...initialConversation, conversation_id: "c2", title: "Second", is_pinned: false, folder_id: null, project_id: null };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (new URL(url).pathname === "/conversations" && init?.method !== "PATCH") {
        return response({ conversations: [{ ...initialConversation, project_id: null }, secondConversation], contract_version: "v1" });
      }
      if (url === "http://ava.test/conversation-folders") return response({ folders: [initialFolder, secondFolder], contract_version: "v1" });
      if (url.endsWith("/conversations/c1/messages")) return response({ conversation_id: "c1", messages: [message], contract_version: "v1" });
      if (url.endsWith("/conversations/c2/messages")) return response({ conversation_id: "c2", messages: [], contract_version: "v1" });
      if (url.endsWith("/conversations/c1/folder") && init?.method === "PATCH") {
        requests.push("c1");
        return c1Move.promise;
      }
      if (url.endsWith("/conversations/c2/folder") && init?.method === "PATCH") {
        requests.push("c2");
        return c2Move.promise;
      }
      return response({}, 404);
    });
    const view = renderProvider(fetchMock as typeof fetch);
    await waitFor(() => expect(view.managerNow().conversations.map((item) => item.id)).toEqual(["c1", "c2"]));

    let move1!: Promise<void>;
    let move2!: Promise<void>;
    act(() => {
      move1 = view.managerNow().moveConversation("c1", "f2");
      move2 = view.managerNow().moveConversation("c2", "f1");
    });
    await waitFor(() => expect(requests).toEqual(["c1", "c2"]));
    c1Move.resolve(response({ ...initialConversation, folder_id: "f2" }));
    c2Move.resolve(response({ ...secondConversation, folder_id: "f1" }));
    await act(async () => { await Promise.all([move1, move2]); });

    expect(view.managerNow().conversations.map((item) => [item.id, item.folderId])).toEqual([
      ["c1", "f2"], ["c2", "f1"],
    ]);
  });

  it("serializes rapid archive/restore intent and preserves pin, Folder, Project, transcript, and active run", async () => {
    const firstArchive = deferred<Response>();
    const archiveTargets: boolean[] = [];
    const projectConversation = { ...initialConversation, project_id: "project-p", is_archived: false };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/conversations") && init?.method !== "PATCH") {
        return response({ conversations: [projectConversation], contract_version: "v1" });
      }
      if (url === "http://ava.test/conversation-folders") return response({ folders: [initialFolder], contract_version: "v1" });
      if (url.endsWith("/conversations/c1/messages")) return response({ conversation_id: "c1", messages: [message], contract_version: "v1" });
      if (url.endsWith("/conversations/c1/archive") && init?.method === "PATCH") {
        const isArchived = JSON.parse(String(init.body)).is_archived as boolean;
        archiveTargets.push(isArchived);
        if (archiveTargets.length === 1) return firstArchive.promise;
        return response({ ...projectConversation, is_archived: isArchived });
      }
      return response({}, 404);
    });
    const view = renderProvider(fetchMock as typeof fetch);
    await waitFor(() => expect(view.managerNow().conversations[0]?.messages[0]?.content).toBe("Transcript retained"));
    act(() => view.managerNow().setRunState("c1", { runId: "run-active", backendStatus: "running", uiPhase: "running" }));

    let archive!: Promise<void>;
    let restore!: Promise<void>;
    act(() => {
      archive = view.managerNow().setConversationArchived("c1", true);
      restore = view.managerNow().setConversationArchived("c1", false);
    });
    expect(archiveTargets).toEqual([true]);
    firstArchive.resolve(response({ ...projectConversation, is_archived: true }));
    await waitFor(() => expect(archiveTargets).toEqual([true, false]));
    expect(view.managerNow().conversations[0].isArchived).toBe(false); // stale intermediate response is not published
    act(() => view.managerNow().updateMessage("c1", "m1", { content: "Streamed after archive" }));
    await act(async () => { await Promise.all([archive, restore]); });

    expect(view.managerNow().conversations[0]).toMatchObject({
      isArchived: false, isPinned: true, folderId: "f1", projectId: "project-p",
    });
    expect(view.managerNow().conversations[0].messages[0].content).toBe("Streamed after archive");
    expect(view.managerNow().conversations[0].run).toMatchObject({ runId: "run-active", uiPhase: "running" });
    expect(view.managerNow().state.activeConversationId).toBe("c1");
  });

  it("reconciles a destination Folder deleted while its move request is pending", async () => {
    const moveResponse = deferred<Response>();
    let serverFolderId: string | null = null;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/conversations") && init?.method !== "PATCH") {
        return response({ conversations: [{ ...initialConversation, folder_id: serverFolderId }], contract_version: "v1" });
      }
      if (url === "http://ava.test/conversation-folders") return response({ folders: [initialFolder, secondFolder], contract_version: "v1" });
      if (url.endsWith("/conversations/c1/messages")) return response({ conversation_id: "c1", messages: [message], contract_version: "v1" });
      if (url.endsWith("/conversations/c1/folder") && init?.method === "PATCH") return moveResponse.promise;
      if (url.endsWith("/conversation-folders/f2") && init?.method === "DELETE") return response({}, 204);
      return response({}, 404);
    });
    const view = renderProvider(fetchMock as typeof fetch);
    await waitFor(() => expect(view.managerNow().foldersLoading).toBe(false));

    let move!: Promise<void>;
    act(() => { move = view.managerNow().moveConversation("c1", "f2"); });
    await act(async () => { await view.managerNow().deleteFolder("f2"); });
    expect(view.managerNow().folders.map((folder) => folder.id)).toEqual(["f1"]);

    moveResponse.resolve(response({ ...initialConversation, folder_id: "f2" }));
    await act(async () => { await move; });
    expect(view.managerNow().conversations[0].folderId).toBeNull();
    expect(view.managerNow().folders.map((folder) => folder.id)).toEqual(["f1"]);
  });

  it("creates a Folder conversation in one request with no inferred Project membership", async () => {
    const created = {
      conversation_id: "new-folder-chat", title: "New Conversation", created_at: TS, updated_at: TS,
      is_pinned: false, is_archived: false, folder_id: "f1", project_id: null, contract_version: "v1",
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "http://ava.test/conversation-folders") return response({ folders: [initialFolder], contract_version: "v1" });
      if (url === "http://ava.test/conversations" && init?.method === "POST") return response(created, 201);
      if (url === "http://ava.test/conversations") return response({ conversations: [created], contract_version: "v1" });
      if (url.endsWith("/conversations/new-folder-chat/messages")) return response({ conversation_id: created.conversation_id, messages: [], contract_version: "v1" });
      return response({}, 404);
    });
    const view = renderProvider(fetchMock as typeof fetch);
    await waitFor(() => expect(view.managerNow().foldersLoading).toBe(false));

    await act(async () => { await view.managerNow().createConversationInFolder("f1"); });

    const post = fetchMock.mock.calls.find(([url, init]) => String(url) === "http://ava.test/conversations" && init?.method === "POST");
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({ folder_id: "f1" });
    expect(view.managerNow().conversations[0]).toMatchObject({ id: "new-folder-chat", folderId: "f1", projectId: null });
    expect(view.managerNow().state.activeConversationId).toBe("new-folder-chat");
  });

  it("deletes a folder locally while preserving its conversations, transcript, selection, and run state", async () => {
    let serverFolderId: string | null = "f1";
    let serverFolders = [initialFolder];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/conversations")) return response({ conversations: [{ ...initialConversation, folder_id: serverFolderId }], contract_version: "v1" });
      if (url === "http://ava.test/conversation-folders") return response({ folders: serverFolders, contract_version: "v1" });
      if (url.endsWith("/conversations/c1/messages")) return response({ conversation_id: "c1", messages: [message], contract_version: "v1" });
      if (url.endsWith("/conversation-folders/f1") && init?.method === "DELETE") {
        serverFolders = [];
        serverFolderId = null;
        return response(null, 204);
      }
      return response({}, 404);
    });
    const view = renderProvider(fetchMock as typeof fetch);
    await waitFor(() => expect(view.managerNow().folders).toHaveLength(1));
    await waitFor(() => expect(view.managerNow().conversations[0]?.messages).toHaveLength(1));
    act(() => view.managerNow().setRunState("c1", { runId: "run-1", backendStatus: "running", uiPhase: "running" }));
    await act(async () => { await view.managerNow().deleteFolder("f1"); });
    expect(view.managerNow().folders).toHaveLength(0);
    expect(view.managerNow().conversations).toHaveLength(1);
    expect(view.managerNow().conversations[0]).toMatchObject({ id: "c1", folderId: null, isPinned: true, isArchived: true });
    expect(view.managerNow().state.activeConversationId).toBe("c1");
    expect(view.managerNow().conversations[0].messages[0].content).toBe("Transcript retained");
    expect(view.managerNow().conversations[0].run).toMatchObject({ runId: "run-1", uiPhase: "running" });
  });

  it("reconciles an already-deleted folder and its ungrouped assignments on DELETE 404", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/conversations")) return response({ conversations: [{ ...initialConversation, folder_id: null }], contract_version: "v1" });
      if (url === "http://ava.test/conversation-folders") return response({ folders: [], contract_version: "v1" });
      if (url.endsWith("/conversations/c1/messages")) return response({ conversation_id: "c1", messages: [message], contract_version: "v1" });
      if (url.endsWith("/conversation-folders/f1") && init?.method === "DELETE") {
        return response({ error_code: "conversation_folder_not_found" }, 404);
      }
      return response({}, 404);
    });
    const view = renderProvider(fetchMock as typeof fetch);
    await waitFor(() => expect(view.managerNow().conversations[0]?.messages).toHaveLength(1));
    await act(async () => { await view.managerNow().deleteFolder("f1"); });
    expect(view.managerNow().folders).toEqual([]);
    expect(view.managerNow().conversations[0]).toMatchObject({ id: "c1", folderId: null });
    expect(view.managerNow().state.activeConversationId).toBe("c1");
  });

  it("reconciles folder 404s without changing the conversation assignment", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/conversations")) return response({ conversations: [initialConversation], contract_version: "v1" });
      if (url === "http://ava.test/conversation-folders") return response({ folders: [initialFolder], contract_version: "v1" });
      if (url.endsWith("/conversations/c1/messages")) return response({ conversation_id: "c1", messages: [message], contract_version: "v1" });
      if (url.endsWith("/conversations/c1/folder") && init?.method === "PATCH") {
        return response({ error_code: "conversation_folder_not_found" }, 404);
      }
      return response({}, 404);
    });
    const view = renderProvider(fetchMock as typeof fetch);
    await waitFor(() => expect(view.managerNow().folders).toHaveLength(1));
    await act(async () => { await view.managerNow().moveConversation("c1", "gone"); });
    expect(view.managerNow().conversations[0].folderId).toBe("f1");
    expect(view.managerNow().folders.map((folder) => folder.id)).toEqual(["f1"]);
    expect(view.managerNow().folderError).toContain("no longer exists");
  });

  it("keeps conversations available when folder loading fails and reconciles create/rename from server order", async () => {
    let serverFolders: Array<typeof initialFolder> = [];
    let folderListReads = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/conversations")) return response({ conversations: [{ ...initialConversation, folder_id: null }], contract_version: "v1" });
      if (url.endsWith("/conversations/c1/messages")) return response({ conversation_id: "c1", messages: [message], contract_version: "v1" });
      if (url === "http://ava.test/conversation-folders" && init?.method === "POST") {
        const created = { ...initialFolder, id: "f1", name: JSON.parse(String(init.body)).name };
        serverFolders = [created];
        return response(created, 201);
      }
      if (url === "http://ava.test/conversation-folders" && init?.method === "GET") {
        folderListReads += 1;
        if (folderListReads === 1) return response({ error_code: "temporary" }, 500);
        return response({ folders: serverFolders, contract_version: "v1" });
      }
      if (url.endsWith("/conversation-folders/f1") && init?.method === "PATCH") {
        const updated = { ...serverFolders[0], name: JSON.parse(String(init.body)).name };
        serverFolders = [updated];
        return response(updated);
      }
      return response({}, 404);
    });
    const view = renderProvider(fetchMock as typeof fetch);
    await waitFor(() => expect(view.managerNow().conversations[0]?.messages).toHaveLength(1));
    await waitFor(() => expect(view.managerNow().folderError).toContain("Unable to load folders"));
    await act(async () => { await view.managerNow().createFolder(" New folder "); });
    expect(view.managerNow().folders.map((folder) => folder.name)).toEqual(["New folder"]);
    await act(async () => { await view.managerNow().renameFolder("f1", "Renamed"); });
    expect(view.managerNow().folders).toMatchObject([{ id: "f1", name: "Renamed" }]);
    expect(view.managerNow().conversations[0].folderId).toBeNull();
    expect(view.managerNow().state.activeConversationId).toBe("c1");
  });

  it("does not restore a folder from the initial list after a successful delete", async () => {
    const foldersResponse = deferred<Response>();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/conversations")) {
        return response({ conversations: [initialConversation], contract_version: "v1" });
      }
      if (url.startsWith("http://ava.test/conversation-folders/") && init?.method === "DELETE") {
        return response(null, 204);
      }
      if (url === "http://ava.test/conversation-folders") return foldersResponse.promise;
      if (url.endsWith("/conversations/c1/messages")) return response({ conversation_id: "c1", messages: [message], contract_version: "v1" });
      return response({}, 404);
    });
    const view = renderProvider(fetchMock as typeof fetch);
    await waitFor(() => expect(view.managerNow().conversations).toHaveLength(1));
    await act(async () => { await view.managerNow().deleteFolder("f1"); });
    foldersResponse.resolve(response({ folders: [initialFolder], contract_version: "v1" }));
    await act(async () => Promise.resolve());
    await waitFor(() => expect(view.managerNow().folders).toEqual([]));
  });
});
