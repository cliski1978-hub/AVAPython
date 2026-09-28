import { describe, expect, it, vi } from "vitest";

import {
  ApiClient,
  ApiError,
  cancelRun,
  getRun,
  getRunEvents,
  startRun,
  streamRun,
  RunStreamProtocolError,
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

function sseResponse(frames: string[], contentType = "text/event-stream"): Response {
  const encoder = new TextEncoder();
  return new Response(new ReadableStream({
    start(controller) {
      for (const frame of frames) controller.enqueue(encoder.encode(frame));
      controller.close();
    },
  }), { headers: { "Content-Type": contentType } });
}

function sseEvent(eventId = "event-1", type = "run_completed"): string {
  const event = {
    event_id: eventId, run_id: "run-001", sequence: 4, event_type: type,
    timestamp: "2026-09-27T00:00:00Z", payload: {}, contract_version: "v1",
  };
  return `id: ${eventId}\nevent: ${type}\ndata: ${JSON.stringify(event)}\n\n`;
}

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

describe("getRunEvents replay cursor", () => {
  it("serializes an exclusive after-sequence cursor", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse([]));
    await getRunEvents(makeClient(fetchMock), "run-001", 7);
    expect(fetchMock.mock.calls[0][0]).toBe("http://localhost:8000/runs/run-001/events?after_sequence=7");
  });

  it("rejects a negative cursor before issuing a request", async () => {
    const fetchMock = vi.fn();
    await expect(getRunEvents(makeClient(fetchMock), "run-001", -1)).rejects.toBeInstanceOf(RangeError);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("streamRun", () => {
  it("serializes an exclusive resume cursor and rejects an invalid cursor locally", async () => {
    const fetchMock = vi.fn().mockResolvedValue(sseResponse([sseEvent()]));
    await streamRun(makeClient(fetchMock), "run-001", {
      afterSequence: 4,
      onEvent: vi.fn(),
    });
    expect(fetchMock.mock.calls[0][0]).toBe("http://localhost:8000/runs/run-001/stream?after_sequence=4");

    const invalid = vi.fn();
    await expect(streamRun(makeClient(invalid), "run-001", {
      afterSequence: -1,
      onEvent: vi.fn(),
    })).rejects.toBeInstanceOf(RangeError);
    expect(invalid).not.toHaveBeenCalled();
  });

  it("parses typed AVA SSE envelopes and sends the SSE accept header", async () => {
    const fetchMock = vi.fn().mockResolvedValue(sseResponse([sseEvent()]));
    const received: unknown[] = [];
    await streamRun(makeClient(fetchMock), "run-001", { onEvent: (event) => { received.push(event); } });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/runs/run-001/stream");
    expect(init.signal).toBeUndefined();
    expect((init.headers as HeadersInit)).toEqual({ Accept: "text/event-stream" });
    expect(received).toEqual([{
      event_id: "event-1", run_id: "run-001", sequence: 4, event_type: "run_completed",
      timestamp: "2026-09-27T00:00:00Z", payload: {}, contract_version: "v1",
    }]);
  });

  it("ignores heartbeat frames and rejects malformed envelopes", async () => {
    const heartbeatClient = makeClient(vi.fn().mockResolvedValue(sseResponse([": heartbeat\n\n"])));
    await expect(streamRun(heartbeatClient, "run-001", { onEvent: vi.fn() })).resolves.toBeUndefined();

    const brokenClient = makeClient(vi.fn().mockResolvedValue(sseResponse([
      "id: broken\nevent: run_completed\ndata: not-json\n\n",
    ])));
    await expect(streamRun(brokenClient, "run-001", { onEvent: vi.fn() }))
      .rejects.toBeInstanceOf(RunStreamProtocolError);
  });

  it("honors AbortSignal without sending a cancellation command", async () => {
    const controller = new AbortController();
    const fetchMock = vi.fn().mockResolvedValue(sseResponse([sseEvent()]));
    await streamRun(makeClient(fetchMock), "run-001", { signal: controller.signal, onEvent: vi.fn() });
    expect((fetchMock.mock.calls[0][1] as RequestInit).signal).toBe(controller.signal);
    expect(fetchMock).toHaveBeenCalledTimes(1);
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
