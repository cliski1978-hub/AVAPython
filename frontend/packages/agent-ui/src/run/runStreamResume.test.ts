import { describe, expect, it, vi } from "vitest";

import type { RunEvent } from "@ava/contracts";

import { observeRunWithResume } from "./runStreamResume";

function event(sequence: number, eventType = "message_content"): RunEvent {
  return {
    event_id: `event-${sequence}`,
    run_id: "run-1",
    sequence,
    event_type: eventType as RunEvent["event_type"],
    timestamp: "2026-09-27T00:00:00Z",
    payload: eventType === "message_content"
      ? { message_id: "message-1", content: `content-${sequence}` }
      : {},
    contract_version: "v1",
  };
}

const immediate = async (): Promise<void> => {};

describe("observeRunWithResume", () => {
  it("resumes from the last successfully applied exclusive sequence", async () => {
    const cursors: number[] = [];
    const applied: number[] = [];
    const agent = {
      streamRun: vi.fn(async (_runId: string, options: { afterSequence?: number; onEvent(event: RunEvent): void | Promise<void> }) => {
        cursors.push(options.afterSequence ?? 0);
        if (cursors.length === 1) {
          await options.onEvent(event(1));
          return;
        }
        await options.onEvent(event(2));
        await options.onEvent(event(3, "run_completed"));
      }),
    };

    await observeRunWithResume({
      agent,
      runId: "run-1",
      isCurrent: () => true,
      applyEvent: async (value) => { applied.push(value.sequence as number); },
      reconcileSnapshot: async () => false,
      onExhausted: vi.fn(),
      wait: immediate,
    });

    expect(cursors).toEqual([0, 1]);
    expect(applied).toEqual([1, 2, 3]);
  });

  it("repairs a sequence gap from the last contiguous cursor without applying the gap", async () => {
    const cursors: number[] = [];
    const applied: number[] = [];
    const agent = {
      streamRun: vi.fn(async (_runId: string, options: { afterSequence?: number; onEvent(event: RunEvent): void | Promise<void> }) => {
        cursors.push(options.afterSequence ?? 0);
        if (cursors.length === 1) {
          await options.onEvent(event(2));
          return;
        }
        await options.onEvent(event(1));
        await options.onEvent(event(2));
        await options.onEvent(event(3, "run_completed"));
      }),
    };

    await observeRunWithResume({
      agent,
      runId: "run-1",
      isCurrent: () => true,
      applyEvent: async (value) => { applied.push(value.sequence as number); },
      reconcileSnapshot: async () => false,
      onExhausted: vi.fn(),
      wait: immediate,
    });

    expect(cursors).toEqual([0, 0]);
    expect(applied).toEqual([1, 2, 3]);
  });

  it("stops after a terminal snapshot without inventing a missing terminal event", async () => {
    const applyEvent = vi.fn();
    const reconcileSnapshot = vi.fn(async () => true);
    const agent = {
      streamRun: vi.fn(async () => {}),
    };

    await observeRunWithResume({
      agent,
      runId: "run-1",
      isCurrent: () => true,
      applyEvent,
      reconcileSnapshot,
      onExhausted: vi.fn(),
      wait: immediate,
    });

    expect(reconcileSnapshot).toHaveBeenCalledOnce();
    expect(applyEvent).not.toHaveBeenCalled();
    expect(agent.streamRun).toHaveBeenCalledOnce();
  });

  it("does not reconnect an intentionally aborted observation", async () => {
    const controller = new AbortController();
    controller.abort();
    const agent = { streamRun: vi.fn() };

    await observeRunWithResume({
      agent,
      runId: "run-1",
      signal: controller.signal,
      isCurrent: () => true,
      applyEvent: vi.fn(),
      reconcileSnapshot: vi.fn(async () => false),
      onExhausted: vi.fn(),
      wait: immediate,
    });

    expect(agent.streamRun).not.toHaveBeenCalled();
  });
});
