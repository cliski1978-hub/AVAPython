import type { ContractVersion } from "./version";

export type MessageRole = "user" | "assistant" | "system";
export type MessageStatus = "pending" | "streaming" | "complete" | "failed" | "cancelled";

export interface ConversationResponse {
  conversation_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  /**
   * Conversation organization metadata. Phase 5.44 makes pin state writable;
   * folder metadata remains read-only.
   *
   * The backend always emits these, so they are required here. `is_pinned` is
   * presentational only and never affects execution; `is_archived` is a
   * reversible hidden state that keeps the conversation and all of its
   * messages, runs, and events (archive is not delete); and `folder_id` is a
   * nullable organizational relationship represented by folder ID. A folder
   * object is not embedded in this conversation response.
   */
  is_pinned: boolean;
  is_archived: boolean;
  folder_id: string | null;
  /** Project relationship, independent from folder membership. */
  project_id: string | null;
  contract_version: ContractVersion;
}
export interface ConversationListResponse { conversations: ConversationResponse[]; contract_version: ContractVersion; }
export interface CreateConversationRequest { title?: string | null; folder_id?: string | null; contract_version?: ContractVersion; }
export interface UpdateConversationRequest { title: string; contract_version?: ContractVersion; }
export interface MessageResponse {
  message_id: string; conversation_id: string; role: MessageRole; content: string;
  status: MessageStatus; source_run_id?: string | null; source_user_message_id?: string | null; error_code?: string | null; created_at: string; updated_at: string;
  contract_version: ContractVersion;
}
export interface MessageListResponse { conversation_id: string; messages: MessageResponse[]; contract_version: ContractVersion; }
export interface CreateMessageRequest { content: string; role?: MessageRole; source_run_id?: string | null; contract_version?: ContractVersion; }

export interface SetConversationPinnedRequest { is_pinned: boolean; contract_version?: ContractVersion; }

export interface SetConversationArchivedRequest { is_archived: boolean; contract_version?: ContractVersion; }

export interface SetConversationFolderRequest { folder_id: string | null; contract_version?: ContractVersion; }
export interface SetConversationProjectRequest { project_id: string | null; contract_version?: ContractVersion; }
