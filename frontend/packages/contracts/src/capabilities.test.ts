import { describe, expect, it } from "vitest";

import { CONTRACT_VERSION } from "./version";
import type { CapabilitiesResponse } from "./index";

describe("capabilities contract", () => {
  it("matches the backend /capabilities response shape", () => {
    const response: CapabilitiesResponse = {
      contract_version: "v1",
      application: "AVA",
      capabilities: {
        health: true,
        runs: false,
        streaming: false,
        tool_calling: false,
        structured_output: false,
        cancellation: false,
        document_operations: false,
        approvals: false,
        local_model: false,
        local_execution: false,
      },
    };
    expect(response.contract_version).toBe(CONTRACT_VERSION);
    expect(response.capabilities.health).toBe(true);
    expect(response.capabilities.runs).toBe(false);
  });
});