import { describe, expect, it } from "vitest";

import { CONTRACT_VERSION } from "./version";
import type { RunRequest, RunResponse } from "./index";

describe("run contracts", () => {
  it("types a run request", () => {
    const request: RunRequest = { prompt: "Summarize the document" };
    expect(request.prompt).toBe("Summarize the document");
  });

  it("types a run response", () => {
    const response: RunResponse = { run_id: "run-1", status: "completed", contract_version: "v1" };
    expect(response.status).toBe("completed");
    expect(response.contract_version).toBe(CONTRACT_VERSION);
  });
});