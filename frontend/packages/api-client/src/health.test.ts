import { describe, expect, it, vi } from "vitest";

import { ApiClient, ApiError, getHealth } from "./index";

describe("getHealth", () => {
  it("returns the health response from the backend", async () => {
    const body = {
      status: "healthy",
      application: "AVA",
      contract_version: "v1",
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

    const health = await getHealth(client);

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/health",
      expect.any(Object),
    );
    expect(health).toEqual(body);
  });

  it("throws ApiError on a non-OK response", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: "not_found" }), { status: 404 }),
    );
    const client = new ApiClient({
      baseUrl: "http://localhost:8000",
      fetchImpl: fetchMock,
    });

    await expect(getHealth(client)).rejects.toBeInstanceOf(ApiError);
  });
});