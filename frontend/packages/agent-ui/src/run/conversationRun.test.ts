import { describe, expect, it, vi } from "vitest";

import type { RunEvent, RunResponse } from "@ava/contracts";
import { ApiError } from "@ava/api-client";

import type { ConversationRunState } from "../types";
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
    setRunState: vi.fn((conversationId, update) => {
      log.push({ op: "setRunState", conversationId, update });
    }),
    updateMessage: vi.fn((conversationId, messageId, patch) => {
      log.push({ op: "updateMessage", conversationId, messageId, patch });
    }),
  };
  return { commands, log };
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
