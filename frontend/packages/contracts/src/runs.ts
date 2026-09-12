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
  contract_version?: ContractVersion;
}

export interface RunResponse {
  run_id: string;
  status: RunStatus;
  contract_version: ContractVersion;
}