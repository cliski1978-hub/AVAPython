/** Frontend run orchestration.
 *
 * Provider-neutral: this module talks to an injected ``RunAgent`` (wrapping
 * @ava/api-client), drives the conversation through injected ``RunCommands``,
 * and interprets results purely in terms of AVA events. Keeping this logic
 * free of React makes the whole loop unit-testable.
 *
 * Message and conversation association is captured once, up front, with
 * stable identifiers — a late completion always updates the conversation and
 * assistant message that started the run, regardless of which conversation is
 * active at completion time.
 */

import type {
  RunEvent,
  RunRequest,
  RunResponse,
} from "@ava/contracts";
import {
  cancelRun,
  getRun,
  getRunEvents,
  listMessages,
  startRun,
  streamRun,
  type ApiClient,
} from "@ava/api-client";

import type { ConversationRunState } from "../types";
import {
  createEntityId,
  type MessagePatch,
} from "../state/conversationReducer";
import {
  applyRunEvent,
  messageStatusForRunStatus,
  uiPhaseForBackendStatus,
} from "./runEventProcessor";
import { observeRunWithResume } from "./runStreamResume";
import { presentAvaError } from "../lib/errorPresentation";
import { ACTIVE_RUN_STATUSES } from "../lib/runActions";
import { selectTranscriptMessages } from "../lib/transcript";
import type { Conversation } from "../types";

/** Minimal backend client surface the orchestrator depends on. */
export interface RunAgent {
  startRun(request: RunRequest): Promise<RunResponse>;
  getRunEvents(runId: string): Promise<RunEvent[]>;
  getRun?(runId: string): Promise<RunResponse>;
  listMessages?(conversationId: string): Promise<{
    messages: Array<{ message_id: string; content: string }>;
  }>;
  streamRun(
    runId: string,
    options: {
      signal?: AbortSignal;
      afterSequence?: number;
      onEvent(event: RunEvent): void | Promise<void>;
    },
  ): Promise<void>;
  cancelRun(runId: string): Promise<RunResponse>;
}

/** Adapt the shared @ava/api-client to the run agent surface. */
export function clientRunAgent(client: ApiClient): RunAgent {
  return {
    startRun: (request) => startRun(client, request),
    getRunEvents: (runId) => getRunEvents(client, runId),
    getRun: (runId) => getRun(client, runId),
    listMessages: (conversationId) => listMessages(client, conversationId),
    streamRun: (runId, options) => streamRun(client, runId, options),
    cancelRun: (runId) => cancelRun(client, runId),
  };
}

/** State operations the orchestrator drives. */
export interface RunCommands {
  addUserMessage(
    conversationId: string | null,
    content: string,
  ): { conversationId: string; messageId: string } | Promise<{ conversationId: string; messageId: string }>;
  addAssistantMessage(
    conversationId: string,
    messageId: string,
    sourceUserMessageId: string | null,
    sourceRunId?: string | null,
  ): void;
  setRunState(conversationId: string, update: Partial<ConversationRunState>): void;
  updateMessage(
    conversationId: string,
    messageId: string,
    patch: MessagePatch,
  ): void;
  /** Removes a local optimistic placeholder when no durable run was created. */
  removeMessage?(conversationId: string, messageId: string): void;
  associateAssistantMessage?(
    conversationId: string,
    placeholderId: string,
    messageId: string,
  ): void;
  persistAssistantMessage?(
    conversationId: string,
    placeholderId: string,
    message: { content: string; sourceUserMessageId?: string | null },
  ): Promise<void>;
  /**
   * Read the current run state of a conversation. Used to detect stale
   * completions: a run whose epoch is no longer the conversation's current
   * one was superseded by a newer run and must not write state or persist.
   * Optional so provider-less callers (static rendering) can omit it.
   */
  getRunState?(conversationId: string): ConversationRunState | null;
}

/** Run commands used when applying events (subset used after run start). */
export type RunEventCommands = Pick<
  RunCommands,
  | "setRunState"
  | "updateMessage"
  | "removeMessage"
  | "getRunState"
  | "associateAssistantMessage"
  // A retry or regenerate appends the new attempt's assistant response once the
  // backend has accepted the run, so it needs the same creation command a first
  // submission uses rather than a second, weaker one.
  | "addAssistantMessage"
>;

