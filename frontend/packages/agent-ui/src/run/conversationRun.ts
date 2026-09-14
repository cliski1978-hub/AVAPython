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
  ErrorResponse,
  RunEvent,
  RunRequest,
  RunResponse,
} from "@ava/contracts";
import {
  ApiError,
  cancelRun,
  getRunEvents,
  startRun,
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

/** Minimal backend client surface the orchestrator depends on. */
export interface RunAgent {
  startRun(request: RunRequest): Promise<RunResponse>;
  getRunEvents(runId: string): Promise<RunEvent[]>;
  cancelRun(runId: string): Promise<RunResponse>;
}

/** Adapt the shared @ava/api-client to the run agent surface. */
export function clientRunAgent(client: ApiClient): RunAgent {
  return {
    startRun: (request) => startRun(client, request),
    getRunEvents: (runId) => getRunEvents(client, runId),
    cancelRun: (runId) => cancelRun(client, runId),
  };
}

/** State operations the orchestrator drives. */
export interface RunCommands {
  addUserMessage(
    conversationId: string | null,
    content: string,
  ): { conversationId: string; messageId: string };
  addAssistantMessage(
    conversationId: string,
    messageId: string,
    sourceUserMessageId: string | null,
  ): void;
  setRunState(conversationId: string, update: Partial<ConversationRunState>): void;
  updateMessage(
    conversationId: string,
    messageId: string,
    patch: MessagePatch,
  ): void;
}

/** Run commands used when applying events (subset used after run start). */
export type RunEventCommands = Pick<
  RunCommands,
  "setRunState" | "updateMessage"
>;

/** Map an unknown failure to a user-readable message (never raw payloads). */
export function runErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const body = error.body as Partial<ErrorResponse> | null | undefined;
    if (body != null && typeof body.message === "string" && body.message.trim() !== "") {
      return body.message;
    }
    return `Request failed (${error.status}).`;
  }
  return "AVA is unavailable. Please try again.";
}

/**
 * Run a prompt into an existing assistant slot. Shared by first submission,
 * retry, and regenerate so the run path is identical for every run. The
 * assistant message is reset to pending and the conversation enters the
 * "starting" phase until the backend assigns a run id.
 */
export async function startRunForPrompt(options: {
  conversationId: string;
  assistantMessageId: string;
  sourceUserMessageId: string | null;
  prompt: string;
  agent: RunAgent;
  commands: RunEventCommands;
}): Promise<void> {
  const { agent, commands } = options;

  commands.setRunState(options.conversationId, {
    runId: null,
    backendStatus: null,
    uiPhase: "starting",
    runError: null,
    pendingMessageId: options.assistantMessageId,
  });
  commands.updateMessage(options.conversationId, options.assistantMessageId, {
    status: "pending",
    error: undefined,
  });

  try {
    const run = await agent.startRun({ prompt: options.prompt });
    commands.setRunState(options.conversationId, {
      runId: run.run_id,
      backendStatus: run.status,
    });

    const events = await agent.getRunEvents(run.run_id);
    applyRunEvents(events, options.conversationId, options.assistantMessageId, commands);
  } catch (error) {
    const message = runErrorMessage(error);
    commands.setRunState(options.conversationId, {
      backendStatus: "failed",
      uiPhase: "failed",
      runError: message,
    });
    commands.updateMessage(options.conversationId, options.assistantMessageId, {
      status: "failed",
      error: message,
    });
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
): Promise<void> {
  const created = commands.addUserMessage(conversationId, prompt);
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
    agent,
    commands,
  });
}

/** Apply backend events in order to a single run's conversation/message. */
export function applyRunEvents(
  events: RunEvent[],
  conversationId: string,
  assistantMessageId: string | null,
  commands: RunEventCommands,
): void {
  for (const event of events) {
    for (const effect of applyRunEvent(event)) {
      switch (effect.kind) {
        case "setBackendStatus":
          commands.setRunState(conversationId, { backendStatus: effect.backendStatus });
          break;
        case "setPhase":
          commands.setRunState(conversationId, { uiPhase: effect.phase });
          break;
        case "setMessageContent":
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
  assistantMessageId: string | null;
  agent: RunAgent;
  commands: RunEventCommands;
}): Promise<void> {
  const { agent, commands } = options;
  if (options.runId == null) return;

  commands.setRunState(options.conversationId, { uiPhase: "stopping" });

  let cancelled: RunResponse;
  try {
    cancelled = await agent.cancelRun(options.runId);
  } catch (error) {
    // The cancel request failed. Let backend events describe the actual state
    // rather than assuming anything about the run.
    try {
      const events = await agent.getRunEvents(options.runId);
      commands.setRunState(options.conversationId, { uiPhase: "running" });
      applyRunEvents(events, options.conversationId, options.assistantMessageId, commands);
    } catch {
      // No event fallback either; restore the active run with a readable error.
      commands.setRunState(options.conversationId, {
        uiPhase: "running",
        runError: runErrorMessage(error),
      });
    }
    return;
  }

  try {
    const events = await agent.getRunEvents(options.runId);
    applyRunEvents(events, options.conversationId, options.assistantMessageId, commands);
  } catch {
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