/** AVA model provider discovery contract. */

import type { ModelInfo, ModelProviderHealth } from "./models";
import type { ContractVersion } from "./version";

export interface ModelProviderDiscoveryItem {
  provider_id: string;
  is_default: boolean;
  model_info: ModelInfo;
  health: ModelProviderHealth;
  contract_version: ContractVersion;
}

export interface ModelProviderDiscoveryResponse {
  contract_version: ContractVersion;
  default_provider_id: string;
  providers: ModelProviderDiscoveryItem[];
}