import { describe, expect, it } from "vitest";

import type { RunEvent } from "@ava/contracts";

import {
  applyRunEvent,
  messageStatusForRunStatus,
  payloadString,
  uiPhaseForBackendStatus,
} from "./runEventProcessor";

function event(
  eventType: string,
  payload: Record<string, unknown> = {},
): RunEvent {
  return {
    event_id: "evt-1",
    run_id: "run-001",
    event_type: eventType as RunEvent["event_type"],
    timestamp: "2026-09-12T00:00:00Z",
    payload: payload as RunEvent["payload"],
    contract_version: "v1",
  };
}

describe("applyRunEvent", () => {
  it("maps run_started to running phase, backend status, and streaming message", () => {
    const effects = applyRunEvent(event("run_started"));
    expect(effects).toEqual([
      { kind: "setPhase", phase: "running" },
      { kind: "setBackendStatus", backendStatus: "running" },
      { kind: "setMessageStatus", messageStatus: "streaming" },
    ]);
  });

  it("maps message_started to an informational association", () => {
    const effects = applyRunEvent(
      event("message_started", { message_id: "msg-backend-1" }),
    );
    expect(effects).toEqual([
      { kind: "associateMessage", messageId: "msg-backend-1" },
    ]);
  });

  it("maps message_content to a content update", () => {
    const effects = applyRunEvent(
      event("message_content", { content: "Hello AVA" }),
    );
    expect(effects).toEqual([
      { kind: "setMessageContent", messageId: null, content: "Hello AVA" },
    ]);
  });

  it("maps run_completed to completed phase + backend status + message complete", () => {
    const effects = applyRunEvent(event("run_completed"));
    expect(effects).toEqual([
      { kind: "setPhase", phase: "completed" },
      { kind: "setBackendStatus", backendStatus: "completed" },
      { kind: "setMessageStatus", messageStatus: "complete" },
    ]);
  });

  it("maps run_cancelled to cancelled phase + backend status + message cancelled", () => {
    const effects = applyRunEvent(event("run_cancelled"));
    expect(effects).toEqual([
      { kind: "setPhase", phase: "cancelled" },
      { kind: "setBackendStatus", backendStatus: "cancelled" },
      { kind: "setMessageStatus", messageStatus: "cancelled" },
    ]);
  });

  it("maps run_failed to failed phase + backend status + message failed", () => {
    const effects = applyRunEvent(event("run_failed"));
    expect(effects).toEqual([
      { kind: "setPhase", phase: "failed" },
      { kind: "setBackendStatus", backendStatus: "failed" },
      { kind: "setMessageStatus", messageStatus: "failed" },
    ]);
  });

  it("ignores unknown AVA event types so future events are safe", () => {
    for (const unknown of ["tool_started", "approval_requested", "doc_written", "snapshot_taken"]) {
      expect(applyRunEvent(event(unknown))).toEqual([{ kind: "ignore" }]);
    }
  });

  it("tolerates missing payload fields", () => {
    const effects = applyRunEvent(
      event("message_content", { other: "x" }),
    );
    expect(effects).toEqual([{ kind: "setMessageContent", messageId: null, content: "" }]);
  });
});

describe("payloadString", () => {
  it("returns string values as-is", () => {
    expect(payloadString({ content: "hi" }, "content")).toBe("hi");
  });

  it("coerces non-string JSON values to empty string", () => {
    expect(payloadString({ content: 42 as unknown as string }, "content")).toBe("");
    expect(payloadString({ content: null }, "content")).toBe("");
    expect(payloadString({ content: { deep: "x" } }, "content")).toBe("");
  });
});

describe("messageStatusForRunStatus", () => {
  it("maps AVA run statuses to UI message statuses", () => {
    expect(messageStatusForRunStatus("completed")).toBe("complete");
    expect(messageStatusForRunStatus("cancelled")).toBe("cancelled");
    expect(messageStatusForRunStatus("failed")).toBe("failed");
    expect(messageStatusForRunStatus("pending")).toBe("pending");
    expect(messageStatusForRunStatus("running")).toBe("pending");
  });
});

describe("uiPhaseForBackendStatus", () => {
  it("maps AVA run statuses to UI phases", () => {
    expect(uiPhaseForBackendStatus("completed")).toBe("completed");
    expect(uiPhaseForBackendStatus("cancelled")).toBe("cancelled");
    expect(uiPhaseForBackendStatus("failed")).toBe("failed");
    expect(uiPhaseForBackendStatus("pending")).toBe("running");
    expect(uiPhaseForBackendStatus("running")).toBe("running");
  });
});
