import { describe, expect, it, vi } from "vitest";

import { ApiClient, ApiError, getCapabilities } from "./index";

describe("getCapabilities", () => {
  it("returns the capabilities response from the backend", async () => {
    const body = {
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

    const capabilities = await getCapabilities(client);

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/capabilities",
      expect.any(Object),
    );
    expect(capabilities).toEqual(body);
  });

  it("throws ApiError on a non-OK response", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error_code: "internal_error" }), { status: 500 }),
    );
    const client = new ApiClient({
      baseUrl: "http://localhost:8000",
      fetchImpl: fetchMock,
    });

    await expect(getCapabilities(client)).rejects.toBeInstanceOf(ApiError);
  });
});