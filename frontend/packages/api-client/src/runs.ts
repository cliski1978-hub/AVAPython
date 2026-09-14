/** Run-related API client operations.
 *
 * These operations speak only to the AVA HTTP run endpoints and return
 * AVA-owned contracts (@ava/contracts). No provider-specific behavior lives
 * here.
 */

import type { RunEvent, RunRequest, RunResponse } from "@ava/contracts";

import { ApiClient } from "./client";

function runPath(runId: string): string {
  return `/runs/${encodeURIComponent(runId)}`;
}

/** Start an AVA run with the submitted prompt (POST /runs). */
export async function startRun(
  client: ApiClient,
  request: RunRequest,
): Promise<RunResponse> {
  const response = await client.request("/runs", {
    method: "POST",
    body: JSON.stringify(request),
  });
  return (await response.json()) as RunResponse;
}

/** Retrieve the stored snapshot for a run (GET /runs/{run_id}). */
export async function getRun(
  client: ApiClient,
  runId: string,
): Promise<RunResponse> {
  const response = await client.request(runPath(runId));
  return (await response.json()) as RunResponse;
}

/** Retrieve a run's normalized events in append order (GET /runs/{run_id}/events). */
export async function getRunEvents(
  client: ApiClient,
  runId: string,
): Promise<RunEvent[]> {
  const response = await client.request(`${runPath(runId)}/events`);
  return (await response.json()) as RunEvent[];
}

/** Cancel an AVA run (POST /runs/{run_id}/cancel). */
export async function cancelRun(
  client: ApiClient,
  runId: string,
): Promise<RunResponse> {
  const response = await client.request(`${runPath(runId)}/cancel`, {
    method: "POST",
  });
  return (await response.json()) as RunResponse;
}