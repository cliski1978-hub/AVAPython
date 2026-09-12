import { describe, expect, it } from "vitest";

import { CONTRACT_VERSION } from "./version";
import type { RunEvent } from "./index";

describe("event contract", () => {
  it("types a run event envelope", () => {
    const event: RunEvent = {
      event_id: "evt-1",
      run_id: "run-1",
      event_type: "run_started",
      timestamp: "2026-09-07T00:00:00Z",
      payload: { source: "test" },
      contract_version: "v1",
    };
    expect(event.event_type).toBe("run_started");
    expect(event.contract_version).toBe(CONTRACT_VERSION);
  });
});