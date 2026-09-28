import { describe, expect, it, vi } from "vitest";

import type { RunEvent, RunResponse } from "@ava/contracts";
import { ApiError } from "@ava/api-client";

import type { ConversationRunState } from "../types";
import { EMPTY_CONVERSATION_RUN } from "../types";
import type { MessagePatch } from "../state/conversationReducer";
import {
  applyRunEvents,
  cancelActiveRun,
  recoverRunForConversation,
  runErrorMessage,
  startRunForPrompt,
  submitPrompt,
  visibleRecoveryCandidate,
  type RunAgent,
  type RunCommands,
} from "./conversationRun";

function evt(
  eventType: string,
  eventId: string,
  payload: Record<string, unknown> = {},
): RunEvent {
  return {
    event_id: eventId,
    run_id: "run-001",
    event_type: eventType as RunEvent["event_type"],
    timestamp: "2026-09-12T00:00:00Z",
    payload: payload as RunEvent["payload"],
    contract_version: "v1",
  };
}

const successfulEvents: RunEvent[] = [
  evt("run_started", "evt-1"),
  evt("message_started", "evt-2", { message_id: "msg-backend-1" }),
  evt("message_content", "evt-3", { content: "Hello AVA" }),
  evt("run_completed", "evt-4"),
];

const cancelledEvents: RunEvent[] = [
  evt("run_started", "evt-1"),
  evt("run_cancelled", "evt-2"),
];

function makeAgent(overrides: Partial<RunAgent> = {}): RunAgent {
  const completed: RunResponse = {
    run_id: "run-001",
    status: "completed",
    contract_version: "v1",
  };
  const cancelled: RunResponse = {
    run_id: "run-001",
    status: "cancelled",
    contract_version: "v1",
  };
  return {
    startRun: vi.fn(async () => completed),
    getRunEvents: vi.fn(async () => successfulEvents),
    streamRun: vi.fn(async (_runId, options) => {
      successfulEvents.forEach((event, index) => options.onEvent({ ...event, sequence: index + 1 }));
    }),
    cancelRun: vi.fn(async () => cancelled),
    ...overrides,
  };
}

interface CommandEntry {
  op: string;
  conversationId?: string | null;
  messageId?: string;
  content?: string;
  resolved?: string;
  patch?: MessagePatch;
  update?: Partial<ConversationRunState>;
  sourceUserMessageId?: string | null;
  placeholderId?: string;
}

function makeCommands() {
  const log: CommandEntry[] = [];
  const runStateRecord: Record<string, ConversationRunState> = {};
  const addUserMessage = vi.fn(
    (conversationId: string | null, content: string) => {
      const conversationIdResolved = conversationId ?? "created-conv";
      const messageId = "user-msg-created";
      log.push({
        op: "addUserMessage",
        conversationId,
        content,
        resolved: conversationIdResolved,
        messageId,
      });
      return { conversationId: conversationIdResolved, messageId };
    },
  );
  const setRunState = vi.fn(
    (conversationId: string, update: Partial<ConversationRunState>) => {
      runStateRecord[conversationId] = {
        ...EMPTY_CONVERSATION_RUN,
        ...(runStateRecord[conversationId] ?? {}),
        ...update,
      };
      log.push({ op: "setRunState", conversationId, update });
    },
  );
  const commands: RunCommands = {
    addUserMessage,
    addAssistantMessage: vi.fn(
      (conversationId, messageId, sourceUserMessageId) => {
        log.push({
          op: "addAssistantMessage",
          conversationId,
          messageId,
          sourceUserMessageId,
        });
      },
    ),
    setRunState,
    getRunState: vi.fn((conversationId: string) => {
      return runStateRecord[conversationId] ?? null;
    }),
    updateMessage: vi.fn((conversationId, messageId, patch) => {
      log.push({ op: "updateMessage", conversationId, messageId, patch });
    }),
    associateAssistantMessage: vi.fn((conversationId, placeholderId, messageId) => {
      log.push({ op: "associateAssistantMessage", conversationId, placeholderId, messageId });
    }),
    persistAssistantMessage: vi.fn(
      async (
        conversationId,
        messageId,
        message: { content: string; sourceUserMessageId?: string | null },
      ) => {
        log.push({
          op: "persistAssistantMessage",
          conversationId,
          messageId,
          content: message.content,
          sourceUserMessageId: message.sourceUserMessageId ?? null,
        });
      },
    ),
  };
  return { commands, log, runStateRecord };
}

function entries(log: CommandEntry[], op: string): CommandEntry[] {
  return log.filter((entry) => entry.op === op);
}

function lastSetRunState(log: CommandEntry[]): Record<string, unknown> | undefined {
  const sets = entries(log, "setRunState");
  return sets[sets.length - 1]?.update as Record<string, unknown> | undefined;
}

