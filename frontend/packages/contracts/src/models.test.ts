import { describe, expect, it } from "vitest";

import type { ModelDiscoveryResponse } from "./index";

describe("model catalog contracts", () => {
  it("models the public-safe GET /models response", () => {
    const response: ModelDiscoveryResponse = {
      contract_version: "v1",
      models: [{
        provider_name: "local",
        provider_id: "local",
        model_id: "ava/local",
        display_name: "Local",
        context_limit: null,
        hosting_mode: "local",
        enabled: true,
        qualifications: [],
        capabilities: {
          chat: true, streaming: false, tool_calling: true, structured_output: false,
          vision: false, embeddings: false, reasoning: false, code_specialization: false,
          contract_version: "v1",
        },
        contract_version: "v1",
      }],
    };

    expect(Object.keys(response.models[0]).sort()).toEqual([
      "capabilities", "context_limit", "contract_version", "display_name", "enabled",
      "hosting_mode", "model_id", "provider_id", "provider_name", "qualifications",
    ]);
  });
});
