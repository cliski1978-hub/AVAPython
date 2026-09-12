import { describe, expect, it, vi } from "vitest";

import { ApiError } from "./client";
import { ApiClient } from "./index";

function makeClient(fetchImpl: typeof fetch): ApiClient {
  return new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl });
}

describe("ApiClient request", () => {
  it("normalizes a base URL that ends with a slash", async () => {
    const baseUrl = "http://localhost:8000/";
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
    const client = new ApiClient({ baseUrl, fetchImpl: fetchMock });

    await client.request("/health");

    expect(fetchMock.mock.calls[0][0]).toBe("http://localhost:8000/health");
  });

  it("prefixes a path that lacks a leading slash", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
    const client = makeClient(fetchMock);

    await client.request("capabilities");

    expect(fetchMock.mock.calls[0][0]).toBe("http://localhost:8000/capabilities");
  });

  it("does not send a Content-Type header on bodyless requests", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
    const client = makeClient(fetchMock);

    await client.request("/health");

    const headers = fetchMock.mock.calls[0][1]?.headers as Record<string, string>;
    expect(headers["Content-Type"]).toBeUndefined();
    expect(headers["Accept"]).toBe("application/json");
  });

  it("adds a JSON Content-Type header when a body is present", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
    const client = makeClient(fetchMock);

    await client.request("/runs", { method: "POST", body: JSON.stringify({ prompt: "Hi" }) });

    const headers = fetchMock.mock.calls[0][1]?.headers as Record<string, string>;
    expect(headers["Content-Type"]).toBe("application/json");
  });

  it("parses structured error bodies", async () => {
    const errorBody = { error_code: "internal_error", message: "boom" };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(errorBody), { status: 500 }),
    );
    const client = makeClient(fetchMock);

    const error = (await client.request("/capabilities").catch((err) => err)) as ApiError;

    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(500);
    expect(error.body).toEqual(errorBody);
  });

  it("keeps raw text for malformed error bodies", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("not json", { status: 502 }));
    const client = makeClient(fetchMock);

    const error = (await client.request("/capabilities").catch((err) => err)) as ApiError;

    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(502);
    expect(error.body).toBe("not json");
  });
});