function hasRunStateUpdate(
  log: CommandEntry[],
  match: Partial<Record<string, unknown>>,
): boolean {
  return entries(log, "setRunState").some((e) =>
    Object.entries(match).every(([k, v]) => (e.update as Record<string, unknown>)?.[k] === v),
  );
}

describe("submitPrompt", () => {
  it("drives the full success lifecycle through events", async () => {
    const agent = makeAgent();
    const { commands, log } = makeCommands();

    await submitPrompt("Hello AVA", null, agent, commands);

    const user = entries(log, "addUserMessage");
    expect(user).toHaveLength(1);
    expect(user[0]).toMatchObject({
      conversationId: null,
      content: "Hello AVA",
      resolved: "created-conv",
    });

    const assistant = entries(log, "addAssistantMessage");
    expect(assistant).toHaveLength(1);
    expect(assistant[0].conversationId).toBe("created-conv");
    expect(assistant[0].sourceUserMessageId).toBe("user-msg-created");

    expect(agent.startRun).toHaveBeenCalledWith({ prompt: "Hello AVA", conversation_id: "created-conv", source_user_message_id: "user-msg-created" });
    expect(agent.streamRun).toHaveBeenCalledWith("run-001", expect.any(Object));

    const phases = entries(log, "setRunState").map(
      (e) => e.update?.uiPhase,
    );
    expect(phases).toContain("starting");
    expect(phases).toContain("completed");

    const patchOp = entries(log, "updateMessage");
    const contentPatch = patchOp.find(
      (e) => e.patch?.content === "Hello AVA",
    );
    expect(contentPatch).toBeTruthy();
    expect(contentPatch?.messageId).toBe(assistant[0].messageId);
    const completePatch = patchOp.find(
      (e) => e.patch?.status === "complete",
    );
    expect(completePatch).toBeTruthy();
  });

  it("threads the selected workspace into the backend run request", async () => {
    const agent = makeAgent();
    const { commands } = makeCommands();

    await submitPrompt("Hello AVA", null, agent, commands, undefined, "workspace-a");

    expect(agent.startRun).toHaveBeenCalledWith({
      prompt: "Hello AVA",
      conversation_id: "created-conv",
      source_user_message_id: "user-msg-created",
      workspace_id: "workspace-a",
    });
  });

  it("omits the workspace from the run request when selection is null", async () => {
    const agent = makeAgent();
    const { commands } = makeCommands();

    await submitPrompt("Hello AVA", null, agent, commands, undefined, null);

    expect(agent.startRun).not.toHaveBeenCalledWith(
      expect.objectContaining({ workspace_id: expect.anything() }),
    );
    expect(agent.startRun).toHaveBeenCalledWith({ prompt: "Hello AVA", conversation_id: "created-conv", source_user_message_id: "user-msg-created" });
  });

  it("sets starting state before the backend call", async () => {
    const agent = makeAgent();
    const { commands, log } = makeCommands();

    await submitPrompt("hi", "conv-a", agent, commands);

    const first = entries(log, "setRunState")[0];
    expect(first).toMatchObject({
      conversationId: "conv-a",
      update: {
        runId: null,
        backendStatus: null,
        uiPhase: "starting",
        runError: null,
      },
    });
  });

  it("marks the assistant message failed when startRun rejects", async () => {
    const agent = makeAgent({
      startRun: vi.fn(async () => {
        throw new ApiError("Backend broke", 500, {
          category: "internal",
          message: "An internal error occurred.",
        });
      }),
    });
    const { commands, log } = makeCommands();

    await submitPrompt("boom", "conv-a", agent, commands);

    expect(agent.getRunEvents).not.toHaveBeenCalled();
    expect(lastSetRunState(log)).toMatchObject({
      backendStatus: "failed",
      uiPhase: "failed",
      runError: "An internal error occurred.",
    });

    const failed = entries(log, "updateMessage").find(
      (e) => e.patch?.status === "failed",
    );
    expect(failed?.conversationId).toBe("conv-a");
    expect(failed?.patch).toMatchObject({
      status: "failed",
      error: "An internal error occurred.",
    });
  });

  it("keeps backend status intact when the live stream is interrupted", async () => {
    const agent = makeAgent({
      streamRun: vi.fn(async () => {
        throw new Error("network down");
      }),
    });
    const { commands, log } = makeCommands();

    await submitPrompt("ok", "conv-a", agent, commands);

    expect(hasRunStateUpdate(log, { backendStatus: "completed" })).toBe(true);
    expect(lastSetRunState(log)).toMatchObject({
      runError: "Live updates disconnected: AVA is unavailable. Please try again.",
    });
    expect(entries(log, "updateMessage").some((e) => e.patch?.status === "failed")).toBe(false);
  });

  it("associates events with the conversation that started the run", async () => {
    const agent = makeAgent();
    const { commands, log } = makeCommands();

    await submitPrompt("convo start", "conv-abc", agent, commands);

    const runStates = entries(log, "setRunState");
    for (const entry of runStates) {
      expect(entry.conversationId).toBe("conv-abc");
    }
    const messageUpdates = entries(log, "updateMessage");
    for (const entry of messageUpdates) {
      expect(entry.conversationId).toBe("conv-abc");
    }
    const assistant = entries(log, "addAssistantMessage");
    for (const entry of messageUpdates) {
      expect(entry.messageId).toBe(assistant[0].messageId);
    }
  });

  it("never creates a second assistant message from message_started", async () => {
    const agent = makeAgent();
    const { commands, log } = makeCommands();

    await submitPrompt("dupe check", "conv-a", agent, commands);

    expect(entries(log, "addAssistantMessage")).toHaveLength(1);
  });
});

