/** Provider-neutral AVA run event interpretation.
 *
 * The UI understands AVA ``EventType`` values, never concrete adapter or
 * provider behavior. Logic like "if agent == mock" or
 * "if content starts with 'AVA mock agent'" is forbidden here and upstream.
 */

import type { JsonValue, RunEvent, RunStatus } from "@ava/contracts";

import type { MessageStatus, UIRunPhase } from "../types";
import { presentRunFailure } from "../lib/errorPresentation";

/** Backend statuses the UI drives from events. */
export type UIRunStatus = "running" | "completed" | "cancelled" | "failed";

export type RunEventEffect =
  | { kind: "setBackendStatus"; backendStatus: UIRunStatus }
  | { kind: "setPhase"; phase: UIRunPhase }
  | { kind: "setMessageStatus"; messageStatus: MessageStatus }
  | { kind: "setMessageError"; error: string; errorCode?: string }
  | { kind: "setMessageContent"; messageId: string | null; content: string }
  | { kind: "associateMessage"; messageId: string }
  | { kind: "ignore" };

/** Extract a string field from an event payload, tolerating any JsonValue. */
export function payloadString(
  payload: Record<string, JsonValue>,
  key: string,
): string {
  const value = payload[key];
  return typeof value === "string" ? value : "";
}

/** Map a single AVA RunEvent to zero or more state effects.
 *
 * Unknown-but-valid AVA event types (tool events, approvals, document
 * events, future events) are ignored safely rather than crashing.
 */
export function applyRunEvent(event: RunEvent): RunEventEffect[] {
  switch (event.event_type) {
    case "run_started":
      return [
        { kind: "setPhase", phase: "running" },
        { kind: "setBackendStatus", backendStatus: "running" },
        { kind: "setMessageStatus", messageStatus: "streaming" },
      ];
    case "message_started":
      return [
        { kind: "associateMessage", messageId: payloadString(event.payload, "message_id") },
      ];
    case "message_content":
      return [{
        kind: "setMessageContent",
        messageId: payloadString(event.payload, "message_id") || null,
        content: payloadString(event.payload, "content"),
      }];
    case "run_completed":
      return [
        { kind: "setPhase", phase: "completed" },
        { kind: "setBackendStatus", backendStatus: "completed" },
        { kind: "setMessageStatus", messageStatus: "complete" },
      ];
    case "run_cancelled":
      return [
        { kind: "setPhase", phase: "cancelled" },
        { kind: "setBackendStatus", backendStatus: "cancelled" },
        { kind: "setMessageStatus", messageStatus: "cancelled" },
      ];
    case "run_failed":
      return [
        { kind: "setPhase", phase: "failed" },
        { kind: "setBackendStatus", backendStatus: "failed" },
        { kind: "setMessageStatus", messageStatus: "failed" },
        { kind: "setMessageError", error: presentRunFailure(event.payload), errorCode: payloadString(event.payload, "error_code") || undefined },
      ];
    default:
      return [{ kind: "ignore" }];
  }
}

/** Map a backend RunStatus to a UI message status (used for fallbacks). */
export function messageStatusForRunStatus(status: RunStatus): MessageStatus {
  switch (status) {
    case "completed":
      return "complete";
    case "cancelled":
      return "cancelled";
    case "failed":
      return "failed";
    default:
      return "pending";
  }
}

/** Map a backend RunStatus to a UI phase (used for fallbacks). */
export function uiPhaseForBackendStatus(status: RunStatus): UIRunPhase {
  switch (status) {
    case "completed":
      return "completed";
    case "cancelled":
      return "cancelled";
    case "failed":
      return "failed";
    default:
      return "running";
  }
}
