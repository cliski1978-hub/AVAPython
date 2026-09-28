/** AVA run contracts. */

import type { ContractVersion } from "./version";

export type RunStatus =
  | "pending"
  | "running"
  | "waiting_for_approval"
  | "completed"
  | "cancelled"
  | "failed";

export interface RunRequest {
  prompt: string;
  /** Durable conversation ownership for a conversation-originated run. */
  conversation_id?: string | null;
  /** Durable user message that caused the run; supplied with conversation_id. */
  source_user_message_id?: string | null;
  execution?: RunExecutionOverride | null;
  /** Opaque AVA workspace id. Omitted when no workspace is selected. */
  workspace_id?: string | null;
  contract_version?: ContractVersion;
}

export interface RunExecutionOverride {
  mode?: "auto";
  runtime_id?: string | null;
  /** Stable, provider-neutral AVA model identity. Preferred over provider id. */
  model_id?: string | null;
  model_provider_id?: string | null;
}

export interface ExecutionProfile {
  id: string;
  name: string;
  description?: string;
  runtime_id: string;
  model_provider_id: string;
}

export interface ExecutionProfileDiscoveryResponse {
  contract_version: ContractVersion;
  default_profile_id: string;
  profiles: ExecutionProfile[];
}

export interface RuntimeDiscoveryItem {
  is_default: boolean;
  runtime_info: { runtime_id: string; display_name?: string | null };
  contract_version: ContractVersion;
}

export interface RuntimeDiscoveryResponse {
  contract_version: ContractVersion;
  default_runtime_id: string;
  runtimes: RuntimeDiscoveryItem[];
}

export interface RunResponse {
  /** Durable intent only; status remains the authoritative outcome. */
  cancellation_requested_at?: string | null;
  run_id: string;
  status: RunStatus;
  conversation_id?: string | null;
  source_user_message_id?: string | null;
  assistant_message_id?: string | null;
  contract_version: ContractVersion;
  execution_selection?: RunExecutionSelection | null;
}

export type ModelHostingMode = "local" | "company_hosted" | "external";

export interface RunExecutionSelection {
  runtime_id?: string | null;
  model_provider_id?: string | null;
  model_id?: string | null;
  hosting_mode?: ModelHostingMode | null;
  contract_version?: ContractVersion;
}
