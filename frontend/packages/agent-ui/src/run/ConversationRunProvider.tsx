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
import type { UIRunPhase } from "../types";
import {
  cancelActiveRun,
  clientRunAgent,
  recoverRunForConversation,
  startRunForPrompt,
  submitPrompt,
  visibleRecoveryCandidate,
  type RunCommands,
} from "./conversationRun";
import { createPersistAssistantMessageCommand } from "./persistAssistantMessage";
import type { RunExecutionOverride } from "@ava/contracts";

/** Phases during which a new run must not start. */
const ACTIVE_PHASES: UIRunPhase[] = ["starting", "running", "stopping"];

export interface AgentRunApi {
  /** Submit a prompt: immediate user + pending assistant, then a backend run. */
  submitPrompt(
    prompt: string,
    execution?: RunExecutionOverride,
    workspaceId?: string | null,
  ): Promise<void>;
  /** Cancel the active run of the active conversation (via the API). */
  stopRun(): void;
  /** Retry a failed/cancelled assistant message from its source prompt. */
  retryMessage(messageId: string): void;
  /** Regenerate a completed assistant message from its source prompt. */
  regenerateMessage(messageId: string): void;
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
  const streamController = useRef<AbortController | null>(null);
  const activeConversationId = useRef<string | null>(conversation.activeConversation?.id ?? null);
  const recoveryKey = useRef<string | null>(null);

  useEffect(() => () => streamController.current?.abort(), []);
  useEffect(() => {
    if (activeConversationId.current !== conversation.activeConversation?.id) {
      streamController.current?.abort();
      streamController.current = null;
      recoveryKey.current = null;
      activeConversationId.current = conversation.activeConversation?.id ?? null;
    }
  }, [conversation.activeConversation?.id]);

  const commands = useMemo<RunCommands>(
    () => ({
      addUserMessage: conversation.addUserMessage,
      addAssistantMessage: conversation.addAssistantMessage,
      setRunState: conversation.setRunState,
      updateMessage: conversation.updateMessage,
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
    const candidate = visibleRecoveryCandidate(activeConversation);
    if (candidate == null) return;
    const key = `${activeConversation.id}:${candidate.assistantMessageId}:${candidate.sourceRunId}`;
    if (recoveryKey.current === key) return;
    recoveryKey.current = key;
    streamController.current?.abort();
    const controller = new AbortController();
    streamController.current = controller;
    void recoverRunForConversation({
      conversation: activeConversation,
      agent,
      commands,
      streamSignal: controller.signal,
    }).catch(() => {
      // A failed lookup is transport state; do not manufacture lifecycle.
      if (!controller.signal.aborted) recoveryKey.current = null;
    });
  }, [activeConversation, agent, commands]);

  const submitPromptFn = useCallback(
    async (prompt: string, execution?: RunExecutionOverride, workspaceId?: string | null) => {
      const current = conversation.activeConversation;
      // One active run per conversation; ignore programmatic double submits.
      if (current?.run != null && ACTIVE_PHASES.includes(current.run.uiPhase)) {
        return;
      }
      const promptText = prompt.trim();
      if (promptText.length === 0) return;
      streamController.current?.abort();
      streamController.current = new AbortController();
      await submitPrompt(
        promptText, current?.id ?? null, agent, commands, execution, workspaceId,
        streamController.current.signal,
      );
    },
    [conversation, agent, commands],
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
      assistantMessageId: run.pendingMessageId,
      agent,
      commands,
    });
  }, [conversation, agent, commands]);

  const rerunMessageFn = useCallback(
    (messageId: string, allowedStatuses: Set<string>) => {
      const current = conversation.activeConversation;
      if (current == null) return;
      if (current.run != null && ACTIVE_PHASES.includes(current.run.uiPhase)) {
        return;
      }
      const message = current.messages.find((m) => m.id === messageId);
      if (message == null || message.role !== "assistant") return;
      const status = message.status ?? "complete";
      if (!allowedStatuses.has(status)) return;
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
      void startRunForPrompt({
        conversationId: current.id,
        assistantMessageId: message.id,
        sourceUserMessageId: sourceUserMessage.id,
        prompt,
        agent,
        commands,
        streamSignal: (() => {
          streamController.current?.abort();
          streamController.current = new AbortController();
          return streamController.current.signal;
        })(),
      });
    },
    [conversation, agent, commands],
  );

  const retryMessageFn = useCallback(
    (messageId: string) =>
      rerunMessageFn(messageId, new Set(["failed", "cancelled"])),
    [rerunMessageFn],
  );

  const regenerateMessageFn = useCallback(
    (messageId: string) => rerunMessageFn(messageId, new Set(["complete"])),
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
