/**
 * Phase 5.39 stale-event and replay race coverage for the resume loop.
 *
 * The resume loop is where two independent client-side races can corrupt a
 * conversation, and both are invisible in ordinary streaming tests because
 * neither involves a failure:
 *
 * 1. **Replay/live overlap.** A reconnect resumes from an exclusive cursor, so a
 *    transport that overlaps the tail re-delivers events the client already
 *    applied. The same event id at the same sequence must be applied *once*; the
 *    same sequence carrying a *different* event id is a protocol conflict and
 *    must be surfaced rather than quietly accepted, because that is exactly the
 *    shape of two writers claiming one sequence.
 * 2. **Supersession mid-stream.** A retry or regenerate makes a newer run
 *    current while the older run's transport is still open. Once the observer
 *    is no longer current it must apply nothing — not the in-flight event, not
 *    the rest of the batch — and must not reconnect, because reconnecting a
 *    superseded run is how a stale response ends up painted over fresh state.
 *
 * A third case, a duplicate event id inside a single live stream, is the
 * degenerate version of the first and is worth pinning because the durable log
 * makes it possible after a client-side retry of a request.
 *
 * These tests assert on the *observable* effects: what was applied, how many
 * times, and how many times the transport was opened. No sleeps, no timing.
 */

import { describe, expect, it, vi } from "vitest";

import type { RunEvent } from "@ava/contracts";

import { observeRunWithResume } from "./runStreamResume";

function event(
  sequence: number,
  eventType = "message_content",
  eventId = `event-${sequence}`,
): RunEvent {
  return {
    event_id: eventId,
    run_id: "run-1",
    sequence,
    event_type: eventType as RunEvent["event_type"],
    timestamp: "2026-09-29T00:00:00Z",
    payload: eventType === "message_content"
      ? { message_id: "message-1", content: `content-${sequence}` }
      : {},
    contract_version: "v1",
  };
}

const immediate = async (): Promise<void> => {};

/**
 * A streamRun double that replays a scripted set of attempts.
 *
 * Once the script runs out, further reconnects return an empty stream — a clean
 * EOF — so a test can watch the loop exhaust its retry allowance after a fault
 * without inventing a second failure to confuse the assertion.
 */
function scriptedAgent(attempts: RunEvent[][]) {
  const cursors: (number | undefined)[] = [];
  const agent = {
    streamRun: vi.fn(
      async (
        _runId: string,
        options: {
          afterSequence?: number;
          onEvent(event: RunEvent): void | Promise<void>;
        },
      ) => {
        cursors.push(options.afterSequence);
        const attempt = attempts[cursors.length - 1] ?? [];
        for (const value of attempt) {
          await options.onEvent(value);
        }
      },
    ),
  };
  return { agent, cursors };
}

function harness(overrides: Partial<Parameters<typeof observeRunWithResume>[0]> = {}) {
  const applied: RunEvent[] = [];
  const onExhausted = vi.fn();
  const isCurrent = vi.fn(() => true);
  const options = {
    agent: { streamRun: vi.fn(async () => {}) },
    runId: "run-1",
    isCurrent,
    applyEvent: async (value: RunEvent) => { applied.push(value); },
    reconcileSnapshot: async () => false,
    onExhausted,
    wait: immediate,
    ...overrides,
  };
  return { options, applied, onExhausted, isCurrent };
}

