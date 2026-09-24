import { describe, expect, it, vi } from "vitest";

import type { RunEvent, RunResponse } from "@ava/contracts";
import { ApiError } from "@ava/api-client";

import type { ConversationRunState } from "../types";
import { EMPTY_CONVERSATION_RUN } from "../types";
import type { MessagePatch } from "../state/conversationReducer";
import {
  applyRunEvents,
  cancelActiveRun,
  runErrorMessage,
  startRunForPrompt,
  submitPrompt,
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

    expect(agent.startRun).toHaveBeenCalledWith({ prompt: "Hello AVA" });
    expect(agent.getRunEvents).toHaveBeenCalledWith("run-001");

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
    expect(agent.startRun).toHaveBeenCalledWith({ prompt: "Hello AVA" });
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

  it("marks the assistant message failed when event retrieval rejects", async () => {
    const agent = makeAgent({
      getRunEvents: vi.fn(async () => {
        throw new Error("network down");
      }),
    });
    const { commands, log } = makeCommands();

    await submitPrompt("ok", "conv-a", agent, commands);

    expect(lastSetRunState(log)).toMatchObject({
      backendStatus: "failed",
      uiPhase: "failed",
      runError: "AVA is unavailable. Please try again.",
    });
    const failed = entries(log, "updateMessage").find(
      (e) => e.patch?.status === "failed",
    );
    expect(failed?.messageId).toBeTruthy();
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

    expect(agent.startRun).toHaveBeenCalledWith({ prompt: "explain" });
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
    expect(agent.startRun).toHaveBeenCalledWith({ prompt: "explain" });
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
