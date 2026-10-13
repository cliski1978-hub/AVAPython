// @vitest-environment jsdom
import { ApiClient, ApiError } from "@ava/api-client";
import {
  createDocument,
  getHealth,
  getModels,
  getDocument,
  getWorkspaces,
  previewContextWindow,
  listDocuments,
  listConversations,
  listMessages,
  createMessage,
  createConversation,
  listProjects,
  listProjectConversations,
  listConversationFolders,
  createProjectConversation,
  relocateConversation,
  setConversationProject,
  setConversationPinned,
  setConversationArchived,
  setCorePromptAssignment,
  listConversationAttachments,
  uploadConversationAttachment,
  deleteConversationAttachment,
  getProject,
  startRun,
  streamRun,
  updateDocument,
} from "@ava/api-client";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { StrictMode } from "react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { AppWorkspace } from "./AppWorkspace";

let nextConversationId = 1;

vi.mock("@ava/api-client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@ava/api-client")>();
  return {
    ...mod,
    getHealth: vi.fn().mockResolvedValue({
      status: "healthy",
      application: "AVA",
      contract_version: "v1",
    }),
    getModels: vi.fn().mockResolvedValue({ contract_version: "v1", models: [], default_model_id: null }),
    previewContextWindow: vi.fn().mockResolvedValue({
      context_window_tokens: null,
      input_budget_tokens: null,
      estimated_input_tokens: 0,
      output_reserve_tokens: 0,
      dropped_message_count: 0,
      dropped_turn_count: 0,
      count_accuracy: "estimated",
      can_fit: true,
      required_input_tokens: null,
      model_id: null,
    }),
    getRuntimes: vi.fn().mockResolvedValue({
      contract_version: "v1",
      default_runtime_id: "native",
      runtimes: [{ runtime_info: { runtime_id: "native", display_name: "Native" } }],
    }),
    getModelProviders: vi.fn().mockResolvedValue({
      contract_version: "v1",
      default_provider_id: "local",
      providers: [{ provider_id: "local", model_info: { model_id: "local-llm" } }],
    }),
    getExecutionProfiles: vi.fn().mockResolvedValue({
      contract_version: "v1",
      default_profile_id: "default",
      profiles: [
        { id: "default", name: "Default", runtime_id: "native", model_provider_id: "local" },
        { id: "fast", name: "Fast", runtime_id: "native", model_provider_id: "local" },
      ],
    }),
    getWorkspaces: vi.fn().mockResolvedValue({
      contract_version: "v1",
      workspaces: [],
    }),
    listProjects: vi.fn().mockResolvedValue({ projects: [], contract_version: "v1" }),
    listProjectConversations: vi.fn().mockResolvedValue({ conversations: [], contract_version: "v1" }),
    listProjectFiles: vi.fn().mockResolvedValue({ project_id: "p-1", files: [], contract_version: "v1" }),
    listConversationFolders: vi.fn().mockResolvedValue({ folders: [], contract_version: "v1" }),
    createProjectConversation: vi.fn(),
    setConversationProject: vi.fn(),
    relocateConversation: vi.fn(),
    setConversationPinned: vi.fn(),
    setConversationArchived: vi.fn(),
    listCorePrompts: vi.fn().mockResolvedValue({ core_prompts: [{ id: "prompt-1", name: "Prompt One", description: null, prompt_text: "Inert", category: "general", is_enabled: true, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", contract_version: "v1" }], contract_version: "v1" }),
    listCorePromptAssignmentsForScope: vi.fn().mockResolvedValue({ assignments: [], contract_version: "v1" }),
    setCorePromptAssignment: vi.fn().mockResolvedValue({ core_prompt_id: "prompt-1", scope_type: "conversation", scope_id: "conversation-1", state: "enable", assignment_id: "assignment-1", created_at: null, updated_at: null, contract_version: "v1" }),
    getProject: vi.fn().mockImplementation(async (_client: unknown, projectId: string) => ({
      id: projectId,
      name: "AVA Engineering",
      description: "Engineering work",
      instructions: "Inert instructions",
      is_archived: false,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
      contract_version: "v1",
    })),
    streamRun: vi.fn().mockImplementation(async (_client: unknown, _runId: string, options: { signal?: AbortSignal }) => {
      await new Promise<void>((resolve) => {
        if (options.signal == null || options.signal.aborted) return resolve();
        options.signal.addEventListener("abort", () => resolve(), { once: true });
      });
    }),
    listDocuments: vi.fn().mockResolvedValue({
      contract_version: "v1",
      documents: [{
        document_id: "document-1",
        title: "Untitled Document",
        content: "<p>Document</p>",
        content_format: "html",
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
        contract_version: "v1",
      }],
    }),
    getDocument: vi.fn().mockImplementation(async (_client: unknown, documentId: string) => ({
      document_id: documentId,
      title: "Untitled Document",
      content: "<p>Document</p>",
      content_format: "html",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
      contract_version: "v1",
    })),
    createDocument: vi.fn().mockImplementation(
      async (_client: unknown, request: { title: string; content: string; content_format: "html" }) => ({
        document_id: "document-2",
        title: request.title,
        content: request.content,
        content_format: request.content_format,
        created_at: "2026-01-02T00:00:00Z",
        updated_at: "2026-01-02T00:00:00Z",
        contract_version: "v1",
      }),
    ),
    updateDocument: vi.fn().mockImplementation(
      async (_client: unknown, documentId: string, request: { title?: string; content?: string; content_format?: "html" }) => ({
        document_id: documentId,
        title: request.title ?? "Untitled Document",
        content: request.content ?? "<p>Document</p>",
        content_format: request.content_format ?? "html",
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T02:00:00Z",
        contract_version: "v1",
      }),
    ),
    listConversations: vi.fn().mockResolvedValue({ contract_version: "v1", conversations: [] }),
    listConversationAttachments: vi.fn().mockResolvedValue({ contract_version: "v1", owner_type: "conversation", owner_id: "conversation-1", attachments: [] }),
    uploadConversationAttachment: vi.fn(),
    deleteConversationAttachment: vi.fn().mockResolvedValue(undefined),
    listMessages: vi.fn().mockResolvedValue({ contract_version: "v1", conversation_id: "conversation-1", messages: [] }),
    createConversation: vi.fn().mockImplementation(async () => {
      const conversation_id = `conversation-${nextConversationId++}`;
      return { conversation_id, title: "New Conversation", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", contract_version: "v1" };
    }),
    createMessage: vi.fn().mockImplementation(async (_client, conversationId, request) => ({ message_id: request.role === "assistant" ? "assistant-1" : "user-1", conversation_id: conversationId, role: request.role ?? "user", content: request.content, status: "complete", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", contract_version: "v1" })),
    startRun: vi.fn().mockResolvedValue({
      run_id: "run-1",
      status: "completed",
      contract_version: "v1",
    }),
    getRunEvents: vi.fn().mockResolvedValue([
      {
        event_id: "e1",
        run_id: "run-1",
        event_type: "run_started",
        timestamp: "2026-09-12T00:00:00Z",
        payload: {},
        contract_version: "v1",
      },
      {
        event_id: "e2",
        run_id: "run-1",
        event_type: "run_completed",
        timestamp: "2026-09-12T00:00:00Z",
        payload: {},
        contract_version: "v1",
      },
    ]),
    cancelRun: vi.fn().mockResolvedValue({
      run_id: "run-1",
      status: "cancelled",
      contract_version: "v1",
    }),
  };
});

beforeAll(() => {
  class TestPointerEvent extends MouseEvent {
    pointerId: number;
    isPrimary: boolean;
    constructor(type: string, init: PointerEventInit = {}) {
      super(type, init);
      this.pointerId = init.pointerId ?? 1;
      this.isPrimary = init.isPrimary ?? true;
    }
  }
  Object.defineProperty(window, "PointerEvent", { configurable: true, value: TestPointerEvent });
});

const client = new ApiClient({ baseUrl: "http://localhost:99999" });

function chatTab() {
  return screen.getByRole("link", { name: "Chat" });
}

function documentsTab() {
  return screen.getByRole("link", { name: "Documents" });
}

function workspaceSelect(): HTMLSelectElement {
  return executionControl("Select workspace");
}

function executionControl(label: string): HTMLSelectElement {
  if (screen.queryByRole("dialog", { name: "Execution settings" }) == null) {
    fireEvent.click(screen.getByRole("button", { name: /Execution settings/ }));
  }
  return screen.getByLabelText(label) as HTMLSelectElement;
}

/** Open the Documents tab and wait for the shared document editor to mount. */
async function openDocumentsTab() {
  fireEvent.click(documentsTab());
  await waitFor(() => {
    expect(
      screen.getByRole("textbox", { name: "Document content" }),
    ).toBeTruthy();
  });
}

/** Submit a prompt and wait for the mocked backend run to complete. */
async function submitPrompt(text: string) {
  fireEvent.change(screen.getByLabelText("Message"), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
  await waitFor(() => {
    expect(screen.getAllByText(text).length).toBeGreaterThan(0);
  });
}

describe("AppWorkspace", () => {
  it("opens and closes the collapsible Run Inspector", async () => {
    window.localStorage.clear();
    render(<AppWorkspace client={client} />);
    fireEvent.click(screen.getByRole("button", { name: "Toggle Run Inspector" }));
    expect(await screen.findByRole("complementary", { name: "Run Inspector" })).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: "Request" }));
    expect(screen.getByRole("tab", { name: "Request" }).getAttribute("aria-selected")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "Toggle Run Inspector" }));
    await waitFor(() => expect(screen.queryByRole("complementary", { name: "Run Inspector" })).toBeNull());
    fireEvent.click(screen.getByRole("button", { name: "Toggle Run Inspector" }));
    const reopenedRequestTab = await screen.findByRole("tab", { name: "Request" });
    expect(reopenedRequestTab.getAttribute("aria-selected")).toBe("true");
  });

  it("loads, uploads, and removes files for the active conversation", async () => {
    vi.mocked(listConversations).mockResolvedValue({
      contract_version: "v1",
      conversations: [{ conversation_id: "attachment-chat", title: "Attachment chat", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", is_pinned: false, is_archived: false, folder_id: null, project_id: null, contract_version: "v1" }],
    });
    vi.mocked(listMessages).mockResolvedValue({ contract_version: "v1", conversation_id: "attachment-chat", messages: [] });
    vi.mocked(listConversationAttachments).mockResolvedValue({
      contract_version: "v1",
      owner_type: "conversation",
      owner_id: "attachment-chat",
      attachments: [],
    });
    vi.mocked(uploadConversationAttachment).mockResolvedValue({
      attachment_id: "attachment-notes",
      file_name: "notes.md",
      media_type: "text/markdown",
      size_bytes: 4,
      owner_type: "conversation",
      owner_id: "attachment-chat",
      status: "available",
      created_at: "2026-01-01T00:00:00Z",
      contract_version: "v1",
    });
    render(<AppWorkspace client={client} />);
    await screen.findByRole("button", { name: "Attachment chat" });
    expect(await screen.findByRole("button", { name: "Attach files" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Attach files" }));
    const input = screen.getByLabelText("Choose files to attach");
    fireEvent.change(input, { target: { files: [new File(["data"], "notes.md", { type: "text/markdown" })] } });
    expect(await screen.findByText("notes.md")).toBeTruthy();
    expect(uploadConversationAttachment).toHaveBeenCalledWith(client, "attachment-chat", expect.any(File));

    fireEvent.click(screen.getByRole("button", { name: "Remove notes.md" }));
    await waitFor(() => expect(deleteConversationAttachment).toHaveBeenCalledWith(client, "attachment-chat", "attachment-notes"));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Remove notes.md" })).toBeNull());
  });

  it("keeps a slow upload attached to its original conversation after switching chats", async () => {
    window.sessionStorage.setItem("ava.activeConversationId", "conversation-a");
    vi.mocked(listConversations).mockResolvedValue({
      contract_version: "v1",
      conversations: [
        { conversation_id: "conversation-a", title: "Conversation A", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", is_pinned: false, is_archived: false, folder_id: null, project_id: null, contract_version: "v1" },
        { conversation_id: "conversation-b", title: "Conversation B", created_at: "2026-01-02T00:00:00Z", updated_at: "2026-01-02T00:00:00Z", is_pinned: false, is_archived: false, folder_id: null, project_id: null, contract_version: "v1" },
      ],
    });
    vi.mocked(listMessages).mockImplementation(async (_client, conversationId) => ({ contract_version: "v1", conversation_id: conversationId, messages: [] }));
    vi.mocked(listConversationAttachments).mockImplementation(async (_client, conversationId) => ({
      contract_version: "v1",
      owner_type: "conversation",
      owner_id: conversationId,
      attachments: [],
    }));
    let releaseUpload!: () => void;
    vi.mocked(uploadConversationAttachment).mockImplementation(async () => new Promise((resolve) => {
      releaseUpload = () => resolve({
        attachment_id: "late-attachment",
        file_name: "late.md",
        media_type: "text/markdown",
        size_bytes: 4,
        owner_type: "conversation",
        owner_id: "conversation-a",
        status: "available",
        created_at: "2026-01-01T00:00:00Z",
        contract_version: "v1",
      });
    }));

    render(<AppWorkspace client={client} />);
    await screen.findByRole("button", { name: "Attach files" });
    fireEvent.click(screen.getByRole("button", { name: "Attach files" }));
    fireEvent.change(screen.getByLabelText("Choose files to attach"), {
      target: { files: [new File(["data"], "late.md", { type: "text/markdown" })] },
    });
    await waitFor(() => expect(uploadConversationAttachment).toHaveBeenCalledWith(client, "conversation-a", expect.any(File)));
    fireEvent.click(screen.getByRole("button", { name: "Conversation B" }));
    await waitFor(() => expect(listConversationAttachments).toHaveBeenCalledWith(client, "conversation-b"));
    releaseUpload();
    await waitFor(() => expect(screen.queryByText("late.md")).toBeNull());
  });

  it("keeps unsent composer drafts scoped to their conversation through rapid switches", async () => {
    window.sessionStorage.setItem("ava.activeConversationId", "conversation-a");
    vi.mocked(listConversations).mockResolvedValue({ contract_version: "v1", conversations: [
      { conversation_id: "conversation-a", title: "Conversation A", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", is_pinned: false, is_archived: false, folder_id: null, project_id: null, contract_version: "v1" },
      { conversation_id: "conversation-b", title: "Conversation B", created_at: "2026-01-02T00:00:00Z", updated_at: "2026-01-02T00:00:00Z", is_pinned: false, is_archived: false, folder_id: null, project_id: null, contract_version: "v1" },
      { conversation_id: "conversation-c", title: "Conversation C", created_at: "2026-01-03T00:00:00Z", updated_at: "2026-01-03T00:00:00Z", is_pinned: false, is_archived: false, folder_id: null, project_id: null, contract_version: "v1" },
    ] });
    vi.mocked(listMessages).mockImplementation(async (_client, conversationId) => ({ contract_version: "v1", conversation_id: conversationId, messages: [] }));
    render(<AppWorkspace client={client} />);
    const composer = await screen.findByLabelText("Message") as HTMLTextAreaElement;
    fireEvent.change(composer, { target: { value: "draft-A" } });
    fireEvent.click(screen.getByRole("button", { name: "Conversation B" }));
    expect((screen.getByLabelText("Message") as HTMLTextAreaElement).value).toBe("");
    fireEvent.click(screen.getByRole("button", { name: "Conversation C" }));
    expect((screen.getByLabelText("Message") as HTMLTextAreaElement).value).toBe("");
    fireEvent.click(screen.getByRole("button", { name: "Conversation A" }));
    expect((screen.getByLabelText("Message") as HTMLTextAreaElement).value).toBe("draft-A");
  });

  it("resizes the Run Inspector within its minimum and maximum widths", async () => {
    window.localStorage.clear();
    render(<AppWorkspace client={client} />);
    fireEvent.click(screen.getByRole("button", { name: "Toggle Run Inspector" }));
    const separator = await screen.findByRole("separator", { name: "Resize Run Inspector" });
    Object.defineProperty(separator, "setPointerCapture", { value: vi.fn(), configurable: true });
    fireEvent.pointerDown(separator, { pointerId: 1 });
    fireEvent.pointerMove(separator, { pointerId: 1, buttons: 1, clientX: window.innerWidth });
    expect(separator.getAttribute("aria-valuenow")).toBe("280");
    expect(window.localStorage.getItem("ava.ui.run-inspector-width")).toBe("280");
    fireEvent.pointerMove(separator, { pointerId: 1, buttons: 1, clientX: window.innerWidth - 500 });
    expect(separator.getAttribute("aria-valuenow")).toBe("500");
    expect(window.localStorage.getItem("ava.ui.run-inspector-width")).toBe("500");
    fireEvent.pointerMove(separator, { pointerId: 1, buttons: 1, clientX: 0 });
    expect(separator.getAttribute("aria-valuenow")).toBe("700");
    expect(window.localStorage.getItem("ava.ui.run-inspector-width")).toBe("700");
  });

  it("gives the shared composer the full responsive Chat canvas with modest gutters", () => {
    render(<AppWorkspace client={client} />);
    const composer = screen.getByLabelText("Message").closest("[data-prompt-composer]");
    expect(composer?.className).toContain("w-full rounded-3xl");
    expect(composer?.parentElement?.className).toContain("mx-auto");
    expect(composer?.parentElement?.className).toContain("max-w-[90rem]");
    expect(composer?.parentElement?.className).toContain("px-3");
    expect(composer?.parentElement?.className).toContain("sm:px-4");
    expect(composer?.parentElement?.className).toContain("lg:px-6");
  });

  it("shows and retries a failed Documents bootstrap without treating it as empty", async () => {
    vi.mocked(listDocuments)
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce({ contract_version: "v1", documents: [] });

    render(<StrictMode><AppWorkspace client={client} /></StrictMode>);
    fireEvent.click(documentsTab());

    expect(await screen.findByRole("alert", { name: "Documents could not be loaded." })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Retry loading documents" }));
    expect(await screen.findByText("No document open")).toBeTruthy();
    await waitFor(() => expect(screen.queryByRole("alert", { name: "Documents could not be loaded." })).toBeNull());
    expect(vi.mocked(listDocuments)).toHaveBeenCalledTimes(3);
  });

  it("recovers failed Conversations and Folder startup loads through in-place retry", async () => {
    vi.mocked(listConversations)
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce({
        contract_version: "v1",
        conversations: [{ conversation_id: "recovered-chat", title: "Recovered after outage", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", is_pinned: false, is_archived: false, folder_id: null, project_id: null, contract_version: "v1" }],
      });
    vi.mocked(listConversationFolders)
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce({ folders: [], contract_version: "v1" });
    vi.mocked(listMessages).mockResolvedValue({ contract_version: "v1", conversation_id: "recovered-chat", messages: [] });

    render(<StrictMode><AppWorkspace client={client} /></StrictMode>);

    await screen.findByText("Unable to load conversations.");
    await screen.findByText("Unable to load folders. Conversations are shown without folders.");
    fireEvent.click(await screen.findByRole("button", { name: "Retry loading conversations" }));
    fireEvent.click(await screen.findByRole("button", { name: "Retry loading folders" }));

    expect((await screen.findAllByText("Recovered after outage")).length).toBeGreaterThan(0);
    await waitFor(() => {
      expect(screen.queryByText("Unable to load conversations.")).toBeNull();
      expect(screen.queryByText("Unable to load folders. Conversations are shown without folders.")).toBeNull();
    });
    expect(vi.mocked(listConversations)).toHaveBeenCalledTimes(3);
    expect(vi.mocked(listConversationFolders)).toHaveBeenCalledTimes(3);
  });

  it("opens the Settings section requested by a hydrated configuration failure", async () => {
    vi.mocked(listConversations).mockResolvedValueOnce({
      contract_version: "v1",
      conversations: [{ conversation_id: "conversation-1", title: "Failed", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", is_pinned: false, is_archived: false, folder_id: null, project_id: null, contract_version: "v1" }],
    });
    vi.mocked(listMessages).mockResolvedValueOnce({
      contract_version: "v1", conversation_id: "conversation-1", messages: [
        { message_id: "assistant-1", conversation_id: "conversation-1", role: "assistant", content: "Partial response", status: "failed", source_run_id: "run-1", error_code: "model_unavailable", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", contract_version: "v1" },
      ],
    });
    render(<AppWorkspace client={client} />);
    await screen.findByText("Partial response");
    // The action names the section it opens, so the test can assert the destination.
    fireEvent.click(screen.getByLabelText("Open Model Settings"));
    expect(
      (await screen.findByRole("tab", { name: "Models" })).getAttribute("aria-selected"),
    ).toBe("true");
  });
  beforeEach(() => {
    nextConversationId = 1;
    vi.clearAllMocks();
    vi.mocked(getHealth).mockReset().mockResolvedValue({ status: "healthy", application: "AVA", contract_version: "v1" });
    vi.mocked(getModels).mockReset().mockResolvedValue({ contract_version: "v1", models: [], default_model_id: null });
    vi.mocked(previewContextWindow).mockReset().mockResolvedValue({
      context_window_tokens: null,
      input_budget_tokens: null,
      estimated_input_tokens: 0,
      output_reserve_tokens: 0,
      dropped_message_count: 0,
      dropped_turn_count: 0,
      count_accuracy: "estimated",
      can_fit: true,
      required_input_tokens: null,
      model_id: null,
    });
    window.sessionStorage.clear();
    window.localStorage.clear();
    vi.mocked(listConversations).mockReset().mockResolvedValue({ contract_version: "v1", conversations: [] });
    vi.mocked(listMessages).mockReset().mockResolvedValue({ contract_version: "v1", conversation_id: "conversation-1", messages: [] });
    vi.mocked(listProjects).mockReset().mockResolvedValue({ projects: [], contract_version: "v1" });
    vi.mocked(listProjectConversations).mockReset().mockResolvedValue({ conversations: [], contract_version: "v1" });
    vi.mocked(listConversationFolders).mockReset().mockResolvedValue({ folders: [], contract_version: "v1" });
    vi.mocked(relocateConversation).mockReset();
    vi.mocked(setConversationProject).mockReset();
    vi.mocked(setConversationArchived).mockReset();
    window.history.replaceState(null, "", "/");
  });

  it("adds Projects navigation and loads the list without disturbing the conversation shell", async () => {
    vi.mocked(listProjects).mockResolvedValue({
      contract_version: "v1",
      projects: [{ id: "p-1", name: "AVA Engineering", description: null, instructions: null, is_archived: false, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", contract_version: "v1" }],
    });
    render(<AppWorkspace client={client} />);
    const projectsTab = screen.getByRole("link", { name: "Projects" });
    expect(projectsTab).toBeTruthy();
    fireEvent.click(projectsTab);
    expect(await screen.findByRole("heading", { name: "Projects" })).toBeTruthy();
    expect(window.location.pathname).toBe("/projects");
    expect(listProjects).toHaveBeenCalledWith(client);
    expect(screen.getByRole("link", { name: "Projects" }).getAttribute("aria-current")).toBe("page");

    fireEvent.click(screen.getByRole("link", { name: "Chat" }));
    expect(await screen.findByLabelText("Message")).toBeTruthy();
    expect(window.location.pathname).toBe("/");
  });

  it("loads Project chats lazily, creates in that Project, and keeps later global New Chat unscoped", async () => {
    const project = { id: "p-chat", name: "Project Chat", description: null, instructions: null, is_archived: false, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", contract_version: "v1" as const };
    vi.mocked(listConversations).mockResolvedValue({
      conversations: [{ conversation_id: "existing-project-chat", title: "Existing Project chat", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", is_pinned: false, is_archived: false, folder_id: null, project_id: project.id, contract_version: "v1" }],
      contract_version: "v1",
    });
    vi.mocked(listProjects).mockResolvedValue({ projects: [project], contract_version: "v1" });
    const existingProjectChat = { conversation_id: "existing-project-chat", title: "Existing Project chat", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", is_pinned: false, is_archived: false, folder_id: null, project_id: project.id, contract_version: "v1" as const };
    const newProjectChat = { conversation_id: "new-project-chat", title: "New Conversation", created_at: "2026-01-02T00:00:00Z", updated_at: "2026-01-02T00:00:00Z", is_pinned: false, is_archived: false, folder_id: null, project_id: project.id, contract_version: "v1" as const };
    vi.mocked(listProjectConversations)
      .mockResolvedValueOnce({ conversations: [existingProjectChat], contract_version: "v1" })
      .mockResolvedValue({ conversations: [newProjectChat, existingProjectChat], contract_version: "v1" });
    vi.mocked(createProjectConversation).mockResolvedValue({
      ...newProjectChat,
    });
    render(<AppWorkspace client={client} />);

    expect(await screen.findByText("Project Chat")).toBeTruthy();
    expect(screen.getByRole("button", { name: "New Chat" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Expand Project Chat" }));
    expect(await screen.findByRole("button", { name: "Existing Project chat" })).toBeTruthy();
    expect(listProjectConversations).toHaveBeenCalledWith(client, project.id);

    const projectNewChat = screen.getByRole("button", { name: "New Chat in Project Chat" });
    expect(projectNewChat.className).toContain("bg-transparent");
    expect(projectNewChat.className).toContain("h-8");
    expect(projectNewChat.querySelector("svg")?.getAttribute("class")).toContain("lucide-plus");
    fireEvent.click(projectNewChat);
    await waitFor(() => expect(createProjectConversation).toHaveBeenCalledWith(client, project.id));
    fireEvent.change(screen.getByLabelText("Message"), { target: { value: "Project first prompt" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(createMessage).toHaveBeenCalledWith(client, "new-project-chat", expect.objectContaining({ content: "Project first prompt" })));
    await waitFor(() => expect(startRun).toHaveBeenCalledWith(client, expect.objectContaining({ conversation_id: "new-project-chat", prompt: "Project first prompt" })));

    fireEvent.click(screen.getByRole("button", { name: "New Chat" }));
    await waitFor(() => expect(createConversation).toHaveBeenCalledWith(client));
    fireEvent.change(screen.getByLabelText("Message"), { target: { value: "Global prompt" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(createMessage).toHaveBeenCalledWith(client, "conversation-1", expect.objectContaining({ content: "Global prompt" })));
    expect(createProjectConversation).toHaveBeenCalledTimes(1);
  });

  it("keeps Chat usable when the Project list fails to load", async () => {
    vi.mocked(listProjects).mockRejectedValueOnce(new Error("project service unavailable"));
    vi.mocked(listConversations).mockResolvedValueOnce({
      conversations: [{ conversation_id: "global-chat", title: "Global chat", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", is_pinned: false, is_archived: false, folder_id: null, project_id: null, contract_version: "v1" }],
      contract_version: "v1",
    });
    render(<AppWorkspace client={client} />);
    expect((await screen.findAllByText("Global chat")).length).toBeGreaterThan(0);
    expect(await screen.findByText("Projects are temporarily unavailable.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "New Chat" })).toBeTruthy();
    expect(screen.getByLabelText("Message")).toBeTruthy();
  });

  it("opens conversation System Prompts without changing selection, transcript, or an active run", async () => {
    vi.mocked(listConversations).mockResolvedValueOnce({
      conversations: [{ conversation_id: "conversation-1", title: "Stay selected", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", is_pinned: false, is_archived: false, folder_id: null, project_id: null, contract_version: "v1" }],
      contract_version: "v1",
    });
    vi.mocked(listMessages).mockResolvedValueOnce({ contract_version: "v1", conversation_id: "conversation-1", messages: [
      { message_id: "user-existing", conversation_id: "conversation-1", role: "user", content: "Transcript remains", status: "complete", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", contract_version: "v1" },
    ] });
    vi.mocked(startRun).mockResolvedValueOnce({ run_id: "prompt-run", status: "running", contract_version: "v1" });
    let runSignal: AbortSignal | undefined;
    vi.mocked(streamRun).mockImplementationOnce(async (_client, _runId, options) => {
      runSignal = options.signal;
      await new Promise<void>((resolve) => options.signal?.addEventListener("abort", () => resolve(), { once: true }));
    });
    render(<AppWorkspace client={client} />);
    expect(await screen.findByText("Transcript remains")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Message"), { target: { value: "Keep run active" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(streamRun).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("button", { name: "Conversation actions for Stay selected" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "System Prompts" }));
    expect(await screen.findByRole("dialog", { name: "System Prompts — Conversation: Stay selected" })).toBeTruthy();
    const assignment = await screen.findByRole("combobox", { name: "Assignment for Prompt One at Conversation: Stay selected" });
    fireEvent.change(assignment, { target: { value: "enable" } });
    await waitFor(() => expect(setCorePromptAssignment).toHaveBeenCalledWith(client, "prompt-1", {
      scope_type: "conversation", scope_id: "conversation-1", state: "enable",
    }));
    expect(screen.getByText("Transcript remains")).toBeTruthy();
    expect(runSignal?.aborted).toBe(false);
    expect(listMessages).toHaveBeenCalledTimes(1);
  });

  it("isolates a failed Project conversation load to that Project section", async () => {
    const project = { id: "p-failing", name: "Unavailable Project", description: null, instructions: null, is_archived: false, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", contract_version: "v1" as const };
    vi.mocked(listProjects).mockResolvedValueOnce({ projects: [project], contract_version: "v1" });
    vi.mocked(listConversations).mockResolvedValueOnce({
      conversations: [{ conversation_id: "global-chat", title: "Global chat", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", is_pinned: false, is_archived: false, folder_id: null, project_id: null, contract_version: "v1" }],
      contract_version: "v1",
    });
    vi.mocked(listProjectConversations).mockRejectedValueOnce(new Error("project conversation service unavailable"));
    render(<AppWorkspace client={client} />);
    fireEvent.click(await screen.findByRole("button", { name: "Expand Unavailable Project" }));
    expect(await screen.findByText("This Project's conversations could not be loaded.")).toBeTruthy();
    expect(screen.getAllByText("Global chat").length).toBeGreaterThan(0);
    expect(screen.getByLabelText("Message")).toBeTruthy();
  });

  it("retries a failed Project conversation load and replaces the error with the loaded chat", async () => {
    const project = { id: "p-retry", name: "Retry Project", description: null, instructions: null, is_archived: false, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", contract_version: "v1" as const };
    const conversation = { conversation_id: "retry-chat", title: "Recovered Project chat", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", is_pinned: false, is_archived: false, folder_id: null, project_id: project.id, contract_version: "v1" as const };
    vi.mocked(listProjects).mockResolvedValueOnce({ projects: [project], contract_version: "v1" });
    vi.mocked(listConversations).mockResolvedValueOnce({ conversations: [conversation], contract_version: "v1" });
    vi.mocked(listProjectConversations)
      .mockRejectedValueOnce(new Error("temporary Project query failure"))
      .mockResolvedValueOnce({ conversations: [conversation], contract_version: "v1" });
    render(<AppWorkspace client={client} />);

    fireEvent.click(await screen.findByRole("button", { name: "Expand Retry Project" }));
    expect(await screen.findByText("This Project's conversations could not be loaded.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByRole("button", { name: "Recovered Project chat" })).toBeTruthy();
    expect(screen.queryByText("This Project's conversations could not be loaded.")).toBeNull();
    expect(listProjectConversations).toHaveBeenCalledTimes(2);
    expect(listProjectConversations).toHaveBeenNthCalledWith(2, client, project.id);
  });

  it("retries failed sidebar Project chat creation after clearing its pending state", async () => {
    const project = { id: "p-create-retry", name: "Create Retry Project", description: null, instructions: null, is_archived: false, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", contract_version: "v1" as const };
    const created = { conversation_id: "created-on-retry", title: "New Conversation", created_at: "2026-01-02T00:00:00Z", updated_at: "2026-01-02T00:00:00Z", is_pinned: false, is_archived: false, folder_id: null, project_id: project.id, contract_version: "v1" as const };
    vi.mocked(listProjects).mockResolvedValueOnce({ projects: [project], contract_version: "v1" });
    vi.mocked(listConversations).mockResolvedValue({ conversations: [created], contract_version: "v1" });
    vi.mocked(listProjectConversations).mockResolvedValue({ conversations: [created], contract_version: "v1" });
    vi.mocked(createProjectConversation).mockRejectedValueOnce(new Error("temporary create failure")).mockResolvedValueOnce(created);
    render(<AppWorkspace client={client} />);

    fireEvent.click(await screen.findByRole("button", { name: "Expand Create Retry Project" }));
    const createButton = await screen.findByRole("button", { name: "New Chat in Create Retry Project" });
    fireEvent.click(createButton);
    expect(await screen.findByText("Unable to create a chat in this Project. Please try again.")).toBeTruthy();
    expect(createButton.hasAttribute("disabled")).toBe(false);

    fireEvent.click(createButton);
    await waitFor(() => expect(createProjectConversation).toHaveBeenCalledTimes(2));
    expect((await screen.findAllByText("New Conversation")).length).toBeGreaterThan(0);
    expect(screen.queryByText("Unable to create a chat in this Project. Please try again.")).toBeNull();
    expect(createProjectConversation).toHaveBeenLastCalledWith(client, project.id);
  });

  it("shows Project-scoped conversations in global search and opens the canonical result", async () => {
    const project = { id: "p-search", name: "Search Project", description: null, instructions: null, is_archived: false, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", contract_version: "v1" as const };
    const conversation = { conversation_id: "search-project-chat", title: "Searchable Project chat", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", is_pinned: false, is_archived: false, folder_id: null, project_id: project.id, contract_version: "v1" as const };
    vi.mocked(listProjects).mockResolvedValueOnce({ projects: [project], contract_version: "v1" });
    vi.mocked(listConversations).mockImplementation(async () => ({
      conversations: [conversation],
      contract_version: "v1",
    }));
    vi.mocked(listProjectConversations).mockResolvedValueOnce({ conversations: [conversation], contract_version: "v1" });
    vi.mocked(listMessages).mockResolvedValue({ conversation_id: conversation.conversation_id, messages: [], contract_version: "v1" });
    render(<AppWorkspace client={client} />);

    fireEvent.click(await screen.findByRole("button", { name: "Expand Search Project" }));
    fireEvent.change(screen.getByRole("searchbox", { name: "Search conversations" }), { target: { value: "Searchable Project" } });
    const result = await screen.findByRole("button", { name: "Searchable Project chat" });
    fireEvent.click(result);

    await waitFor(() => expect(listMessages).toHaveBeenCalledTimes(2));
    expect(listMessages).toHaveBeenLastCalledWith(client, conversation.conversation_id);
    expect(screen.getByRole("heading", { name: "Searchable Project chat" })).toBeTruthy();
  });

  it("moves a canonical conversation between Projects and out with exclusive persisted destinations", async () => {
    const projectA = { id: "p-a", name: "Project A", description: null, instructions: null, is_archived: false, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", contract_version: "v1" as const };
    const projectB = { id: "p-b", name: "Project B", description: null, instructions: null, is_archived: false, created_at: "2026-01-02T00:00:00Z", updated_at: "2026-01-02T00:00:00Z", contract_version: "v1" as const };
    let assignedProject: string | null = null;
    let assignedFolder: string | null = "folder-a";
    const projectAssignments: Array<string | null> = [];
    const canonical = { conversation_id: "move-me", title: "Move me", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", is_pinned: false, is_archived: false, folder_id: "folder-a", project_id: null, contract_version: "v1" as const };
    vi.mocked(listProjects).mockResolvedValue({ projects: [projectA, projectB], contract_version: "v1" });
    vi.mocked(listConversations).mockResolvedValue({ conversations: [canonical], contract_version: "v1" });
    vi.mocked(listConversationFolders).mockResolvedValue({ folders: [{ id: "folder-a", name: "Folder A", created_at: canonical.created_at, updated_at: canonical.updated_at, contract_version: "v1" }], contract_version: "v1" });
    vi.mocked(listMessages).mockResolvedValue({ contract_version: "v1", conversation_id: canonical.conversation_id, messages: [
      { message_id: "user-existing", conversation_id: canonical.conversation_id, role: "user", content: "Transcript stays", status: "complete", created_at: canonical.created_at, updated_at: canonical.created_at, contract_version: "v1" },
    ] });
    vi.mocked(listProjectConversations).mockImplementation(async (_client, projectId) => ({
      contract_version: "v1",
      conversations: assignedProject === projectId ? [{ ...canonical, folder_id: assignedFolder, project_id: projectId }] : [],
    }));
    vi.mocked(relocateConversation).mockImplementation(async (_client, _id, request) => {
      assignedProject = request.destination_type === "project" ? request.destination_id ?? null : null;
      assignedFolder = request.destination_type === "folder" ? request.destination_id ?? null : null;
      projectAssignments.push(assignedProject);
      return { ...canonical, folder_id: assignedFolder, project_id: assignedProject };
    });
    render(<AppWorkspace client={client} />);
    expect(await screen.findByText("Transcript stays")).toBeTruthy();
    vi.mocked(startRun).mockResolvedValueOnce({ run_id: "move-run", status: "running", contract_version: "v1" });
    let runSignal: AbortSignal | undefined;
    vi.mocked(streamRun).mockImplementationOnce(async (_client, _runId, options) => {
      runSignal = options.signal;
      await new Promise<void>((resolve) => {
        if (options.signal == null || options.signal.aborted) return resolve();
        options.signal.addEventListener("abort", () => resolve(), { once: true });
      });
    });
    fireEvent.change(screen.getByLabelText("Message"), { target: { value: "Keep this run" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(streamRun).toHaveBeenCalled());

    const openActions = () => fireEvent.click(screen.getAllByLabelText("Conversation actions for Move me")[0]);
    const moveTo = (projectName: string) => {
      fireEvent.click(screen.getByRole("menuitem", { name: "Move" }));
      fireEvent.change(screen.getByLabelText("Move destination"), { target: { value: projectName === "No Project" ? "__none__" : projectName === "Project A" ? "p-a" : "p-b" } });
      fireEvent.click(screen.getByRole("button", { name: "Move" }));
    };
    openActions();
    moveTo("Project A");
    await waitFor(() => expect(relocateConversation).toHaveBeenLastCalledWith(client, "move-me", { destination_type: "project", destination_id: "p-a" }));
    expect(screen.getByText("Transcript stays")).toBeTruthy();
    expect(runSignal?.aborted).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Expand Project A" }));
    expect((await screen.findAllByLabelText("Conversation actions for Move me")).length).toBe(1);
    openActions();
    moveTo("Project B");
    await waitFor(() => expect(relocateConversation).toHaveBeenLastCalledWith(client, "move-me", { destination_type: "project", destination_id: "p-b" }));
    expect(screen.getByText("Transcript stays")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Expand Project B" }));
    openActions();
    moveTo("No Project");
    await waitFor(() => expect(relocateConversation).toHaveBeenLastCalledWith(client, "move-me", { destination_type: "ungrouped" }));
    expect(screen.getByText("Transcript stays")).toBeTruthy();
    expect(document.querySelector('[data-folder-drop-target="folder-a"] [data-conversation-row="move-me"]')).toBeNull();
    expect(projectAssignments).toEqual(["p-a", "p-b", null]);
  });

  it("updates Project conversation pin/archive metadata without losing membership", async () => {
    const project = { id: "p-meta", name: "Metadata Project", description: null, instructions: null, is_archived: false, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", contract_version: "v1" as const };
    const canonical = { conversation_id: "metadata-chat", title: "Metadata chat", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", is_pinned: false, is_archived: false, folder_id: null, project_id: project.id, contract_version: "v1" as const };
    vi.mocked(listProjects).mockResolvedValueOnce({ projects: [project], contract_version: "v1" });
    vi.mocked(listConversations).mockResolvedValueOnce({ conversations: [canonical], contract_version: "v1" });
    vi.mocked(listProjectConversations).mockResolvedValue({ conversations: [canonical], contract_version: "v1" });
    vi.mocked(setConversationPinned).mockResolvedValue({ ...canonical, is_pinned: true });
    vi.mocked(setConversationArchived).mockResolvedValue({ ...canonical, is_pinned: true, is_archived: true });
    render(<AppWorkspace client={client} />);
    await screen.findByText("Metadata chat");
    fireEvent.click(screen.getByRole("button", { name: "Expand Metadata Project" }));
    await screen.findByRole("button", { name: "Metadata chat" });
    const openActions = () => fireEvent.click(screen.getByLabelText("Conversation actions for Metadata chat"));
    openActions();
    fireEvent.click(screen.getByRole("menuitem", { name: "Pin" }));
    await waitFor(() => expect(setConversationPinned).toHaveBeenCalledWith(client, "metadata-chat", { is_pinned: true }));
    openActions();
    expect(screen.getByRole("menuitem", { name: "Unpin" })).toBeTruthy();
    fireEvent.click(screen.getByRole("menuitem", { name: "Archive" }));
    await waitFor(() => expect(setConversationArchived).toHaveBeenCalledWith(client, "metadata-chat", { is_archived: true }));
    expect(screen.getByText("No conversation selected.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Archived" }));
    expect(screen.getByRole("button", { name: "Metadata chat" })).toBeTruthy();
    expect(listProjectConversations).toHaveBeenCalledWith(client, project.id);
  });

  it("loads a direct Project route on refresh and keeps background run observation across navigation", async () => {
    window.history.replaceState(null, "", "/projects/p-1");
    vi.mocked(listProjects).mockResolvedValue({
      projects: [{ id: "p-1", name: "AVA Engineering", description: null, instructions: "Inert", is_archived: true, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", contract_version: "v1" }],
      contract_version: "v1",
    });
    vi.mocked(getProject).mockResolvedValue({
      id: "p-1", name: "AVA Engineering", description: null, instructions: "Inert", is_archived: true,
      created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", contract_version: "v1",
    });
    render(<AppWorkspace client={client} />);
    expect(await screen.findByRole("heading", { name: "AVA Engineering" })).toBeTruthy();
    expect(getProject).toHaveBeenCalledWith(client, "p-1");
    fireEvent.click(screen.getByRole("button", { name: "Back to Projects" }));
    await screen.findByRole("heading", { name: "Projects" });

    fireEvent.click(screen.getByRole("link", { name: "Chat" }));
    fireEvent.click(screen.getByRole("button", { name: "New Chat" }));
    await screen.findByLabelText("Message");
    vi.mocked(startRun).mockResolvedValueOnce({
      run_id: "run-project-nav",
      status: "running",
      assistant_message_id: "assistant-project-nav",
      contract_version: "v1",
    });
    let runSignal: AbortSignal | undefined;
    vi.mocked(streamRun).mockImplementationOnce(async (_apiClient, _runId, options) => {
      runSignal = options.signal;
      await new Promise<void>((resolve) => {
        if (options.signal == null || options.signal.aborted) return resolve();
        options.signal.addEventListener("abort", () => resolve(), { once: true });
      });
    });
    fireEvent.change(screen.getByLabelText("Message"), { target: { value: "Keep streaming" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(streamRun).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("link", { name: "Projects" }));
    await screen.findByRole("heading", { name: "Projects" });
    fireEvent.click(screen.getByRole("button", { name: "Open" }));
    expect(await screen.findByRole("heading", { name: "AVA Engineering" })).toBeTruthy();
    expect(screen.getByLabelText("Archived Project")).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: "Files" }));
    expect(await screen.findByText("No files in this Project yet.")).toBeTruthy();
    expect(runSignal?.aborted).toBe(false);
    fireEvent.click(screen.getByRole("link", { name: "Chat" }));
    expect((await screen.findAllByText("Keep streaming")).length).toBeGreaterThan(0);
    expect(runSignal?.aborted).toBe(false);
  });

  it("shows a safe not-found state for a directly refreshed unknown Project route", async () => {
    window.history.replaceState(null, "", "/projects/missing-project");
    vi.mocked(getProject).mockRejectedValueOnce(new ApiError(
      "Request failed: 404", 404, { error_code: "project_not_found" },
    ));
    render(<AppWorkspace client={client} />);
    expect(await screen.findByRole("heading", { name: "Project not found" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Projects" }).getAttribute("aria-current")).toBe("page");
    expect(getProject).toHaveBeenCalledWith(client, "missing-project");
  });

  it("starts in the chat workspace with the document workspace closed", () => {
    render(<AppWorkspace client={client} />);
    expect(chatTab().getAttribute("aria-current")).toBe("page");
    expect(documentsTab().getAttribute("aria-current")).toBeNull();
    expect(screen.getByText("No conversation selected.")).toBeTruthy();
    expect(screen.getByLabelText("Message")).toBeTruthy();
    expect(
      screen.queryByRole("textbox", { name: "Document content" }),
    ).toBeNull();
  });

  it("loads Documents directly and marks its primary route", async () => {
    window.history.replaceState(null, "", "/documents");
    render(<AppWorkspace client={client} />);
    expect(screen.getByRole("link", { name: "Documents" }).getAttribute("aria-current")).toBe("page");
    expect(await screen.findByRole("textbox", { name: "Document content" })).toBeTruthy();
  });

  it("loads Settings directly and marks its primary route", async () => {
    window.history.replaceState(null, "", "/settings");
    render(<AppWorkspace client={client} />);
    expect(screen.getByRole("link", { name: "Settings" }).getAttribute("aria-current")).toBe("page");
    expect(await screen.findByTestId("settings-workspace")).toBeTruthy();
  });

  it("loads the shared Approvals view directly and stays read-only without an authorized adapter", async () => {
    window.history.replaceState(null, "", "/approvals");
    render(<AppWorkspace client={client} />);
    expect(screen.getByRole("link", { name: "Approvals" }).getAttribute("aria-current")).toBe("page");
    expect(await screen.findByText("Approval service unavailable")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
  });

  it("shows Unavailable for a transport failure from another ApiClient instance and recovers on success", async () => {
    let resolveInitialHealth!: (value: { status: "healthy"; application: string; contract_version: "v1" }) => void;
    vi.mocked(getHealth).mockImplementationOnce(() => new Promise((resolve) => { resolveInitialHealth = resolve; }));
    const bootstrapRequests = vi.fn().mockRejectedValue(new TypeError("unexpected bootstrap request"));
    const appClient = new ApiClient({ baseUrl: "http://localhost:99999", fetchImpl: bootstrapRequests });
    render(<AppWorkspace client={appClient} />);
    await waitFor(() => expect(resolveInitialHealth).toBeTypeOf("function"));
    await act(async () => resolveInitialHealth({ status: "healthy", application: "AVA", contract_version: "v1" }));
    await waitFor(() => expect(screen.getByText("Connected")).toBeTruthy());

    const failingClient = new ApiClient({
      baseUrl: "http://localhost:8000",
      fetchImpl: vi.fn().mockRejectedValue(new TypeError("backend down")),
    });
    await expect(failingClient.request("/runs")).rejects.toThrow("backend down");
    await waitFor(() => expect(screen.getByText("Unavailable")).toBeTruthy());

    const recoveredClient = new ApiClient({
      baseUrl: "http://localhost:8000",
      fetchImpl: vi.fn().mockResolvedValue(new Response("{}", { status: 200 })),
    });
    await recoveredClient.request("/documents/document-1");
    await waitFor(() => expect(screen.getByText("Connected")).toBeTruthy());
  });

  it("does not let an older health success overwrite a later transport failure", async () => {
    let resolveHealth: ((value: { status: "healthy"; application: string; contract_version: "v1" }) => void) | undefined;
    vi.mocked(getHealth).mockImplementationOnce(() => new Promise((resolve) => { resolveHealth = resolve; }));
    render(<AppWorkspace client={client} />);

    const failingClient = new ApiClient({
      baseUrl: "http://localhost:8000",
      fetchImpl: vi.fn().mockRejectedValue(new TypeError("backend down")),
    });
    await expect(failingClient.request("/health")).rejects.toThrow("backend down");
    await waitFor(() => expect(screen.getByText("Unavailable")).toBeTruthy());

    resolveHealth?.({ status: "healthy", application: "AVA", contract_version: "v1" });
    await Promise.resolve();
    expect(screen.getByText("Unavailable")).toBeTruthy();
  });

  it("opens the document workspace and returns to chat", async () => {
    render(<AppWorkspace client={client} />);
    fireEvent.click(documentsTab());
    await waitFor(() => {
      expect(
        screen.getByRole("textbox", { name: "Document content" }),
      ).toBeTruthy();
    });
    expect(documentsTab().getAttribute("aria-current")).toBe("page");
    expect(chatTab().getAttribute("aria-current")).toBeNull();

    fireEvent.click(chatTab());
    await waitFor(() => {
      expect(chatTab().getAttribute("aria-current")).toBe("page");
    });
  });

  it("preserves conversation state across workspace switches", async () => {
    render(<AppWorkspace client={client} />);
    fireEvent.change(screen.getByLabelText("Message"), {
      target: { value: "Hello preserved conversation" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => {
      expect(
        screen.getAllByText("Hello preserved conversation").length,
      ).toBeGreaterThan(0);
    });

    fireEvent.click(documentsTab());
    await waitFor(() => {
      expect(
        screen.getByRole("textbox", { name: "Document content" }),
      ).toBeTruthy();
    });

    fireEvent.click(chatTab());
    await waitFor(() => {
      expect(
        screen.getAllByText("Hello preserved conversation").length,
      ).toBeGreaterThan(0);
    });
  });

  it("keeps the document editor mounted, preserving its session", async () => {
    render(<AppWorkspace client={client} />);
    fireEvent.click(documentsTab());
    const editorNode = await screen.findByRole("textbox", {
      name: "Document content",
    });
    fireEvent.click(chatTab());
    await waitFor(() => {
      expect(chatTab().getAttribute("aria-current")).toBe("page");
    });
    fireEvent.click(documentsTab());
    await waitFor(() => {
      expect(documentsTab().getAttribute("aria-current")).toBe("page");
    });
    const editorNodeAfter = screen.getByRole("textbox", {
      name: "Document content",
    });
    expect(editorNodeAfter).toBe(editorNode);
  });

  it("shows None for the workspace by default when the registry is empty", async () => {
    render(<AppWorkspace client={client} />);
    fireEvent.click(screen.getByRole("button", { name: /Execution settings/ }));
    await waitFor(() => {
      expect(vi.mocked(getWorkspaces)).toHaveBeenCalled();
    });
    const select = workspaceSelect();
    expect(select.value).toBe("");
    expect(screen.getByRole("option", { name: "None" })).toBeTruthy();
  });

  it("lists discovered workspaces and includes the selection in the run request", async () => {
    vi.mocked(getWorkspaces).mockResolvedValueOnce({
      contract_version: "v1",
      workspaces: [
        { workspace_id: "workspace-a", display_name: "Workspace A", kind: "local" },
        { workspace_id: "workspace-b", display_name: "Workspace B", kind: "ephemeral" },
      ],
    });
    render(<AppWorkspace client={client} />);
    fireEvent.click(screen.getByRole("button", { name: /Execution settings/ }));

    await waitFor(() => {
      expect(screen.getAllByRole("option", { name: "Workspace A" }).length).toBeGreaterThan(0);
    });
    expect(screen.getByRole("option", { name: "None" })).toBeTruthy();
    expect(screen.getByRole("option", { name: "Workspace B" })).toBeTruthy();

    fireEvent.change(workspaceSelect(), { target: { value: "workspace-a" } });
    expect(workspaceSelect().value).toBe("workspace-a");

    await submitPrompt("check the project workspace");

    await waitFor(() => {
      expect(vi.mocked(startRun)).toHaveBeenCalledWith(
        client,
        expect.objectContaining({
          prompt: "check the project workspace",
          workspace_id: "workspace-a",
        }),
      );
    });
  });

  it("omits workspace_id from the run request when no workspace is selected", async () => {
    render(<AppWorkspace client={client} />);
    await waitFor(() => {
      expect(vi.mocked(getWorkspaces)).toHaveBeenCalled();
    });

    await submitPrompt("plain prompt");

    await waitFor(() => {
      expect(vi.mocked(startRun)).toHaveBeenCalledWith(
        client,
        expect.not.objectContaining({ workspace_id: expect.anything() }),
      );
    });
    expect(vi.mocked(startRun)).toHaveBeenCalledWith(
      client,
      expect.objectContaining({ prompt: "plain prompt" }),
    );
  });

  it("keeps the workspace selection when switching execution profile", async () => {
    vi.mocked(getWorkspaces).mockResolvedValueOnce({
      contract_version: "v1",
      workspaces: [
        { workspace_id: "workspace-a", display_name: "Workspace A", kind: "local" },
      ],
    });
    render(<AppWorkspace client={client} />);
    fireEvent.click(screen.getByRole("button", { name: /Execution settings/ }));

    await waitFor(() => {
      expect(screen.getByRole("option", { name: "Workspace A" })).toBeTruthy();
    });
    fireEvent.change(workspaceSelect(), { target: { value: "workspace-a" } });
    expect(workspaceSelect().value).toBe("workspace-a");

    fireEvent.change(
      executionControl("Select execution profile"),
      { target: { value: "fast" } },
    );

    expect(workspaceSelect().value).toBe("workspace-a");
    expect(vi.mocked(getWorkspaces)).toHaveBeenCalledTimes(1);
  });

  it("keeps the workspace selection when switching runtime or model", async () => {
    vi.mocked(getWorkspaces).mockResolvedValueOnce({
      contract_version: "v1",
      workspaces: [
        { workspace_id: "workspace-a", display_name: "Workspace A", kind: "local" },
      ],
    });
    render(<AppWorkspace client={client} />);
    fireEvent.click(screen.getByRole("button", { name: /Execution settings/ }));

    await waitFor(() => {
      expect(screen.getByRole("option", { name: "Workspace A" })).toBeTruthy();
    });
    fireEvent.change(workspaceSelect(), { target: { value: "workspace-a" } });

    fireEvent.change(executionControl("Select runtime"), {
      target: { value: "native" },
    });
    expect(workspaceSelect().value).toBe("workspace-a");

    fireEvent.change(executionControl("Select model"), {
      target: { value: "local" },
    });
    expect(workspaceSelect().value).toBe("workspace-a");
  });

  it("keeps the workspace selection when switching to Auto execution", async () => {
    vi.mocked(getWorkspaces).mockResolvedValueOnce({
      contract_version: "v1",
      workspaces: [
        { workspace_id: "workspace-a", display_name: "Workspace A", kind: "local" },
      ],
    });
    render(<AppWorkspace client={client} />);
    fireEvent.click(screen.getByRole("button", { name: /Execution settings/ }));

    await waitFor(() => {
      expect(screen.getByRole("option", { name: "Workspace A" })).toBeTruthy();
    });
    fireEvent.change(workspaceSelect(), { target: { value: "workspace-a" } });

    fireEvent.change(
      executionControl("Select execution profile"),
      { target: { value: "auto" } },
    );

    expect(workspaceSelect().value).toBe("workspace-a");
  });

  it("keeps the composer usable and swallows the workspace selector when discovery fails", async () => {
    vi.mocked(getWorkspaces).mockRejectedValueOnce(new Error("boom"));
    render(<AppWorkspace client={client} />);
    fireEvent.click(screen.getByRole("button", { name: /Execution settings/ }));

    await waitFor(() => {
      expect(screen.getByText("Workspace options unavailable")).toBeTruthy();
    });
    expect(workspaceSelect().disabled).toBe(true);
    expect(screen.getByLabelText("Message")).toBeTruthy();

    await submitPrompt("still promptable");
    await waitFor(() => {
      expect(vi.mocked(startRun)).toHaveBeenCalledWith(
        client,
        expect.not.objectContaining({ workspace_id: expect.anything() }),
      );
    });
  });

  it("recovers to None for the workspace after a fresh discovery without the stale id", async () => {
    vi.mocked(getWorkspaces)
      .mockResolvedValueOnce({
        contract_version: "v1",
        workspaces: [
          { workspace_id: "workspace-a", display_name: "Workspace A", kind: "local" },
        ],
      })
      .mockResolvedValueOnce({ contract_version: "v1", workspaces: [] });
    const first = render(<AppWorkspace client={client} />);
    fireEvent.click(screen.getByRole("button", { name: /Execution settings/ }));

    await waitFor(() => {
      expect(screen.getByRole("option", { name: "Workspace A" })).toBeTruthy();
    });
    fireEvent.change(workspaceSelect(), { target: { value: "workspace-a" } });
    expect(workspaceSelect().value).toBe("workspace-a");

    first.unmount();
    render(<AppWorkspace client={client} />);
    fireEvent.click(screen.getByRole("button", { name: /Execution settings/ }));

    const newSelect = await screen.findByLabelText("Select workspace");
    await waitFor(() => {
      expect((newSelect as HTMLSelectElement).value).toBe("");
    });
    expect(screen.getAllByRole("option", { name: "None" }).length).toBeGreaterThan(0);
    expect(screen.queryByRole("option", { name: "Workspace A" })).toBeNull();
  });

  it("hydrates durable documents through the shared workspace composition", async () => {
    render(<AppWorkspace client={client} />);
    await openDocumentsTab();

    expect(screen.getByRole("button", { name: "Untitled Document" })).toBeTruthy();
    const editor = screen.getByRole("textbox", { name: "Document content" });
    await waitFor(() => expect(editor.textContent).toContain("Document"));
    expect(vi.mocked(listDocuments)).toHaveBeenCalledWith(client);
    expect(vi.mocked(listDocuments)).toHaveBeenCalledTimes(1);
    expect(vi.mocked(getDocument)).not.toHaveBeenCalled();
  });

  it("treats an empty durable document collection as valid without inventing one", async () => {
    vi.mocked(listDocuments).mockResolvedValueOnce({
      contract_version: "v1",
      documents: [],
    });
    render(<AppWorkspace client={client} />);
    fireEvent.click(documentsTab());
    await screen.findByText("No document open");

    expect(screen.queryByRole("button", { name: /Untitled Document/ })).toBeNull();
    expect(vi.mocked(listDocuments)).toHaveBeenCalledTimes(1);
    expect(vi.mocked(createDocument)).not.toHaveBeenCalled();
  });

  it("creates exactly one backend document and takes its identity as authoritative", async () => {
    render(<AppWorkspace client={client} />);
    await openDocumentsTab();

    fireEvent.click(screen.getByRole("button", { name: "New Document" }));
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Untitled Document 2" }),
      ).toBeTruthy();
    });

    expect(vi.mocked(createDocument)).toHaveBeenCalledTimes(1);
    const [createClient, request] = vi.mocked(createDocument).mock.calls[0];
    expect(createClient).toBe(client);
    expect(request).toEqual({
      title: "Untitled Document 2",
      content: "<p></p>",
      content_format: "html",
    });
    expect(screen.getByRole("button", { name: "Untitled Document 2" }).getAttribute("aria-current")).toBe("page");
    expect(vi.mocked(listDocuments)).toHaveBeenCalledTimes(1);
  });

  it("persists a completed rename immediately with a title-only PATCH and reconciles clean", async () => {
    render(<AppWorkspace client={client} />);
    await openDocumentsTab();

    fireEvent.click(screen.getByRole("button", { name: "Rename document" }));
    fireEvent.change(
      screen.getByRole("textbox", { name: "Document title" }),
      { target: { value: "Durable Notes" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Finish renaming" }));

    await waitFor(() => expect(vi.mocked(updateDocument)).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.queryByText("Unsaved changes")).toBeNull());

    const [updateClient, documentId, request] = vi.mocked(updateDocument).mock.calls[0];
    expect(updateClient).toBe(client);
    expect(documentId).toBe("document-1");
    expect(request).toEqual({ title: "Durable Notes" });
    expect(screen.getByRole("button", { name: "Durable Notes" }).getAttribute("aria-current")).toBe("page");
    expect((screen.getByRole("button", { name: "Save document" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("keeps the workspace mounted and the renamed document dirty when the rename fails to persist", async () => {
    vi.mocked(updateDocument).mockRejectedValueOnce(new Error("save unavailable"));
    render(<AppWorkspace client={client} />);
    await openDocumentsTab();

    fireEvent.click(screen.getByRole("button", { name: "Rename document" }));
    fireEvent.change(
      screen.getByRole("textbox", { name: "Document title" }),
      { target: { value: "Durable Notes" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Finish renaming" }));
    await waitFor(() => expect(vi.mocked(updateDocument)).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByText("Unsaved changes")).toBeTruthy());

    expect(screen.getByRole("link", { name: "Chat" })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Durable Notes/ }).textContent).toBe("Durable Notes \u2022");
    expect(screen.queryByRole("button", { name: /Untitled Document 2/ })).toBeNull();
  });

  it("closes a document locally, keeping it in the sidebar, without issuing any document request", async () => {
    render(<AppWorkspace client={client} />);
    await openDocumentsTab();
    const item = screen.getByRole("button", { name: "Untitled Document" });
    expect(item).toBeTruthy();
    expect(item.getAttribute("aria-current")).toBe("page");

    fireEvent.click(screen.getByRole("button", { name: "Close document" }));
    await screen.findByText("No document open");

    expect(screen.getByRole("button", { name: "Untitled Document" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Untitled Document" }).getAttribute("aria-current")).toBeNull();
    expect(vi.mocked(listDocuments)).toHaveBeenCalledTimes(1);
    expect(vi.mocked(getDocument)).not.toHaveBeenCalled();
    expect(vi.mocked(createDocument)).not.toHaveBeenCalled();
    expect(vi.mocked(updateDocument)).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Untitled Document" }));
    await screen.findByRole("textbox", { name: "Document content" });
    expect(screen.getByRole("button", { name: "Untitled Document" }).getAttribute("aria-current")).toBe("page");
    expect(vi.mocked(listDocuments)).toHaveBeenCalledTimes(1);
    expect(vi.mocked(getDocument)).not.toHaveBeenCalled();
  });

  it("switches between hydrated documents locally without a per-selection GET", async () => {
    vi.mocked(listDocuments).mockResolvedValueOnce({
      contract_version: "v1",
      documents: [
        {
          document_id: "document-1", title: "First Note", content: "<p>First</p>", content_format: "html",
          created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", contract_version: "v1",
        },
        {
          document_id: "document-2", title: "Second Note", content: "<p>Second</p>", content_format: "html",
          created_at: "2026-01-02T00:00:00Z", updated_at: "2026-01-02T00:00:00Z", contract_version: "v1",
        },
      ],
    });
    render(<AppWorkspace client={client} />);
    await openDocumentsTab();

    const first = screen.getByRole("button", { name: "First Note" });
    const second = screen.getByRole("button", { name: "Second Note" });
    expect(first.getAttribute("aria-current")).toBe("page");
    fireEvent.click(second);
    await waitFor(() => {
      expect(second.getAttribute("aria-current")).toBe("page");
      expect(first.getAttribute("aria-current")).toBeNull();
    });

    expect(vi.mocked(listDocuments)).toHaveBeenCalledTimes(1);
    expect(vi.mocked(getDocument)).not.toHaveBeenCalled();
    expect(vi.mocked(createDocument)).not.toHaveBeenCalled();
    expect(vi.mocked(updateDocument)).not.toHaveBeenCalled();
  });
});
