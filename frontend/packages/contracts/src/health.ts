/** AVA health contract. */

import type { ContractVersion } from "./version";

export type HealthStatus = "healthy" | "unhealthy";

export interface HealthResponse {
  status: HealthStatus;
  application: string;
  contract_version: ContractVersion;
}