describe("replay and live overlap", () => {
  it("applies a duplicate event id at the same sequence exactly once", async () => {
    // The transport re-delivers event 1 mid-batch. Sequence and identity both
    // agree, so this is an overlap, not a conflict.
    const { agent, cursors } = scriptedAgent([
      [event(1), event(1), event(2, "run_completed")],
    ]);
    const { options, applied, onExhausted } = harness({ agent });

    await observeRunWithResume(options);

    expect(applied.map((value) => value.sequence)).toEqual([1, 2]);
    expect(cursors).toEqual([0]);
    expect(onExhausted).not.toHaveBeenCalled();
  });

  it("resumes past a tail the reconnect re-delivers instead of rewinding", async () => {
    // The reconnect resumes from cursor 2 but the transport overlaps events 1
    // and 2 again. They are already applied, so the loop must ignore them and
    // continue from 3 — never rewind the cursor, never double-apply content.
    const { agent, cursors } = scriptedAgent([
      [event(1), event(2)],
      [event(1), event(2), event(3, "run_completed")],
    ]);
    const { options, applied } = harness({ agent });

    await observeRunWithResume(options);

    expect(applied.map((value) => value.sequence)).toEqual([1, 2, 3]);
    // The exclusive cursor advanced rather than restarting.
    expect(cursors).toEqual([0, 2]);
  });

  it("surfaces a replayed sequence carrying a different event id as a protocol fault", async () => {
    // Sequence 2 is already applied, but under a new identity. This is the shape
    // of two writers claiming one sequence, so it must be reported, not applied.
    const { agent, cursors } = scriptedAgent([
      [event(1), event(2)],
      [event(2, "message_content", "other-event-2"), event(3, "run_completed")],
    ]);
    const { options, applied, onExhausted } = harness({ agent });

    await observeRunWithResume(options);

    // The first pass is legitimate; the contradictory replay is never applied,
    // and the cursor did not rewind to re-read it.
    expect(applied.map((value) => value.event_id)).toEqual(["event-1", "event-2"]);
    expect(cursors.slice(0, 2)).toEqual([0, 2]);
    // Exhausted rather than silently trusting a contradictory log.
    expect(onExhausted).toHaveBeenCalled();
    expect(String(onExhausted.mock.calls.at(-1)?.[0])).toMatch(/sequence/i);
  });

  it("rejects an event id reused at a different sequence", async () => {
    const { agent } = scriptedAgent([
      [event(1, "message_content", "shared-id"), event(2, "message_content", "shared-id")],
    ]);
    const { options, applied, onExhausted } = harness({ agent });

    await observeRunWithResume(options);

    // Only the first event landed; the identity reuse was refused.
    expect(applied.map((value) => value.sequence)).toEqual([1]);
    expect(onExhausted).toHaveBeenCalled();
    expect(String(onExhausted.mock.calls.at(-1)?.[0])).toMatch(/event id/i);
  });
});

describe("supersession mid-stream", () => {
  it("applies nothing once a newer run becomes current, and never reconnects", async () => {
    // The retry that supersedes this run lands after the first event. The
    // remaining events of this batch, including a terminal one, are the old
    // run's business and must not touch state.
    const { agent, cursors } = scriptedAgent([
      [event(1), event(2, "run_completed")],
    ]);
    let calls = 0;
    const isCurrent = vi.fn(() => {
      calls += 1;
      // True while event 1 is applied, false from then on.
      return calls <= 2;
    });
    const { options, applied, onExhausted } = harness({ agent, isCurrent });

    await observeRunWithResume(options);

    expect(applied.map((value) => value.sequence)).toEqual([1]);
    // One transport only: a superseded observer must not resume.
    expect(cursors).toEqual([0]);
    expect(onExhausted).not.toHaveBeenCalled();
  });

  it("does not report transport failure for a run that was merely superseded", async () => {
    // A superseded run is abandoned, not broken. Surfacing "live updates
    // disconnected" would tell the user something is wrong when a retry simply
    // took over.
    const { agent } = scriptedAgent([[event(1)]]);
    const isCurrent = vi.fn(() => {
      // Exhaust every retry allowance as "not current".
      return isCurrent.mock.calls.length < 2;
    });
    const { options, onExhausted } = harness({ agent, isCurrent });

    await observeRunWithResume(options);

    expect(onExhausted).not.toHaveBeenCalled();
  });

  it("applies nothing at all when the run was superseded before the first event", async () => {
    const { agent } = scriptedAgent([[event(1), event(2, "run_completed")]]);
    const { options, applied } = harness({ agent, isCurrent: () => false });

    await observeRunWithResume(options);

    expect(applied).toEqual([]);
  });

  it("stops mid-batch when supersession lands between two events", async () => {
    // The in-flight event is applied, the next one is not: the batch is
    // abandoned at the first sign of supersession rather than drained.
    const { agent } = scriptedAgent([[event(1), event(2), event(3, "run_completed")]]);
    let appliedCount = 0;
    const isCurrent = () => appliedCount < 1;
    const { options, applied } = harness({
      agent,
      isCurrent,
      applyEvent: async (value: RunEvent) => {
        applied.push(value);
        appliedCount += 1;
      },
    });

    await observeRunWithResume(options);

    expect(applied.map((value) => value.sequence)).toEqual([1]);
  });
});
