import type { ToolFeaturesResponse, UpdateToolFeaturesRequest } from "@ava/contracts";
import type { ApiClient } from "./client";

export async function getToolFeatures(client: ApiClient): Promise<ToolFeaturesResponse> {
  return (await client.request("/settings/tool-features")).json();
}
export async function updateToolFeatures(client: ApiClient, request: UpdateToolFeaturesRequest): Promise<ToolFeaturesResponse> {
  return (await client.request("/settings/tool-features", {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(request),
  })).json();
}
