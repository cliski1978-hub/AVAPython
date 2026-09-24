import type { RuntimeDiscoveryResponse } from "@ava/contracts";
import { ApiClient } from "./client";

export async function getRuntimes(client: ApiClient): Promise<RuntimeDiscoveryResponse> {
  const response = await client.request("/runtimes");
  return (await response.json()) as RuntimeDiscoveryResponse;
}
