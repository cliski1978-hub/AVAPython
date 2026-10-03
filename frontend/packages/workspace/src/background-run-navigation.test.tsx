// @vitest-environment jsdom
/**
 * Background conversation reconciliation after navigation.
 *
 * Run ownership belongs to the conversation and its durable run, never to the
 * selected conversation. These tests hold a run's stream open so a navigation
 * can happen mid-flight, then assert that the hidden conversation's projection
 * keeps advancing and that returning to it needs no refresh.
 *
 * The backend is mocked at the api-client boundary with a controllable durable
 * store: emitting an event also persists it, exactly as the real backend does,
 * so "stale cache" and "lost run" stay distinguishable.
 */
import { ApiClient } from "@ava/api-client";
import {
  AgentRunProvider,
  ConversationList,
  ConversationProvider,
  ConversationView,
  useAgentRun,
  useConversationState,
} from "@ava/agent-ui";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const TS = "2026-01-01T00:00:00Z";

interface StoredRun {
  runId: string;
  conversationId: string;
  assistantMessageId: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  sequence: number;
}

interface StoredMessage {
  message_id: string;
  conversation_id: string;
  role: "user" | "assistant";
  content: string;
  status: "pending" | "complete" | "failed" | "cancelled";
  source_run_id?: string;
  source_user_message_id?: string;
}

let serverConversations: Array<{ conversation_id: string; title: string }> = [];
let serverMessages: Record<string, StoredMessage[]> = {};
const runs = new Map<string, StoredRun>();
/** Live observer per run, mirroring the single SSE controller per run id. */
const observers = new Map<string, (event: unknown) => void>();
let nextRunId = 1;
let nextMessageId = 1;