describe("startRunForPrompt", () => {
  it("resets the assistant message to pending and sets the starting phase", async () => {
    const agent = makeAgent();
    const { commands, log } = makeCommands();

    await startRunForPrompt({
      conversationId: "conv-x",
      assistantMessageId: "asm-1",
      sourceUserMessageId: "user-1",
      prompt: "hi",
      agent,
      commands,
    });

    const first = entries(log, "setRunState")[0];
    expect(first).toMatchObject({
      conversationId: "conv-x",
      update: {
        runId: null,
        backendStatus: null,
        uiPhase: "starting",
        runError: null,
        pendingMessageId: "asm-1",
      },
    });
    expect(entries(log, "updateMessage")[0]).toMatchObject({
      conversationId: "conv-x",
      messageId: "asm-1",
      patch: { status: "pending", error: undefined },
    });
  });

  it("sets backendStatus on startRun success before events arrive", async () => {
    const agent = makeAgent();
    const { commands, log } = makeCommands();

    await startRunForPrompt({
      conversationId: "conv-x",
      assistantMessageId: "asm-1",
      sourceUserMessageId: "user-1",
      prompt: "hi",
      agent,
      commands,
    });

    const runStates = entries(log, "setRunState");
    const backendStatusSet = runStates.find(
      (e) => e.update?.backendStatus != null,
    );
    expect(backendStatusSet).toMatchObject({
      conversationId: "conv-x",
      update: { backendStatus: "completed" },
    });
  });

  it("includes workspace_id when a workspace is selected", async () => {
    const agent = makeAgent();
    const { commands } = makeCommands();

    await startRunForPrompt({
      conversationId: "conv-x",
      assistantMessageId: "asm-1",
      sourceUserMessageId: "user-1",
      prompt: "explain",
      workspaceId: "approved-workspace",
      agent,
      commands,
    });

    expect(agent.startRun).toHaveBeenCalledWith({
      prompt: "explain",
      conversation_id: "conv-x",
      source_user_message_id: "user-1",
      workspace_id: "approved-workspace",
    });
  });

  it("omits workspace_id from the run request when not provided", async () => {
    const agent = makeAgent();
    const { commands } = makeCommands();

    await startRunForPrompt({
      conversationId: "conv-x",
      assistantMessageId: "asm-1",
      sourceUserMessageId: "user-1",
      prompt: "explain",
      agent,
      commands,
    });

    expect(agent.startRun).toHaveBeenCalledWith({ prompt: "explain", conversation_id: "conv-x", source_user_message_id: "user-1" });
  });

  it("omits workspace_id from the run request when it is null", async () => {
    const agent = makeAgent();
    const { commands } = makeCommands();

    await startRunForPrompt({
      conversationId: "conv-x",
      assistantMessageId: "asm-1",
      sourceUserMessageId: "user-1",
      prompt: "explain",
      workspaceId: null,
      agent,
      commands,
    });

    expect(agent.startRun).not.toHaveBeenCalledWith(
      expect.objectContaining({ workspace_id: "" }),
    );
    expect(agent.startRun).toHaveBeenCalledWith({ prompt: "explain", conversation_id: "conv-x", source_user_message_id: "user-1" });
  });

  it("combines execution and workspace in the run request", async () => {
    const agent = makeAgent();
    const { commands } = makeCommands();

    await startRunForPrompt({
      conversationId: "conv-x",
      assistantMessageId: "asm-1",
      sourceUserMessageId: "user-1",
      prompt: "explain",
      execution: { mode: "auto" },
      workspaceId: "approved-workspace",
      agent,
      commands,
    });

    expect(agent.startRun).toHaveBeenCalledWith({
      prompt: "explain",
      conversation_id: "conv-x",
      source_user_message_id: "user-1",
      execution: { mode: "auto" },
      workspace_id: "approved-workspace",
    });
  });
});

