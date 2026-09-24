import type { ContractVersion } from "./version";

export type MessageRole = "user" | "assistant" | "system";
export type MessageStatus = "pending" | "complete" | "failed" | "cancelled";

export interface ConversationResponse {
  conversation_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  contract_version: ContractVersion;
}
export interface ConversationListResponse { conversations: ConversationResponse[]; contract_version: ContractVersion; }
export interface CreateConversationRequest { title?: string | null; contract_version?: ContractVersion; }
export interface UpdateConversationRequest { title: string; contract_version?: ContractVersion; }
export interface MessageResponse {
  message_id: string; conversation_id: string; role: MessageRole; content: string;
  status: MessageStatus; source_run_id?: string | null; created_at: string; updated_at: string;
  contract_version: ContractVersion;
}
export interface MessageListResponse { conversation_id: string; messages: MessageResponse[]; contract_version: ContractVersion; }
export interface CreateMessageRequest { content: string; role?: MessageRole; source_run_id?: string | null; contract_version?: ContractVersion; }
