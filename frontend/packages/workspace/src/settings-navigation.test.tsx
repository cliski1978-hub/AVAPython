// @vitest-environment jsdom
import { ApiClient } from "@ava/api-client";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppWorkspace } from "./AppWorkspace";

/**
 * Settings as a first-class top-level view.
 *
 * The mocks cover the whole composition, including the Settings read endpoints
 * that `@ava/settings-core` calls through the same `@ava/api-client` module, so
 * these tests can assert that entering Settings issues the 5.10 calls.
 */

// Declared with vi.hoisted so the mock factory below (hoisted above ordinary
// module code by vitest) can reference them without a temporal-dead-zone error.
const mocks = vi.hoisted(() => ({
  listProviderConnections: vi.fn(),
  listModelConfigurations: vi.fn(),
  listRuntimeConfigurations: vi.fn(),
  listCorePrompts: vi.fn(),
  getExecutionDefaults: vi.fn(),
  listConversations: vi.fn(),
  listMessages: vi.fn(),
  createDocument: vi.fn(),
  getDocument: vi.fn(),
}));

const {
  createDocument,
  getDocument,
  listProviderConnections,
  listModelConfigurations,
  listRuntimeConfigurations,
  listCorePrompts,
  getExecutionDefaults,
  listConversations,
  listMessages,
} = mocks;

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
      profiles: [],
    }),
    getWorkspaces: vi.fn().mockResolvedValue({ contract_version: "v1", workspaces: [] }),
    listDocuments: vi.fn().mockResolvedValue({
      contract_version: "v1",
      documents: [
        {
          document_id: "document-1",
          title: "Untitled Document",
          content: "<p>Document</p>",
          content_format: "html",
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
          contract_version: "v1",
        },
      ],
    }),
    listConversations: mocks.listConversations,
    listMessages: mocks.listMessages,
    createDocument: mocks.createDocument,
    getDocument: mocks.getDocument,
    listProviderConnections: mocks.listProviderConnections,
    listModelConfigurations: mocks.listModelConfigurations,
    listRuntimeConfigurations: mocks.listRuntimeConfigurations,
    listCorePrompts: mocks.listCorePrompts,
    getExecutionDefaults: mocks.getExecutionDefaults,
  };
});

const client = new ApiClient({ baseUrl: "http://localhost:99999" });

/**
 * True when the element has an ancestor with `display: none`.
 *
 * The composition hides conversation-specific chrome with `display: none`
 * rather than unmounting it, so composer drafts and in-flight state survive a
 * view switch. Testing absence from the DOM would assert the opposite of the
 * intended behaviour.
 */
function isHiddenByAncestor(element: HTMLElement): boolean {
  let node: HTMLElement | null = element;
  while (node != null) {
    if (node.style?.display === "none") return true;
    node = node.parentElement;
  }
  return false;
}

function primaryLink(name: string): HTMLElement {
  return screen.getByRole("link", { name });
}

async function openSettings() {
  fireEvent.click(primaryLink("Settings"));
  await waitFor(() => expect(screen.getByTestId("settings-workspace")).toBeTruthy());
}

beforeEach(() => {
  vi.clearAllMocks();
  window.history.replaceState(null, "", "/");
  listConversations.mockResolvedValue({ contract_version: "v1", conversations: [] });
  listMessages.mockResolvedValue({
    contract_version: "v1",
    conversation_id: "conversation-1",
    messages: [],
  });
  listProviderConnections.mockResolvedValue({
    contract_version: "v1",
    provider_connections: [
      {
        provider_connection_id: "acme-primary",
        provider_id: "acme",
        display_name: "Acme Primary",
        endpoint: "https://api.acme.test",
        enabled: true,
        credential_reference: "env:ACME_API_KEY",
        contract_version: "v1",
      },
    ],
  });
  listModelConfigurations.mockResolvedValue({ contract_version: "v1", models: [] });
  listRuntimeConfigurations.mockResolvedValue({ contract_version: "v1", runtimes: [] });
  listCorePrompts.mockResolvedValue({ contract_version: "v1", core_prompts: [] });
  getExecutionDefaults.mockResolvedValue({
    configured: false,
    defaults: null,
    contract_version: "v1",
  });
  createDocument.mockResolvedValue(undefined);
  getDocument.mockImplementation(async (_client: unknown, documentId: string) => ({
    document_id: documentId,
    title: "Untitled Document",
    content: "<p>Document</p>",
    content_format: "html",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    contract_version: "v1",
  }));
});

