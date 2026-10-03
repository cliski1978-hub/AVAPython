// @vitest-environment jsdom
import { ApiClient } from "@ava/api-client";
import { ConversationProvider, useConversationState } from "@ava/agent-ui";
import { act, render, screen, waitFor } from "@testing-library/react";
import { StrictMode, useEffect, useRef } from "react";
import { describe, expect, it } from "vitest";

type Deferred<T> = {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (error: Error) => void;
};

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function jsonResponse(value: unknown): Response {
  return new Response(JSON.stringify(value), { status: 200, headers: { "Content-Type": "application/json" } });
}

const conversation = (id: string, title: string) => ({
  conversation_id: id,
  title,
  created_at: "2026-10-03T00:00:00Z",
  updated_at: "2026-10-03T00:00:00Z",
  is_pinned: false,
  is_archived: false,
  folder_id: null,
  project_id: null,
  contract_version: "v1" as const,
});

describe("shared loading recovery diagnostics", () => {
  it("ignores an older StrictMode startup result after a newer request succeeds", async () => {
    const older = deferred<Response>();
    const newer = deferred<Response>();
    const trace: Array<{
      requestId: number;
      method: string;
      url: string;
      startedAt: number;
      endedAt?: number;
      status?: number;
      errorName?: string;
    }> = [];
    let requestId = 0;
    let conversationRequestCount = 0;
    let observedState = "unobserved";

    const fetchImpl: typeof fetch = (input, init) => {
      const url = String(input);
      const id = ++requestId;
      const entry: (typeof trace)[number] = { requestId: id, method: init?.method ?? "GET", url, startedAt: Date.now() };
      trace.push(entry);
      const path = new URL(url).pathname;
      let response: Promise<Response>;
      if (path === "/conversations") {
        conversationRequestCount += 1;
        response = conversationRequestCount === 1 ? older.promise : newer.promise;
      } else if (path === "/conversation-folders") {
        response = Promise.resolve(jsonResponse({ contract_version: "v1", folders: [] }));
      } else if (path.startsWith("/conversations/")) {
        response = Promise.resolve(jsonResponse({ contract_version: "v1", conversation_id: "latest", messages: [] }));
      } else {
        response = Promise.reject(new Error(`Unexpected startup request: ${path}`));
      }
      return response.then((result) => {
        entry.endedAt = Date.now();
        entry.status = result.status;
        return result;
      }, (error: unknown) => {
        entry.endedAt = Date.now();
        entry.errorName = error instanceof Error ? error.name : "UnknownError";
        throw error;
      });
    };

    const client = new ApiClient({ baseUrl: "http://ava.test", fetchImpl });
    function Probe() {
      const manager = useConversationState();
      const identity = useRef("conversation-provider-consumer");
      const description = `${identity.current}:${manager.state.loading ? "loading" : manager.state.loadError ? "error" : `ready:${manager.conversations.map((item) => item.title).join(",")}`}`;
      useEffect(() => {
        observedState = description;
      }, [manager.conversations, manager.state.loadError, manager.state.loading]);
      return <output data-testid="conversation-state">{description}</output>;
    }

    render(<StrictMode><ConversationProvider client={client}><Probe /></ConversationProvider></StrictMode>);
    await waitFor(() => expect(conversationRequestCount).toBe(2));

    await act(async () => {
      newer.resolve(jsonResponse({ contract_version: "v1", conversations: [conversation("latest", "Latest response")] }));
      await newer.promise;
    });
    await screen.findByText("conversation-provider-consumer:ready:Latest response");

    await act(async () => {
      older.reject(new TypeError("simulated stale transport failure"));
      await expect(older.promise).rejects.toThrow("simulated stale transport failure");
    });

    expect(screen.getByTestId("conversation-state").textContent).toBe("conversation-provider-consumer:ready:Latest response");
    await waitFor(() => expect(observedState).toBe("conversation-provider-consumer:ready:Latest response"));
    expect(trace).toHaveLength(5);
    expect(trace.map((entry) => [entry.method, new URL(entry.url).pathname])).toEqual([
      ["GET", "/conversations"],
      ["GET", "/conversation-folders"],
      ["GET", "/conversations"],
      ["GET", "/conversation-folders"],
      ["GET", "/conversations/latest/messages"],
    ]);
    expect(trace[0]?.errorName).toBe("TypeError");
    expect(trace[2]?.status).toBe(200);
    expect(trace.every((entry) => entry.endedAt != null && entry.endedAt >= entry.startedAt)).toBe(true);
  });
});
