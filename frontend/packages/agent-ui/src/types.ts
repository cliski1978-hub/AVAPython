import type { RunStatus } from "@ava/contracts";

export type MessageRole = "user" | "assistant" | "system";

export type MessageStatus = "pending" | "complete" | "failed" | "cancelled";

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
   * User-readable failure detail for failed assistant messages. Never raw
   * payloads, stack traces, or HTTP bodies.
   */
  error?: string;
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
  /** Frontend-only phase driving the composer and message UI. */
  uiPhase: UIRunPhase;
  /** User-readable error from the most recent transport/API failure. */
  runError: string | null;
  /** Stable id of the pending assistant message created for this run. */
  pendingMessageId: string | null;
}

export const EMPTY_CONVERSATION_RUN: ConversationRunState = {
  runId: null,
  backendStatus: null,
  uiPhase: "idle",
  runError: null,
  pendingMessageId: null,
};

export interface Conversation {
  id: string;
  title: string;
  messages: ConversationMessage[];
  /** Run lifecycle state for the most recent run started in this conversation. */
  run?: ConversationRunState;
  createdAt?: string;
}