import type {
  ApplicationExecutionDefaultsState,
  CreateModelConfigurationRequest,
  CreateProviderConnectionRequest,
  CreateRuntimeConfigurationRequest,
  ModelConfigurationListResponse,
  ModelConfigurationResponse,
  ProviderConnectionListResponse,
  ProviderConnectionResponse,
  RuntimeConfigurationListResponse,
  RuntimeConfigurationResponse,
  SetApplicationExecutionDefaultsRequest,
  UpdateModelConfigurationRequest,
  UpdateProviderConnectionRequest,
  UpdateRuntimeConfigurationRequest,
} from "@ava/contracts";

import { ApiClient } from "./client";

/**
 * Thin transport wrappers for the persisted Settings API (`/settings/*`).
 *
 * These are configuration calls, not discovery: `/model-providers`, `/models`,
 * and `/runtimes` continue to report what is currently available. No
 * credential is ever sent or received here — a `credential_reference` names a
 * location, and a client can neither read nor write resolved secret material.
 */

const providerPath = (id: string) => `/settings/providers/${encodeURIComponent(id)}`;
const modelPath = (id: string) => `/settings/models/${encodeURIComponent(id)}`;
const runtimePath = (id: string) => `/settings/runtimes/${encodeURIComponent(id)}`;

const json = (body: unknown): RequestInit => ({ body: JSON.stringify(body) });

// ============================================================
// Provider connections
// ============================================================

export async function listProviderConnections(
  client: ApiClient,
): Promise<ProviderConnectionListResponse> {
  return (await client.request("/settings/providers")).json();
}

export async function getProviderConnection(
  client: ApiClient,
  providerConnectionId: string,
): Promise<ProviderConnectionResponse> {
  return (await client.request(providerPath(providerConnectionId))).json();
}

export async function createProviderConnection(
  client: ApiClient,
  request: CreateProviderConnectionRequest,
): Promise<ProviderConnectionResponse> {
  return (await client.request("/settings/providers", { method: "POST", ...json(request) })).json();
}

export async function updateProviderConnection(
  client: ApiClient,
  providerConnectionId: string,
  request: UpdateProviderConnectionRequest,
): Promise<ProviderConnectionResponse> {
  return (
    await client.request(providerPath(providerConnectionId), { method: "PUT", ...json(request) })
  ).json();
}

// ============================================================
// Model configurations
// ============================================================

export async function listModelConfigurations(
  client: ApiClient,
): Promise<ModelConfigurationListResponse> {
  return (await client.request("/settings/models")).json();
}

export async function getModelConfiguration(
  client: ApiClient,
  modelId: string,
): Promise<ModelConfigurationResponse> {
  return (await client.request(modelPath(modelId))).json();
}

export async function createModelConfiguration(
  client: ApiClient,
  request: CreateModelConfigurationRequest,
): Promise<ModelConfigurationResponse> {
  return (await client.request("/settings/models", { method: "POST", ...json(request) })).json();
}

export async function updateModelConfiguration(
  client: ApiClient,
  modelId: string,
  request: UpdateModelConfigurationRequest,
): Promise<ModelConfigurationResponse> {
  return (await client.request(modelPath(modelId), { method: "PUT", ...json(request) })).json();
}

// ============================================================
// Runtime configurations
// ============================================================

export async function listRuntimeConfigurations(
  client: ApiClient,
): Promise<RuntimeConfigurationListResponse> {
  return (await client.request("/settings/runtimes")).json();
}

export async function getRuntimeConfiguration(
  client: ApiClient,
  runtimeConfigurationId: string,
): Promise<RuntimeConfigurationResponse> {
  return (await client.request(runtimePath(runtimeConfigurationId))).json();
}

export async function createRuntimeConfiguration(
  client: ApiClient,
  request: CreateRuntimeConfigurationRequest,
): Promise<RuntimeConfigurationResponse> {
  return (await client.request("/settings/runtimes", { method: "POST", ...json(request) })).json();
}

export async function updateRuntimeConfiguration(
  client: ApiClient,
  runtimeConfigurationId: string,
  request: UpdateRuntimeConfigurationRequest,
): Promise<RuntimeConfigurationResponse> {
  return (
    await client.request(runtimePath(runtimeConfigurationId), { method: "PUT", ...json(request) })
  ).json();
}

// ============================================================
// Application execution defaults
// ============================================================

export async function getExecutionDefaults(
  client: ApiClient,
): Promise<ApplicationExecutionDefaultsState> {
  return (await client.request("/settings/defaults")).json();
}

export async function setExecutionDefaults(
  client: ApiClient,
  request: SetApplicationExecutionDefaultsRequest,
): Promise<ApplicationExecutionDefaultsState> {
  return (await client.request("/settings/defaults", { method: "PUT", ...json(request) })).json();
}
