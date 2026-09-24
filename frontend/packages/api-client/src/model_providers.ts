/** Model provider discovery API client operations. */

import type { ModelProviderDiscoveryResponse } from "@ava/contracts";

import { ApiClient } from "./client";

export async function getModelProviders(
  client: ApiClient,
): Promise<ModelProviderDiscoveryResponse> {
  const response = await client.request("/model-providers");
  return (await response.json()) as ModelProviderDiscoveryResponse;
}