describe("applyRunEvents", () => {
  it("applies events in order to the given conversation and message", () => {
    const { commands, log } = makeCommands();

    applyRunEvents(cancelledEvents, "conv-x", "asm-x", commands);

    expect(hasRunStateUpdate(log, { uiPhase: "cancelled" })).toBe(true);
    expect(hasRunStateUpdate(log, { backendStatus: "cancelled" })).toBe(true);
    expect(entries(log, "updateMessage")).toEqual([
      {
        op: "updateMessage",
        conversationId: "conv-x",
        messageId: "asm-x",
        patch: { status: "streaming" },
      },
      {
        op: "updateMessage",
        conversationId: "conv-x",
        messageId: "asm-x",
        patch: { status: "cancelled" },
      },
    ]);
  });

  it("skips message effects when no assistant message id is known", () => {
    const { commands, log } = makeCommands();

    applyRunEvents(successfulEvents, "conv-x", null, commands);

    expect(entries(log, "updateMessage")).toHaveLength(0);
    expect(hasRunStateUpdate(log, { uiPhase: "completed" })).toBe(true);
    expect(hasRunStateUpdate(log, { backendStatus: "completed" })).toBe(true);
  });
});

describe("cancelActiveRun", () => {
  it("is a no-op when there is no run id", async () => {
    const agent = makeAgent();
    const { commands } = makeCommands();

    await cancelActiveRun({
      conversationId: "conv-a",
      runId: null,
      assistantMessageId: "asm-a",
      agent,
      commands,
    });

    expect(agent.cancelRun).not.toHaveBeenCalled();
    expect(agent.getRunEvents).not.toHaveBeenCalled();
  });

  it("enters the stopping phase before calling cancelRun", async () => {
    const agent = makeAgent({ getRunEvents: vi.fn(async () => cancelledEvents) });
    const { commands, log } = makeCommands();

    await cancelActiveRun({
      conversationId: "conv-a",
      runId: "run-001",
      assistantMessageId: "asm-a",
      agent,
      commands,
    });

    const stopping = entries(log, "setRunState")[0];
    expect(stopping).toMatchObject({
      conversationId: "conv-a",
      update: { uiPhase: "stopping" },
    });
  });

  it("cancels then applies backend events to the terminal state", async () => {
    const agent = makeAgent({ getRunEvents: vi.fn(async () => cancelledEvents) });
    const { commands, log } = makeCommands();

    await cancelActiveRun({
      conversationId: "conv-a",
      runId: "run-001",
      assistantMessageId: "asm-a",
      agent,
      commands,
    });

    expect(agent.cancelRun).toHaveBeenCalledWith("run-001");
    expect(hasRunStateUpdate(log, { uiPhase: "cancelled" })).toBe(true);
    expect(entries(log, "updateMessage")).toEqual([
      {
        op: "updateMessage",
        conversationId: "conv-a",
        messageId: "asm-a",
        patch: { status: "streaming" },
      },
      {
        op: "updateMessage",
        conversationId: "conv-a",
        messageId: "asm-a",
        patch: { status: "cancelled" },
      },
    ]);
  });

  it("restores the running phase with a readable error when cancel itself fails and events are unavailable", async () => {
    const agent = makeAgent({
      cancelRun: vi.fn(async () => {
        throw new ApiError("g", 502, {
          category: "unavailable",
          message: "Bad gateway",
        });
      }),
      getRunEvents: vi.fn(async () => {
        throw new Error("network");
      }),
    });
    const { commands, log } = makeCommands();

    await cancelActiveRun({
      conversationId: "conv-a",
      runId: "run-001",
      assistantMessageId: "asm-a",
      agent,
      commands,
    });

    expect(lastSetRunState(log)).toMatchObject({
      uiPhase: "running",
      runError: "Bad gateway",
    });
  });

  it("recovers from a failed cancel by falling back to backend events", async () => {
    const agent = makeAgent({
      cancelRun: vi.fn(async () => {
        throw new ApiError("g", 502, { category: "unavailable", message: "Bad gateway" });
      }),
      getRunEvents: vi.fn(async () => cancelledEvents),
    });
    const { commands, log } = makeCommands();

    await cancelActiveRun({
      conversationId: "conv-a",
      runId: "run-001",
      assistantMessageId: "asm-a",
      agent,
      commands,
    });

    expect(agent.getRunEvents).toHaveBeenCalledWith("run-001");
    expect(hasRunStateUpdate(log, { uiPhase: "cancelled" })).toBe(true);
    expect(entries(log, "updateMessage")).toEqual([
      {
        op: "updateMessage",
        conversationId: "conv-a",
        messageId: "asm-a",
        patch: { status: "streaming" },
      },
      {
        op: "updateMessage",
        conversationId: "conv-a",
        messageId: "asm-a",
        patch: { status: "cancelled" },
      },
    ]);
  });

  it("falls back to the cancel response when event retrieval fails", async () => {
    const agent = makeAgent({
      getRunEvents: vi.fn(async () => {
        throw new Error("down");
      }),
    });
    const { commands, log } = makeCommands();

    await cancelActiveRun({
      conversationId: "conv-a",
      runId: "run-001",
      assistantMessageId: "asm-a",
      agent,
      commands,
    });

    expect(lastSetRunState(log)).toMatchObject({
      backendStatus: "cancelled",
      uiPhase: "cancelled",
    });
    expect(entries(log, "updateMessage")).toEqual([
      {
        op: "updateMessage",
        conversationId: "conv-a",
        messageId: "asm-a",
        patch: { status: "cancelled" },
      },
    ]);
  });

  it("is a safe no-op for a second stop while already stopping", async () => {
    const agent = makeAgent();
    const { commands, log } = makeCommands();

    // First cancel: enters stopping
    await cancelActiveRun({
      conversationId: "conv-a",
      runId: "run-001",
      assistantMessageId: "asm-a",
      agent,
      commands,
    });

    // Second cancel with the same run id: the agent sets stopping again
    // then proceeds; the duplicate cancel is not harmful.
    await cancelActiveRun({
      conversationId: "conv-a",
      runId: "run-001",
      assistantMessageId: "asm-a",
      agent,
      commands,
    });

    const stoppings = entries(log, "setRunState").filter(
      (e) => e.update?.uiPhase === "stopping",
    );
    expect(stoppings.length).toBeGreaterThanOrEqual(2);
  });
});