describe("Settings navigation", () => {
  it("offers Settings alongside the existing top-level views", () => {
    render(<AppWorkspace client={client} />);

    expect(primaryLink("Chat")).toBeTruthy();
    expect(primaryLink("Documents")).toBeTruthy();
    expect(primaryLink("Settings")).toBeTruthy();
    expect(primaryLink("Settings").getAttribute("aria-current")).toBeNull();
    expect(primaryLink("Chat").getAttribute("aria-current")).toBe("page");
  });

  it("does not mount or fetch the Settings surface before it is opened", () => {
    render(<AppWorkspace client={client} />);

    expect(screen.queryByTestId("settings-workspace")).toBeNull();
    expect(listProviderConnections).not.toHaveBeenCalled();
  });

  it("opens the Settings workspace from the main navigation", async () => {
    render(<AppWorkspace client={client} />);
    await openSettings();

    expect(primaryLink("Settings").getAttribute("aria-current")).toBe("page");
    expect(screen.getByRole("heading", { name: "Settings" })).toBeTruthy();
    await waitFor(() => expect(listProviderConnections).toHaveBeenCalled());
  });

  it("loads the read-only Settings sections from the settings endpoints", async () => {
    render(<AppWorkspace client={client} />);
    await openSettings();

    await screen.findByText("Acme Primary");

    fireEvent.click(screen.getByRole("tab", { name: "Models" }));
    await waitFor(() => expect(listModelConfigurations).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("tab", { name: "Runtimes" }));
    await waitFor(() => expect(listRuntimeConfigurations).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("tab", { name: "Defaults" }));
    await waitFor(() => expect(getExecutionDefaults).toHaveBeenCalled());
  });

  it("keeps CORE prompts current when prior Settings sections resolve late", async () => {
    let resolveModels!: (value: { contract_version: "v1"; models: Array<{ model_id: string; name: string }> }) => void;
    let resolveRuntimes!: (value: { contract_version: "v1"; runtimes: unknown[] }) => void;
    let resolveProviders!: (value: { contract_version: "v1"; provider_connections: Array<{ provider_connection_id: string; display_name: string; endpoint: string; enabled: boolean; credential_reference: string; provider_id: string }> }) => void;
    const models = new Promise<{ contract_version: "v1"; models: Array<{ model_id: string; name: string }> }>((resolve) => { resolveModels = resolve; });
    const runtimes = new Promise<{ contract_version: "v1"; runtimes: unknown[] }>((resolve) => { resolveRuntimes = resolve; });
    const providers = new Promise<{ contract_version: "v1"; provider_connections: Array<{ provider_connection_id: string; display_name: string; endpoint: string; enabled: boolean; credential_reference: string; provider_id: string }> }>((resolve) => { resolveProviders = resolve; });
    listModelConfigurations.mockReturnValueOnce(models);
    listRuntimeConfigurations.mockReturnValueOnce(runtimes);
    listProviderConnections.mockReturnValueOnce(providers);
    render(<AppWorkspace client={client} />);
    await openSettings();

    fireEvent.click(screen.getByRole("tab", { name: "Models" }));
    fireEvent.click(screen.getByRole("tab", { name: "Runtimes" }));
    fireEvent.click(screen.getByRole("tab", { name: "Providers" }));
    fireEvent.click(screen.getByRole("tab", { name: "System Prompts" }));
    expect(await screen.findByText("Manage reusable CORE prompt definitions and inspect explicit assignments.")).toBeTruthy();

    resolveModels({ contract_version: "v1", models: [{ model_id: "late-model", name: "Late Models Response" }] });
    resolveRuntimes({ contract_version: "v1", runtimes: [{ runtime_id: "late-runtime", name: "Late Runtimes Response" }] });
    resolveProviders({ contract_version: "v1", provider_connections: [{ provider_connection_id: "late-provider", provider_id: "late", display_name: "Late Providers Response", endpoint: "https://late.test", enabled: true, credential_reference: "env:LATE" }] });
    await waitFor(() => expect(screen.getByRole("tab", { name: "System Prompts" }).getAttribute("aria-selected")).toBe("true"));
    expect(screen.getByText("Manage reusable CORE prompt definitions and inspect explicit assignments.").textContent).not.toContain("Late");
    expect(screen.queryByText("Late Models Response")).toBeNull();
    expect(screen.queryByText("Late Runtimes Response")).toBeNull();
    expect(screen.queryByText("Late Providers Response")).toBeNull();
  });

  it("returns to the chat workspace and keeps it usable", async () => {
    render(<AppWorkspace client={client} />);
    await openSettings();

    fireEvent.click(primaryLink("Chat"));

    expect(primaryLink("Chat").getAttribute("aria-current")).toBe("page");
    await waitFor(() => expect(screen.getByLabelText("Message")).toBeTruthy());
    expect(screen.getByText("No conversation selected.")).toBeTruthy();
  });

  it("keeps the document workspace reachable from Settings", async () => {
    render(<AppWorkspace client={client} />);
    await openSettings();

    fireEvent.click(primaryLink("Documents"));

    expect(primaryLink("Documents").getAttribute("aria-current")).toBe("page");
    await waitFor(() =>
      expect(screen.getByRole("textbox", { name: "Document content" })).toBeTruthy(),
    );
  });

  it("hides the conversation sidebar in Settings and restores it in chat", async () => {
    render(<AppWorkspace client={client} />);

    expect(screen.getByText("Conversations")).toBeTruthy();

    await openSettings();
    // The sidebar is conversation-specific chrome; a Settings view must not
    // show an unrelated conversation list.
    expect(screen.queryByText("Conversations")).toBeNull();

    fireEvent.click(primaryLink("Chat"));
    expect(screen.getByText("Conversations")).toBeTruthy();
  });

  it("keeps the conversation sidebar out of the Settings view", async () => {
    render(<AppWorkspace client={client} />);
    await openSettings();

    // The sidebar is not merely empty, it is not rendered at all, so no
    // conversation-specific chrome appears next to Settings content.
    expect(screen.queryByText("Conversations")).toBeNull();
    expect(screen.queryByRole("button", { name: "New conversation" })).toBeNull();
  });

  it("hides the prompt composer in Settings", async () => {
    render(<AppWorkspace client={client} />);
    await openSettings();

    // The composer stays mounted so its draft survives, but is not visible.
    const composer = screen.getByLabelText("Message");
    expect(isHiddenByAncestor(composer)).toBe(true);

    fireEvent.click(primaryLink("Chat"));
    expect(isHiddenByAncestor(screen.getByLabelText("Message"))).toBe(false);
  });

  it("preserves conversation state across a visit to Settings", async () => {
    let conversationId = 0;
    listConversations.mockResolvedValue({
      contract_version: "v1",
      conversations: [
        {
          conversation_id: "conversation-1",
          title: "First conversation",
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
          contract_version: "v1",
        },
      ],
    });
    listMessages.mockImplementation(async (_client: unknown, id: string) => ({
      contract_version: "v1" as const,
      conversation_id: id,
      messages: [],
    }));
    conversationId += 1;
    expect(conversationId).toBe(1);

    render(<AppWorkspace client={client} />);

    await waitFor(() =>
      expect(screen.getAllByText("First conversation").length).toBeGreaterThan(0),
    );
    fireEvent.click(screen.getAllByText("First conversation")[0]);
    await waitFor(() =>
      // Once active, the title also appears in the view header.
      expect(screen.getAllByText("First conversation").length).toBeGreaterThan(1),
    );

    await openSettings();
    fireEvent.click(primaryLink("Chat"));

    // The conversation is still listed and still active after returning.
    await waitFor(() =>
      expect(screen.getAllByText("First conversation").length).toBeGreaterThan(1),
    );
    expect(screen.getByLabelText("Message")).toBeTruthy();
  });
});
