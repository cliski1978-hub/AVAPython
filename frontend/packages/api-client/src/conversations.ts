import type { ConversationListResponse, ConversationResponse, CreateConversationRequest, CreateMessageRequest, MessageListResponse, MessageResponse, UpdateConversationRequest } from "@ava/contracts";
import { ApiClient } from "./client";

const path = (id: string) => `/conversations/${encodeURIComponent(id)}`;
export async function listConversations(client: ApiClient): Promise<ConversationListResponse> { return (await client.request("/conversations")).json(); }
export async function createConversation(client: ApiClient, request: CreateConversationRequest = {}): Promise<ConversationResponse> { return (await client.request("/conversations", { method: "POST", body: JSON.stringify(request) })).json(); }
export async function getConversation(client: ApiClient, id: string): Promise<ConversationResponse> { return (await client.request(path(id))).json(); }
export async function updateConversation(client: ApiClient, id: string, request: UpdateConversationRequest): Promise<ConversationResponse> { return (await client.request(path(id), { method: "PATCH", body: JSON.stringify(request) })).json(); }
export async function listMessages(client: ApiClient, id: string): Promise<MessageListResponse> { return (await client.request(`${path(id)}/messages`)).json(); }
export async function createMessage(client: ApiClient, id: string, request: CreateMessageRequest): Promise<MessageResponse> { return (await client.request(`${path(id)}/messages`, { method: "POST", body: JSON.stringify(request) })).json(); }