describe("streamed run events", () => {
  it("renders a persisted partial snapshot before the stream closes and binds the backend message id", async () => {
    const { commands, log } = makeCommands();
    let emit!: (event: RunEvent) => void;
    let close!: () => void;
    const stream = new Promise<void>((resolve) => { close = resolve; });
    const agent = makeAgent({
      startRun: vi.fn(async (): Promise<RunResponse> => ({
        run_id: "run-001", status: "running", assistant_message_id: "backend-assistant",
        contract_version: "v1",
      })),
      streamRun: vi.fn(async (_runId, options) => {
        emit = options.onEvent;
        await stream;
      }),
    });
    const running = startRunForPrompt({
      conversationId: "conv-x", assistantMessageId: "local-assistant",
      sourceUserMessageId: "user-x", prompt: "hello", agent, commands,
    });
    await vi.waitFor(() => expect(emit).toBeTypeOf("function"));
    emit({ ...evt("run_started", "started"), sequence: 1 });
    emit({ ...evt("message_started", "message-started", { message_id: "backend-assistant" }), sequence: 2 });
    emit({ ...evt("message_content", "partial", {
      message_id: "backend-assistant", content: "**bold",
    }), sequence: 3 });
    expect(entries(log, "associateAssistantMessage")).toEqual([
      expect.objectContaining({
        placeholderId: "local-assistant", messageId: "backend-assistant",
      }),
    ]);
    await vi.waitFor(() => expect(entries(log, "updateMessage")).toContainEqual(expect.objectContaining({
      messageId: "backend-assistant", patch: { content: "**bold" },
    })));
    close();
    await running;
  });

  it("deduplicates and sequence-orders partial snapshots and rejects wrong ownership", async () => {
    const { commands, log } = makeCommands();
    const agent = makeAgent({
      startRun: vi.fn(async (): Promise<RunResponse> => ({
        run_id: "run-001", status: "running", assistant_message_id: "backend-assistant",
        contract_version: "v1",
      })),
      streamRun: vi.fn(async (_runId, options) => {
        options.onEvent({ ...evt("run_started", "started"), sequence: 1 });
        options.onEvent({ ...evt("message_started", "message-started", {
          message_id: "backend-assistant",
        }), sequence: 2 });
        options.onEvent({ ...evt("message_content", "accepted", {
          message_id: "backend-assistant", content: "Hello",
        }), sequence: 3 });
        options.onEvent({ ...evt("message_content", "accepted", {
          message_id: "backend-assistant", content: "duplicate",
        }), sequence: 3 });
        options.onEvent({ ...evt("message_content", "older", {
          message_id: "backend-assistant", content: "older",
        }), sequence: 2 });
        options.onEvent({ ...evt("message_content", "wrong-message", {
          message_id: "another-message", content: "wrong",
        }), sequence: 4 });
        options.onEvent({ ...evt("message_content", "wrong-run", {
          message_id: "backend-assistant", content: "wrong run",
        }), run_id: "other-run", sequence: 5 });
      }),
    });
    await startRunForPrompt({
      conversationId: "conv-x", assistantMessageId: "local-assistant",
      sourceUserMessageId: "user-x", prompt: "hello", agent, commands,
    });
    await vi.waitFor(() => {
      const content = entries(log, "updateMessage").filter((entry) => entry.patch?.content != null);
      expect(content).toEqual([
        expect.objectContaining({ messageId: "backend-assistant", patch: { content: "Hello" } }),
      ]);
    });
  });

  it("drops an old run stream after a newer epoch becomes current", async () => {
    const { commands, log, runStateRecord } = makeCommands();
    const agent = makeAgent({
      startRun: vi.fn(async (): Promise<RunResponse> => ({
        run_id: "old-run",
        status: "running",
        contract_version: "v1",
      })),
      streamRun: vi.fn(async (_runId, options) => {
        commands.setRunState("conv-x", { runEpoch: "newer-run" });
        options.onEvent({ ...evt("run_completed", "old-terminal"), sequence: 2 });
      }),
    });

    await startRunForPrompt({
      conversationId: "conv-x", assistantMessageId: "assistant-x", sourceUserMessageId: "user-x",
      prompt: "hello", agent, commands,
    });

    expect(runStateRecord["conv-x"]?.runEpoch).toBe("newer-run");
    expect(log.some((entry) => entry.patch?.status === "complete")).toBe(false);
  });
});

