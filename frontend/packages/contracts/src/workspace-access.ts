import type { WorkspaceKind } from "./workspaces";

export type ToolCapability = "file_read" | "file_write" | "file_delete" | "command_execution" | "network_access";
export type WorkspaceAccessStatus = "active" | "revoked";
export interface WorkspaceAccessItem {
  workspace_id: string;
  name: string | null;
  kind: WorkspaceKind;
  root_path: string | null;
  allowed_capabilities: ToolCapability[];
  status: WorkspaceAccessStatus;
  revision: number;
  created_at: string;
  updated_at: string;
}
export interface WorkspaceAccessResponse {
  workspaces: WorkspaceAccessItem[];
  can_manage: boolean;
  roots_disclosed: boolean;
  configuration_status: "valid" | "invalid";
  contract_version: "v1";
}
export interface CreateWorkspaceAccessRequest {
  workspace_id: string;
  name?: string | null;
  kind: WorkspaceKind;
  root_path: string;
  allowed_capabilities: ToolCapability[];
  contract_version?: "v1";
}
export interface UpdateWorkspaceAccessRequest {
  name?: string | null;
  kind: WorkspaceKind;
  root_path: string;
  allowed_capabilities: ToolCapability[];
  status: WorkspaceAccessStatus;
  expected_revision: number;
  contract_version?: "v1";
}
