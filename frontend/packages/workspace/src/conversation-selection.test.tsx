// @vitest-environment jsdom
import { ApiClient, ApiError } from "@ava/api-client";
import {
  cancelRun,
  createConversation,
  createMessage,
  deleteConversation,
  getRunEvents,
  listConversations,
  listMessages,
  startRun,
  streamRun,
  updateConversation,
} from "@ava/api-client";
import {
  AgentRunProvider,
  ConversationList,
  ConversationProvider,
  ConversationView,
  useAgentRun,
  useConversationState,
} from "@ava/agent-ui";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const PROMPT = "Original question";
const TS = "2026-01-01T00:00:00Z";

type TestRunEvent = Awaited<ReturnType<typeof getRunEvents>>[number];

interface MockConversationResponse {
  conversation_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  is_pinned: boolean;
  is_archived: boolean;
  folder_id: string | null;
  project_id: string | null;
  contract_version: "v1";
}

interface MockMessageResponse {
  message_id: string;
  conversation_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  status: "pending" | "complete" | "failed" | "cancelled";
  created_at: string;
  updated_at: string;
  contract_version: "v1";
}

interface MockMessageListResponse {
  conversation_id: string;
  messages: MockMessageResponse[];
  contract_version: "v1";
}

let nextConversationId = 1;
let nextRunId = 1;
let nextMessageId = 1;
let serverConversations: MockConversationResponse[] = [];
let serverMessages: Record<string, MockMessageResponse[]> = {};
const assistantMessageByRun = new Map<string, string>();
const conversationByRun = new Map<string, string>();

vi.mock("@ava/api-client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@ava/api-client")>();
  return {
    ...mod,
    listConversations: vi.fn().mockImplementation(async (_client: unknown, options?: { search?: string }) => ({
      contract_version: "v1",
      conversations: options?.search?.trim()
        ? serverConversations.filter((item) => item.title.toLowerCase().includes(options.search!.trim().toLowerCase()))
        : serverConversations,
    })),
    listMessages: vi.fn().mockImplementation(
      async (_client: unknown, conversationId: string) => ({
        contract_version: "v1",
        conversation_id: conversationId,
        messages: serverMessages[conversationId] ?? [],
      }),
    ),
    createConversation: vi.fn().mockImplementation(
      async (_client: unknown, request?: { title?: string | null }) => {
        const conversation: MockConversationResponse = {
          conversation_id: `conversation-${nextConversationId++}`,
          title: request?.title ?? "New Conversation",
          created_at: TS,
          updated_at: TS,
          is_pinned: false,
          is_archived: false,
          folder_id: null,
          project_id: null,
          contract_version: "v1",
        };
        serverConversations = [...serverConversations, conversation];
        return conversation;
      },
    ),
    updateConversation: vi.fn().mockImplementation(
      async (
        _client: unknown,
        conversationId: string,
        request: { title?: string | null },
      ) => {
        const current = serverConversations.find(
          (item) => item.conversation_id === conversationId,
        );
        if (current == null) throw new Error("not found");
        const updated: MockConversationResponse = {
          ...current,
          title: request?.title ?? current.title,
          updated_at: TS,
        };
        serverConversations = serverConversations.map((item) =>
          item.conversation_id === conversationId ? updated : item,
        );
        return updated;
      },
    ),
    deleteConversation: vi.fn().mockImplementation(async (_client: unknown, conversationId: string) => {
      serverConversations = serverConversations.filter((item) => item.conversation_id !== conversationId);
      delete serverMessages[conversationId];
    }),
    createMessage: vi.fn().mockImplementation(
      async (
        _client: unknown,
        conversationId: string,
        request: { content: string; role?: string },
      ) => {
        const role = request.role === "assistant" ? "assistant" : "user";
        const message: MockMessageResponse = {
          message_id: `${role}-${nextMessageId++}`,
          conversation_id: conversationId,
          role,
          content: request.content,
          status: "complete",
          created_at: TS,
          updated_at: TS,
          contract_version: "v1",
        };
        serverMessages[conversationId] = [
          ...(serverMessages[conversationId] ?? []),
          message,
        ];
        return message;
      },
    ),
    startRun: vi.fn().mockImplementation(async (_client: unknown, request: { conversation_id?: string }) => {
      const runId = `run-${nextRunId++}`;
      const assistantMessageId = `assistant-${runId}`;
      assistantMessageByRun.set(runId, assistantMessageId);
      if (request.conversation_id != null) {
        conversationByRun.set(runId, request.conversation_id);
        const placeholder: MockMessageResponse = {
          message_id: assistantMessageId,
          conversation_id: request.conversation_id,
          role: "assistant",
          content: "",
          status: "pending",
          created_at: TS,
          updated_at: TS,
          contract_version: "v1",
        };
        serverMessages[request.conversation_id] = [
          ...(serverMessages[request.conversation_id] ?? []),
          placeholder,
        ];
      }
      return {
        run_id: runId,
        status: "running",
        assistant_message_id: assistantMessageId,
        contract_version: "v1",
      };
    }),
    getRunEvents: vi.fn().mockResolvedValue([]),
    streamRun: vi.fn().mockImplementation(
      async (
        client: ApiClient,
        runId: string,
        options: { onEvent(event: TestRunEvent & { sequence: number }): void },
      ) => {
        const events = await getRunEvents(client, runId);
        events.forEach((event, index) => {
          const messageId = assistantMessageByRun.get(runId);
          const payload = event.event_type === "message_started" || event.event_type === "message_content"
            ? { ...event.payload, message_id: messageId ?? "" }
            : event.payload;
          const conversationId = conversationByRun.get(runId);
          if (conversationId != null && messageId != null && event.event_type === "message_content") {
            serverMessages[conversationId] = (serverMessages[conversationId] ?? []).map((message) =>
              message.message_id === messageId
                ? { ...message, content: String(payload["content"] ?? ""), status: "complete" }
                : message,
            );
          }
          options.onEvent({ ...event, run_id: runId, payload, sequence: event.sequence ?? index + 1 });
        });
      },
    ),
    cancelRun: vi.fn().mockResolvedValue({
      run_id: "run-1",
      status: "cancelled",
      contract_version: "v1",
    }),
  };
});

const client = new ApiClient({ baseUrl: "http://localhost:99999" });
const defaultStreamRunImplementation = vi.mocked(streamRun).getMockImplementation();

function serverMessage(
  id: string,
  conversationId: string,
  role: "user" | "assistant",
  content: string,
): MockMessageResponse {
  return {
    message_id: id,
    conversation_id: conversationId,
    role,
    content,
    status: "complete",
    created_at: TS,
    updated_at: TS,
    contract_version: "v1",
  };
}

function seedConversation(
  id: string,
  title: string,
  messages: MockMessageResponse[],
  metadata: { is_pinned?: boolean; is_archived?: boolean; folder_id?: string | null } = {},
): void {
  serverConversations = [
    ...serverConversations,
    {
      conversation_id: id,
      title,
      created_at: TS,
      updated_at: TS,
      is_pinned: metadata.is_pinned ?? false,
      is_archived: metadata.is_archived ?? false,
      folder_id: metadata.folder_id ?? null,
      project_id: null,
      contract_version: "v1",
    },
  ];
  serverMessages[id] = messages;
}

