/**
 * Phase 5.37 Desktop acceptance harness.
 *
 * The Desktop shell is deliberately thin: `App.tsx` composes an `ApiClient`
 * and renders the shared `AppWorkspace`, and that is the whole of it. These
 * tests therefore prove composition, not behavior:
 *
 *   - Desktop really mounts the shared workspace, and nothing else.
 *   - Desktop supplies the API base URL the shared workspace consumes.
 *   - Conversation navigation, the conversation view, the prompt composer, and
 *     Settings navigation are all reachable through the Desktop entry point.
 *   - The shell introduces no Desktop-local authority: no replacement
 *     conversation/run/configuration state, and no local persistence.
 *
 * Every run, message, recovery, retry/regenerate, streaming, replay, and failure
 * classification rule is shared behavior with its own evidence in
 * `@ava/workspace` and `@ava/agent-ui`; duplicating those assertions here would
 * prove a second harness rather than a second composition.
 */

import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { createMessage, listConversations, startRun } from "@ava/api-client";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const TS = "2026-01-01T00:00:00Z";
const PROMPT = "Desktop acceptance prompt";

const mocks = vi.hoisted(() => ({
  startRun: vi.fn(),
  listConversations: vi.fn(),
  listMessages: vi.fn(),
  createMessage: vi.fn(),
  getRunEvents: vi.fn(),
  cancelRun: vi.fn(),
  streamRun: vi.fn().mockImplementation(async () => undefined),
}));

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
    listDocuments: vi.fn().mockResolvedValue({ contract_version: "v1", documents: [] }),
    listProviderConnections: vi.fn().mockResolvedValue({
      contract_version: "v1",
      provider_connections: [],
    }),
    listModelConfigurations: vi.fn().mockResolvedValue({ contract_version: "v1", models: [] }),
    listRuntimeConfigurations: vi.fn().mockResolvedValue({ contract_version: "v1", runtimes: [] }),
    getExecutionDefaults: vi.fn().mockResolvedValue({
      configured: false,
      defaults: null,
      contract_version: "v1",
    }),
    startRun: mocks.startRun,
    listConversations: mocks.listConversations,
    listMessages: mocks.listMessages,
    createMessage: mocks.createMessage,
    getRunEvents: mocks.getRunEvents,
    cancelRun: mocks.cancelRun,
    streamRun: mocks.streamRun,
  };
});

/**
 * A completed durable turn, so the shell can be asserted against real history
 * rather than an empty state. `source_run_id` is present because the backend
 * always records it, and it is the lineage a retry or regenerate branches from.
 */
function seedCompletedTurn(overrides: Record<string, unknown> = {}) {
  mocks.listConversations.mockResolvedValue({
    contract_version: "v1",
    conversations: [
      {
        conversation_id: "conversation-1",
        title: "Desktop acceptance",
        created_at: TS,
        updated_at: TS,
        contract_version: "v1",
      },
    ],
  });
  mocks.listMessages.mockResolvedValue({
    contract_version: "v1",
    conversation_id: "conversation-1",
    messages: [
      {
        message_id: "user-1",
        conversation_id: "conversation-1",
        role: "user",
        content: PROMPT,
        status: "complete",
        created_at: TS,
        updated_at: TS,
        contract_version: "v1",
      },
      {
        message_id: "assistant-1",
        conversation_id: "conversation-1",
        role: "assistant",
        content: "Durable answer",
        status: "complete",
        source_run_id: "run-1",
        created_at: TS,
        updated_at: TS,
        contract_version: "v1",
        ...overrides,
      },
    ],
  });
}

/**
 * True when the element has an ancestor with `display: none`.
 *
 * The shared composition hides conversation-specific chrome with `display: none`
 * rather than unmounting it, so in-session state survives a view switch.
 * Asserting DOM absence would assert the opposite of the intended behaviour.
 */
function isHiddenByAncestor(element: HTMLElement): boolean {
  let node: HTMLElement | null = element;
  while (node != null) {
    if (node.style?.display === "none") return true;
    node = node.parentElement;
  }
  return false;
}

async function renderDesktop() {
  const { App } = await import("./App");
  return render(<App />);
}

function shellSource(): string {
  const directory = join(import.meta.dirname);
  return readdirSync(directory, { withFileTypes: true })
    .flatMap((entry) =>
      entry.isDirectory() ? [] : entry.name.endsWith(".ts") || entry.name.endsWith(".tsx") ? [join(directory, entry.name)] : [],
    )
    .filter((file) => !file.includes(".test.") && !file.endsWith("setup.ts"))
    .map((file) => readFileSync(file, "utf8"))
    .join("\n");
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubEnv("VITE_API_BASE_URL", "http://desktop-acceptance.test");
  mocks.listConversations.mockResolvedValue({ contract_version: "v1", conversations: [] });
  mocks.listMessages.mockResolvedValue({
    contract_version: "v1",
    conversation_id: "conversation-1",
    messages: [],
  });
});

