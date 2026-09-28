// @vitest-environment jsdom
import { ApiClient } from "@ava/api-client";
import {
  cancelRun,
  createConversation,
  createMessage,
  getRunEvents,
  listConversations,
  listMessages,
  startRun,
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
import { beforeEach, describe, expect, it, vi } from "vitest";

const PROMPT = "Original question";
const TS = "2026-01-01T00:00:00Z";

type TestRunEvent = Awaited<ReturnType<typeof getRunEvents>>[number];

interface MockConversationResponse {
  conversation_id: string;
  title: string;
  created_at: string;
  updated_at: string;
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
    listConversations: vi.fn().mockImplementation(async () => ({
      contract_version: "v1",
      conversations: serverConversations,
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
): void {
  serverConversations = [
    ...serverConversations,
    {
      conversation_id: id,
      title,
      created_at: TS,
      updated_at: TS,
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
        conversations={conversation.conversations}
        activeConversationId={conversation.activeConversation?.id ?? null}
        onNewChat={() => void conversation.createConversation()}
        onSelect={(id) => void conversation.selectConversation(id)}
        onRename={conversation.renameConversation}
        error={conversation.state.error ?? null}
      />
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
  beforeEach(() => {
    nextConversationId = 1;
    nextRunId = 1;
    assistantMessageByRun.clear();
    conversationByRun.clear();
    nextMessageId = 1;
    serverConversations = [];
    serverMessages = {};
    vi.clearAllMocks();
    vi.mocked(listConversations).mockImplementation(async () => ({
      contract_version: "v1",
      conversations: serverConversations,
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
    expect(
      document.querySelector('[data-conversation-error]')!.textContent,
    ).toContain("backend down");
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
    await waitFor(() => {
      expect(
        document.querySelector('[data-message-state="failed"]'),
      ).not.toBeNull();
    });
    expect(messageElements("assistant")).toHaveLength(1);
    expect(messageElements("user")).toHaveLength(1);
    expect(
      document.querySelector('[data-testid="assistant-message-error"]')
        ?.textContent,
    ).toContain("AVA is unavailable. Please try again.");

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