function answerEvents(answer: string): TestRunEvent[] {
  return [
    {
      event_id: "e1",
      run_id: "run-1",
      event_type: "run_started",
      timestamp: TS,
      payload: {},
      contract_version: "v1" as const,
    },
    {
      event_id: "e2",
      run_id: "run-1",
      event_type: "message_content",
      timestamp: TS,
      payload: { content: answer },
      contract_version: "v1" as const,
    },
    {
      event_id: "e3",
      run_id: "run-1",
      event_type: "run_completed",
      timestamp: TS,
      payload: {},
      contract_version: "v1" as const,
    },
  ] as unknown as TestRunEvent[];
}

function conversationItem(id: string): HTMLElement {
  const el = document.querySelector(`[data-conversation-item="${id}"]`);
  if (el == null) throw new Error(`Missing conversation item ${id}`);
  return el as HTMLElement;
}

function messageElements(role: string): HTMLElement[] {
  return Array.from(
    document.querySelectorAll(`[data-message-role="${role}"]`),
  ) as HTMLElement[];
}

async function advanceSearchDebounce(milliseconds = 250): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(milliseconds);
  });
}

function Harness() {
  const conversation = useConversationState();
  const run = useAgentRun();
  return (
    <div>
      <button
        type="button"
        onClick={() => void run.submitPrompt(PROMPT)}
      >
        send-prompt
      </button>
      <ConversationList
        conversations={conversation.conversationList}
        activeConversationId={conversation.activeConversation?.id ?? null}
        onNewChat={() => void conversation.createConversation()}
        onSelect={(id) => void conversation.selectConversation(id)}
        onRename={async (id, title) => {
          try {
            await conversation.renameConversation(id, title);
          } catch (error) {
            if (error instanceof ApiError && error.status === 404) run.forgetConversation(id);
            throw error;
          }
        }}
        onDelete={async (id) => {
          await conversation.deleteConversation(id);
          run.forgetConversation(id);
        }}
        error={conversation.state.error ?? null}
        searchQuery={conversation.searchQuery}
        onSearchChange={conversation.setSearchQuery}
        searchLoading={conversation.searchLoading}
        searchError={conversation.searchError}
      />
      <output data-search-list-metadata="">
        {JSON.stringify(conversation.conversationList.map(({ id, isPinned, isArchived, folderId }) => ({ id, isPinned, isArchived, folderId })))}
      </output>
      <ConversationView
        conversation={conversation.activeConversation}
        onRetryMessage={run.retryMessage}
        onRegenerateMessage={run.regenerateMessage}
      />
    </div>
  );
}

function TestRoot({ client: apiClient }: { client: ApiClient }) {
  return (
    <ConversationProvider client={apiClient}>
      <AgentRunProvider client={apiClient}>
        <Harness />
      </AgentRunProvider>
    </ConversationProvider>
  );
}