vi.mock("@ava/api-client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@ava/api-client")>();
  return {
    ...mod,
    listConversations: vi.fn().mockImplementation(async () => ({
      contract_version: "v1",
      conversations: serverConversations.map((conversation) => ({
        ...conversation,
        created_at: TS,
        updated_at: TS,
        contract_version: "v1" as const,
      })),
    })),
    listMessages: vi.fn().mockImplementation(
      async (_client: unknown, conversationId: string) => ({
        contract_version: "v1" as const,
        conversation_id: conversationId,
        messages: (serverMessages[conversationId] ?? []).map((message) => ({
          ...message,
          created_at: TS,
          updated_at: TS,
          contract_version: "v1" as const,
        })),
      }),
    ),
    createConversation: vi.fn().mockImplementation(
      async (_client: unknown, request?: { title?: string | null }) => {
        const conversation = {
          conversation_id: `conversation-${serverConversations.length + 1}`,
          title: request?.title ?? "New Conversation",
        };
        serverConversations = [...serverConversations, conversation];
        return { ...conversation, created_at: TS, updated_at: TS, contract_version: "v1" as const };
      },
    ),
    createMessage: vi.fn().mockImplementation(
      async (
        _client: unknown,
        conversationId: string,
        request: { content: string; role?: string },
      ) => {
        const message: StoredMessage = {
          message_id: `message-${nextMessageId++}`,
          conversation_id: conversationId,
          role: request.role === "assistant" ? "assistant" : "user",
          content: request.content,
          status: "complete",
        };
        serverMessages[conversationId] = [...(serverMessages[conversationId] ?? []), message];
        return { ...message, created_at: TS, updated_at: TS, contract_version: "v1" as const };
      },
    ),
    updateConversation: vi.fn().mockImplementation(
      async (_client: unknown, conversationId: string, request: { title?: string | null }) => {
        const current = serverConversations.find((item) => item.conversation_id === conversationId);
        if (current == null) throw new Error("not found");
        const updated = { ...current, title: request.title ?? current.title };
        serverConversations = serverConversations.map((item) => item.conversation_id === conversationId ? updated : item);
        return { ...updated, created_at: TS, updated_at: TS, is_pinned: false, is_archived: false, folder_id: null, contract_version: "v1" as const };
      },
    ),
    listConversationFolders: vi.fn().mockResolvedValue({ folders: [{ folder_id: "folder-1", name: "Work", position: 0, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" }] }),
    setConversationFolder: vi.fn().mockImplementation(async (_client: unknown, conversationId: string, request: { folder_id: string | null }) => {
      const current = serverConversations.find((item) => item.conversation_id === conversationId);
      if (current == null) throw new Error("not found");
      return { ...current, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", folder_id: request.folder_id, is_pinned: false, is_archived: false, contract_version: "v1" as const };
    }),
    startRun: vi.fn().mockImplementation(
      async (
        _client: unknown,
        request: { conversation_id?: string; source_user_message_id?: string },
      ) => {
        const runId = `run-${nextRunId++}`;
        const conversationId = request.conversation_id ?? "unknown";
        const userMessage = (serverMessages[conversationId] ?? []).find(
          (message) => message.message_id === request.source_user_message_id,
        );
        const assistantMessageId = `assistant-${runId}`;
        serverMessages[conversationId] = [
          ...(serverMessages[conversationId] ?? []),
          {
            message_id: assistantMessageId,
            conversation_id: conversationId,
            role: "assistant",
            content: "",
            status: "pending",
            source_run_id: runId,
            source_user_message_id: userMessage?.message_id,
          },
        ];
        runs.set(runId, {
          runId,
          conversationId,
          assistantMessageId,
          status: "running",
          sequence: 0,
        });
        return {
          run_id: runId,
          status: "running",
          assistant_message_id: assistantMessageId,
          contract_version: "v1" as const,
        };
      },
    ),
    getRun: vi.fn().mockImplementation(async (_client: unknown, runId: string) => {
      const run = runs.get(runId);
      if (run == null) throw new Error("not found");
      return {
        run_id: run.runId,
        status: run.status,
        assistant_message_id: run.assistantMessageId,
        cancellation_requested_at: null,
        contract_version: "v1" as const,
      };
    }),
    streamRun: vi.fn().mockImplementation(
      async (
        _client: unknown,
        runId: string,
        options: {
          signal?: AbortSignal;
          afterSequence?: number;
          onEvent(event: unknown): void | Promise<void>;
        },
      ) => {
        observers.set(runId, options.onEvent);
        // The API cursor is exclusive, so a (re)connecting observer receives
        // every event after the one it last applied.
        for (const event of runEvents.get(runId) ?? []) {
          if ((event["sequence"] as number) <= (options.afterSequence ?? 0)) continue;
          if (options.signal?.aborted) return;
          await options.onEvent(event);
        }
        await new Promise<void>((resolve) => {
          const finish = () => {
            options.signal?.removeEventListener("abort", finish);
            observers.delete(runId);
            resolve();
          };
          options.signal?.addEventListener("abort", finish);
        });
      },
    ),
  };
});

const client = new ApiClient({ baseUrl: "http://localhost:99999" });

/**
 * Deliver one durable event: persist it to the durable store first (as the
 * backend does), then hand it to every live observer.
 */
async function emit(
  runId: string,
  event: { event_type: string; payload?: Record<string, unknown> },
): Promise<void> {
  const run = runs.get(runId);
  if (run == null) throw new Error(`unknown run ${runId}`);
  run.sequence += 1;
  if (event.event_type === "message_content") {
    const content = String(event.payload?.content ?? "");
    serverMessages[run.conversationId] = (serverMessages[run.conversationId] ?? []).map(
      (message) =>
        message.message_id === run.assistantMessageId
          ? { ...message, content, status: "complete" as const }
          : message,
    );
  }
  if (event.event_type === "run_completed") run.status = "completed";
  if (event.event_type === "run_failed") run.status = "failed";
  if (event.event_type === "run_cancelled") run.status = "cancelled";
  const stored = {
    event_id: `${runId}-${run.sequence}`,
    run_id: runId,
    event_type: event.event_type,
    timestamp: TS,
    payload: {
      ...event.payload,
      ...(event.event_type === "message_content"
        ? { message_id: run.assistantMessageId }
        : {}),
    },
    sequence: run.sequence,
    contract_version: "v1",
  };
  runEvents.set(runId, [...(runEvents.get(runId) ?? []), stored]);

  const observer = observers.get(runId);
  if (observer == null) return;
  await act(async () => {
    await observer(stored);
  });
}

/** Durable event log per run, replayed from the exclusive cursor like the API. */
const runEvents = new Map<string, Array<Record<string, unknown>>>();

function seed(id: string, title: string): void {
  serverConversations = [...serverConversations, { conversation_id: id, title }];
  serverMessages[id] = [];
}

function conversationItem(id: string): HTMLElement {
  const element = document.querySelector(`[data-conversation-item="${id}"]`);
  if (element == null) throw new Error(`Missing conversation item ${id}`);
  return element as HTMLElement;
}

function assistants(): HTMLElement[] {
  return Array.from(
    document.querySelectorAll('[data-message-role="assistant"]'),
  ) as HTMLElement[];
}

function transcriptText(): string {
  return assistants().map((element) => element.textContent ?? "").join("|");
}

/** Reports the cache for a conversation that is not selected. */
function CacheProbe({ conversationId }: { conversationId: string }) {
  const conversation = useConversationState();
  const cached = conversation.state.conversations.find((item) => item.id === conversationId);
  const assistant = cached?.messages.find((message) => message.role === "assistant");
  return (
    <span
      data-testid={`cache-${conversationId}`}
      data-cache-content={assistant?.content ?? ""}
      data-cache-phase={cached?.run?.uiPhase ?? "idle"}
      data-cache-run={cached?.run?.runId ?? ""}
      data-cache-folder={cached?.folderId ?? ""}
    />
  );
}

function Harness({ probeId }: { probeId: string }) {
  const conversation = useConversationState();
  const run = useAgentRun();
  return (
    <div>
      <button type="button" onClick={() => void run.submitPrompt("long prompt")}>
        start-a
      </button>
      <button type="button" onClick={() => void conversation.moveConversation("conversation-1", "folder-1")}>
        move-a-to-work
      </button>
      <span data-testid="is-running">{String(run.isRunning)}</span>
      <CacheProbe conversationId={probeId} />
      <ConversationList
        conversations={conversation.conversations}
        activeConversationId={conversation.activeConversation?.id ?? null}
        onNewChat={() => void conversation.createConversation()}
        onSelect={(id) => void conversation.selectConversation(id)}
        onRename={async (id, title) => {
          await conversation.renameConversation(id, title);
        }}
        error={conversation.state.error ?? null}
      />
      <ConversationView conversation={conversation.activeConversation} />
    </div>
  );
}

async function renderWorkspace(): Promise<ReturnType<typeof render>> {
  const view = render(
    <ConversationProvider client={client}>
      <AgentRunProvider client={client}>
        <Harness probeId="conversation-1" />
      </AgentRunProvider>
    </ConversationProvider>,
  );
  await waitFor(() => {
    expect(conversationItem("conversation-1")).toBeDefined();
  });
  return view;
}

async function startRunInA(): Promise<string> {
  fireEvent.click(screen.getByRole("button", { name: "start-a" }));
  await waitFor(() => {
    expect(runs.size).toBe(1);
  });
  const runId = [...runs.keys()][0];
  await waitFor(() => {
    expect(observers.has(runId)).toBe(true);
  });
  return runId;
}

function cacheContent(conversationId: string): string {
  return (
    document.querySelector(`[data-testid="cache-${conversationId}"]`)?.getAttribute("data-cache-content") ?? ""
  );
}

beforeEach(() => {
  serverConversations = [];
  serverMessages = {};
  runs.clear();
  observers.clear();
  runEvents.clear();
  nextRunId = 1;
  nextMessageId = 1;
  seed("conversation-1", "A");
  seed("conversation-2", "B");
});

describe("background conversation reconciliation after navigation", () => {
  it("keeps observing a run whose conversation is no longer selected", async () => {
    await renderWorkspace();
    fireEvent.click(conversationItem("conversation-1"));
    await waitFor(() => {
      expect(conversationItem("conversation-1").getAttribute("aria-current")).toBe("true");
    });
    const runId = await startRunInA();

    await emit(runId, { event_type: "message_content", payload: { content: "Hello" } });
    await waitFor(() => {
      expect(transcriptText()).toContain("Hello");
    });

    // Navigate away mid-stream. The backend run must keep going.
    fireEvent.click(conversationItem("conversation-2"));
    await waitFor(() => {
      expect(conversationItem("conversation-2").getAttribute("aria-current")).toBe("true");
    });
    expect(runs.get(runId)?.status).toBe("running");

    // The run is still observed in the background, so the hidden
    // conversation's cache keeps advancing.
    await emit(runId, { event_type: "message_content", payload: { content: "Hello world" } });
    await waitFor(() => {
      expect(cacheContent("conversation-1")).toBe("Hello world");
    });

    await emit(runId, { event_type: "run_completed" });
    await waitFor(() => {
      expect(cacheContent("conversation-1")).toBe("Hello world");
    });
  });

  it("shows the latest content on return without a refresh or duplicate bubble", async () => {
    await renderWorkspace();
    fireEvent.click(conversationItem("conversation-1"));
    await waitFor(() => {
      expect(conversationItem("conversation-1").getAttribute("aria-current")).toBe("true");
    });
    const runId = await startRunInA();
    await emit(runId, { event_type: "message_content", payload: { content: "Hello" } });
    await waitFor(() => {
      expect(transcriptText()).toContain("Hello");
    });

    fireEvent.click(conversationItem("conversation-2"));
    await waitFor(() => {
      expect(conversationItem("conversation-2").getAttribute("aria-current")).toBe("true");
    });
    await emit(runId, { event_type: "message_content", payload: { content: "Hello world" } });
    await emit(runId, { event_type: "run_completed" });

    fireEvent.click(conversationItem("conversation-1"));
    await waitFor(() => {
      expect(transcriptText()).toContain("Hello world");
    });
    expect(transcriptText()).not.toContain("HelloHello");
    expect(assistants()).toHaveLength(1);
  });

  it("allows renaming a streaming background conversation without losing its observer", async () => {
    await renderWorkspace();
    const runId = await startRunInA();
    fireEvent.click(conversationItem("conversation-2"));
    await waitFor(() => expect(conversationItem("conversation-2").getAttribute("aria-current")).toBe("true"));

    fireEvent.click(screen.getByRole("button", { name: "Conversation actions for long prompt" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Rename" }));
    const input = screen.getByRole("textbox", { name: "Rename conversation" });
    fireEvent.change(input, { target: { value: "Renamed A" } });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => expect(conversationItem("conversation-1").getAttribute("title")).toBe("Renamed A"));
    expect(conversationItem("conversation-2").getAttribute("aria-current")).toBe("true");
    expect(runs.get(runId)?.status).toBe("running");
    expect(observers.has(runId)).toBe(true);

    await emit(runId, { event_type: "message_content", payload: { content: "Continued after rename" } });
    await waitFor(() => expect(cacheContent("conversation-1")).toBe("Continued after rename"));
    fireEvent.click(conversationItem("conversation-1"));
    await waitFor(() => expect(transcriptText()).toContain("Continued after rename"));
  });

  it("keeps observing an active run while its conversation moves into a folder", async () => {
    await renderWorkspace();
    const runId = await startRunInA();

    fireEvent.click(screen.getByRole("button", { name: "move-a-to-work" }));
    await waitFor(() => {
      expect(document.querySelector('[data-testid="cache-conversation-1"]')?.getAttribute("data-cache-folder")).toBe("folder-1");
    });
    expect(observers.has(runId)).toBe(true);
    expect(runs.get(runId)?.status).toBe("running");

    await emit(runId, { event_type: "message_content", payload: { content: "Still streaming after move" } });
    await waitFor(() => expect(cacheContent("conversation-1")).toBe("Still streaming after move"));
    fireEvent.click(conversationItem("conversation-2"));
    await waitFor(() => expect(conversationItem("conversation-2").getAttribute("aria-current")).toBe("true"));
    fireEvent.click(conversationItem("conversation-1"));
    await waitFor(() => expect(transcriptText()).toContain("Still streaming after move"));
  });

  it("shows a response that completed while the conversation was hidden", async () => {
    await renderWorkspace();
    fireEvent.click(conversationItem("conversation-1"));
    await waitFor(() => {
      expect(conversationItem("conversation-1").getAttribute("aria-current")).toBe("true");
    });
    const runId = await startRunInA();
    await emit(runId, { event_type: "message_content", payload: { content: "Hello" } });
    await waitFor(() => {
      expect(transcriptText()).toContain("Hello");
    });

    fireEvent.click(conversationItem("conversation-2"));
    await waitFor(() => {
      expect(conversationItem("conversation-2").getAttribute("aria-current")).toBe("true");
    });
    await emit(runId, {
      event_type: "message_content",
      payload: { content: "Hello world, finished while hidden" },
    });
    await emit(runId, { event_type: "run_completed" });

    fireEvent.click(conversationItem("conversation-1"));
    await waitFor(() => {
      expect(transcriptText()).toContain("finished while hidden");
    });
    expect(assistants()).toHaveLength(1);
  });

  it("does not leave a completed hidden run showing a stale active phase", async () => {
    await renderWorkspace();
    fireEvent.click(conversationItem("conversation-1"));
    await waitFor(() => {
      expect(conversationItem("conversation-1").getAttribute("aria-current")).toBe("true");
    });
    const runId = await startRunInA();
    await emit(runId, { event_type: "message_content", payload: { content: "Hello" } });
    fireEvent.click(conversationItem("conversation-2"));
    await waitFor(() => {
      expect(conversationItem("conversation-2").getAttribute("aria-current")).toBe("true");
    });
    await emit(runId, { event_type: "run_completed" });

    await waitFor(() => {
      expect(
        document
          .querySelector('[data-testid="cache-conversation-1"]')
          ?.getAttribute("data-cache-phase"),
      ).not.toBe("running");
    });
  });

  it("reports a run that failed while hidden with a terminal failed state", async () => {
    await renderWorkspace();
    fireEvent.click(conversationItem("conversation-1"));
    await waitFor(() => {
      expect(conversationItem("conversation-1").getAttribute("aria-current")).toBe("true");
    });
    const runId = await startRunInA();
    await emit(runId, { event_type: "message_content", payload: { content: "partial answer" } });
    await waitFor(() => {
      expect(transcriptText()).toContain("partial answer");
    });

    fireEvent.click(conversationItem("conversation-2"));
    await waitFor(() => {
      expect(conversationItem("conversation-2").getAttribute("aria-current")).toBe("true");
    });
    await emit(runId, {
      event_type: "run_failed",
      payload: { error_code: "provider_authentication_failed", error: "boom" },
    });

    fireEvent.click(conversationItem("conversation-1"));
    await waitFor(() => {
      expect(
        document.querySelector('[data-message-role="assistant"]')?.getAttribute("data-message-state"),
      ).toBe("failed");
    });
  });

  it("does not cancel a run merely because the user navigated away", async () => {
    await renderWorkspace();
    fireEvent.click(conversationItem("conversation-1"));
    await waitFor(() => {
      expect(conversationItem("conversation-1").getAttribute("aria-current")).toBe("true");
    });
    const runId = await startRunInA();
    await emit(runId, { event_type: "message_content", payload: { content: "Hello" } });

    fireEvent.click(conversationItem("conversation-2"));
    await waitFor(() => {
      expect(conversationItem("conversation-2").getAttribute("aria-current")).toBe("true");
    });
    // No cancel request reached the backend and the run keeps its run id.
    expect(runs.get(runId)?.status).toBe("running");
    expect(observers.has(runId)).toBe(true);
  });

  it("shows a cancelled terminal state when a run is cancelled while hidden", async () => {
    await renderWorkspace();
    fireEvent.click(conversationItem("conversation-1"));
    await waitFor(() => {
      expect(conversationItem("conversation-1").getAttribute("aria-current")).toBe("true");
    });
    const runId = await startRunInA();
    await emit(runId, { event_type: "message_content", payload: { content: "Hello" } });
    await waitFor(() => {
      expect(transcriptText()).toContain("Hello");
    });

    fireEvent.click(conversationItem("conversation-2"));
    await waitFor(() => {
      expect(conversationItem("conversation-2").getAttribute("aria-current")).toBe("true");
    });
    await emit(runId, { event_type: "run_cancelled" });

    fireEvent.click(conversationItem("conversation-1"));
    await waitFor(() => {
      expect(
        document.querySelector('[data-message-role="assistant"]')?.getAttribute("data-message-state"),
      ).toBe("cancelled");
    });
  });

  it("keeps refresh recovery working after the navigation fix", async () => {
    const first = await renderWorkspace();
    fireEvent.click(conversationItem("conversation-1"));
    await waitFor(() => {
      expect(conversationItem("conversation-1").getAttribute("aria-current")).toBe("true");
    });
    const runId = await startRunInA();
    await emit(runId, { event_type: "message_content", payload: { content: "Hello" } });

    // A refresh is a brand new session with the same durable store: the whole
    // provider tree is torn down and rebuilt from persisted facts.
    first.unmount();
    const observersWhileGone = observers.has(runId);
    await renderWorkspace();
    fireEvent.click(conversationItem("conversation-1"));
    await waitFor(() => {
      expect(transcriptText()).toContain("Hello");
    });
    // Recovery re-owned the run and continues the same run from its durable
    // snapshot, so the same message keeps growing.
    expect(observersWhileGone).toBe(false);
    await waitFor(() => {
      expect(observers.has(runId)).toBe(true);
    });
    await emit(runId, { event_type: "message_content", payload: { content: "Hello world" } });
    await waitFor(() => {
      expect(transcriptText()).toContain("Hello world");
    });
    expect(assistants()).toHaveLength(1);
  });
});
