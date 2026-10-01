import type { ApiClient } from "@ava/api-client";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  type ReactNode,
} from "react";

import { useConversationState } from "../state/ConversationProvider";
import { canRegenerateResponse, canRetryResponse, isActiveRunPhase } from "../lib/runActions";
import type { MessageStatus } from "../types";
import {
  cancelActiveRun,
  clientRunAgent,
  recoverRunForConversation,
  rerunAssistantResponse,
  submitPrompt,
  visibleRecoveryCandidate,
  type AcquireRunStream,
  type RunCommands,
} from "./conversationRun";
import { createPersistAssistantMessageCommand } from "./persistAssistantMessage";
import type { RunExecutionOverride } from "@ava/contracts";

export interface AgentRunApi {
  /** Submit a prompt: immediate user + pending assistant, then a backend run. */
  submitPrompt(
    prompt: string,
    execution?: RunExecutionOverride,
    workspaceId?: string | null,
  ): Promise<void>;
  /** Cancel the active run of the active conversation (via the API). */
  stopRun(): void;
  /**
   * Retry a failed/cancelled assistant response by starting a new run for the
   * same source user message. The prior response is left untouched as durable
   * history and a new assistant response becomes the visible one.
   */
  retryMessage(
    messageId: string,
    execution?: RunExecutionOverride,
    workspaceId?: string | null,
  ): void;
  /**
   * Regenerate a completed assistant response by starting a new run for the
   * same source user message. Same machinery as retry; the only difference is
   * the prior response's status.
   */
  regenerateMessage(
    messageId: string,
    execution?: RunExecutionOverride,
    workspaceId?: string | null,
  ): void;
  /** True while the backend run id is being created (no Stop available yet). */
  isStarting: boolean;
  /** True while the active conversation has a run in progress. */
  isRunning: boolean;
  /** True while a cancellation request is in flight. */
  isStopping: boolean;
  /** User-readable error from the active conversation's last run attempt. */
  runError: string | null;
}

const AgentRunContext = createContext<AgentRunApi | null>(null);

/**
 * Wires the shared conversation state to the run backend through the pure
 * orchestrator. Must be rendered inside a {@link ConversationProvider}.
 *
 * Run/message association is stable: the active conversation id and message
 * id are captured when a prompt is submitted, so completions always land in
 * the originating conversation.
 */