/**
 * Observer ownership for one conversation's run.
 *
 * Ownership is claimed per conversation and released when that run's
 * observation loop settles, so a run keeps its observer after the user selects
 * another conversation while a later run can always take ownership again.
 */
export interface RunStreamHandle {
  signal: AbortSignal;
  /** Releases observer ownership. Never touches backend run lifecycle. */
  release(): void;
}

export type AcquireRunStream = (conversationId: string) => RunStreamHandle;

/**
 * Finds the one assistant response that is visible under the existing
 * transcript projection and can therefore own refresh recovery. This is
 * deliberately conversation-scoped: hidden regenerated answers are never
 * candidates, and no global run scan is involved.
 */
export function visibleRecoveryCandidate(conversation: Conversation): {
  assistantMessageId: string;
  sourceRunId: string;
  sourceUserMessageId: string | null;
  durableContent: string;
} | null {
  const visible = selectTranscriptMessages(conversation.messages);
  const assistant = [...visible].reverse().find(
    (message) => message.role === "assistant" && message.sourceRunId != null,
  );
  if (assistant == null || assistant.sourceRunId == null) return null;
  return {
    assistantMessageId: assistant.id,
    sourceRunId: assistant.sourceRunId,
    sourceUserMessageId: assistant.sourceUserMessageId ?? null,
    durableContent: assistant.content,
  };
}

/**
 * Rebuild local observer ownership after a frontend refresh. All inputs are
 * durable snapshots; this function never creates a run or a message.
 */
export async function recoverRunForConversation(options: {
  conversation: Conversation;
  agent: RunAgent;
  commands: RunEventCommands;
  acquireRunStream?: AcquireRunStream;
}): Promise<boolean> {
  const candidate = visibleRecoveryCandidate(options.conversation);
  if (candidate == null || options.agent.getRun == null) return false;

  const snapshot = await options.agent.getRun(candidate.sourceRunId);
  if (
    snapshot.assistant_message_id !== candidate.assistantMessageId
    || !ACTIVE_RUN_STATUSES.has(snapshot.status)
  ) {
    return false;
  }

  const stream = options.acquireRunStream?.(options.conversation.id);

  // A refresh starts a new frontend session. Epoch is intentionally new and
  // local; the durable ids above remain the ownership authority.
  const runEpoch = createEntityId();
  options.commands.setRunState(options.conversation.id, {
    runEpoch,
    runId: snapshot.run_id,
    backendStatus: snapshot.status,
    cancellationRequestedAt: snapshot.cancellation_requested_at ?? null,
    uiPhase: uiPhaseForBackendStatus(snapshot.status),
    runError: null,
    pendingMessageId: candidate.assistantMessageId,
  });
  options.commands.updateMessage(options.conversation.id, candidate.assistantMessageId, {
    status: messageStatusForRunStatus(snapshot.status),
  });

  // The conversation snapshot is the durable current-content authority. The
  // replay starts at zero to rebuild event identity/cursor state, but older
  // full-content facts must not roll this rendered snapshot backwards.
  let bootstrapContent: string | null = candidate.durableContent;
  try {
    await observeRunWithResume({
      agent: options.agent,
      runId: snapshot.run_id,
      signal: stream?.signal,
    isCurrent: () => isRunCurrent(options.commands, options.conversation.id, runEpoch),
    applyEvent: async (event) => {
      if (
        event.run_id !== snapshot.run_id
        || (event.event_type === "message_content"
          && event.payload.message_id != null
          && event.payload.message_id !== candidate.assistantMessageId)
      ) {
        throw new Error("Run stream event does not own the recovered assistant message.");
      }
      if (event.event_type === "message_content" && bootstrapContent != null) {
        const content = event.payload.content;
        if (typeof content === "string" && !content.startsWith(bootstrapContent)) {
          // Historical snapshot: consume it for the cursor, but retain the
          // newer durable message snapshot already rendered at bootstrap.
          return;
        }
        bootstrapContent = null;
      }
      if (
        bootstrapContent != null
        && event.event_type !== "run_completed"
        && event.event_type !== "run_failed"
        && event.event_type !== "run_cancelled"
      ) {
        // Current RunResponse already projects lifecycle state. Historical
        // run_started/message_started facts only rebuild transport state.
        return;
      }
      await applyRunEvents([event], options.conversation.id, candidate.assistantMessageId, options.commands, {
        sourceUserMessageId: candidate.sourceUserMessageId,
        runEpoch,
        assistantResponseIsDurable: true,
      });
    },
    reconcileSnapshot: async () => {
      const current = await options.agent.getRun?.(snapshot.run_id);
      if (current == null || !isRunCurrent(options.commands, options.conversation.id, runEpoch)) return false;
      options.commands.setRunState(options.conversation.id, {
        backendStatus: current.status,
        cancellationRequestedAt: current.cancellation_requested_at ?? null,
        uiPhase: uiPhaseForBackendStatus(current.status),
      });
      if (current.assistant_message_id != null && options.agent.listMessages != null) {
        const messages = await options.agent.listMessages(options.conversation.id);
        const message = messages.messages.find(({ message_id }) => message_id === current.assistant_message_id);
        if (message != null) {
          options.commands.updateMessage(options.conversation.id, candidate.assistantMessageId, {
            content: message.content,
            status: messageStatusForRunStatus(current.status),
          });
        }
      }
      return !ACTIVE_RUN_STATUSES.has(current.status);
    },
    onExhausted: (error) => {
      if (!isRunCurrent(options.commands, options.conversation.id, runEpoch)) return;
      options.commands.setRunState(options.conversation.id, {
        runError: runErrorMessage(error),
      });
    },
  });
  } finally {
    stream?.release();
  }
  return true;
}

