/** Health-related API client operations. */

import type { HealthResponse } from "@ava/contracts";

import { ApiClient } from "./client";

export async function getHealth(client: ApiClient): Promise<HealthResponse> {
  const response = await client.request("/health");
  return (await response.json()) as HealthResponse;
}
