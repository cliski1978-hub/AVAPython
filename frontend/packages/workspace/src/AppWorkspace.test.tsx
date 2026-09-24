// @vitest-environment jsdom
import { ApiClient } from "@ava/api-client";
import {
  createDocument,
  getHealth,
  getDocument,
  getWorkspaces,
  listDocuments,
  startRun,
  updateDocument,
} from "@ava/api-client";
import {
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

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

const client = new ApiClient({ baseUrl: "http://localhost:99999" });

function chatTab() {
  return screen.getByRole("tab", { name: "Chat" });
}

function documentsTab() {
  return screen.getByRole("tab", { name: "Documents" });
}

function workspaceSelect(): HTMLSelectElement {
  return screen.getByLabelText("Select workspace") as HTMLSelectElement;
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
  beforeEach(() => {
    nextConversationId = 1;
    vi.clearAllMocks();
  });

  it("starts in the chat workspace with the document workspace closed", () => {
    render(<AppWorkspace client={client} />);
    expect(chatTab().getAttribute("aria-selected")).toBe("true");
    expect(documentsTab().getAttribute("aria-selected")).toBe("false");
    expect(screen.getByText("No conversation selected.")).toBeTruthy();
    expect(screen.getByLabelText("Message")).toBeTruthy();
    expect(
      screen.queryByRole("textbox", { name: "Document content" }),
    ).toBeNull();
  });

  it("shows Unavailable for a transport failure from another ApiClient instance and recovers on success", async () => {
    render(<AppWorkspace client={client} />);
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
    expect(documentsTab().getAttribute("aria-selected")).toBe("true");
    expect(chatTab().getAttribute("aria-selected")).toBe("false");

    fireEvent.click(chatTab());
    await waitFor(() => {
      expect(chatTab().getAttribute("aria-selected")).toBe("true");
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
      expect(chatTab().getAttribute("aria-selected")).toBe("true");
    });
    fireEvent.click(documentsTab());
    await waitFor(() => {
      expect(documentsTab().getAttribute("aria-selected")).toBe("true");
    });
    const editorNodeAfter = screen.getByRole("textbox", {
      name: "Document content",
    });
    expect(editorNodeAfter).toBe(editorNode);
  });

  it("shows None for the workspace by default when the registry is empty", async () => {
    render(<AppWorkspace client={client} />);
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

    await waitFor(() => {
      expect(screen.getByRole("option", { name: "Workspace A" })).toBeTruthy();
    });
    fireEvent.change(workspaceSelect(), { target: { value: "workspace-a" } });
    expect(workspaceSelect().value).toBe("workspace-a");

    fireEvent.change(
      screen.getByLabelText("Select execution profile"),
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

    await waitFor(() => {
      expect(screen.getByRole("option", { name: "Workspace A" })).toBeTruthy();
    });
    fireEvent.change(workspaceSelect(), { target: { value: "workspace-a" } });

    fireEvent.change(screen.getByLabelText("Select runtime"), {
      target: { value: "native" },
    });
    expect(workspaceSelect().value).toBe("workspace-a");

    fireEvent.change(screen.getByLabelText("Select model"), {
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

    await waitFor(() => {
      expect(screen.getByRole("option", { name: "Workspace A" })).toBeTruthy();
    });
    fireEvent.change(workspaceSelect(), { target: { value: "workspace-a" } });

    fireEvent.change(
      screen.getByLabelText("Select execution profile"),
      { target: { value: "auto" } },
    );

    expect(workspaceSelect().value).toBe("workspace-a");
  });

  it("keeps the composer usable and swallows the workspace selector when discovery fails", async () => {
    vi.mocked(getWorkspaces).mockRejectedValueOnce(new Error("boom"));
    render(<AppWorkspace client={client} />);

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

    await waitFor(() => {
      expect(screen.getByRole("option", { name: "Workspace A" })).toBeTruthy();
    });
    fireEvent.change(workspaceSelect(), { target: { value: "workspace-a" } });
    expect(workspaceSelect().value).toBe("workspace-a");

    first.unmount();
    render(<AppWorkspace client={client} />);

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

    expect(screen.getByRole("tab", { name: "Chat" })).toBeTruthy();
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