/** Map an unknown failure to a user-readable message (never raw payloads). */
export function runErrorMessage(error: unknown): string {
  return presentAvaError(error, "Connection to AVA was interrupted.");
}

/**
 * True when the given run epoch is still the conversation's current run.
 *
 * Identity is the run epoch captured when the run STARTED (a fresh id set
 * synchronously before any await), never message text or ordering heuristics.
 * A run with no recorded epoch check available (no ``getRunState`` reader)
 * is treated as current, preserving provider-less/static usage.
 */
function isRunCurrent(
  commands: Pick<RunCommands, "getRunState">,
  conversationId: string,
  runEpoch: string,
): boolean {
  const current = commands.getRunState?.(conversationId);
  if (current == null) return true;
  return current.runEpoch === runEpoch;
}

/**
 * Run a prompt into a conversation. Shared by first submission, retry, and
 * regenerate so the run path is identical for every run: one request, one
 * observe loop, one event application.
 *
 * `assistantMessageId` selects how the assistant response is bound locally:
 *
 *   an id      an optimistic local slot already exists and is reset to
 *              pending. Used by first submission, which shows its response
 *              immediately.
 *   `null`     the assistant message is created only once the backend has
 *              accepted the run, under the durable id it returned. Used by
 *              retry and regenerate, which must not touch the prior attempt's
 *              response at all: a failed creation then leaves the transcript
 *              exactly as it was, with no ghost bubble and no re-key.
 */
