/** AVA capabilities contract. */

import type { ContractVersion } from "./version";

export type CapabilityName =
  | "health"
  | "runs"
  | "streaming"
  | "tool_calling"
  | "structured_output"
  | "cancellation"
  | "document_operations"
  | "approvals"
  | "local_model"
  | "local_execution";

export interface CapabilitiesResponse {
  contract_version: ContractVersion;
  application: string;
  capabilities: Record<CapabilityName, boolean>;
}