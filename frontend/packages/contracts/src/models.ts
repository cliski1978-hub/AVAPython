/** AVA model provider contracts. */

import type { ContractVersion } from "./version";

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
  contract_version: ContractVersion;
}

export interface ModelMessage {
  role: string;
  content: string;
}

export interface ModelRequest {
  messages: ModelMessage[];
  temperature?: number;
  max_output_tokens?: number;
  contract_version?: ContractVersion;
}

export interface ModelResponse {
  content: string;
  model_id: string;
  contract_version: ContractVersion;
}