describe("runErrorMessage", () => {
  it("prefers the backend error message", () => {
    const error = new ApiError("t", 500, {
      category: "internal",
      message: "An internal error occurred.",
    });
    expect(runErrorMessage(error)).toBe("An internal error occurred.");
  });

  it("falls back to a status line when the body has no message", () => {
    expect(runErrorMessage(new ApiError("t", 502, {}))).toBe(
      "Request failed (502).",
    );
  });

  it("uses a stable message for non-API failures", () => {
    expect(runErrorMessage(new Error("boom"))).toBe(
      "AVA is unavailable. Please try again.",
    );
  });
});

describe("completed assistant persistence", () => {
  it("persists the originating placeholder exactly once after completion", async () => {
    const { commands, log } = makeCommands();
    await applyRunEvents(successfulEvents, "conversation-a", "local-assistant", commands);
    const persisted = entries(log, "persistAssistantMessage");
    expect(persisted).toEqual([
      {
        op: "persistAssistantMessage",
        conversationId: "conversation-a",
        messageId: "local-assistant",
        // Handed directly from the applied events, never read back from state.
        content: "Hello AVA",
        sourceUserMessageId: null,
      },
    ]);
  });

  it("passes through the source user message when known", async () => {
    const { commands, log } = makeCommands();
    await applyRunEvents(
      successfulEvents,
      "conversation-a",
      "local-assistant",
      commands,
      { sourceUserMessageId: "user-local-1" },
    );
    expect(entries(log, "persistAssistantMessage")).toEqual([
      expect.objectContaining({
        conversationId: "conversation-a",
        messageId: "local-assistant",
        content: "Hello AVA",
        sourceUserMessageId: "user-local-1",
      }),
    ]);
  });

  it("does not persist assistant output for failed or cancelled runs", async () => {
    for (const events of [
      [evt("run_failed", "failed")],
      [evt("run_cancelled", "cancelled")],
    ]) {
      const { commands, log } = makeCommands();
      await applyRunEvents(events, "conversation-a", "local-assistant", commands);
      expect(entries(log, "persistAssistantMessage")).toHaveLength(0);
    }
  });

  it("keeps a completed run successful when assistant persistence rejects", async () => {
    const { commands, log } = makeCommands();
    commands.persistAssistantMessage = vi.fn(async () => { throw new Error("storage down"); });
    await applyRunEvents(successfulEvents, "conversation-a", "local-assistant", commands);
    expect(entries(log, "setRunState").some((entry) => entry.update?.uiPhase === "failed")).toBe(false);
    expect(entries(log, "setRunState").some((entry) => entry.update?.runError != null)).toBe(true);
  });
});

