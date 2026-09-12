/** Capability-related API client operations. */

import type { CapabilitiesResponse } from "@ava/contracts";

import { ApiClient } from "./client";

export async function getCapabilities(client: ApiClient): Promise<CapabilitiesResponse> {
  const response = await client.request("/capabilities");
  return (await response.json()) as CapabilitiesResponse;
}