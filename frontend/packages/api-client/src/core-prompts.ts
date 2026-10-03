import type {
  CorePrompt,
  CorePromptListResponse,
  CreateCorePromptRequest,
  SetCorePromptEnabledRequest,
  UpdateCorePromptRequest,
  CorePromptAssignment,
  CorePromptAssignmentListResponse,
  CorePromptScopeType,
  SetCorePromptAssignmentRequest,
  ResolveCorePromptsRequest,
  EffectivePromptSet,
} from "@ava/contracts";
import { ApiClient } from "./client";

const path = (corePromptId: string) => `/core-prompts/${encodeURIComponent(corePromptId)}`;

export async function listCorePrompts(client: ApiClient): Promise<CorePromptListResponse> {
  return (await client.request("/core-prompts")).json();
}

export async function getCorePrompt(client: ApiClient, corePromptId: string): Promise<CorePrompt> {
  return (await client.request(path(corePromptId))).json();
}

export async function createCorePrompt(client: ApiClient, request: CreateCorePromptRequest): Promise<CorePrompt> {
  return (await client.request("/core-prompts", { method: "POST", body: JSON.stringify(request) })).json();
}

export async function updateCorePrompt(
  client: ApiClient,
  corePromptId: string,
  request: UpdateCorePromptRequest,
): Promise<CorePrompt> {
  return (await client.request(path(corePromptId), { method: "PATCH", body: JSON.stringify(request) })).json();
}

export async function setCorePromptEnabled(
  client: ApiClient,
  corePromptId: string,
  request: SetCorePromptEnabledRequest,
): Promise<CorePrompt> {
  return (await client.request(`${path(corePromptId)}/enabled`, {
    method: "PATCH",
    body: JSON.stringify(request),
  })).json();
}

export async function deleteCorePrompt(client: ApiClient, corePromptId: string): Promise<void> {
  await client.request(path(corePromptId), { method: "DELETE" });
}

export async function listCorePromptAssignments(client: ApiClient, corePromptId: string): Promise<CorePromptAssignmentListResponse> {
  return (await client.request(`${path(corePromptId)}/assignments`)).json();
}

export async function setCorePromptAssignment(client: ApiClient, corePromptId: string,
                                              request: SetCorePromptAssignmentRequest): Promise<CorePromptAssignment> {
  return (await client.request(`${path(corePromptId)}/assignments`, {
    method: "PUT", body: JSON.stringify(request),
  })).json();
}

export async function listCorePromptAssignmentsForScope(client: ApiClient, scopeType: CorePromptScopeType,
                                                        scopeId: string | null): Promise<CorePromptAssignmentListResponse> {
  const query = new URLSearchParams({ scope_type: scopeType });
  if (scopeId !== null) query.set("scope_id", scopeId);
  return (await client.request(`/core-prompt-assignments?${query.toString()}`)).json();
}

export async function resolveCorePrompts(
  client: ApiClient,
  request: ResolveCorePromptsRequest,
): Promise<EffectivePromptSet> {
  return (await client.request("/core-prompts/resolve", {
    method: "POST",
    body: JSON.stringify(request),
  })).json();
}