describe("regenerate reconciliation and stale-run protection", () => {
  it("a regenerate run reuses the original assistant slot without creating a second assistant message", async () => {
    const agent = makeAgent();
    const { commands, log } = makeCommands();

    // A completed A1 in the conversation, then the user regenerates it.
    await startRunForPrompt({
      conversationId: "conv-reg",
      assistantMessageId: "assistant-a1",
      sourceUserMessageId: "user-u1",
      prompt: "hi",
      agent,
      commands,
    });

    expect(entries(log, "addAssistantMessage")).toHaveLength(0);
    const persisted = entries(log, "persistAssistantMessage");
    expect(persisted).toHaveLength(1);
    expect(persisted[0].messageId).toBe("assistant-a1");
    expect(persisted[0].sourceUserMessageId).toBe("user-u1");
  });

  it("persists a completed run when it is still the current run", async () => {
    const { commands, log } = makeCommands();
    commands.getRunState = vi.fn(() => ({
      ...EMPTY_CONVERSATION_RUN,
      runEpoch: "epoch-current",
    }));
    await applyRunEvents(successfulEvents, "conv", "asm", commands, {
      sourceUserMessageId: "user-u1",
      runEpoch: "epoch-current",
    });
    const persisted = entries(log, "persistAssistantMessage");
    expect(persisted).toHaveLength(1);
    expect(persisted[0].messageId).toBe("asm");
    expect(persisted[0].sourceUserMessageId).toBe("user-u1");
  });

  it("a stale run that completes last never persists or paints its older response", async () => {
    const { commands, log } = makeCommands();
    commands.getRunState = vi.fn(() => ({
      ...EMPTY_CONVERSATION_RUN,
      runEpoch: "epoch-newer",
    }));

    await applyRunEvents(successfulEvents, "conv", "asm", commands, {
      sourceUserMessageId: "user-u1",
      runEpoch: "epoch-stale",
    });

    expect(entries(log, "persistAssistantMessage")).toHaveLength(0);
    expect(entries(log, "updateMessage")).toHaveLength(0);
    expect(entries(log, "setRunState")).toHaveLength(0);
  });

  it("a stale run must not flip the conversation phase to a terminal state", async () => {
    const { commands, log } = makeCommands();
    commands.getRunState = vi.fn(() => ({
      ...EMPTY_CONVERSATION_RUN,
      runEpoch: "epoch-newer",
    }));
    await applyRunEvents(successfulEvents, "conv", "asm", commands, {
      runEpoch: "epoch-stale",
    });
    expect(
      entries(log, "setRunState").some(
        (entry) => entry.update?.uiPhase === "completed",
      ),
    ).toBe(false);
  });

  it("abandons a run whose backend start resolves after a newer run superseded it", async () => {
    const { commands, log } = makeCommands();
    let startSlowResolve!: (run: RunResponse) => void;
    const startSlowGate = new Promise<RunResponse>((resolve) => {
      startSlowResolve = resolve;
    });
    const slowAgent = makeAgent({
      startRun: vi.fn(() => startSlowGate),
    });

    const slowRun = startRunForPrompt({
      conversationId: "conv",
      assistantMessageId: "asm",
      sourceUserMessageId: "user-u1",
      prompt: "A",
      agent: slowAgent,
      commands,
    });

    await startRunForPrompt({
      conversationId: "conv",
      assistantMessageId: "asm",
      sourceUserMessageId: "user-u1",
      prompt: "B",
      agent: makeAgent(),
      commands,
    });

    startSlowResolve({
      run_id: "run-slow",
      status: "completed",
      contract_version: "v1",
    });
    await slowRun;

    expect(slowAgent.getRunEvents).not.toHaveBeenCalled();
    expect(
      entries(log, "setRunState").some(
        (entry) => entry.update?.runId === "run-slow",
      ),
    ).toBe(false);
    const persisted = entries(log, "persistAssistantMessage");
    expect(persisted).toHaveLength(1);
  });

  it("rejects the first run without marking it failed when a newer run superseded it", async () => {
    const { commands, log } = makeCommands();
    commands.getRunState = vi.fn(() => ({
      ...EMPTY_CONVERSATION_RUN,
      runEpoch: "epoch-newer",
    }));
    const failingAgent = makeAgent({
      startRun: vi.fn(async () => {
        throw new Error("backend down");
      }),
    });

    await startRunForPrompt({
      conversationId: "conv",
      assistantMessageId: "asm",
      sourceUserMessageId: "user-u1",
      prompt: "A",
      agent: failingAgent,
      commands,
    });

    expect(
      entries(log, "setRunState").some(
        (entry) => entry.update?.uiPhase === "failed" || entry.update?.backendStatus === "failed",
      ),
    ).toBe(false);
    expect(
      entries(log, "updateMessage").some(
        (entry) => entry.patch?.status === "failed",
      ),
    ).toBe(false);
  });
});

