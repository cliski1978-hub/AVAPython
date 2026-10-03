import type { ContractVersion } from "./version";

/** Flat organizational grouping for conversations; it carries no execution semantics. */
export interface ConversationFolder {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
  contract_version: ContractVersion;
}

export interface ConversationFolderListResponse { folders: ConversationFolder[]; contract_version: ContractVersion; }

export interface CreateConversationFolderRequest {
  name: string;
  contract_version?: ContractVersion;
}

export interface UpdateConversationFolderRequest {
  name: string;
  contract_version?: ContractVersion;
}