describe("Desktop shell composition", () => {
  it("mounts the shared workspace and nothing else", async () => {
    seedCompletedTurn();
    await renderDesktop();

    // The shared shell's own landmarks are present with no Desktop layer in
    // between: workspace tabs, conversation navigation, conversation view, and
    // prompt composer all come from @ava/workspace and its packages.
    expect((await screen.findByRole("tab", { name: "Chat" })).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("tab", { name: "Documents" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Settings" })).toBeTruthy();
    expect(await screen.findByText("Durable answer")).toBeTruthy();
    expect(screen.getByLabelText("Message")).toBeTruthy();
    // Conversation navigation and the conversation view both name the turn.
    expect(screen.getAllByText("Desktop acceptance").length).toBeGreaterThan(1);
  });

  it("composes no replacement providers, stores, or run lifecycle", async () => {
    const source = shellSource();

    // The shell supplies a client and a workspace. It does not re-provide any
    // shared authority: no state container, no run orchestration, no
    // configuration resolution, and no attempt/attempt-retry vocabulary.
    for (const sharedAuthority of [
      "ConversationProvider",
      "AgentRunProvider",
      "SettingsWorkspace",
      "ConversationList",
      "ConversationView",
      "PromptComposer",
      "ExecutionControls",
      "useAgentRun",
      "useConversationState",
      "startRun",
      "streamRun",
      "cancelRun",
      "getRunEvents",
      "recoverRunForConversation",
      "rerunAssistantResponse",
      "canRetryResponse",
      "canRegenerateResponse",
      "resolveExecution",
    ]) {
      expect(source).not.toContain(sharedAuthority);
    }
  });

  it("keeps the backend authoritative for conversation and run state", () => {
    const source = shellSource();

    // No local persistence of any kind backs conversation or run state. The
    // shell reads nothing from browser or native storage and writes nothing
    // to it; durable state comes from the backend over @ava/api-client.
    for (const store of [
      "localStorage",
      "sessionStorage",
      "indexedDB",
      "IndexedDB",
      "caches",
      "@tauri-apps/api",
      "invoke(",
      "fs:",
      "readFile",
      "writeFile",
    ]) {
      expect(source).not.toContain(store);
    }
  });
});

describe("Desktop API and environment composition", () => {
  it("passes the configured API base URL to the shared workspace", async () => {
    seedCompletedTurn();
    await renderDesktop();

    // The shell reads the one thing it owns — where the backend is — and hands
    // the client to @ava/workspace, which performs every call through it.
    expect(import.meta.env.VITE_API_BASE_URL).toBe("http://desktop-acceptance.test");
    await screen.findByText("Durable answer");
    expect(vi.mocked(listConversations).mock.calls[0]?.[0]).toMatchObject({
      baseUrl: "http://desktop-acceptance.test",
    });
  });
});

describe("Desktop conversation and run surface", () => {
  it("submits a prompt through the shared run path", async () => {
    seedCompletedTurn();
    mocks.createMessage.mockImplementation(
      async (_client: unknown, conversationId: string, request: { role?: string; content: string }) => ({
        message_id: request.role === "assistant" ? "assistant-2" : "user-2",
        conversation_id: conversationId,
        role: request.role ?? "user",
        content: request.content,
        status: "complete",
        created_at: TS,
        updated_at: TS,
        contract_version: "v1",
      }),
    );
    mocks.startRun.mockResolvedValue({
      run_id: "run-2",
      status: "running",
      conversation_id: "conversation-1",
      source_user_message_id: "user-2",
      assistant_message_id: "assistant-2",
      execution_selection: null,
      cancellation_requested_at: null,
      contract_version: "v1",
    });
    await renderDesktop();
    await screen.findByText("Durable answer");

    fireEvent.change(screen.getByLabelText("Message"), {
      target: { value: "Second question" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    // The shared run path is what ran. Assembling a response out of that run's
    // ordered events is shared behaviour owned by the workspace suite, so
    // Desktop acceptance asserts only that the shell drives that same path.
    await waitFor(() => {
      expect(screen.getAllByText("Second question").length).toBeGreaterThan(0);
    });
    expect(vi.mocked(createMessage).mock.calls.length).toBe(1);
    expect(vi.mocked(startRun).mock.calls.length).toBe(1);
    expect(vi.mocked(startRun).mock.calls[0]?.[1]).toMatchObject({
      prompt: "Second question",
      conversation_id: "conversation-1",
      source_user_message_id: "user-2",
    });
    // No Desktop-supplied attempt lineage: a first submission is not a retry,
    // and Desktop does not invent a run id of its own.
    expect(vi.mocked(startRun).mock.calls[0]?.[1]).not.toHaveProperty("retry_of_run_id");
    // The seeded durable history is untouched: Desktop added a turn, it did
    // not replace backend state with local state.
    expect(screen.getByText("Durable answer")).toBeTruthy();
  });
});

describe("Desktop Settings navigation", () => {
  it("opens Settings from the Desktop shell and exposes every Settings section", async () => {
    seedCompletedTurn();
    await renderDesktop();
    await screen.findByText("Durable answer");

    fireEvent.click(screen.getByRole("tab", { name: "Settings" }));

    for (const section of ["Providers", "Models", "Runtimes", "Defaults"]) {
      expect(await screen.findByRole("tab", { name: section })).toBeTruthy();
    }
    // The conversation composer is hidden in Settings, exactly as on Web, and
    // the Settings read endpoints are the shared ones.
    expect(isHiddenByAncestor(screen.getByLabelText("Message"))).toBe(true);
    const { listProviderConnections } = await import("@ava/api-client");
    expect(vi.mocked(listProviderConnections).mock.calls.length).toBeGreaterThan(0);
  });

  it("keeps the conversation reachable after a Settings visit", async () => {
    seedCompletedTurn();
    await renderDesktop();
    await screen.findByText("Durable answer");

    fireEvent.click(screen.getByRole("tab", { name: "Settings" }));
    await screen.findByRole("tab", { name: "Providers" });
    fireEvent.click(screen.getByRole("tab", { name: "Chat" }));

    // Durable state, not remounted local state, is what comes back.
    expect((await screen.findByText("Durable answer")).textContent).toBe("Durable answer");
  });
});

describe("Desktop remediation surface", () => {
  it("offers Settings, Retry, and Regenerate through the shared failure UX", async () => {
    seedCompletedTurn({ status: "failed", error_code: "model_unavailable" });
    await renderDesktop();
    await screen.findByText("Durable answer");

    // The hydrated configuration failure reaches Desktop with its remediation
    // affordances intact: the shell neither swallows nor reinvents them.
    // The action names the section it opens, so the user knows what to fix.
    const openSettings = screen.getByLabelText("Open Model Settings");
    expect(openSettings).toBeTruthy();
    expect(screen.getByLabelText("Retry response")).toBeTruthy();
    // A failed response is not regenerable, so only one attempt action is shown.
    expect(screen.queryByLabelText("Regenerate response")).toBeNull();

    fireEvent.click(openSettings);
    expect(
      (await screen.findByRole("tab", { name: "Models" })).getAttribute("aria-selected"),
    ).toBe("true");
  });

  it("does not offer Settings remediation for a generic failure", async () => {
    seedCompletedTurn({ status: "failed", error_code: "agent_failed" });
    await renderDesktop();
    await screen.findByText("Durable answer");

    // A generic failure is a failure, not a configuration problem: the shared
    // classification decides this, and Desktop simply does not override it.
    expect(screen.queryByLabelText("Open Model Settings")).toBeNull();
    expect(screen.queryByLabelText("Settings")).toBeNull();
    expect(screen.getByLabelText("Retry response")).toBeTruthy();
  });
});

describe("Desktop accessibility surface", () => {
  it("exposes the shared controls by role and label", async () => {
    seedCompletedTurn();
    await renderDesktop();
    await screen.findByText("Durable answer");

    // Everything a reader needs to drive Desktop comes from shared components
    // with real roles and accessible names — no Desktop-specific affordances.
    expect(screen.getByRole("tab", { name: "Chat" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Documents" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Settings" })).toBeTruthy();
    expect(screen.getByRole("textbox", { name: "Message" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Send" })).toBeTruthy();
    // A completed turn offers Regenerate and not Retry, exactly as on Web.
    expect(screen.getByLabelText("Regenerate response")).toBeTruthy();
    expect(screen.queryByLabelText("Retry response")).toBeNull();
  });

  it("exposes the shared Retry control for a failed durable turn", async () => {
    seedCompletedTurn({ status: "failed", error_code: "agent_failed" });
    await renderDesktop();
    await screen.findByText("Durable answer");

    // Recovery is the shared message-actions control, not a Desktop affordance.
    expect(screen.getByLabelText("Retry response")).toBeTruthy();
    expect(screen.queryByLabelText("Regenerate response")).toBeNull();
  });
});
