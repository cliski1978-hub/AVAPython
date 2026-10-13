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
    removeMessage: vi.fn((conversationId, messageId) => {
      log.push({ op: "removeMessage", conversationId, messageId });
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

  it("removes the optimistic assistant shell and rejects the submission when run creation fails", async () => {
    const agent = makeAgent({
      startRun: vi.fn(async () => {
        throw new ApiError("Configuration missing", 422, {
          error_code: "configuration_missing",
          category: "validation",
          message: "The selected execution configuration is incomplete.",
        });
      }),
    });
    const { commands, log } = makeCommands();

    await expect(submitPrompt("boom", "conv-a", agent, commands)).rejects.toBeInstanceOf(ApiError);

    expect(agent.getRunEvents).not.toHaveBeenCalled();
    expect(lastSetRunState(log)).toMatchObject({
      backendStatus: null,
      uiPhase: "idle",
      runError: "Unable to start this run. The selected execution configuration is incomplete. Choose a valid runtime, model, and provider, then try again.",
    });

    expect(entries(log, "updateMessage").some((e) => e.patch?.status === "failed")).toBe(false);
    expect(entries(log, "removeMessage")).toContainEqual(expect.objectContaining({
      conversationId: "conv-a",
    }));
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
      runError: "Connection to AVA was interrupted.",
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
  it("does not let a late cancellation result mutate the newer run", async () => {
    let resolveCancel!: (response: RunResponse) => void;
    const cancelGate = new Promise<RunResponse>((resolve) => { resolveCancel = resolve; });
    const agent = makeAgent({ cancelRun: vi.fn(() => cancelGate) });
    const { commands, log, runStateRecord } = makeCommands();
    runStateRecord["conv-a"] = {
      ...EMPTY_CONVERSATION_RUN,
      runId: "run-a",
      runEpoch: "epoch-a",
      backendStatus: "running",
      uiPhase: "running",
      pendingMessageId: "message-a",
    };

    const cancellation = cancelActiveRun({
      conversationId: "conv-a", runId: "run-a", runEpoch: "epoch-a",
      assistantMessageId: "message-a", agent, commands,
    });
    runStateRecord["conv-a"] = {
      ...EMPTY_CONVERSATION_RUN,
      runId: "run-b",
      runEpoch: "epoch-b",
      backendStatus: "running",
      uiPhase: "running",
      pendingMessageId: "message-b",
      runError: null,
    };
    resolveCancel({ run_id: "run-a", status: "cancelled", contract_version: "v1" });
    await cancellation;

    expect(runStateRecord["conv-a"]).toMatchObject({
      runId: "run-b", runEpoch: "epoch-b", backendStatus: "running", uiPhase: "running",
      pendingMessageId: "message-b", runError: null,
    });
    expect(entries(log, "updateMessage").some((entry) => entry.messageId === "message-b")).toBe(false);
  });

  it("does not let a late cancellation error mutate the newer run", async () => {
    let rejectCancel!: (error: Error) => void;
    const cancelGate = new Promise<RunResponse>((_resolve, reject) => { rejectCancel = reject; });
    const agent = makeAgent({ cancelRun: vi.fn(() => cancelGate) });
    const { commands, runStateRecord } = makeCommands();
    runStateRecord["conv-a"] = { ...EMPTY_CONVERSATION_RUN, runId: "run-a", runEpoch: "epoch-a", backendStatus: "running", uiPhase: "running", pendingMessageId: "message-a" };
    const cancellation = cancelActiveRun({ conversationId: "conv-a", runId: "run-a", runEpoch: "epoch-a", assistantMessageId: "message-a", agent, commands });
    runStateRecord["conv-a"] = { ...EMPTY_CONVERSATION_RUN, runId: "run-b", runEpoch: "epoch-b", backendStatus: "running", uiPhase: "running", pendingMessageId: "message-b", runError: null };
    rejectCancel(new Error("late failure"));
    await cancellation;
    expect(runStateRecord["conv-a"]).toMatchObject({ runId: "run-b", runEpoch: "epoch-b", backendStatus: "running", uiPhase: "running", pendingMessageId: "message-b", runError: null });
  });

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
      runError: "Connection to AVA was interrupted.",
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
  it("uses AVA-owned wording for known API errors", () => {
    const error = new ApiError("t", 500, {
      category: "internal",
      message: "An internal error occurred.",
    });
    expect(runErrorMessage(error)).toBe("Connection to AVA was interrupted.");
  });

  it("does not expose HTTP status wording when the body has no message", () => {
    expect(runErrorMessage(new ApiError("t", 502, {}))).toBe(
      "Connection to AVA was interrupted.",
    );
  });

  it("uses a stable message for non-API failures", () => {
    expect(runErrorMessage(new Error("boom"))).toBe(
      "Connection to AVA was interrupted.",
    );
  });

  it("maps a conversation concurrency conflict to localized feedback", () => {
    expect(runErrorMessage(new ApiError("t", 409, {
      error_code: "conversation_run_active",
    }))).toBe("This conversation already has a response in progress.");
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

  it("treats a run failed by backend restart recovery as terminal, not as work to resume", async () => {
    // Phase 5.30 settles stranded active runs as `failed` at cold start. A
    // refresh after that restart must show the durable partial text and the
    // failed projection, and must not resurrect an observer for an execution
    // that no longer exists.
    const { commands, log, runStateRecord } = makeCommands();
    const agent = makeAgent({
      getRun: vi.fn(async (): Promise<RunResponse> => ({
        run_id: "run-recovered",
        status: "failed",
        assistant_message_id: "assistant-1",
        cancellation_requested_at: "2026-05-06T07:08:09+00:00",
        contract_version: "v1",
      })),
    });

    await expect(
      recoverRunForConversation({ conversation: recoveredConversation, agent, commands }),
    ).resolves.toBe(false);

    expect(agent.streamRun).not.toHaveBeenCalled();
    expect(agent.startRun).not.toHaveBeenCalled();
    // No frontend run state is created, so there is nothing to cancel or resume.
    expect(runStateRecord["conversation-1"]).toBeUndefined();
    // Nothing is mutated: the durable text and the server's failed projection
    // come from hydration alone, with no replacement assistant message.
    expect(log).toHaveLength(0);
  });
});

// ============================================================
// BEGIN: Charter B - incremental snapshot application
// ============================================================


describe("streaming content snapshots", () => {
  /**
   * Every ``message_content`` payload is the whole text so far, never a delta.
   * Downstream code replaces content; appending here is what duplicates the
   * prefix on every update and corrupts replay and refresh.
   */
  it("replaces the assistant content on each snapshot rather than appending", () => {
    const { commands, log } = makeCommands();
    const snapshots = ["Hel", "Hello ", "Hello world"];

    applyRunEvents(
      [
        evt("run_started", "e1"),
        evt("message_started", "e2", { message_id: "msg-1" }),
        ...snapshots.map((content, index) =>
          evt("message_content", `e${index + 3}`, { content }),
        ),
        evt("run_completed", "e9"),
      ],
      "conv-x",
      "asm-x",
      commands,
    );

    const contents = entries(log, "updateMessage")
      .map((entry) => entry.patch?.content)
      .filter((content): content is string => typeof content === "string");

    expect(contents).toEqual(snapshots);
    // Strictly growing, and the final text is the single final snapshot.
    expect(contents[contents.length - 1]).toBe("Hello world");
    expect(contents.some((content) => content.includes("Hello Hello"))).toBe(false);
  });

  it("marks the assistant message as streaming until the terminal event", () => {
    const { commands, log } = makeCommands();

    applyRunEvents(
      [
        evt("run_started", "e1"),
        evt("message_started", "e2", { message_id: "msg-1" }),
        evt("message_content", "e3", { content: "partial" }),
        evt("run_completed", "e4"),
      ],
      "conv-x",
      "asm-x",
      commands,
    );

    const statuses = entries(log, "updateMessage").map((entry) => entry.patch?.status);
    expect(statuses).toContain("streaming");
    expect(statuses[statuses.length - 1]).toBe("complete");
  });
});

// ============================================================
// END: Charter B - incremental snapshot application
// ============================================================

// ============================================================
// BEGIN: Charter B - progressive projection during a live run
// ============================================================


describe("progressive content projection", () => {
  /**
   * Drives a real run through the orchestration path with a deferred stream,
   * so each snapshot is projected while the run is still open. Asserts the
   * user-visible property: one assistant message whose text grows, never a
   * second bubble and never an appended duplicate.
   */
  it("grows one assistant message across successive snapshots before completion", async () => {
    const { commands, log } = makeCommands();
    let emit!: (event: RunEvent) => void;
    let resolveStream!: () => void;
    const stream = new Promise<void>((resolve) => { resolveStream = resolve; });
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
    emit({ ...evt("run_started", "s1"), sequence: 1 });
    emit({ ...evt("message_started", "s2", { message_id: "backend-assistant" }), sequence: 2 });

    const contents = () =>
      entries(log, "updateMessage")
        .map((entry) => entry.patch?.content)
        .filter((content): content is string => typeof content === "string");

    const snapshots = ["Hel", "Hello ", "Hello world"];
    for (const [index, content] of snapshots.entries()) {
      emit({ ...evt("message_content", `c${index}`, {
        message_id: "backend-assistant", content,
      }), sequence: index + 3 });
      // Each snapshot is visible before the next one is even emitted.
      await vi.waitFor(() => expect(contents().at(-1)).toBe(content));
      // The run is still open: no terminal status was projected.
      expect(
        entries(log, "updateMessage").some((e) => e.patch?.status === "complete"),
      ).toBe(false);
    }
    expect(contents()).toEqual(snapshots);

    // Every content update lands on the one backend assistant message; the
    // local placeholder is only ever touched with status, never with text.
    const contentOwners = new Set(
      entries(log, "updateMessage")
        .filter((entry) => typeof entry.patch?.content === "string")
        .map((entry) => entry.messageId),
    );
    expect(contentOwners).toEqual(new Set(["backend-assistant"]));

    emit({ ...evt("run_completed", "s9"), sequence: 9 });
    resolveStream();
    await running;
  });
});

// ============================================================
// END: Charter B - progressive projection during a live run
// ============================================================
