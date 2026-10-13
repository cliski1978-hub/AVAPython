import type { CreateWorkspaceAccessRequest, UpdateWorkspaceAccessRequest, WorkspaceAccessResponse } from "@ava/contracts";
import type { ApiClient } from "./client";

const json = (body: unknown) => ({ body: JSON.stringify(body) });
export async function getWorkspaceAccess(client: ApiClient): Promise<WorkspaceAccessResponse> {
  return (await client.request("/settings/workspace-access")).json();
}
export async function createWorkspaceAccess(client: ApiClient, request: CreateWorkspaceAccessRequest): Promise<WorkspaceAccessResponse> {
  return (await client.request("/settings/workspace-access", { method: "POST", ...json(request) })).json();
}
export async function updateWorkspaceAccess(client: ApiClient, id: string, request: UpdateWorkspaceAccessRequest): Promise<WorkspaceAccessResponse> {
  return (await client.request(`/settings/workspace-access/${encodeURIComponent(id)}`, { method: "PUT", ...json(request) })).json();
}