export async function startRunForPrompt(options: {
  conversationId: string;
  assistantMessageId: string | null;
  sourceUserMessageId: string | null;
  prompt: string;
  retryOfRunId?: string | null;
  execution?: RunRequest["execution"];
  workspaceId?: string | null;
  acquireRunStream?: AcquireRunStream;
  agent: RunAgent;
  commands: RunEventCommands;
  /** Let an initial composer submission restore its draft when creation fails. */
  rejectOnStartFailure?: boolean;
}): Promise<void> {
  const { agent, commands } = options;
  const reusesLocalSlot = options.assistantMessageId != null;

  // Observer ownership is claimed for THIS run's conversation before any await,
  // so a run keeps observing after the user selects a different conversation and
  // a later run in the same conversation can always supersede it.
  const stream = options.acquireRunStream?.(options.conversationId);

  // Epoch of THIS run, claimed synchronously before any await so a newer run
  // starting later supersedes it unambiguously (never by text or timestamps).
  const runEpoch = createEntityId();

  commands.setRunState(options.conversationId, {
    runEpoch,
    runId: null,
    backendStatus: null,
    cancellationRequestedAt: null,
    uiPhase: "starting",
    runError: null,
    pendingMessageId: options.assistantMessageId,
  });
  if (options.assistantMessageId != null) {
    commands.updateMessage(options.conversationId, options.assistantMessageId, {
      status: "pending",
      error: undefined,
    });
  }

  // Bound by the run once the backend has answered: the optimistic slot for a
  // first submission, or the durable response the new run just created.
  let assistantMessageId = options.assistantMessageId;

  try {
    const run = await agent.startRun({
      prompt: options.prompt,
      conversation_id: options.conversationId,
      ...(options.sourceUserMessageId ? { source_user_message_id: options.sourceUserMessageId } : {}),
      ...(options.retryOfRunId ? { retry_of_run_id: options.retryOfRunId } : {}),
      ...(options.execution ? { execution: options.execution } : {}),
      ...(options.workspaceId ? { workspace_id: options.workspaceId } : {}),
    });
    if (!isRunCurrent(commands, options.conversationId, runEpoch)) {
      // A newer run superseded this one while the backend call was in
      // flight. Nothing from this run may touch state or the transcript.
      return;
    }
    commands.setRunState(options.conversationId, {
      runId: run.run_id,
      backendStatus: run.status,
      cancellationRequestedAt: run.cancellation_requested_at ?? null,
    });

    const durableMessageId = run.assistant_message_id ?? assistantMessageId;
    if (reusesLocalSlot && assistantMessageId != null) {
      if (
        run.assistant_message_id != null &&
        run.assistant_message_id !== assistantMessageId
      ) {
        commands.associateAssistantMessage?.(
          options.conversationId,
          assistantMessageId,
          run.assistant_message_id,
        );
        commands.setRunState(options.conversationId, {
          pendingMessageId: run.assistant_message_id,
        });
      }
      // Record the run that owns this response so its lineage is available
      // without re-reading the conversation. Retry and regenerate branch from
      // it; the run id is never inferred from position or text. Keyed by the
      // durable id, which a re-key above has already taken over from the
      // optimistic slot.
      if (durableMessageId != null) {
        commands.updateMessage(options.conversationId, durableMessageId, {
          sourceRunId: run.run_id,
        });
      }
    } else if (run.assistant_message_id != null) {
      // A retry or regenerate never reuses the prior attempt's message. The new
      // response is appended after it, so the existing transcript projection
      // keeps the prior response as durable hidden history and shows this one.
      commands.addAssistantMessage(
        options.conversationId,
        run.assistant_message_id,
        options.sourceUserMessageId,
        run.run_id,
      );
      commands.setRunState(options.conversationId, {
        pendingMessageId: run.assistant_message_id,
      });
    }
    assistantMessageId = durableMessageId;

    await observeRunWithResume({
      agent,
      runId: run.run_id,
      signal: stream?.signal,
      isCurrent: () => isRunCurrent(commands, options.conversationId, runEpoch),
      applyEvent: async (event) => {
        if (
          event.run_id !== run.run_id
          || (event.event_type === "message_content"
            && event.payload.message_id != null
            && event.payload.message_id !== durableMessageId)
        ) {
          throw new Error("Run stream event does not own the active assistant message.");
        }
        await applyRunEvents([event], options.conversationId, durableMessageId, commands, {
          sourceUserMessageId: options.sourceUserMessageId,
          runEpoch,
          assistantResponseIsDurable: run.assistant_message_id != null,
        });
      },
      reconcileSnapshot: async () => {
        const snapshot = await agent.getRun?.(run.run_id);
        if (snapshot == null || !isRunCurrent(commands, options.conversationId, runEpoch)) return false;
        commands.setRunState(options.conversationId, {
          backendStatus: snapshot.status,
          cancellationRequestedAt: snapshot.cancellation_requested_at ?? null,
          uiPhase: uiPhaseForBackendStatus(snapshot.status),
        });
        if (snapshot.assistant_message_id != null && agent.listMessages != null) {
          const messages = await agent.listMessages(options.conversationId);
          const message = messages.messages.find(
            ({ message_id }) => message_id === snapshot.assistant_message_id,
          );
          if (message != null && durableMessageId != null) {
            commands.updateMessage(options.conversationId, durableMessageId, {
              content: message.content,
              status: messageStatusForRunStatus(snapshot.status),
            });
          }
        }
        return snapshot.status === "completed"
          || snapshot.status === "failed"
          || snapshot.status === "cancelled";
      },
      onExhausted: (error) => {
        if (!isRunCurrent(commands, options.conversationId, runEpoch)) return;
        commands.setRunState(options.conversationId, {
          runError: runErrorMessage(error),
        });
      },
    });
  } catch (error) {
    if (!isRunCurrent(commands, options.conversationId, runEpoch)) return;
    const message = runErrorMessage(error);
    commands.setRunState(options.conversationId, {
      backendStatus: null,
      uiPhase: "idle",
      runError: message,
      pendingMessageId: null,
    });
    // A rejected creation has no durable run and therefore cannot produce a
    // failed assistant response. Remove only the local optimistic shell; the
    // persisted user prompt remains available for the user to submit again.
    if (options.assistantMessageId != null) {
      commands.removeMessage?.(options.conversationId, options.assistantMessageId);
    }
    if (options.rejectOnStartFailure) throw error;
  } finally {
    // This run no longer observes, so its conversation may be recovered again.
    stream?.release();
  }
}

