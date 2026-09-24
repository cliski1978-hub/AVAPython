import { describe, expect, it, vi } from "vitest";

import { ApiClient, ApiError, getModelProviders } from "./index";

describe("getModelProviders", () => {
  it("returns the model provider discovery response from the backend", async () => {
    const body = {
      contract_version: "v1",
      default_provider_id: "local",
      providers: [
        {
          provider_id: "local",
          is_default: true,
          model_info: {
            provider_name: "local",
            model_id: "local-model",
            display_name: null,
            context_limit: null,
            contract_version: "v1",
          },
          health: {
            available: true,
            status: "healthy",
            message: null,
            contract_version: "v1",
          },
          contract_version: "v1",
        },
      ],
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const client = new ApiClient({
      baseUrl: "http://localhost:8000",
      fetchImpl: fetchMock,
    });

    const providers = await getModelProviders(client);

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/model-providers",
      expect.any(Object),
    );
    expect(providers).toEqual(body);
  });

  it("throws ApiError on a non-OK response", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error_code: "internal_error" }), { status: 500 }),
    );
    const client = new ApiClient({
      baseUrl: "http://localhost:8000",
      fetchImpl: fetchMock,
    });

    await expect(getModelProviders(client)).rejects.toBeInstanceOf(ApiError);
  });
});