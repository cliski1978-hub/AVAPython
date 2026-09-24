/** Workspace discovery API client operations. */

import type { WorkspaceDiscoveryResponse } from "@ava/contracts";

import { ApiClient } from "./client";

export async function getWorkspaces(
  client: ApiClient,
): Promise<WorkspaceDiscoveryResponse> {
  const response = await client.request("/workspaces");
  return (await response.json()) as WorkspaceDiscoveryResponse;
}