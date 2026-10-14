/** AVA event contracts.
 *
 * Every run event shares this common envelope so clients can handle all
 * event types uniformly.
 */

import type { JsonValue } from "./json_types";
import type { ContractVersion } from "./version";

export type EventType =
  | "run_started"
  | "run_cancel_requested"
  | "message_started"
  | "message_content"
  | "tool_started"
  | "tool_progress"
  | "tool_completed"
  | "tool_requested"
  | "tool_rejected"
  | "tool_outcome"
  | "approval_requested"
  | "document_change_proposed"
  | "artifact_created"
  | "run_completed"
  | "run_cancelled"
  | "run_failed";

export interface RunEvent {
  event_id: string;
  run_id: string;
  /** Stable monotonic order within a run when supplied by event persistence. */
  sequence?: number;
  event_type: EventType;
  timestamp: string;
  payload: Record<string, JsonValue>;
  contract_version: ContractVersion;
}
