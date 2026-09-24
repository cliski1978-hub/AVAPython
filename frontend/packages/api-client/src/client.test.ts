import { describe, expect, it, vi } from "vitest";

import { ApiError, subscribeConnectivity } from "./client";
import { ApiClient } from "./index";
import { updateDocument } from "./documents";
import { startRun } from "./runs";

function makeClient(fetchImpl: typeof fetch): ApiClient {
  return new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl });
}

describe("ApiClient request", () => {
  it("reports a transport failure from the real chat and document request paths across client instances", async () => {
    const seen: string[] = [];
    const unsubscribe = subscribeConnectivity((status) => seen.push(status));
    const chatClient = makeClient(vi.fn().mockRejectedValue(new TypeError("backend down")));
    const documentClient = makeClient(vi.fn().mockRejectedValue(new TypeError("backend down")));

    await expect(startRun(chatClient, { prompt: "Hello" })).rejects.toThrow("backend down");
    await expect(updateDocument(documentClient, "document-1", { content: "<p>Draft</p>", content_format: "html" })).rejects.toThrow("backend down");

    unsubscribe();
    expect(seen).toEqual(["unavailable", "unavailable"]);
  });

  it("reports reachability for HTTP errors and a later successful request", async () => {
    const seen: string[] = [];
    const unsubscribe = subscribeConnectivity((status) => seen.push(status));
    const client = makeClient(vi.fn()
      .mockRejectedValueOnce(new TypeError("backend down"))
      .mockResolvedValueOnce(new Response("unavailable", { status: 503 }))
      .mockResolvedValueOnce(new Response("{}", { status: 200 })));

    await expect(client.request("/health")).rejects.toThrow("backend down");
    await expect(client.request("/health")).rejects.toBeInstanceOf(ApiError);
    await client.request("/health");

    unsubscribe();
    expect(seen).toEqual(["unavailable", "reachable", "reachable"]);
  });
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

  it("does not force a JSON Content-Type on FormData bodies", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
    const client = makeClient(fetchMock);
    const formData = new FormData();
    formData.append("file", new Blob([new Uint8Array([1, 2, 3])]), "a.txt");

    await client.request("/attachments", { method: "POST", body: formData });

    const [, init] = fetchMock.mock.calls[0];
    const headers = init?.headers as Record<string, string>;
    expect(headers["Content-Type"]).toBeUndefined();
    expect(headers["Accept"]).toBe("application/json");
    expect(init?.body).toBeInstanceOf(FormData);
  });

  it("can pass a pre-set Content-Type header untouched on FormData bodies", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
    const client = makeClient(fetchMock);
    const formData = new FormData();

    await client.request("/attachments", {
      method: "POST",
      body: formData,
      headers: { "X-Custom": "yes" },
    });

    const headers = fetchMock.mock.calls[0][1]?.headers as Record<string, string>;
    expect(headers["Content-Type"]).toBeUndefined();
    expect(headers["X-Custom"]).toBe("yes");
  });

  it("still injects a JSON Content-Type for JSON string bodies", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
    const client = makeClient(fetchMock);

    await client.request("/runs", { method: "POST", body: JSON.stringify({ prompt: "Hi" }) });

    const headers = fetchMock.mock.calls[0][1]?.headers as Record<string, string>;
    expect(headers["Content-Type"]).toBe("application/json");
  });
});

describe("ApiClient requestBlob", () => {
  it("decodes a successful response as a Blob without JSON round-tripping", async () => {
    const bytes = Uint8Array.from({ length: 256 }, (_, index) => index);
    const fetchMock = vi.fn().mockResolvedValue(new Response(new Blob([bytes]), { status: 200 }));
    const client = makeClient(fetchMock);

    const blob = await client.requestBlob("/attachments/a-1/content");

    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/attachments/a-1/content", expect.any(Object));
    expect(blob).toBeInstanceOf(Blob);
    expect(Array.from(new Uint8Array(await blob.arrayBuffer()))).toEqual(Array.from(bytes));
  });

  it("turns non-2xx responses into ApiError instead of a Blob", async () => {
    const errorBody = { error_code: "attachment_content_unavailable", message: "nope" };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(errorBody), { status: 409, headers: { "Content-Type": "application/json" } }),
    );
    const client = makeClient(fetchMock);

    const error = (await client.requestBlob("/attachments/a-1/content").catch((err) => err)) as ApiError;

    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(409);
    expect(error.body).toEqual(errorBody);
  });
});
