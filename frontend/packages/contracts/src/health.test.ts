import { describe, expect, it } from "vitest";

import { CONTRACT_VERSION } from "./version";
import type { HealthResponse } from "./health";

describe("health contract", () => {
  it("matches the backend /health response shape", () => {
    const response: HealthResponse = {
      status: "healthy",
      application: "AVA",
      contract_version: "v1",
    };
    expect(response.status).toBe("healthy");
    expect(response.application).toBe("AVA");
    expect(response.contract_version).toBe(CONTRACT_VERSION);
  });
});