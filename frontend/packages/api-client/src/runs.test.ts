import { describe, expect, it, vi } from "vitest";

import {
  ApiClient,
  ApiError,
  cancelRun,
  getRun,
  getRunEvents,
  startRun,
} from "./index";

function makeClient(fetchImpl: typeof fetch): ApiClient {
  return new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl });
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const runResponse = {
  run_id: "run-001",
  status: "completed",
  contract_version: "v1",
};

describe("startRun", () => {
  it("POSTs the serialized RunRequest to /runs and parses RunResponse", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(runResponse));
    const client = makeClient(fetchMock);

    const result = await startRun(client, { prompt: "Hello AVA" });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/runs");
    expect(init.method).toBe("POST");
    expect(init.body).toBe(JSON.stringify({ prompt: "Hello AVA" }));
    expect(result).toEqual(runResponse);
    expect(result.contract_version).toBe("v1");
  });

  it("throws ApiError on a backend run failure", async () => {
    const body = {
      error_code: "internal_error",
      category: "internal",
      message: "An internal error occurred.",
      recoverable: false,
      details: {},
      correlation_id: null,
      contract_version: "v1",
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(body, 500));
    const client = makeClient(fetchMock);

    const error = await startRun(client, { prompt: "boom" }).catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(500);
    expect((error as ApiError).body).toEqual(body);
  });
});

describe("getRun", () => {
  it("GETs /runs/{run_id} and parses RunResponse", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(runResponse));
    const client = makeClient(fetchMock);

    const result = await getRun(client, "run-001");

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/runs/run-001");
    expect(init.method ?? "GET").toBe("GET");
    expect(result).toEqual(runResponse);
  });

  it("throws ApiError carrying the ErrorResponse body on 404", async () => {
    const body = {
      error_code: "run_not_found",
      category: "not_found",
      message: "Unknown run: run-404",
      recoverable: false,
      details: {},
      correlation_id: null,
      contract_version: "v1",
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(body, 404));
    const client = makeClient(fetchMock);

    const error = await getRun(client, "run-404").catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(404);
    const errBody = (error as ApiError).body as Record<string, unknown>;
    expect(errBody.error_code).toBe("run_not_found");
    expect(errBody.category).toBe("not_found");
  });
});

describe("getRunEvents", () => {
  it("GETs /runs/{run_id}/events and parses the RunEvent array", async () => {
    const events = [
      {
        event_id: "e1",
        run_id: "run-001",
        event_type: "run_started",
        timestamp: "2026-09-12T00:00:00Z",
        payload: {},
        contract_version: "v1",
      },
      {
        event_id: "e2",
        run_id: "run-001",
        event_type: "run_completed",
        timestamp: "2026-09-12T00:00:01Z",
        payload: {},
        contract_version: "v1",
      },
    ];
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(events));
    const client = makeClient(fetchMock);

    const result = await getRunEvents(client, "run-001");

    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toBe("http://localhost:8000/runs/run-001/events");
    expect(result).toEqual(events);
    expect(result[0].event_type).toBe("run_started");
  });
});

describe("cancelRun", () => {
  it("POSTs /runs/{run_id}/cancel without a body and parses RunResponse", async () => {
    const cancelled = { ...runResponse, status: "cancelled" };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(cancelled));
    const client = makeClient(fetchMock);

    const result = await cancelRun(client, "run-001");

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/runs/run-001/cancel");
    expect(init.method).toBe("POST");
    expect(init.body).toBeUndefined();
    expect(result.status).toBe("cancelled");
  });

  it("throws ApiError on a non-OK cancel response", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ detail: "nope" }, 500));
    const client = makeClient(fetchMock);

    await expect(cancelRun(client, "run-001")).rejects.toBeInstanceOf(ApiError);
  });
});