/**
 * Full prompt-submission flow.
 *
 * 1. The user message appears immediately (creating a conversation if none);
 *    its returned id is recorded on the pending assistant message so
 *    retry/regenerate can reuse this prompt without re-adding a message.
 * 2. A pending assistant message appears immediately.
 * 3. The backend run starts and its normalized events are applied in order.
 */
export async function submitPrompt(
  prompt: string,
  conversationId: string | null,
  agent: RunAgent,
  commands: RunCommands,
  execution?: RunRequest["execution"],
  workspaceId?: string | null,
  acquireRunStream?: AcquireRunStream,
): Promise<void> {
  const created = await commands.addUserMessage(conversationId, prompt);
  const assistantMessageId = createEntityId();
  commands.addAssistantMessage(
    created.conversationId,
    assistantMessageId,
    created.messageId,
  );

  await startRunForPrompt({
    conversationId: created.conversationId,
    assistantMessageId,
    sourceUserMessageId: created.messageId,
    prompt,
    execution,
    workspaceId,
    acquireRunStream,
    agent,
    commands,
    rejectOnStartFailure: true,
  });
}

/**
 * Branch a new attempt from a prior run for the same source user message.
 *
 * The shared retry and regenerate path. The only difference between the two
 * intents is which prior response the caller selected — the request, the run
 * creation, and the observation are identical — so the two buttons cannot drift
 * apart in behavior.
 *
 * The prior attempt is never resumed, reused, or edited: the backend reads its
 * durable source user message and creates a new run with a new assistant
 * response, and locally the new response is appended after the old one, which
 * the transcript projection already knows how to hide.
 */
export async function rerunAssistantResponse(options: {
  conversationId: string;
  /** The durable source user message; never inferred from array position. */
  sourceUserMessageId: string;
  prompt: string;
  /** Prior run being branched from, for backend-side eligibility and lineage. */
  retryOfRunId: string;
  execution?: RunRequest["execution"];
  workspaceId?: string | null;
  acquireRunStream?: AcquireRunStream;
  agent: RunAgent;
  commands: RunEventCommands;
}): Promise<void> {
  await startRunForPrompt({
    conversationId: options.conversationId,
    assistantMessageId: null,
    sourceUserMessageId: options.sourceUserMessageId,
    prompt: options.prompt,
    retryOfRunId: options.retryOfRunId,
    execution: options.execution,
    workspaceId: options.workspaceId,
    acquireRunStream: options.acquireRunStream,
    agent: options.agent,
    commands: options.commands,
  });
}

