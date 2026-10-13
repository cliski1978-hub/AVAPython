import type { ConversationFolder, ConversationFolderListResponse, CreateConversationFolderRequest, UpdateConversationFolderRequest, ConversationListResponse, ConversationResponse, CreateConversationRequest, CreateMessageRequest, MessageListResponse, MessageResponse, RelocateConversationRequest, RunPromptPreview, SetConversationArchivedRequest, SetConversationFolderRequest, SetConversationPinnedRequest, SetConversationProjectRequest, UpdateConversationRequest } from "@ava/contracts";
import { ApiClient } from "./client";
export type { RunPromptPreview } from "@ava/contracts";

const path = (id: string) => `/conversations/${encodeURIComponent(id)}`;
export interface ListConversationsOptions { search?: string }
export async function listConversations(client: ApiClient, options: ListConversationsOptions = {}): Promise<ConversationListResponse> {
  const search = options.search?.trim();
  const query = search ? `?${new URLSearchParams({ search }).toString()}` : "";
  return (await client.request(`/conversations${query}`)).json();
}
export async function createConversation(client: ApiClient, request: CreateConversationRequest = {}): Promise<ConversationResponse> { return (await client.request("/conversations", { method: "POST", body: JSON.stringify(request) })).json(); }
export async function getConversation(client: ApiClient, id: string): Promise<ConversationResponse> { return (await client.request(path(id))).json(); }
export async function getConversationPromptPreview(client: ApiClient, id?: string | null): Promise<RunPromptPreview> { return (await client.request(id == null ? "/prompt-preview" : `${path(id)}/prompt-preview`)).json(); }
export async function updateConversation(client: ApiClient, id: string, request: UpdateConversationRequest): Promise<ConversationResponse> { return (await client.request(path(id), { method: "PATCH", body: JSON.stringify(request) })).json(); }
export async function listMessages(client: ApiClient, id: string): Promise<MessageListResponse> { return (await client.request(`${path(id)}/messages`)).json(); }
export async function createMessage(client: ApiClient, id: string, request: CreateMessageRequest): Promise<MessageResponse> { return (await client.request(`${path(id)}/messages`, { method: "POST", body: JSON.stringify(request) })).json(); }

export async function setConversationPinned(client: ApiClient, id: string, request: SetConversationPinnedRequest): Promise<ConversationResponse> { return (await client.request(`${path(id)}/pin`, { method: "PATCH", body: JSON.stringify(request) })).json(); }

export async function setConversationArchived(client: ApiClient, id: string, request: SetConversationArchivedRequest): Promise<ConversationResponse> { return (await client.request(`${path(id)}/archive`, { method: "PATCH", body: JSON.stringify(request) })).json(); }

export async function setConversationProject(client: ApiClient, id: string, request: SetConversationProjectRequest): Promise<ConversationResponse> { return (await client.request(`${path(id)}/project`, { method: "PATCH", body: JSON.stringify(request) })).json(); }
export async function relocateConversation(client: ApiClient, id: string, request: RelocateConversationRequest): Promise<ConversationResponse> { return (await client.request(`${path(id)}/move`, { method: "PATCH", body: JSON.stringify(request) })).json(); }

export async function deleteConversation(client: ApiClient, conversationId: string): Promise<void> {
  await client.request(path(conversationId), { method: "DELETE" });
}

export async function createConversationFolder(client: ApiClient, request: CreateConversationFolderRequest): Promise<ConversationFolder> { return (await client.request("/conversation-folders", { method: "POST", body: JSON.stringify(request) })).json(); }
export async function listConversationFolders(client: ApiClient): Promise<ConversationFolderListResponse> { return (await client.request("/conversation-folders")).json(); }
export async function getConversationFolder(client: ApiClient, folderId: string): Promise<ConversationFolder> { return (await client.request(`/conversation-folders/${encodeURIComponent(folderId)}`)).json(); }
export async function updateConversationFolder(client: ApiClient, folderId: string, request: UpdateConversationFolderRequest): Promise<ConversationFolder> { return (await client.request(`/conversation-folders/${encodeURIComponent(folderId)}`, { method: "PATCH", body: JSON.stringify(request) })).json(); }
export async function deleteConversationFolder(client: ApiClient, folderId: string): Promise<void> { await client.request(`/conversation-folders/${encodeURIComponent(folderId)}`, { method: "DELETE" }); }
export async function setConversationFolder(client: ApiClient, conversationId: string, request: SetConversationFolderRequest): Promise<ConversationResponse> { return (await client.request(`${path(conversationId)}/folder`, { method: "PATCH", body: JSON.stringify(request) })).json(); }
