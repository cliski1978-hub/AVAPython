/** AVA model provider contracts. */

import type { ContractVersion } from "./version";
import type { ModelHostingMode } from "./runs";
import type { JsonValue } from "./json_types";

export type ModelProviderHealthStatus =
  | "healthy"
  | "degraded"
  | "unavailable"
  | "runtime_unavailable"
  | "model_not_loaded"
  | "authentication_failed"
  | "configuration_invalid";

export interface ModelProviderHealth {
  available: boolean;
  status: ModelProviderHealthStatus;
  message: string | null;
  contract_version: ContractVersion;
}

export interface ModelInfo {
  provider_name: string;
  model_id: string;
  display_name: string | null;
  context_limit: number | null;
  capabilities: ModelCapabilities;
  provider_id: string | null;
  hosting_mode: ModelHostingMode | null;
  enabled: boolean | null;
  qualifications: ModelQualificationInfo[];
  contract_version: ContractVersion;
}

/** Measured evidence summary; it never grants permissions or selects a model. */
export type QualificationStatus = "pass" | "partial" | "fail" | "not_tested";

export interface ModelQualificationInfo {
  qualification_id: string;
  status: QualificationStatus;
  runtime_id: string | null;
  task_class: string;
  evidence_summary: string | null;
  measured_at: string | null;
  contract_version: ContractVersion;
}

/** Declared, provider-neutral model capabilities. They grant no permissions. */
export interface ModelCapabilities {
  chat: boolean;
  streaming: boolean;
  tool_calling: boolean;
  structured_output: boolean;
  vision: boolean;
  embeddings: boolean;
  reasoning: boolean;
  code_specialization: boolean;
  contract_version: ContractVersion;
}

/** Read-only configured-model catalog returned by GET /models. */
export interface ModelDiscoveryResponse {
  contract_version: ContractVersion;
  models: ModelInfo[];
  /**
   * The configured model the application defaults select, or null when no
   * default is configured. Mirrors `default_runtime_id` on `/runtimes`.
   */
  default_model_id?: string | null;
}

export interface ModelToolDefinition {
  name: string;
  description: string;
  parameters: Record<string, JsonValue>;
}

/** Structured provider response; arguments remain untrusted JSON text. */
export interface ModelToolCall {
  id: string;
  name: string;
  arguments: string;
}

export interface ModelMessage {
  role: string;
  content: string;
  tool_calls?: ModelToolCall[];
  tool_call_id?: string | null;
  name?: string | null;
}

export interface ModelRequest {
  messages: ModelMessage[];
  temperature?: number;
  max_output_tokens?: number;
  tools?: ModelToolDefinition[];
  contract_version?: ContractVersion;
}

export interface ModelResponse {
  content: string;
  model_id: string;
  tool_calls?: ModelToolCall[];
  contract_version: ContractVersion;
}
