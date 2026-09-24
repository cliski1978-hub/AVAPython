/** Model catalog discovery API client operations. */

import type { ModelDiscoveryResponse } from "@ava/contracts";

import { ApiClient } from "./client";

export async function getModels(client: ApiClient): Promise<ModelDiscoveryResponse> {
  const response = await client.request("/models");
  return (await response.json()) as ModelDiscoveryResponse;
}