describe("conversation selection and message hydration", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  beforeEach(() => {
    nextConversationId = 1;
    nextRunId = 1;
    assistantMessageByRun.clear();
    conversationByRun.clear();
    nextMessageId = 1;
    serverConversations = [];
    serverMessages = {};
    vi.clearAllMocks();
    if (defaultStreamRunImplementation != null) {
      vi.mocked(streamRun).mockImplementation(defaultStreamRunImplementation);
    }
    vi.mocked(listConversations).mockImplementation(async (_client: unknown, options?: { search?: string }) => ({
      contract_version: "v1",
      conversations: options?.search?.trim()
        ? serverConversations.filter((item) => item.title.toLowerCase().includes(options.search!.trim().toLowerCase()))
        : serverConversations,
    }));
    vi.mocked(listMessages).mockImplementation(
      async (_client: unknown, conversationId: string) => ({
        contract_version: "v1",
        conversation_id: conversationId,
        messages: serverMessages[conversationId] ?? [],
      }),
    );
    vi.mocked(createConversation).mockImplementation(
      async (_client: unknown, request?: { title?: string | null }) => {
        const conversation: MockConversationResponse = {
          conversation_id: `conversation-${nextConversationId++}`,
          title: request?.title ?? "New Conversation",
          created_at: TS,
          updated_at: TS,
          is_pinned: false,
          is_archived: false,
          folder_id: null,
          project_id: null,
          contract_version: "v1",
        };
        serverConversations = [...serverConversations, conversation];
        return conversation;
      },
    );
    vi.mocked(createMessage).mockImplementation(
      async (
        _client: unknown,
        conversationId: string,
        request: { content: string; role?: string },
      ) => {
        const role = request.role === "assistant" ? "assistant" : "user";
        const message: MockMessageResponse = {
          message_id: `${role}-${nextMessageId++}`,
          conversation_id: conversationId,
          role,
          content: request.content,
          status: "complete",
          created_at: TS,
          updated_at: TS,
          contract_version: "v1",
        };
        serverMessages[conversationId] = [
          ...(serverMessages[conversationId] ?? []),
          message,
        ];
        return message;
      },
    );
    vi.mocked(deleteConversation).mockImplementation(async (_client: unknown, conversationId: string) => {
      serverConversations = serverConversations.filter((item) => item.conversation_id !== conversationId);
      delete serverMessages[conversationId];
    });
    vi.mocked(startRun).mockImplementation(async (_client: unknown, request: { conversation_id?: string | null }) => {
      const runId = `run-${nextRunId++}`;
      const assistantMessageId = `assistant-${runId}`;
      assistantMessageByRun.set(runId, assistantMessageId);
      if (request.conversation_id != null) {
        conversationByRun.set(runId, request.conversation_id);
        serverMessages[request.conversation_id] = [
          ...(serverMessages[request.conversation_id] ?? []),
          {
            message_id: assistantMessageId,
            conversation_id: request.conversation_id,
            role: "assistant",
            content: "",
            status: "pending",
            created_at: TS,
            updated_at: TS,
            contract_version: "v1",
          },
        ];
      }
      return {
        run_id: runId,
        status: "running",
        assistant_message_id: assistantMessageId,
        contract_version: "v1",
      };
    });
    vi.mocked(getRunEvents).mockResolvedValue([]);
    vi.mocked(cancelRun).mockResolvedValue({
      run_id: "run-1",
      status: "cancelled",
      contract_version: "v1",
    });
  });

  async function openDelete(title: string) {
    const row = Array.from(document.querySelectorAll("[data-conversation-row]")).find((item) =>
      item.querySelector("[data-conversation-item]")?.textContent === title,
    );
    const actions = row?.querySelector('[aria-label^="Conversation actions for "]');
    if (actions == null) throw new Error(`Missing conversation actions for ${title}`);
    fireEvent.click(actions);
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete" }));
    expect(await screen.findByRole("dialog")).toBeTruthy();
  }

  it("deletes an unselected conversation without changing the selected transcript", async () => {
    seedConversation("conversation-1", "Thread A", [serverMessage("a", "conversation-1", "user", "A transcript")]);
    seedConversation("conversation-2", "Thread B", [serverMessage("b", "conversation-2", "user", "B transcript")]);
    render(<TestRoot client={client} />);
    await waitFor(() => expect(screen.getByText("A transcript")).toBeTruthy());
    fireEvent.click(conversationItem("conversation-2"));
    await waitFor(() => expect(screen.getByText("B transcript")).toBeTruthy());
    await openDelete("Thread A");
    fireEvent.click(screen.getByRole("button", { name: "Delete permanently" }));
    await waitFor(() => expect(document.querySelector('[data-conversation-item="conversation-1"]')).toBeNull());
    expect(conversationItem("conversation-2").getAttribute("aria-current")).toBe("true");
    expect(screen.getByText("B transcript")).toBeTruthy();
    expect(screen.queryByText("A transcript")).toBeNull();
  });

  it("deletes the selected conversation and selects the next item in existing order", async () => {
    seedConversation("conversation-1", "Thread A", [serverMessage("a", "conversation-1", "user", "A transcript")]);
    seedConversation("conversation-2", "Thread B", [serverMessage("b", "conversation-2", "user", "B transcript")]);
    render(<TestRoot client={client} />);
    await waitFor(() => expect(screen.getByText("A transcript")).toBeTruthy());
    await openDelete("Thread A");
    fireEvent.click(screen.getByRole("button", { name: "Delete permanently" }));
    await waitFor(() => expect(conversationItem("conversation-2").getAttribute("aria-current")).toBe("true"));
    expect(document.querySelector('[data-conversation-item="conversation-1"]')).toBeNull();
    expect(screen.getByText("B transcript")).toBeTruthy();
    expect(screen.queryByText("A transcript")).toBeNull();
  });

  it("leaves an empty safe state after deleting the last conversation", async () => {
    seedConversation("conversation-1", "Only Thread", [serverMessage("a", "conversation-1", "user", "Only transcript")]);
    render(<TestRoot client={client} />);
    await waitFor(() => expect(screen.getByText("Only transcript")).toBeTruthy());
    await openDelete("Only Thread");
    fireEvent.click(screen.getByRole("button", { name: "Delete permanently" }));
    await waitFor(() => expect(document.querySelectorAll("[data-conversation-item]")).toHaveLength(0));
    expect(screen.getByText("New Conversation")).toBeTruthy();
    expect(document.querySelectorAll("[data-conversation-item]")).toHaveLength(0);
    expect(screen.queryByText("Only transcript")).toBeNull();
  });

  it("cancel closes confirmation without issuing DELETE or changing selection", async () => {
    seedConversation("conversation-1", "Thread A", []);
    render(<TestRoot client={client} />);
    await waitFor(() => expect(conversationItem("conversation-1")).toBeTruthy());
    await openDelete("Thread A");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(deleteConversation).not.toHaveBeenCalled();
    expect(conversationItem("conversation-1").getAttribute("aria-current")).toBe("true");
  });

  it("keeps the conversation intact and explains an active-run conflict", async () => {
    seedConversation("conversation-1", "Thread A", []);
    vi.mocked(deleteConversation).mockRejectedValueOnce(new ApiError("conflict", 409, { error_code: "conversation_run_active" }));
    render(<TestRoot client={client} />);
    await waitFor(() => expect(conversationItem("conversation-1")).toBeTruthy());
    await openDelete("Thread A");
    fireEvent.click(screen.getByRole("button", { name: "Delete permanently" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Stop the active response before deleting");
    expect(conversationItem("conversation-1").getAttribute("aria-current")).toBe("true");
    expect(screen.getByRole("dialog")).toBeTruthy();
  });

  it("reconciles a server-confirmed 404 by removing the stale local item", async () => {
    seedConversation("conversation-1", "Stale Thread", []);
    seedConversation("conversation-2", "Remaining Thread", []);
    vi.mocked(deleteConversation).mockRejectedValueOnce(new ApiError("gone", 404, { error_code: "conversation_not_found" }));
    render(<TestRoot client={client} />);
    await waitFor(() => expect(conversationItem("conversation-1")).toBeTruthy());
    await openDelete("Stale Thread");
    fireEvent.click(screen.getByRole("button", { name: "Delete permanently" }));
    await waitFor(() => expect(document.querySelector('[data-conversation-item="conversation-1"]')).toBeNull());
    expect(conversationItem("conversation-2").getAttribute("aria-current")).toBe("true");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("preserves item and selection after an unknown failure", async () => {
    seedConversation("conversation-1", "Thread A", []);
    vi.mocked(deleteConversation).mockRejectedValueOnce(new Error("network offline"));
    render(<TestRoot client={client} />);
    await waitFor(() => expect(conversationItem("conversation-1")).toBeTruthy());
    await openDelete("Thread A");
    fireEvent.click(screen.getByRole("button", { name: "Delete permanently" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Unable to delete this conversation");
    expect(document.body.textContent).not.toContain("network offline");
    expect(conversationItem("conversation-1").getAttribute("aria-current")).toBe("true");
    expect(screen.getByRole("dialog")).toBeTruthy();
  });

  it("prevents duplicate DELETE submissions while the request is pending", async () => {
    seedConversation("conversation-1", "Thread A", []);
    let resolveDelete!: () => void;
    vi.mocked(deleteConversation).mockImplementationOnce(() => new Promise<void>((resolve) => { resolveDelete = resolve; }));
    render(<TestRoot client={client} />);
    await waitFor(() => expect(conversationItem("conversation-1")).toBeTruthy());
    await openDelete("Thread A");
    const confirm = screen.getByRole("button", { name: "Delete permanently" });
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    expect(deleteConversation).toHaveBeenCalledTimes(1);
    expect(confirm.hasAttribute("disabled")).toBe(true);
    await act(async () => resolveDelete());
    await waitFor(() => expect(document.querySelector('[data-conversation-item="conversation-1"]')).toBeNull());
  });

  it("aborts only the deleted conversation's stream observer", async () => {
    seedConversation("conversation-1", "Thread A", []);
    seedConversation("conversation-2", "Thread B", []);
    const signals = new Map<string, AbortSignal | undefined>();
    vi.mocked(streamRun)
      .mockImplementationOnce(async (_client, runId, options) => {
        signals.set(conversationByRun.get(runId)!, options.signal);
        await new Promise<void>(() => undefined);
      })
      .mockImplementationOnce(async (_client, runId, options) => {
        signals.set(conversationByRun.get(runId)!, options.signal);
        await new Promise<void>(() => undefined);
      });
    render(<TestRoot client={client} />);
    await waitFor(() => expect(conversationItem("conversation-1")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "send-prompt" }));
    await waitFor(() => expect(signals.has("conversation-1")).toBe(true));
    fireEvent.click(conversationItem("conversation-2"));
    await waitFor(() => expect(conversationItem("conversation-2").getAttribute("aria-current")).toBe("true"));
    fireEvent.click(screen.getByRole("button", { name: "send-prompt" }));
    await waitFor(() => expect(signals.has("conversation-2")).toBe(true));

    await openDelete("Original question");
    fireEvent.click(screen.getByRole("button", { name: "Delete permanently" }));
    await waitFor(() => expect(signals.get("conversation-1")?.aborted).toBe(true));
    expect(signals.get("conversation-2")?.aborted).toBe(false);
  });

  it("ignores a late run event after the observed conversation is deleted", async () => {
    seedConversation("conversation-1", "Thread A", []);
    seedConversation("conversation-2", "Thread B", []);
    let deliverLateEvent: ((event: TestRunEvent & { sequence: number }) => void) | undefined;
    vi.mocked(streamRun).mockImplementation(async (_client, _runId, options) => {
      deliverLateEvent = options.onEvent;
      await new Promise<void>(() => undefined); // Deliberately ignores AbortSignal.
    });
    render(<TestRoot client={client} />);
    await waitFor(() => expect(conversationItem("conversation-1")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "send-prompt" }));
    await waitFor(() => expect(deliverLateEvent).toBeDefined());

    await openDelete("Original question");
    fireEvent.click(screen.getByRole("button", { name: "Delete permanently" }));
    await waitFor(() => expect(conversationItem("conversation-2").getAttribute("aria-current")).toBe("true"));
    await act(async () => {
      deliverLateEvent?.({
        event_id: "late-event",
        run_id: "run-1",
        event_type: "message_content",
        timestamp: TS,
        payload: { content: "late deleted transcript" },
        contract_version: "v1",
        sequence: 99,
      } as TestRunEvent & { sequence: number });
    });

    expect(document.querySelector('[data-conversation-item="conversation-1"]')).toBeNull();
    expect(conversationItem("conversation-2").getAttribute("aria-current")).toBe("true");
    expect(screen.queryByText("late deleted transcript")).toBeNull();
    expect(screen.queryByText("Original question")).toBeNull();
  });

  it("shows the selected conversation's persisted history", async () => {
    seedConversation("conversation-1", "Persisted Chat", [
      serverMessage("u1", "conversation-1", "user", "Old question"),
      serverMessage("a1", "conversation-1", "assistant", "Old Answer A"),
    ]);
    render(<TestRoot client={client} />);

    await waitFor(() => {
      expect(screen.getAllByText("Old Answer A")).toHaveLength(1);
    });
    expect(screen.getAllByText("Old question").length).toBeGreaterThan(0);
    expect(messageElements("user")).toHaveLength(1);
    expect(messageElements("assistant")).toHaveLength(1);
    expect(
      conversationItem("conversation-1").getAttribute("aria-current"),
    ).toBe("true");
  });

  it("keeps conversations isolated when switching back and forth", async () => {
    seedConversation("conversation-1", "Thread One", [
      serverMessage("u1", "conversation-1", "user", "One question"),
      serverMessage("a1", "conversation-1", "assistant", "One answer"),
    ]);
    seedConversation("conversation-2", "Thread Two", [
      serverMessage("u2", "conversation-2", "user", "Two question"),
      serverMessage("a2", "conversation-2", "assistant", "Two answer"),
    ]);
    render(<TestRoot client={client} />);

    await waitFor(() => {
      expect(screen.getAllByText("One answer")).toHaveLength(1);
    });

    fireEvent.click(conversationItem("conversation-2"));
    await waitFor(() => {
      expect(screen.getAllByText("Two answer")).toHaveLength(1);
    });
    expect(screen.queryByText("One answer")).toBeNull();
    expect(screen.queryByText("One question")).toBeNull();

    fireEvent.click(conversationItem("conversation-1"));
    await waitFor(() => {
      expect(screen.getAllByText("One answer")).toHaveLength(1);
    });
    expect(screen.queryByText("Two answer")).toBeNull();
    expect(screen.queryByText("Two question")).toBeNull();
  });

  it("does not duplicate messages when reselecting the same conversation", async () => {
    seedConversation("conversation-1", "Persisted Chat", [
      serverMessage("u1", "conversation-1", "user", "Single question"),
      serverMessage("a1", "conversation-1", "assistant", "Single answer"),
    ]);
    render(<TestRoot client={client} />);
    await waitFor(() => {
      expect(screen.getAllByText("Single answer")).toHaveLength(1);
    });

    fireEvent.click(conversationItem("conversation-1"));
    await waitFor(() => {
      expect(screen.getAllByText("Single answer")).toHaveLength(1);
    });
    expect(messageElements("assistant")).toHaveLength(1);
    expect(screen.getAllByText("Single question").length).toBeGreaterThan(0);
  });

  it("ignores a stale list response resolving after switching conversations", async () => {
    seedConversation("conversation-1", "Thread One", [
      serverMessage("u1", "conversation-1", "user", "Stale question"),
      serverMessage("a1", "conversation-1", "assistant", "Stale answer"),
    ]);
    seedConversation("conversation-2", "Thread Two", [
      serverMessage("u2", "conversation-2", "user", "Fresh question"),
      serverMessage("a2", "conversation-2", "assistant", "Fresh answer"),
    ]);
    render(<TestRoot client={client} />);
    await waitFor(() => {
      expect(screen.getAllByText("Stale answer")).toHaveLength(1);
    });

    let resolveC1!: (value: MockMessageListResponse) => void;
    const c1Gate = new Promise<MockMessageListResponse>((resolve) => {
      resolveC1 = resolve;
    });
    vi.mocked(listMessages).mockImplementationOnce(
      async (_client: unknown, conversationId: string) =>
        conversationId === "conversation-1"
          ? c1Gate
          : {
              contract_version: "v1",
              conversation_id: conversationId,
              messages: serverMessages[conversationId] ?? [],
            },
    );

    fireEvent.click(conversationItem("conversation-1"));
    fireEvent.click(conversationItem("conversation-2"));
    await waitFor(() => {
      expect(
        conversationItem("conversation-2").getAttribute("aria-current"),
      ).toBe("true");
    });
    expect(screen.getAllByText("Fresh answer")).toHaveLength(1);

    await act(async () => {
      resolveC1({
        contract_version: "v1",
        conversation_id: "conversation-1",
        messages: [
          serverMessage("u1", "conversation-1", "user", "Stale question"),
        ],
      });
    });

    expect(
      conversationItem("conversation-2").getAttribute("aria-current"),
    ).toBe("true");
    expect(screen.getAllByText("Fresh answer")).toHaveLength(1);
    expect(screen.queryByText("Stale answer")).toBeNull();
  });

  it("keeps an in-flight assistant response visible when reselecting its conversation", async () => {
    seedConversation("conversation-1", "Running Thread", []);
    vi.mocked(getRunEvents).mockResolvedValue(answerEvents("Answer A"));

    vi.mocked(createMessage).mockImplementation(
      async (
        _client: unknown,
        conversationId: string,
        request: { content: string; role?: string },
      ) => {
        const role = request.role === "assistant" ? "assistant" : "user";
        const message: MockMessageResponse = {
          message_id: `${role}-save-${nextMessageId++}`,
          conversation_id: conversationId,
          role,
          content: request.content,
          status: "complete",
          created_at: TS,
          updated_at: TS,
          contract_version: "v1",
        };
        serverMessages[conversationId] = [
          ...(serverMessages[conversationId] ?? []),
          message,
        ];
        return message;
      },
    );

    render(<TestRoot client={client} />);
    await waitFor(() => {
      expect(
        conversationItem("conversation-1").getAttribute("aria-current"),
      ).toBe("true");
    });
    fireEvent.click(screen.getByRole("button", { name: "send-prompt" }));

    await waitFor(() => {
      expect(screen.getAllByText("Answer A")).toHaveLength(1);
    });

    let resolveRehydrate!: (value: MockMessageListResponse) => void;
    const rehydrateGate = new Promise<MockMessageListResponse>((resolve) => {
      resolveRehydrate = resolve;
    });
    vi.mocked(listMessages).mockImplementationOnce(
      async (_client: unknown, conversationId: string) =>
        conversationId === "conversation-1"
          ? rehydrateGate
          : {
              contract_version: "v1",
              conversation_id: conversationId,
              messages: serverMessages[conversationId] ?? [],
            },
    );

    fireEvent.click(conversationItem("conversation-1"));
    await waitFor(() => {
      expect(vi.mocked(listMessages)).toHaveBeenCalledTimes(2);
    });
    expect(screen.getAllByText("Answer A")).toHaveLength(1);

    await act(async () => {
      resolveRehydrate({
        contract_version: "v1",
        conversation_id: "conversation-1",
        messages: [serverMessage("user-save-1", "conversation-1", "user", PROMPT)],
      });
    });

    await waitFor(() => {
      expect(screen.getAllByText("Answer A")).toHaveLength(1);
    });
    expect(messageElements("assistant")).toHaveLength(1);
    expect(messageElements("user")).toHaveLength(1);

    expect(serverMessages["conversation-1"]?.some(
      (message) => message.role === "assistant" && message.content === "Answer A",
    )).toBe(true);
  });

  it("shows the same persisted history after a remount (refresh)", async () => {
    seedConversation("conversation-1", "Running Thread", []);
    vi.mocked(getRunEvents).mockResolvedValue(
      answerEvents("Persisted Answer"),
    );

    const first = render(<TestRoot client={client} />);
    await waitFor(() => {
      expect(
        conversationItem("conversation-1").getAttribute("aria-current"),
      ).toBe("true");
    });
    fireEvent.click(screen.getByRole("button", { name: "send-prompt" }));
    await waitFor(() => {
      expect(screen.getAllByText("Persisted Answer")).toHaveLength(1);
    });
    expect(serverMessages["conversation-1"]?.some(
      (message) => message.role === "assistant" && message.content === "Persisted Answer",
    )).toBe(true);
    expect(messageElements("assistant")).toHaveLength(1);

    first.unmount();
    render(<TestRoot client={client} />);

    await waitFor(() => {
      expect(screen.getAllByText("Persisted Answer")).toHaveLength(1);
    });
    expect(messageElements("user")).toHaveLength(1);
    expect(messageElements("assistant")).toHaveLength(1);
    expect(vi.mocked(listConversations)).toHaveBeenCalledTimes(2);
  });

  it("debounces title search and clearing or whitespace restores the unfiltered list", async () => {
    seedConversation("conversation-1", "Architecture Review", []);
    seedConversation("conversation-2", "Planning notes", []);
    render(<TestRoot client={client} />);
    await waitFor(() => expect(conversationItem("conversation-1")).toBeTruthy());
    expect(listConversations).toHaveBeenCalledTimes(1);

    vi.useFakeTimers();
    const search = screen.getByRole("searchbox", { name: "Search conversations" });
    fireEvent.change(search, { target: { value: "a" } });
    fireEvent.change(search, { target: { value: "ar" } });
    fireEvent.change(search, { target: { value: "  arch  " } });
    await advanceSearchDebounce(249);
    expect(listConversations).toHaveBeenCalledTimes(1);
    await advanceSearchDebounce(1);

    expect(listConversations).toHaveBeenLastCalledWith(client, { search: "arch" });
    expect(document.querySelectorAll("[data-conversation-item]")).toHaveLength(1);
    expect(conversationItem("conversation-1")).toBeTruthy();

    fireEvent.change(search, { target: { value: "   " } });
    expect(document.querySelectorAll("[data-conversation-item]")).toHaveLength(2);
    expect(listConversations).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getByRole("button", { name: "Clear conversation search" }));
    expect((screen.getByRole("searchbox", { name: "Search conversations" }) as HTMLInputElement).value).toBe("");
    expect(document.querySelectorAll("[data-conversation-item]")).toHaveLength(2);
    fireEvent.change(search, { target: { value: "arch" } });
    fireEvent.keyDown(search, { key: "Escape" });
    expect((screen.getByRole("searchbox", { name: "Search conversations" }) as HTMLInputElement).value).toBe("");
    expect(document.querySelectorAll("[data-conversation-item]")).toHaveLength(2);
  });

  it("shows a search-specific empty state and concise recoverable error", async () => {
    seedConversation("conversation-1", "Architecture Review", []);
    render(<TestRoot client={client} />);
    await waitFor(() => expect(conversationItem("conversation-1")).toBeTruthy());
    vi.useFakeTimers();
    const search = screen.getByRole("searchbox", { name: "Search conversations" });
    fireEvent.change(search, { target: { value: "no-match" } });
    await advanceSearchDebounce();
    expect(screen.getByText('No conversations found for “no-match”.')).toBeTruthy();
    expect(screen.queryByText("No conversations yet")).toBeNull();

    vi.mocked(listConversations).mockRejectedValueOnce(new Error("private transport detail"));
    fireEvent.change(search, { target: { value: "retry" } });
    await advanceSearchDebounce();
    expect(screen.getByText("Unable to search conversations.")).toBeTruthy();
    expect(document.body.textContent).not.toContain("private transport detail");
    fireEvent.click(screen.getByRole("button", { name: "Clear conversation search" }));
    expect(conversationItem("conversation-1")).toBeTruthy();
    expect(screen.queryByText("Unable to search conversations.")).toBeNull();
  });

  it("ignores an older search response after the newer query completes", async () => {
    seedConversation("conversation-a", "Alpha notes", []);
    seedConversation("conversation-arch", "Architecture review", []);
    render(<TestRoot client={client} />);
    await waitFor(() => expect(conversationItem("conversation-a")).toBeTruthy());
    let resolveOld!: (value: { contract_version: "v1"; conversations: MockConversationResponse[] }) => void;
    let resolveNew!: (value: { contract_version: "v1"; conversations: MockConversationResponse[] }) => void;
    vi.mocked(listConversations).mockImplementation((_client: unknown, options?: { search?: string }) => {
      if (options?.search === "a") return new Promise((resolve) => { resolveOld = resolve; });
      if (options?.search === "architecture") return new Promise((resolve) => { resolveNew = resolve; });
      return Promise.resolve({ contract_version: "v1", conversations: serverConversations });
    });

    vi.useFakeTimers();
    const search = screen.getByRole("searchbox", { name: "Search conversations" });
    fireEvent.change(search, { target: { value: "a" } });
    await advanceSearchDebounce();
    fireEvent.change(search, { target: { value: "architecture" } });
    await advanceSearchDebounce();
    expect(screen.getByText("Searching…")).toBeTruthy();

    await act(async () => resolveNew({
      contract_version: "v1",
      conversations: serverConversations.filter((item) => item.conversation_id === "conversation-arch"),
    }));
    expect(conversationItem("conversation-arch")).toBeTruthy();
    await act(async () => resolveOld({
      contract_version: "v1",
      conversations: serverConversations.filter((item) => item.conversation_id === "conversation-a"),
    }));
    expect(conversationItem("conversation-arch")).toBeTruthy();
    expect(document.querySelector('[data-conversation-item="conversation-a"]')).toBeNull();
  });

  it("keeps selection and transcript when filtered out, and search results select normally", async () => {
    seedConversation("conversation-1", "Architecture Review", [serverMessage("a", "conversation-1", "user", "Architecture transcript")]);
    seedConversation("conversation-2", "Planning Notes", [serverMessage("b", "conversation-2", "user", "Planning transcript")]);
    render(<TestRoot client={client} />);
    await waitFor(() => expect(screen.getByText("Architecture transcript")).toBeTruthy());
    await waitFor(() => expect(conversationItem("conversation-1").getAttribute("aria-current")).toBe("true"));

    vi.useFakeTimers();
    fireEvent.change(screen.getByRole("searchbox", { name: "Search conversations" }), { target: { value: "planning" } });
    await advanceSearchDebounce();
    expect(document.querySelector('[data-conversation-item="conversation-1"]')).toBeNull();
    expect(conversationItem("conversation-2").getAttribute("aria-current")).toBeNull();
    expect(screen.getByText("Architecture transcript")).toBeTruthy();

    fireEvent.click(conversationItem("conversation-2"));
    await act(async () => Promise.resolve());
    expect(conversationItem("conversation-2").getAttribute("aria-current")).toBe("true");
    expect(screen.getByText("Planning transcript")).toBeTruthy();
  });

  it("preserves pinned, archived, and folder metadata on server search results", async () => {
    seedConversation("conversation-1", "Architecture Review", [serverMessage("archived-message", "conversation-1", "user", "Archived transcript")], {
      is_pinned: true,
      is_archived: true,
      folder_id: "folder-7",
    });
    render(<TestRoot client={client} />);
    await waitFor(() => expect(document.querySelector("[data-search-list-metadata]")?.textContent).toContain('"isPinned":true,"isArchived":true,"folderId":"folder-7"'));
    expect(document.querySelector('[data-conversation-item="conversation-1"]')).toBeNull();
    await waitFor(() => expect(screen.getByText("Archived transcript")).toBeTruthy());
    vi.useFakeTimers();
    fireEvent.change(screen.getByRole("searchbox", { name: "Search conversations" }), { target: { value: "architecture" } });
    await advanceSearchDebounce();
    expect(conversationItem("conversation-1")).toBeTruthy();
    expect(document.querySelector('[data-archived-indicator]')?.textContent).toBe("Archived");
    fireEvent.click(conversationItem("conversation-1"));
    expect(screen.getByText("Archived transcript")).toBeTruthy();
    expect(document.querySelector("[data-search-list-metadata]")?.textContent).toContain('"isPinned":true,"isArchived":true,"folderId":"folder-7"');
  });

  it("preserves the server-provided order for the normal list and search results", async () => {
    seedConversation("unpinned-c", "Sorting conversation C", []);
    seedConversation("pinned-b", "Sorting conversation B", [], { is_pinned: true });
    seedConversation("pinned-a", "Sorting conversation A", [], { is_pinned: true });
    const ordered = [serverConversations[2], serverConversations[1], serverConversations[0]];
    vi.mocked(listConversations).mockImplementation(async () => ({
      contract_version: "v1",
      conversations: ordered,
    }));

    render(<TestRoot client={client} />);
    await waitFor(() => expect(conversationItem("pinned-a")).toBeTruthy());
    const ids = () => Array.from(document.querySelectorAll("[data-conversation-item]"))
      .map((item) => item.getAttribute("data-conversation-item"));
    expect(ids()).toEqual(["pinned-a", "pinned-b", "unpinned-c"]);

    vi.useFakeTimers();
    fireEvent.change(screen.getByRole("searchbox", { name: "Search conversations" }), { target: { value: "sorting" } });
    await advanceSearchDebounce();
    expect(ids()).toEqual(["pinned-a", "pinned-b", "unpinned-c"]);
  });

  it("reconciles a new conversation to the ordering returned by the server", async () => {
    seedConversation("conversation-old", "Older", []);
    let listCalls = 0;
    vi.mocked(listConversations).mockImplementation(async () => {
      listCalls += 1;
      const conversations = [...serverConversations];
      return {
        contract_version: "v1",
        conversations: listCalls > 1 ? conversations.reverse() : conversations,
      };
    });
    render(<TestRoot client={client} />);
    await waitFor(() => expect(conversationItem("conversation-old")).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: "New Chat" }));
    await waitFor(() => expect(document.querySelectorAll("[data-conversation-item]")).toHaveLength(2));
    expect(Array.from(document.querySelectorAll("[data-conversation-item]"))
      .map((item) => item.getAttribute("data-conversation-item")))
      .toEqual(["conversation-1", "conversation-old"]);
  });

  it("reconciles a rename against the active server-backed search", async () => {
    seedConversation("conversation-1", "Architecture Review", []);
    render(<TestRoot client={client} />);
    await waitFor(() => expect(conversationItem("conversation-1")).toBeTruthy());
    vi.useFakeTimers();
    const search = screen.getByRole("searchbox", { name: "Search conversations" });
    fireEvent.change(search, { target: { value: "arch" } });
    await advanceSearchDebounce();
    expect(conversationItem("conversation-1")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Conversation actions for Architecture Review" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Rename" }));
    const rename = screen.getByRole("textbox", { name: "Rename conversation" });
    fireEvent.change(rename, { target: { value: "Meeting Notes" } });
    fireEvent.keyDown(rename, { key: "Enter" });
    await act(async () => Promise.resolve());
    await advanceSearchDebounce();
    expect(document.querySelector('[data-conversation-item="conversation-1"]')).toBeNull();
    expect(screen.getByText('No conversations found for “arch”.')).toBeTruthy();
    expect((search as HTMLInputElement).value).toBe("arch");
  });

  it("removes a deleted search result while retaining the query", async () => {
    seedConversation("conversation-1", "Architecture Review", []);
    seedConversation("conversation-2", "Planning Notes", []);
    render(<TestRoot client={client} />);
    await waitFor(() => expect(conversationItem("conversation-1")).toBeTruthy());
    vi.useFakeTimers();
    const search = screen.getByRole("searchbox", { name: "Search conversations" });
    fireEvent.change(search, { target: { value: "architecture" } });
    await advanceSearchDebounce();
    fireEvent.click(screen.getByRole("button", { name: "Conversation actions for Architecture Review" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete" }));
    expect(screen.getByRole("dialog")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Delete permanently" }));
    await act(async () => Promise.resolve());
    expect(document.querySelector('[data-conversation-item="conversation-1"]')).toBeNull();
    expect((search as HTMLInputElement).value).toBe("architecture");
    expect(screen.getByText('No conversations found for “architecture”.')).toBeTruthy();
  });

  it("does not restore a deleted search result from a late search response", async () => {
    seedConversation("conversation-1", "Architecture Review", []);
    let resolveSearch!: (value: Awaited<ReturnType<typeof listConversations>>) => void;
    vi.mocked(listConversations).mockImplementation((_client: unknown, options?: { search?: string }) => {
      if (options?.search === "architecture") {
        return new Promise((resolve) => { resolveSearch = resolve; });
      }
      return Promise.resolve({ contract_version: "v1", conversations: serverConversations });
    });
    render(<TestRoot client={client} />);
    await waitFor(() => expect(conversationItem("conversation-1")).toBeTruthy());
    vi.useFakeTimers();
    const search = screen.getByRole("searchbox", { name: "Search conversations" });
    fireEvent.change(search, { target: { value: "architecture" } });
    await advanceSearchDebounce();
    const row = document.querySelector('[data-conversation-item="conversation-1"]')?.closest("[data-conversation-row]");
    const actions = row?.querySelector('[aria-label^="Conversation actions for "]');
    if (actions == null) throw new Error("Missing delete actions for pending search row");
    fireEvent.click(actions);
    fireEvent.click(screen.getByRole("menuitem", { name: "Delete" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete permanently" }));
    await act(async () => Promise.resolve());
    resolveSearch({ contract_version: "v1", conversations: [serverConversations[0] ?? {
      conversation_id: "conversation-1", title: "Architecture Review", created_at: TS, updated_at: TS,
      is_pinned: false, is_archived: false, folder_id: null, project_id: null, contract_version: "v1",
    }] });
    await act(async () => Promise.resolve());
    expect(document.querySelector('[data-conversation-item="conversation-1"]')).toBeNull();
    expect(screen.getByText('No conversations found for “architecture”.')).toBeTruthy();
  });

  it("does not abort a background run when search hides its conversation", async () => {
    seedConversation("conversation-1", "Alpha thread", []);
    seedConversation("conversation-2", "Beta thread", []);
    let streamSignal: AbortSignal | undefined;
    vi.mocked(streamRun).mockImplementation(async (_client, _runId, options) => {
      streamSignal = options.signal;
      await new Promise<void>(() => undefined);
    });
    render(<TestRoot client={client} />);
    await waitFor(() => expect(conversationItem("conversation-1")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "send-prompt" }));
    await waitFor(() => expect(streamSignal).toBeDefined());
    fireEvent.click(conversationItem("conversation-2"));
    await waitFor(() => expect(conversationItem("conversation-2").getAttribute("aria-current")).toBe("true"));

    vi.useFakeTimers();
    fireEvent.change(screen.getByRole("searchbox", { name: "Search conversations" }), { target: { value: "beta" } });
    await advanceSearchDebounce();
    expect(document.querySelector('[data-conversation-item="conversation-1"]')).toBeNull();
    expect(streamSignal?.aborted).toBe(false);
  });

  it("renames a conversation through the conversation API without switching selection", async () => {
    seedConversation("conversation-1", "Thread One", [
      serverMessage("m1", "conversation-1", "user", "Hello"),
    ]);
    seedConversation("conversation-2", "Thread Two", [
      serverMessage("m2", "conversation-2", "user", "Hi"),
    ]);

    render(<TestRoot client={client} />);
    await waitFor(() => {
      expect(
        conversationItem("conversation-1").getAttribute("aria-current"),
      ).toBe("true");
    });

    fireEvent.click(
      screen.getByRole("button", {
        name: "Conversation actions for Thread Two",
      }),
    );
    fireEvent.click(screen.getByRole("menuitem", { name: "Rename" }));
    const input = screen.getByRole("textbox", {
      name: "Rename conversation",
    }) as HTMLInputElement;
    expect(input.value).toBe("Thread Two");

    fireEvent.change(input, { target: { value: "Renamed Thread" } });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => {
      expect(vi.mocked(updateConversation)).toHaveBeenCalledWith(
        client,
        "conversation-2",
        { title: "Renamed Thread" },
      );
    });
    await waitFor(() => {
      expect(screen.getAllByText("Renamed Thread").length).toBeGreaterThan(0);
    });

    expect(
      conversationItem("conversation-1").getAttribute("aria-current"),
    ).toBe("true");
    expect(
      screen.queryByRole("textbox", { name: "Rename conversation" }),
    ).toBeNull();
    expect(vi.mocked(updateConversation)).toHaveBeenCalledTimes(1);
  });

  it("renames the selected conversation in place without replacing its transcript or order", async () => {
    seedConversation("conversation-1", "Thread One", [
      serverMessage("m1", "conversation-1", "user", "Selected transcript"),
    ]);
    seedConversation("conversation-2", "Thread Two", []);
    render(<TestRoot client={client} />);
    await waitFor(() => expect(screen.getByText("Selected transcript")).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: "Conversation actions for Thread One" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Rename" }));
    const input = screen.getByRole("textbox", { name: "Rename conversation" });
    fireEvent.change(input, { target: { value: "Renamed Selected" } });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => expect(conversationItem("conversation-1").getAttribute("title")).toBe("Renamed Selected"));
    expect(conversationItem("conversation-1").getAttribute("aria-current")).toBe("true");
    expect(screen.getByText("Selected transcript")).toBeTruthy();
    expect(Array.from(document.querySelectorAll("[data-conversation-item]")).map((item) => item.getAttribute("data-conversation-item"))).toEqual(["conversation-1", "conversation-2"]);
  });

  it("removes a stale conversation and selects safely when rename returns 404", async () => {
    seedConversation("conversation-1", "Missing Thread", [serverMessage("m1", "conversation-1", "user", "Stale transcript")]);
    seedConversation("conversation-2", "Remaining Thread", [serverMessage("m2", "conversation-2", "user", "Remaining transcript")]);
    vi.mocked(updateConversation).mockRejectedValueOnce(new ApiError("missing", 404, { error_code: "conversation_not_found" }));
    render(<TestRoot client={client} />);
    await waitFor(() => expect(screen.getByText("Stale transcript")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Conversation actions for Missing Thread" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Rename" }));
    const input = screen.getByRole("textbox", { name: "Rename conversation" });
    fireEvent.change(input, { target: { value: "New Title" } });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => expect(document.querySelector('[data-conversation-item="conversation-1"]')).toBeNull());
    expect(conversationItem("conversation-2").getAttribute("aria-current")).toBe("true");
    expect(screen.getByText("Remaining transcript")).toBeTruthy();
    expect(screen.queryByText("Stale transcript")).toBeNull();
  });

  it("surfaces a failed rename and preserves the prior title", async () => {
    seedConversation("conversation-1", "Thread One", []);
    vi.mocked(updateConversation).mockRejectedValueOnce(
      new Error("backend down"),
    );

    render(<TestRoot client={client} />);
    await waitFor(() => {
      expect(
        conversationItem("conversation-1").getAttribute("aria-current"),
      ).toBe("true");
    });

    fireEvent.click(
      screen.getByRole("button", {
        name: "Conversation actions for Thread One",
      }),
    );
    fireEvent.click(screen.getByRole("menuitem", { name: "Rename" }));
    const input = screen.getByRole("textbox", {
      name: "Rename conversation",
    }) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "Never Applied" } });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => {
      expect(screen.getAllByText("Thread One").length).toBeGreaterThan(0);
    });
    expect(screen.queryByText("Never Applied")).toBeNull();
    expect(
      document.querySelector('[data-conversation-error]'),
    ).not.toBeNull();
    // AVA-owned wording only: the transport's own text is never surfaced.
    expect(
      document.querySelector('[data-conversation-error]')!.textContent,
    ).toContain("Unable to rename conversation.");
    expect(document.body.textContent).not.toContain("backend down");
  });

  it("regenerate keeps one visible assistant response after navigating away and back", async () => {
    seedConversation("conversation-1", "Regen Chat", []);
    seedConversation("conversation-2", "Other Chat", [
      serverMessage("u2", "conversation-2", "user", "Other question"),
    ]);
    vi.mocked(getRunEvents).mockResolvedValue(answerEvents("Answer One"));

    render(<TestRoot client={client} />);
    await waitFor(() => {
      expect(
        conversationItem("conversation-1").getAttribute("aria-current"),
      ).toBe("true");
    });
    fireEvent.click(screen.getByRole("button", { name: "send-prompt" }));
    await waitFor(() => {
      expect(screen.getAllByText("Answer One")).toHaveLength(1);
    });
    expect(messageElements("user")).toHaveLength(1);
    expect(messageElements("assistant")).toHaveLength(1);

    vi.mocked(getRunEvents).mockResolvedValue(answerEvents("Answer Two"));
    fireEvent.click(
      screen.getByRole("button", { name: "Regenerate response" }),
    );
    await waitFor(() => {
      expect(screen.getAllByText("Answer Two")).toHaveLength(1);
    });
    expect(messageElements("user")).toHaveLength(1);
    expect(messageElements("assistant")).toHaveLength(1);
    expect(screen.queryByText("Answer One")).toBeNull();

    fireEvent.click(conversationItem("conversation-2"));
    await waitFor(() => {
      expect(
        conversationItem("conversation-2").getAttribute("aria-current"),
      ).toBe("true");
    });

    fireEvent.click(conversationItem("conversation-1"));
    await waitFor(() => {
      expect(screen.getAllByText("Answer Two")).toHaveLength(1);
    });
    expect(messageElements("user")).toHaveLength(1);
    expect(messageElements("assistant")).toHaveLength(1);
    expect(screen.queryByText("Answer One")).toBeNull();
  });

  it("regenerate shows the same single response after a remount (refresh)", async () => {
    seedConversation("conversation-1", "Regen Chat", []);
    vi.mocked(getRunEvents).mockResolvedValue(answerEvents("Answer One"));

    const first = render(<TestRoot client={client} />);
    await waitFor(() => {
      expect(
        conversationItem("conversation-1").getAttribute("aria-current"),
      ).toBe("true");
    });
    fireEvent.click(screen.getByRole("button", { name: "send-prompt" }));
    await waitFor(() => {
      expect(screen.getAllByText("Answer One")).toHaveLength(1);
    });

    vi.mocked(getRunEvents).mockResolvedValue(answerEvents("Answer Two"));
    fireEvent.click(
      screen.getByRole("button", { name: "Regenerate response" }),
    );
    await waitFor(() => {
      expect(screen.getAllByText("Answer Two")).toHaveLength(1);
    });
    expect(messageElements("assistant")).toHaveLength(1);

    first.unmount();
    render(<TestRoot client={client} />);

    await waitFor(() => {
      expect(screen.getAllByText("Answer Two")).toHaveLength(1);
    });
    expect(messageElements("user")).toHaveLength(1);
    expect(messageElements("assistant")).toHaveLength(1);
    expect(screen.queryByText("Answer One")).toBeNull();
  });

  it("regenerate twice keeps only the latest assistant response visible", async () => {
    seedConversation("conversation-1", "Regen Chat", []);
    vi.mocked(getRunEvents).mockResolvedValue(answerEvents("Answer One"));

    render(<TestRoot client={client} />);
    await waitFor(() => {
      expect(
        conversationItem("conversation-1").getAttribute("aria-current"),
      ).toBe("true");
    });
    fireEvent.click(screen.getByRole("button", { name: "send-prompt" }));
    await waitFor(() => {
      expect(screen.getAllByText("Answer One")).toHaveLength(1);
    });

    vi.mocked(getRunEvents).mockResolvedValue(answerEvents("Answer Two"));
    fireEvent.click(
      screen.getByRole("button", { name: "Regenerate response" }),
    );
    await waitFor(() => {
      expect(screen.getAllByText("Answer Two")).toHaveLength(1);
    });

    vi.mocked(getRunEvents).mockResolvedValue(answerEvents("Answer Three"));
    fireEvent.click(
      screen.getByRole("button", { name: "Regenerate response" }),
    );
    await waitFor(() => {
      expect(screen.getAllByText("Answer Three")).toHaveLength(1);
    });
    expect(messageElements("user")).toHaveLength(1);
    expect(messageElements("assistant")).toHaveLength(1);
    expect(screen.queryByText("Answer Two")).toBeNull();
    expect(screen.queryByText("Answer One")).toBeNull();

    fireEvent.click(conversationItem("conversation-1"));
    await waitFor(() => {
      expect(screen.getAllByText("Answer Three")).toHaveLength(1);
    });
    expect(messageElements("assistant")).toHaveLength(1);
    expect(screen.queryByText("Answer Two")).toBeNull();
  });

  it("failed regenerate keeps the prior valid transcript without a new assistant message", async () => {
    seedConversation("conversation-1", "Regen Chat", []);
    vi.mocked(getRunEvents).mockResolvedValue(answerEvents("Answer One"));

    render(<TestRoot client={client} />);
    await waitFor(() => {
      expect(
        conversationItem("conversation-1").getAttribute("aria-current"),
      ).toBe("true");
    });
    fireEvent.click(screen.getByRole("button", { name: "send-prompt" }));
    await waitFor(() => {
      expect(screen.getAllByText("Answer One")).toHaveLength(1);
    });

    vi.mocked(startRun).mockRejectedValueOnce(new Error("backend down"));
    fireEvent.click(
      screen.getByRole("button", { name: "Regenerate response" }),
    );
    // A rejected creation has no durable run, so it cannot produce a failed
    // assistant response: the prior transcript must be left exactly as it was,
    // and the raw transport text must never reach the user.
    await waitFor(() => {
      expect(screen.getAllByText("Answer One")).toHaveLength(1);
    });
    expect(
      Array.from(document.querySelectorAll("[data-message-state]")).map((element) =>
        element.getAttribute("data-message-state"),
      ),
    ).not.toContain("failed");
    expect(document.body.textContent).not.toContain("backend down");
    expect(messageElements("assistant")).toHaveLength(1);
    expect(messageElements("user")).toHaveLength(1);
    // The failure is reported as run state, never as raw transport prose.
    expect(document.querySelector('[data-testid="assistant-message-error"]')).toBeNull();

    fireEvent.click(conversationItem("conversation-1"));
    await waitFor(() => {
      expect(screen.getAllByText("Answer One")).toHaveLength(1);
    });
    expect(messageElements("assistant")).toHaveLength(1);
    expect(
      document.querySelector('[data-message-state="failed"]'),
    ).toBeNull();
  });

  it("reconciles regenerated responses by identity, not by message text", async () => {
    seedConversation("conversation-1", "Regen Chat", []);
    vi.mocked(getRunEvents).mockResolvedValue(answerEvents("Same text"));

    render(<TestRoot client={client} />);
    await waitFor(() => {
      expect(
        conversationItem("conversation-1").getAttribute("aria-current"),
      ).toBe("true");
    });
    fireEvent.click(screen.getByRole("button", { name: "send-prompt" }));
    await waitFor(() => {
      expect(screen.getAllByText("Same text")).toHaveLength(1);
    });

    vi.mocked(getRunEvents).mockResolvedValue(answerEvents("Same text"));
    fireEvent.click(
      screen.getByRole("button", { name: "Regenerate response" }),
    );
    await waitFor(() => {
      expect(screen.getAllByText("Same text")).toHaveLength(1);
    });
    expect(messageElements("assistant")).toHaveLength(1);

    fireEvent.click(conversationItem("conversation-1"));
    await waitFor(() => {
      expect(screen.getAllByText("Same text")).toHaveLength(1);
    });
    expect(messageElements("assistant")).toHaveLength(1);
  });
});
