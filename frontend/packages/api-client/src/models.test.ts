import { describe, expect, it, vi } from "vitest";

import { ApiClient, getModels } from "./index";

describe("getModels", () => {
  it("returns the safe configured-model catalog from the backend", async () => {
    const body = {
      contract_version: "v1",
      models: [{
        provider_name: "local",
        model_id: "ava/local",
        display_name: "Local",
        context_limit: null,
        capabilities: {
          chat: true, streaming: false, tool_calling: false, structured_output: false,
          vision: false, embeddings: false, reasoning: false, code_specialization: false,
          contract_version: "v1",
        },
        provider_id: "local",
        hosting_mode: "local",
        enabled: true,
        qualifications: [],
        contract_version: "v1",
      }],
    };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status: 200 }));
    const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });

    expect(await getModels(client)).toEqual(body);
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/models", expect.any(Object));
  });
});
