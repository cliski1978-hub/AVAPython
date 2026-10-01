import type { MessageStatus, UIRunPhase } from "../types";

/**
 * Phase 5.31 attempt policy.
 *
 * Retry and regenerate are two user intents, not two names for one operation:
 *
 *   Retry      = a new run for the same source user message after an attempt
 *                that produced no usable response
 *   Regenerate = a new run for the same source user message after an attempt
 *                that succeeded
 *
 * Both create a new run with a new assistant response. Neither reuses, clears,
 * or re-keys the prior response, and neither resumes the prior run. The mirrors
 * of `RETRYABLE_RUN_STATUSES` / `REGENERATABLE_RUN_STATUSES` in the backend's
 * `ava.contracts.attempts`; the two vocabularies are deliberately narrow and
 * disjoint so the two buttons can never mean the same thing.
 *
 * The split is made on the *projected* assistant status, which is derived from
 * the authoritative run, so this policy never needs the run id to decide.
 */

/** Prior response statuses a retry may branch from. */
export const RETRYABLE_RESPONSE_STATUSES: ReadonlySet<MessageStatus> = new Set<MessageStatus>([
  "failed",
  "cancelled",
]);

/** Prior response statuses a regenerate may branch from. */
export const REGENERATABLE_RESPONSE_STATUSES: ReadonlySet<MessageStatus> = new Set<MessageStatus>([
  "complete",
]);

/**
 * Conversation phases during which a run owns the conversation. A retry or
 * regenerate started in one of these phases would race the run already in
 * flight, so both the provider and the action buttons refuse them.
 */
export const ACTIVE_RUN_PHASES: readonly UIRunPhase[] = ["starting", "running", "stopping"];

/** Whether a prior assistant response may be retried. */
export function canRetryResponse(status: MessageStatus): boolean {
  return RETRYABLE_RESPONSE_STATUSES.has(status);
}

/** Whether a completed assistant response may be regenerated. */
export function canRegenerateResponse(status: MessageStatus): boolean {
  return REGENERATABLE_RESPONSE_STATUSES.has(status);
}

/** Whether a run currently owns its conversation, blocking new attempts. */
export function isActiveRunPhase(phase: UIRunPhase | undefined): boolean {
  return phase != null && ACTIVE_RUN_PHASES.includes(phase);
}
