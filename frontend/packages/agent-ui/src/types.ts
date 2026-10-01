import type { RunStatus } from "@ava/contracts";

export type MessageRole = "user" | "assistant" | "system";

export type MessageStatus = "pending" | "streaming" | "complete" | "failed" | "cancelled";

export interface ConversationMessage {
  id: string;
  role: MessageRole;
  content: string;
  /**
   * Present for assistant (and future agent) messages. User and system
   * messages do not carry a generation status.
   */
  status?: MessageStatus;
  /**
   * Stable id of the user message this assistant message responds to. Set
   * when a run creates the assistant message so retry/regenerate can reuse
   * the original prompt without re-adding a user message or guessing the
   * previous array element.
   */
  sourceUserMessageId?: string;
  /**
   * Durable run that produced this assistant response. This comes directly
   * from the conversation snapshot; it is never inferred from message order
   * or content. It lets a fresh frontend session recover an active observer.
   */
  sourceRunId?: string | null;
  /**
   * User-readable failure detail for failed assistant messages. Never raw
   * payloads, stack traces, or HTTP bodies.
   */
  error?: string;
  /** Stable normalized failure code projected from the durable run event. */
  errorCode?: string;
  createdAt?: string;
}

/**
 * Frontend-only run phase. Mirrors what the UI shows and what actions are
 * enabled; distinct from the backend {@link RunStatus}, which is tracked
 * separately as {@link ConversationRunState.backendStatus}.
 */
export type UIRunPhase =
  | "idle"
  | "starting"
  | "running"
  | "stopping"
  | "completed"
  | "failed"
  | "cancelled";

/** Per-conversation run bookkeeping (frontend-owned, not a backend contract). */
export interface ConversationRunState {
  /** Backend run identifier assigned after POST /runs succeeds. */
  runId: string | null;
  /** Latest AVA run status observed. Null before a run exists. */
  backendStatus: RunStatus | null;
  /** Last observed durable cancellation intent; never a terminal outcome. */
  cancellationRequestedAt?: string | null;
  /** Frontend-only phase driving the composer and message UI. */
  uiPhase: UIRunPhase;
  /** User-readable error from the most recent transport/API failure. */
  runError: string | null;
  /** Stable id of the pending assistant message created for this run. */
  pendingMessageId: string | null;
  /**
   * Monotonic identity of the most recent run started in this conversation.
   * Assigned synchronously when a run starts (before any await) so a stale
   * run that completes late can detect it has been superseded and must not
   * overwrite newer state or persist its (older) assistant response.
   */
  runEpoch: string | null;
}

export const EMPTY_CONVERSATION_RUN: ConversationRunState = {
  runId: null,
  backendStatus: null,
  uiPhase: "idle",
  runError: null,
  pendingMessageId: null,
  runEpoch: null,
};

export interface Conversation {
  id: string;
  title: string;
  messages: ConversationMessage[];
  /** Run lifecycle state for the most recent run started in this conversation. */
  run?: ConversationRunState;
  createdAt?: string;
}
