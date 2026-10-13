/** AVA run contracts. */

import type { ContractVersion } from "./version";
import type { JsonValue } from "./json_types";
import type { RunEvent } from "./events";

export type RunStatus =
  | "pending"
  | "running"
  | "waiting_for_approval"
  | "completed"
  | "cancelled"
  | "failed";

/** Run-scoped tool-execution ceiling. Omitted requests default to chat. */
export type ExecutionMode = "chat" | "plan" | "agent";

export interface RunRequest {
  prompt: string;
  /** Durable conversation ownership for a conversation-originated run. */
  conversation_id?: string | null;
  /** Durable user message that caused the run; supplied with conversation_id. */
  source_user_message_id?: string | null;
  execution?: RunExecutionOverride | null;
  execution_mode?: ExecutionMode;
  /** Opaque AVA workspace id. Omitted when no workspace is selected. */
  workspace_id?: string | null;
  /**
   * Prior attempt a retry or regenerate branches from. Request-time intent
   * only: it is never persisted, and the durable lineage is the
   * `source_user_message_id` the new run inherits from the named run. The
   * backend resolves the prompt and source from that run's durable records and
   * requires it to be terminal.
   */
  retry_of_run_id?: string | null;
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
  /** Persisted mode; optional for compatibility with older servers. */
  execution_mode?: ExecutionMode;
}

export interface InspectedContextMessage {
  role: "system" | "assistant" | "user";
  content: string;
  message_id?: string | null;
}

export interface RunInspectionSnapshot {
  attachments?: AttachmentContextItem[];
  execution_resolution: Record<string, JsonValue>;
  prompt_layers?: {
    root_system_prompt: string;
    resolved_core_prompts: Array<{
      id: string;
      name: string;
      category: string;
      prompt_text: string;
      winning_scope_type: string;
      winning_scope_id?: string | null;
      winning_assignment_id?: string | null;
    }>;
    project_instructions?: string | null;
  } | null;
  normalized_request: InspectedContextMessage[];
  context_window?: {
    context_window_tokens: number | null;
    input_budget_tokens: number | null;
    estimated_input_tokens: number;
    output_reserve_tokens: number;
    dropped_message_count: number;
    dropped_turn_count: number;
    count_accuracy: "estimated" | "exact";
    can_fit?: boolean;
    required_input_tokens?: number | null;
    model_id?: string | null;
    attachment_context_tokens?: number;
    attachments?: AttachmentContextItem[];
  } | null;
  context_compaction?: {
    attempted: boolean;
    used: boolean;
    failed: boolean;
    failure_reason?: string | null;
    summary_id?: string | null;
    summary_version?: number | null;
    summary_content?: string | null;
    summary_token_count: number;
    covers_through_message_id?: string | null;
    covers_through_sequence?: number | null;
    recent_message_ids: string[];
    source_token_count: number;
    estimated_before_tokens: number;
    estimated_after_tokens: number;
    trigger_percent: number;
    target_percent: number;
  } | null;
  runtime_request?: JsonValue;
  runtime_response?: JsonValue;
  normalized_response?: JsonValue;
}

export interface ContextWindowPreview {
  attachment_context_tokens?: number;
  attachments?: AttachmentContextItem[];
  context_window_tokens: number | null;
  input_budget_tokens: number | null;
  estimated_input_tokens: number;
  output_reserve_tokens: number;
  dropped_message_count: number;
  dropped_turn_count: number;
  count_accuracy: "estimated" | "exact";
  can_fit: boolean;
  required_input_tokens: number | null;
  model_id: string | null;
  estimated_before_compaction_tokens?: number | null;
  compaction_recommended?: boolean;
  active_summary_version?: number | null;
  active_summary_token_count?: number;
}

export interface AttachmentContextItem {
  attachment_id: string;
  file_name: string;
  media_type: string;
  status: "included" | "unsupported" | "extraction_failed" | "excluded_context_limit";
  included: boolean;
  text: string | null;
  token_count: number;
  count_accuracy: "estimated" | "exact";
  error_code: string | null;
  error_message: string | null;
}

export interface RunInspectionResponse {
  run_id: string;
  conversation_id?: string | null;
  source_user_message_id?: string | null;
  status: RunStatus;
  created_at: string;
  updated_at: string;
  execution_selection?: RunExecutionSelection | null;
  execution_mode?: ExecutionMode;
  assistant_message_id?: string | null;
  assistant_message?: string | null;
  snapshot?: RunInspectionSnapshot | null;
  events: RunEvent[];
}

export interface RunPromptPreview {
  root_system_prompt: string;
  resolved_core_prompts: NonNullable<RunInspectionSnapshot["prompt_layers"]>["resolved_core_prompts"];
  project_instructions?: string | null;
}

export interface RunListItem {
  run_id: string;
  status: RunStatus;
  created_at: string;
  updated_at: string;
  execution_mode?: ExecutionMode;
}

export type ModelHostingMode = "local" | "company_hosted" | "external";

export interface RunExecutionSelection {
  runtime_id?: string | null;
  model_provider_id?: string | null;
  model_id?: string | null;
  hosting_mode?: ModelHostingMode | null;
  runtime_source?: string | null;
  model_source?: string | null;
  provider_connection_id?: string | null;
  runtime_configuration_id?: string | null;
  project_id?: string | null;
  contract_version?: ContractVersion;
}