export function AgentRunProvider({
  client,
  children,
}: {
  client: ApiClient;
  children: ReactNode;
}) {
  const conversation = useConversationState();
  const agent = useMemo(() => clientRunAgent(client), [client]);
  // Observer ownership is keyed by conversation, never by selection: run
  // ownership belongs to the durable run's conversation. Selecting another
  // conversation must not stop an observer, or the hidden conversation's
  // projection silently freezes at whatever it last received. One entry per
  // conversation preserves the existing one-active-run-per-conversation rule;
  // this is not a concurrency change.
  const observers = useRef(new Map<string, AbortController>());
  const recoveryKeys = useRef(new Map<string, string>());

  const acquireRunStream = useCallback<AcquireRunStream>(
    (conversationId) => {
      // A newer run in this conversation supersedes the previous observer, so
      // two observers can never own the same visible response.
      observers.current.get(conversationId)?.abort();
      const controller = new AbortController();
      observers.current.set(conversationId, controller);
      return {
        signal: controller.signal,
        release: () => {
          if (observers.current.get(conversationId) === controller) {
            observers.current.delete(conversationId);
          }
        },
      };
    },
    [],
  );

  useEffect(() => {
    const owned = observers.current;
    return () => {
      for (const controller of owned.values()) controller.abort();
      owned.clear();
    };
  }, []);

  const commands = useMemo<RunCommands>(
    () => ({
      addUserMessage: conversation.addUserMessage,
      addAssistantMessage: conversation.addAssistantMessage,
      setRunState: conversation.setRunState,
      updateMessage: conversation.updateMessage,
      removeMessage: conversation.removeMessage,
      associateAssistantMessage: conversation.associateAssistantMessage,
      getRunState: conversation.getRunState,
      // The run hands us the final content/source directly: reading them back
      // from state here would race React's re-render after the last event.
      persistAssistantMessage: async (conversationId, placeholderId, message) => {
        await createPersistAssistantMessageCommand({ client, replaceMessage: conversation.replaceMessage })(
          conversationId,
          placeholderId,
          message.content,
          message.sourceUserMessageId ?? undefined,
        );
      },
    }),
    [conversation, client],
  );

  const activeConversation = conversation.activeConversation;
  const activeRun = activeConversation?.run;
  const uiPhase = activeRun?.uiPhase ?? "idle";
  const isStarting = uiPhase === "starting";
  const isRunning = uiPhase === "running";
  const isStopping = uiPhase === "stopping";
  const runError = activeRun?.runError ?? null;

  useEffect(() => {
    if (activeConversation == null) return;
    // A persisted epoch says which run is current, not that this provider has
    // an observer. Only this session's ownership proves it: a conversation this
    // session is already observing needs no recovery, however it was reached.
    if (observers.current.has(activeConversation.id)) return;
    const candidate = visibleRecoveryCandidate(activeConversation);
    if (candidate == null) return;
    const key = `${activeConversation.id}:${candidate.assistantMessageId}:${candidate.sourceRunId}`;
    if (recoveryKeys.current.get(activeConversation.id) === key) return;
    recoveryKeys.current.set(activeConversation.id, key);
    void recoverRunForConversation({
      conversation: activeConversation,
      agent,
      commands,
      acquireRunStream,
    }).catch(() => {
      // A failed lookup is transport state; do not manufacture lifecycle.
      if (!observers.current.has(activeConversation.id)) {
        recoveryKeys.current.delete(activeConversation.id);
      }
    });
  }, [activeConversation, agent, commands, acquireRunStream]);

  const submitPromptFn = useCallback(
    async (prompt: string, execution?: RunExecutionOverride, workspaceId?: string | null) => {
      const current = conversation.activeConversation;
      // One active run per conversation; ignore programmatic double submits.
      if (isActiveRunPhase(current?.run?.uiPhase)) {
        return;
      }
      const promptText = prompt.trim();
      if (promptText.length === 0) return;
      // A new run makes its conversation recoverable again if this one fails.
      if (current?.id != null) recoveryKeys.current.delete(current.id);
      await submitPrompt(
        promptText, current?.id ?? null, agent, commands, execution, workspaceId,
        acquireRunStream,
      );
    },
    [conversation, agent, commands, acquireRunStream],
  );

  const stopRunFn = useCallback(() => {
    const current = conversation.activeConversation;
    const run = current?.run;
    // Only a run with a real backend id can be cancelled. Before the id
    // exists (starting) or during an in-flight cancel (stopping) this is a
    // safe no-op; the enabled Stop is never shown in those phases.
    if (current == null || run == null || run.runId == null) return;
    if (run.uiPhase !== "running") return;
    void cancelActiveRun({
      conversationId: current.id,
      runId: run.runId,
      runEpoch: run.runEpoch,
      assistantMessageId: run.pendingMessageId,
      agent,
      commands,
    });
  }, [conversation, agent, commands]);

  const rerunMessageFn = useCallback(
    (
      messageId: string,
      isEligible: (status: MessageStatus) => boolean,
      execution?: RunExecutionOverride,
      workspaceId?: string | null,
    ) => {
      const current = conversation.activeConversation;
      if (current == null) return;
      // An active run owns the conversation. A second attempt against the same
      // turn would race it; the backend refuses that case too.
      if (isActiveRunPhase(current.run?.uiPhase)) return;
      const message = current.messages.find((m) => m.id === messageId);
      if (message == null || message.role !== "assistant") return;
      const status = message.status ?? "complete";
      if (!isEligible(status)) return;
      // Prompt association is AVA-owned through sourceUserMessageId — never
      // the "previous array element" heuristic.
      const sourceUserMessageId = message.sourceUserMessageId;
      if (sourceUserMessageId == null) return;
      const sourceUserMessage = current.messages.find(
        (m) => m.id === sourceUserMessageId,
      );
      if (sourceUserMessage == null || sourceUserMessage.role !== "user") return;
      const prompt = sourceUserMessage.content;
      if (prompt.trim().length === 0) return;
      // The backend resolves durable lineage and checks eligibility from the
      // current persisted run. A response with no run behind it (legacy or
      // client-authored) has no attempt to branch from.
      const retryOfRunId = message.sourceRunId;
      if (retryOfRunId == null) return;
      void rerunAssistantResponse({
        conversationId: current.id,
        sourceUserMessageId: sourceUserMessage.id,
        prompt,
        retryOfRunId,
        execution,
        workspaceId,
        agent,
        commands,
        // Abort this conversation's previous observer before the new run binds,
        // so two observers can never own the same visible response.
        acquireRunStream,
      });
    },
    [conversation, agent, commands, acquireRunStream],
  );

  const retryMessageFn = useCallback(
    (
      messageId: string,
      execution?: RunExecutionOverride,
      workspaceId?: string | null,
    ) => {
      rerunMessageFn(messageId, canRetryResponse, execution, workspaceId);
    },
    [rerunMessageFn],
  );

  const regenerateMessageFn = useCallback(
    (
      messageId: string,
      execution?: RunExecutionOverride,
      workspaceId?: string | null,
    ) => {
      rerunMessageFn(messageId, canRegenerateResponse, execution, workspaceId);
    },
    [rerunMessageFn],
  );

  const api = useMemo<AgentRunApi>(
    () => ({
      submitPrompt: submitPromptFn,
      stopRun: stopRunFn,
      retryMessage: retryMessageFn,
      regenerateMessage: regenerateMessageFn,
      isStarting,
      isRunning,
      isStopping,
      runError,
    }),
    [
      submitPromptFn,
      stopRunFn,
      retryMessageFn,
      regenerateMessageFn,
      isStarting,
      isRunning,
      isStopping,
      runError,
    ],
  );

  return (
    <AgentRunContext.Provider value={api}>{children}</AgentRunContext.Provider>
  );
}

export function useAgentRun(): AgentRunApi {
  const context = useContext(AgentRunContext);
  if (context == null) {
    throw new Error("useAgentRun must be used within an AgentRunProvider");
  }
  return context;
}
