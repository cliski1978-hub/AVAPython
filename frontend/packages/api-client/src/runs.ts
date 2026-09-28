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
  afterSequence = 0,
): Promise<RunEvent[]> {
  if (!Number.isInteger(afterSequence) || afterSequence < 0) {
    throw new RangeError("afterSequence must be a non-negative integer.");
  }
  const cursor = afterSequence === 0 ? "" : `?after_sequence=${afterSequence}`;
  const response = await client.request(`${runPath(runId)}/events${cursor}`);
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

/** A parsed AVA SSE event; the envelope is the persisted RunEvent contract. */
export type RunStreamEvent = RunEvent & { sequence: number };

export class RunStreamProtocolError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "RunStreamProtocolError";
  }
}

/**
 * Consume the SSE observation stream for one run.
 *
 * Aborting unsubscribes only this HTTP request. It never calls the cancel API,
 * and a normal network close resolves without inventing a terminal outcome.
 */
export async function streamRun(
  client: ApiClient,
  runId: string,
  options: {
    signal?: AbortSignal;
    /** Exclusive persisted cursor. Omitted preserves a full-history stream. */
    afterSequence?: number;
    onEvent(event: RunStreamEvent): void | Promise<void>;
  },
): Promise<void> {
  const afterSequence = options.afterSequence ?? 0;
  if (!Number.isInteger(afterSequence) || afterSequence < 0) {
    throw new RangeError("afterSequence must be a non-negative integer.");
  }
  const cursor = afterSequence === 0 ? "" : `?after_sequence=${afterSequence}`;
  const response = await client.stream(`${runPath(runId)}/stream${cursor}`, options.signal);
  if (!response.headers.get("content-type")?.startsWith("text/event-stream")) {
    throw new RunStreamProtocolError("Run stream did not return event-stream content.");
  }
  if (response.body == null) {
    throw new RunStreamProtocolError("Run stream has no readable body.");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let pending = "";
  try {
    while (true) {
      const next = await reader.read();
      if (next.done) break;
      pending += decoder.decode(next.value, { stream: true });
      const frames = pending.split("\n\n");
      pending = frames.pop() ?? "";
      for (const frame of frames) {
        const event = parseRunStreamFrame(frame);
        if (event != null) await options.onEvent(event);
      }
    }
    pending += decoder.decode();
    if (pending.trim() !== "") {
      const event = parseRunStreamFrame(pending);
      if (event != null) await options.onEvent(event);
    }
  } finally {
    reader.releaseLock();
  }
}

function parseRunStreamFrame(frame: string): RunStreamEvent | null {
  if (frame.startsWith(":")) return null;
  const fields = new Map<string, string>();
  for (const line of frame.split("\n")) {
    const separator = line.indexOf(":");
    if (separator === -1) continue;
    fields.set(line.slice(0, separator), line.slice(separator + 1).trimStart());
  }
  const data = fields.get("data");
  if (data == null) return null;
  let value: unknown;
  try {
    value = JSON.parse(data);
  } catch {
    throw new RunStreamProtocolError("Run stream contained malformed JSON.");
  }
  if (!isRunStreamEvent(value)) {
    throw new RunStreamProtocolError("Run stream contained an invalid AVA event envelope.");
  }
  if (fields.get("id") !== value.event_id || fields.get("event") !== value.event_type) {
    throw new RunStreamProtocolError("Run stream framing does not match its AVA envelope.");
  }
  return value;
}

function isRunStreamEvent(value: unknown): value is RunStreamEvent {
  if (value == null || typeof value !== "object") return false;
  const event = value as Partial<RunStreamEvent>;
  return typeof event.event_id === "string"
    && typeof event.run_id === "string"
    && typeof event.sequence === "number"
    && typeof event.event_type === "string"
    && typeof event.timestamp === "string"
    && event.payload != null
    && typeof event.payload === "object"
    && typeof event.contract_version === "string";
}
