/** AVA error contracts. */

import type { JsonValue } from "./json_types";
import type { ContractVersion } from "./version";

export type ErrorCategory =
  | "validation"
  | "configuration"
  | "unavailable"
  | "timeout"
  | "cancelled"
  | "provider"
  | "agent"
  | "internal";

export interface ErrorResponse {
  error_code: string;
  category: ErrorCategory;
  message: string;
  recoverable: boolean;
  details: Record<string, JsonValue>;
  correlation_id: string | null;
  contract_version: ContractVersion;
}