describe("durable cancellation intent", () => {
  it.each([false, true])("keeps an accepted request active when events unavailable=%s", async (unavailable) => {
    const timestamp = "2026-09-27T12:00:00Z";
    const agent = makeAgent({
      cancelRun: vi.fn(async (): Promise<RunResponse> => ({
        run_id: "run-001", status: "running", contract_version: "v1",
        cancellation_requested_at: timestamp,
      })),
      getRunEvents: vi.fn(async () => {
        if (unavailable) throw new Error("offline");
        return [evt("run_started", "start"), evt("run_cancel_requested", "request")];
      }),
    });
    const { commands, log } = makeCommands();
    for (let i = 0; i < 2; i++) {
      await cancelActiveRun({ conversationId: "conv-x", runId: "run-001",
        assistantMessageId: "asm-x", agent, commands });
    }
    expect(hasRunStateUpdate(log, { cancellationRequestedAt: timestamp, backendStatus: "running" })).toBe(true);
    expect(hasRunStateUpdate(log, { backendStatus: "cancelled" })).toBe(false);
    expect(log.some((entry) => entry.patch?.status === "cancelled")).toBe(false);
  });

  it("allows completion to win despite durable cancellation intent", async () => {
    const { commands, log } = makeCommands();
    const agent = makeAgent({
      cancelRun: vi.fn(async (): Promise<RunResponse> => ({ run_id: "run-001", status: "completed", contract_version: "v1",
        cancellation_requested_at: "2026-09-27T12:00:00Z" })),
    });
    await cancelActiveRun({ conversationId: "conv-x", runId: "run-001",
      assistantMessageId: "asm-x", agent, commands });
    expect(hasRunStateUpdate(log, { backendStatus: "completed" })).toBe(true);
    expect(hasRunStateUpdate(log, { backendStatus: "cancelled" })).toBe(false);
  });
});

describe("refresh recovery", () => {
  const recoveredConversation = {
    id: "conversation-1",
    title: "Durable conversation",
    messages: [
      { id: "user-1", role: "user" as const, content: "Explain", status: "complete" as const },
      {
        id: "assistant-1",
        role: "assistant" as const,
        content: "Hello world",
        status: "streaming" as const,
        sourceUserMessageId: "user-1",
        sourceRunId: "run-recovered",
      },
    ],
  };

  it("selects only the visible regenerated assistant response", () => {
    const candidate = visibleRecoveryCandidate({
      ...recoveredConversation,
      messages: [
        recoveredConversation.messages[0],
        { ...recoveredConversation.messages[1], id: "assistant-old", sourceRunId: "run-old" },
        recoveredConversation.messages[1],
      ],
    });
    expect(candidate).toMatchObject({
      assistantMessageId: "assistant-1",
      sourceRunId: "run-recovered",
    });
  });

  it("recovers the durable run from cursor zero without creating a run or message", async () => {
    const { commands, log, runStateRecord } = makeCommands();
    const streamRun = vi.fn(async (_runId: string, options: { afterSequence?: number; onEvent(event: RunEvent): void | Promise<void> }) => {
      await options.onEvent({ ...evt("run_started", "event-1"), run_id: "run-recovered", sequence: 1 });
      await options.onEvent({ ...evt("message_content", "event-2", { message_id: "assistant-1", content: "Hel" }), run_id: "run-recovered", sequence: 2 });
      await options.onEvent({ ...evt("message_content", "event-3", { message_id: "assistant-1", content: "Hello" }), run_id: "run-recovered", sequence: 3 });
      await options.onEvent({ ...evt("message_content", "event-4", { message_id: "assistant-1", content: "Hello world!" }), run_id: "run-recovered", sequence: 4 });
      await options.onEvent({ ...evt("run_completed", "event-5"), run_id: "run-recovered", sequence: 5 });
    });
    const agent = makeAgent({
      startRun: vi.fn(),
      streamRun,
      getRun: vi.fn(async (): Promise<RunResponse> => ({
        run_id: "run-recovered", status: "running", assistant_message_id: "assistant-1", contract_version: "v1",
      })),
    });

    await recoverRunForConversation({ conversation: recoveredConversation, agent, commands });

    expect(agent.startRun).not.toHaveBeenCalled();
    expect(entries(log, "addAssistantMessage")).toHaveLength(0);
    expect(streamRun).toHaveBeenCalledWith("run-recovered", expect.objectContaining({ afterSequence: 0 }));
    expect(runStateRecord["conversation-1"]).toMatchObject({
      runId: "run-recovered",
      pendingMessageId: "assistant-1",
      backendStatus: "completed",
    });
    expect(runStateRecord["conversation-1"].runEpoch).toEqual(expect.any(String));
    expect(entries(log, "updateMessage").some((entry) => entry.patch?.content === "Hel" || entry.patch?.content === "Hello")).toBe(false);
    expect(entries(log, "updateMessage").some((entry) => entry.patch?.content === "Hello world!")).toBe(true);
  });

  it("does not observe a terminal durable run", async () => {
    const { commands } = makeCommands();
    const agent = makeAgent({
      getRun: vi.fn(async (): Promise<RunResponse> => ({
        run_id: "run-recovered", status: "completed", assistant_message_id: "assistant-1", contract_version: "v1",
      })),
    });

    await expect(recoverRunForConversation({ conversation: recoveredConversation, agent, commands })).resolves.toBe(false);
    expect(agent.streamRun).not.toHaveBeenCalled();
    expect(agent.startRun).not.toHaveBeenCalled();
  });
});
