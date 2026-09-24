import type { ExecutionProfileDiscoveryResponse } from "@ava/contracts";
import { ApiClient } from "./client";
export async function getExecutionProfiles(client: ApiClient): Promise<ExecutionProfileDiscoveryResponse> {
  const response = await client.request("/execution-profiles");
  return (await response.json()) as ExecutionProfileDiscoveryResponse;
}
