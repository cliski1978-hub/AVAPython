import { expect, it, vi } from "vitest";
import {
  ApiClient,
  createConversationFolder,
  deleteConversationFolder,
  getConversationFolder,
  listConversationFolders,
  setConversationFolder,
  updateConversationFolder,
} from "./index";

it("supports typed folder CRUD and stable URL encoding", async () => {
  const folder = { id: "f/1", name: "Engineering", created_at: "now", updated_at: "now", contract_version: "1.0" };
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify(folder)))
    .mockResolvedValueOnce(new Response(JSON.stringify({ folders: [folder] })))
    .mockResolvedValueOnce(new Response(JSON.stringify(folder)))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ...folder, name: "Platform" })));
  const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
  await expect(createConversationFolder(client, { name: "Engineering" })).resolves.toEqual(folder);
  await expect(listConversationFolders(client)).resolves.toEqual({ folders: [folder] });
  await expect(getConversationFolder(client, "f/1")).resolves.toEqual(folder);
  await expect(updateConversationFolder(client, "f/1", { name: "Platform" })).resolves.toMatchObject({ name: "Platform" });
  expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
    "http://localhost:8000/conversation-folders",
    "http://localhost:8000/conversation-folders",
    "http://localhost:8000/conversation-folders/f%2F1",
    "http://localhost:8000/conversation-folders/f%2F1",
  ]);
  expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: "POST", body: JSON.stringify({ name: "Engineering" }) });
  expect(fetchMock.mock.calls[3][1]).toMatchObject({ method: "PATCH", body: JSON.stringify({ name: "Platform" }) });
});

it("deletes folders with an empty 204 and propagates API errors", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(null, { status: 204 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ error_code: "conversation_folder_not_found" }), { status: 404 }));
  const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
  await expect(deleteConversationFolder(client, "f/1")).resolves.toBeUndefined();
  expect(fetchMock.mock.calls[0][1]?.method).toBe("DELETE");
  expect(fetchMock.mock.calls[0][1]?.body).toBeUndefined();
  await expect(getConversationFolder(client, "missing")).rejects.toMatchObject({ status: 404 });
});

it("sends a nullable assignment payload and returns the updated conversation", async () => {
  const response = { conversation_id: "c/1", folder_id: null, title: "Chat" };
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(response)));
  const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
  await expect(setConversationFolder(client, "c/1", { folder_id: null })).resolves.toEqual(response);
  expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/conversations/c%2F1/folder",
    expect.objectContaining({ method: "PATCH", body: JSON.stringify({ folder_id: null }) }));
});