/** Apply backend events in order to a single run's conversation/message. */
export async function applyRunEvents(
  events: RunEvent[],
  conversationId: string,
  assistantMessageId: string | null,
  commands: RunEventCommands,
  options?: {
    sourceUserMessageId?: string | null;
    /** Epoch of the run these events belong to. When provided and no longer
     *  the conversation's current run, the events are stale and are not
     *  applied (and are never persisted). */
    runEpoch?: string;
    /** The backend already created the assistant response linked to this run. */
    assistantResponseIsDurable?: boolean;
  },
): Promise<void> {
  let completed = false;
  let content = "";
  for (const event of events) {
    for (const effect of applyRunEvent(event)) {
      if (
        options?.runEpoch != null &&
        !isRunCurrent(commands, conversationId, options.runEpoch)
      ) {
        // Superseded by a newer run mid-apply; stop touching state.
        return;
      }
      switch (effect.kind) {
        case "setBackendStatus":
          commands.setRunState(conversationId, { backendStatus: effect.backendStatus });
          break;
        case "setPhase":
          commands.setRunState(conversationId, { uiPhase: effect.phase });
          break;
        case "setMessageContent":
          if (
            effect.messageId != null &&
            assistantMessageId != null &&
            effect.messageId !== assistantMessageId
          ) {
            break;
          }
          content = effect.content;
          if (assistantMessageId != null) {
            commands.updateMessage(conversationId, assistantMessageId, {
              content: effect.content,
            });
          }
          break;
        case "setMessageStatus":
          if (assistantMessageId != null) {
            commands.updateMessage(conversationId, assistantMessageId, {
              status: effect.messageStatus,
            });
          }
          if (effect.messageStatus === "complete") completed = true;
          break;
        case "setMessageError":
          if (assistantMessageId != null) {
            commands.updateMessage(conversationId, assistantMessageId, {
              error: effect.error,
              errorCode: effect.errorCode,
            });
          }
          break;
        case "associateMessage":
          // Informational only: the stable pending assistant message id already
          // anchors this run. No duplicate assistant message is ever created.
          break;
        case "ignore":
          break;
      }
    }
  }
  if (
    completed &&
    !options?.assistantResponseIsDurable &&
    assistantMessageId != null &&
    (options?.runEpoch == null ||
      isRunCurrent(commands, conversationId, options.runEpoch))
  ) {
    try {
      await (commands as RunCommands).persistAssistantMessage?.(
        conversationId,
        assistantMessageId,
        { content, sourceUserMessageId: options?.sourceUserMessageId ?? null },
      );
    } catch (error) {
      commands.setRunState(conversationId, { runError: `Assistant response was not saved: ${runErrorMessage(error)}` });
    }
  }
}

/**
 * Cancel the active run for a conversation.
 *
 * Requires a run id; without one (e.g. the run is still being created) this is
 * a safe no-op. The conversation enters the "stopping" phase immediately so
 * repeated stops are ignored, then the backend's final event state is trusted
 * over the local cancel intent — the cancel response or a race where the run
 * completed before the cancel landed is never assumed to win.
 */
export async function cancelActiveRun(options: {
  conversationId: string;
  runId: string | null;
  runEpoch?: string | null;
  assistantMessageId: string | null;
  agent: RunAgent;
  commands: RunEventCommands;
}): Promise<void> {
  const { agent, commands } = options;
  if (options.runId == null) return;
  const isCurrent = () =>
    options.runEpoch == null || isRunCurrent(commands, options.conversationId, options.runEpoch);

  commands.setRunState(options.conversationId, { uiPhase: "stopping" });

  let cancelled: RunResponse;
  try {
    cancelled = await agent.cancelRun(options.runId);
  } catch (error) {
    if (!isCurrent()) return;
    // The cancel request failed. Let backend events describe the actual state
    // rather than assuming anything about the run.
    try {
      const events = await agent.getRunEvents(options.runId);
      if (!isCurrent()) return;
      commands.setRunState(options.conversationId, { uiPhase: "running" });
      applyRunEvents(events, options.conversationId, options.assistantMessageId, commands, { runEpoch: options.runEpoch ?? undefined });
    } catch {
      if (!isCurrent()) return;
      // No event fallback either; restore the active run with a readable error.
      commands.setRunState(options.conversationId, {
        uiPhase: "running",
        runError: runErrorMessage(error),
      });
    }
    return;
  }

  if (!isCurrent()) return;

  commands.setRunState(options.conversationId, {
    backendStatus: cancelled.status,
    cancellationRequestedAt: cancelled.cancellation_requested_at ?? null,
    uiPhase: uiPhaseForBackendStatus(cancelled.status),
  });
  try {
    const events = await agent.getRunEvents(options.runId);
    if (!isCurrent()) return;
    await applyRunEvents(events, options.conversationId, options.assistantMessageId, commands, { runEpoch: options.runEpoch ?? undefined });
  } catch {
    if (!isCurrent()) return;
    // Event retrieval failed after a successful cancel; close the loop using
    // the returned run state so the UI reaches a terminal state.
    commands.setRunState(options.conversationId, {
      backendStatus: cancelled.status,
      uiPhase: uiPhaseForBackendStatus(cancelled.status),
    });
    if (options.assistantMessageId != null) {
      commands.updateMessage(options.conversationId, options.assistantMessageId, {
        status: messageStatusForRunStatus(cancelled.status),
      });
    }
  }
}
