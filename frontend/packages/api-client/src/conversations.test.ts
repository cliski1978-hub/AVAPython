import { expect, it, vi } from "vitest";
import { ApiClient, createConversation, deleteConversation, listConversations, setConversationArchived, setConversationPinned, setConversationProject, updateConversation } from "./index";

it("creates a conversation directly in a Folder when requested", async () => {
  const created = {
    conversation_id: "folder-chat",
    title: "New Conversation",
    folder_id: "folder-x",
    project_id: null,
  };
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(created), { status: 201 }));
  const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });

  await expect(createConversation(client, { folder_id: "folder-x" })).resolves.toEqual(created);
  expect(fetchMock).toHaveBeenCalledWith(
    "http://localhost:8000/conversations",
    expect.objectContaining({ method: "POST", body: JSON.stringify({ folder_id: "folder-x" }) }),
  );
});

it("lists conversations without a search query by default", async () => {
  const response = { conversations: [] };
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(response)));
  const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
  await expect(listConversations(client)).resolves.toEqual(response);
  expect(fetchMock.mock.calls[0][0]).toBe("http://localhost:8000/conversations");
});

it.each(["", "   "])("omits a blank search query (%j)", async (search) => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ conversations: [] })));
  const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
  await listConversations(client, { search });
  expect(fetchMock.mock.calls[0][0]).toBe("http://localhost:8000/conversations");
});

it("trims and URL-encodes a search query", async () => {
  const response = { conversations: [{ conversation_id: "c1", title: "Café & tea?" }] };
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(response)));
  const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
  await expect(listConversations(client, { search: " Café & tea? " })).resolves.toEqual(response);
  expect(fetchMock.mock.calls[0][0]).toBe(
    "http://localhost:8000/conversations?search=Caf%C3%A9+%26+tea%3F",
  );
});

it("propagates list search HTTP errors", async () => {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ error_code: "search_failed" }), { status: 500 }),
  );
  const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
  await expect(listConversations(client, { search: "arch" })).rejects.toMatchObject({ status: 500 });
  expect(fetchMock.mock.calls[0][0]).toBe("http://localhost:8000/conversations?search=arch");
});

it.each([true, false])("sends pin-only state %s and returns the updated response", async (is_pinned) => {
  const response = { conversation_id: "a/b", title: "Keep", is_pinned, is_archived: true, folder_id: "folder-x" };
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(response)));
  const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
  await expect(setConversationPinned(client, "a/b", { is_pinned })).resolves.toEqual(response);
  expect(fetchMock).toHaveBeenCalledOnce();
  expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/conversations/a%2Fb/pin",
    expect.objectContaining({ method: "PATCH", body: JSON.stringify({ is_pinned }) }));
});

it("retains the separate rename request", async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ title: "Renamed" })));
  const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
  await updateConversation(client, "c1", { title: "Renamed" });
  expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/conversations/c1",
    expect.objectContaining({ method: "PATCH", body: JSON.stringify({ title: "Renamed" }) }));
});

it.each([true, false])("sends archive state %s to the narrow archive route", async (is_archived) => {
  const response = {
    conversation_id: "archive-1", title: "Keep", is_pinned: true,
    is_archived, folder_id: "folder-123",
  };
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(response)));
  const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
  await expect(setConversationArchived(client, "archive-1", { is_archived })).resolves.toEqual(response);
  expect(fetchMock).toHaveBeenCalledOnce();
  expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/conversations/archive-1/archive",
    expect.objectContaining({ method: "PATCH", body: JSON.stringify({ is_archived }) }));
});

it("propagates archive endpoint HTTP errors", async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ error_code: "conversation_not_found" }), { status: 404 }));
  const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
  await expect(setConversationArchived(client, "missing", { is_archived: true })).rejects.toMatchObject({ status: 404 });
});

it.each(["project-1", null])("assigns or clears conversation Project membership (%s)", async (project_id) => {
  const response = { conversation_id: "c1", project_id };
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(response)));
  const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
  await expect(setConversationProject(client, "c1", { project_id })).resolves.toEqual(response);
  expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/conversations/c1/project",
    expect.objectContaining({ method: "PATCH", body: JSON.stringify({ project_id }) }));
});

it("deletes a conversation with no body and handles an empty 204 response", async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
  const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
  await expect(deleteConversation(client, "a/b")).resolves.toBeUndefined();
  expect(fetchMock).toHaveBeenCalledOnce();
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe("http://localhost:8000/conversations/a%2Fb");
  expect(init?.method).toBe("DELETE");
  expect(init?.body).toBeUndefined();
});

it.each([
  [404, "conversation_not_found"],
  [409, "conversation_run_active"],
])("propagates DELETE HTTP %s errors through ApiError", async (status, error_code) => {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ error_code }), { status }),
  );
  const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
  await expect(deleteConversation(client, "c1")).rejects.toMatchObject({ status });
  expect(fetchMock).toHaveBeenCalledOnce();
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe("http://localhost:8000/conversations/c1");
  expect(init?.method).toBe("DELETE");
  expect(init?.body).toBeUndefined();
});
