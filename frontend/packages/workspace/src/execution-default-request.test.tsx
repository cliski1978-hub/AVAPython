// @vitest-environment jsdom
import { ApiClient } from "@ava/api-client";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AppWorkspace } from "./AppWorkspace";

// Real workspace, providers, and API client. Only the HTTP boundary is replaced.
function transport(options: { models?: unknown[]; defaultModelId?: string | null; projectDefaultModelId?: string | null; failModels?: boolean } = {}) {
  const runs: Record<string, unknown>[] = [];
  const conversation = {
    conversation_id: "conversation", title: "Chat", created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z", contract_version: "v1",
  };
  const projectConversation = { ...conversation, conversation_id: "project-conversation", project_id: "project" };
  const fetchImpl: typeof fetch = async (input, init) => {
    const path = new URL(String(input)).pathname;
    const method = init?.method ?? "GET";
    let body: unknown;
    if (path === "/health") body = { status: "healthy", application: "AVA", contract_version: "v1" };
    else if (path === "/runtimes") body = {
      default_runtime_id: "native", runtimes: [
        { runtime_info: { runtime_id: "native", display_name: "Native" } },
        { runtime_info: { runtime_id: "openhands", display_name: "OpenHands" } },
      ],
    };
    else if (path === "/model-providers") body = {
      default_provider_id: "local", providers: [{ provider_id: "local", model_info: { model_id: "legacy-model" } }],
    };
    // The composer lists configured models, so discovery is part of what the
    // workspace needs before it can render a choice.
    else if (path === "/models") {
      if (options.failModels) throw new Error("model catalog unavailable");
      body = {
        default_model_id: options.defaultModelId ?? null,
        models: options.models ?? [],
        contract_version: "v1",
      };
    }
    else if (path === "/execution-profiles") body = {
      default_profile_id: "local-default", profiles: [
        { id: "local-default", name: "Local Coding", runtime_id: "native", model_provider_id: "local" },
        { id: "openhands-local", name: "OpenHands Local", runtime_id: "openhands", model_provider_id: "local" },
      ],
    };
    else if (path === "/workspaces") body = { workspaces: [] };
    else if (path === "/projects") body = { projects: [{ id: "project", name: "Project A", is_archived: false }] };
    else if (path === "/projects/project/execution-defaults") body = {
      project_id: "project", runtime_key: null, model_id: options.projectDefaultModelId ?? null, contract_version: "v1",
    };
    else if (path === "/projects/project/conversations") body = method === "POST"
      ? projectConversation
      : { conversations: [projectConversation] };
    else if (path === "/conversations") body = method === "POST" ? conversation : { conversations: [] };
    else if (path === "/conversations/conversation/messages" || path === "/conversations/project-conversation/messages") {
      const activeConversation = path.includes("project-conversation") ? projectConversation : conversation;
      body = method === "POST" ? {
        ...JSON.parse(String(init?.body)), message_id: "message", conversation_id: activeConversation.conversation_id, status: "complete",
        created_at: activeConversation.created_at, updated_at: activeConversation.updated_at, contract_version: "v1",
      } : { conversation_id: activeConversation.conversation_id, messages: [] };
    } else if (path === "/runs" && method === "POST") {
      runs.push(JSON.parse(String(init?.body)));
      body = { run_id: "run", status: "completed", contract_version: "v1" };
    } else if (path === "/runs/run/events") body = [];
    else throw new Error(`Unexpected request: ${method} ${path}`);
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  };
  return { runs, client: new ApiClient({ baseUrl: "http://ava.test", fetchImpl }) };
}

async function submit(runs: Record<string, unknown>[]) {
  fireEvent.change(screen.getByLabelText("Message"), { target: { value: "Use my execution settings" } });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
  await waitFor(() => expect(runs).toHaveLength(1));
  return runs[0];
}

async function setup(options: { models?: unknown[]; defaultModelId?: string | null; projectDefaultModelId?: string | null; failModels?: boolean } = {}) {
  const fixture = transport(options);
  render(<AppWorkspace client={fixture.client} />);
  fireEvent.click(screen.getByRole("button", { name: /Execution settings/ }));
  await screen.findByRole("option", { name: "Local Coding" });
  return fixture;
}

describe("application defaults and explicit execution request bodies", () => {
  it("omits execution after bootstrap discovery populated its options", async () => {
    const { runs } = await setup();
    expect((screen.getByLabelText("Select execution profile") as HTMLSelectElement).value).toBe("application-default");
    expect(await submit(runs)).not.toHaveProperty("execution");
  });

  it.each([
    ["Select runtime", "openhands", { runtime_id: "openhands" }],
    ["Select model", "local", { model_provider_id: "local" }],
    ["Select execution profile", "local-default", { runtime_id: "native", model_provider_id: "local" }],
    ["Select execution profile", "openhands-local", { runtime_id: "openhands", model_provider_id: "local" }],
    ["Select execution profile", "auto", { mode: "auto" }],
  ])("preserves the explicit choice from %s (%s)", async (label, value, expected) => {
    const { runs } = await setup();
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
    expect((await submit(runs)).execution).toEqual(expected);
  });

  it("can return from a profile to Application default", async () => {
    const { runs } = await setup();
    const select = screen.getByLabelText("Select execution profile");
    fireEvent.change(select, { target: { value: "openhands-local" } });
    fireEvent.change(select, { target: { value: "application-default" } });
    expect((screen.getByLabelText("Select runtime") as HTMLSelectElement).value).toBe("");
    expect((screen.getByLabelText("Select model") as HTMLSelectElement).value).toBe("");
    expect(await submit(runs)).not.toHaveProperty("execution");
  });

  it("sends only the chosen axis when the model stays on Legacy default", async () => {
    // The composer's Model control is a provider selector whose empty option is
    // labelled "Legacy default" once a choice is in play. Leaving it there must
    // omit the model entirely rather than send an empty or "default" id, so the
    // backend can tell "explicit runtime, model on application default" apart
    // from "explicitly chose a model".
    const { runs } = await setup();
    fireEvent.change(screen.getByLabelText("Select runtime"), { target: { value: "openhands" } });
    expect((screen.getByLabelText("Select execution profile") as HTMLSelectElement).value).toBe("custom");
    expect((screen.getByLabelText("Select model") as HTMLSelectElement).value).toBe("");
    const body = await submit(runs) as { execution: Record<string, unknown> };
    expect(body.execution).toEqual({ runtime_id: "openhands" });
    expect(Object.keys(body.execution)).not.toContain("model_provider_id");
    expect(Object.keys(body.execution)).not.toContain("model_id");
  });

  it("sends only the chosen axis when the runtime stays on Legacy default", async () => {
    const { runs } = await setup();
    fireEvent.change(screen.getByLabelText("Select model"), { target: { value: "local" } });
    expect((screen.getByLabelText("Select execution profile") as HTMLSelectElement).value).toBe("custom");
    expect((screen.getByLabelText("Select runtime") as HTMLSelectElement).value).toBe("");
    const body = await submit(runs) as { execution: Record<string, unknown> };
    expect(body.execution).toEqual({ model_provider_id: "local" });
  });

  it("does not send an empty-string or default id for an unchosen axis", async () => {
    const { runs } = await setup();
    fireEvent.change(screen.getByLabelText("Select runtime"), { target: { value: "openhands" } });
    const body = await submit(runs) as { execution: Record<string, unknown> };
    for (const value of Object.values(body.execution)) {
      expect(typeof value).toBe("string");
      expect(value).not.toBe("");
      expect(value).not.toBe("default");
    }
  });
});

// A catalog shaped like the live one: several models behind a single provider,
// one of them disabled, plus the bootstrap profile the backend always reports.
const CONFIGURED_CATALOG = [
  { model_id: "qwen25-coder-7b", display_name: "Qwen 2.5 Coder 7B", provider_id: "local", enabled: true },
  { model_id: "qwen35-9b", display_name: "Qwen 3.5 9B", provider_id: "local", enabled: true },
  { model_id: "disabled-model", display_name: "Disabled Test Model", provider_id: "local", enabled: false },
  { model_id: "legacy-model", display_name: "Legacy Bootstrap", provider_id: "local", enabled: true },
];

describe("configured models in the composer", () => {
  it("shows the active Project's inherited model without sending it as an explicit override", async () => {
    const { runs } = await setup({ models: CONFIGURED_CATALOG, defaultModelId: "qwen25-coder-7b", projectDefaultModelId: "qwen35-9b" });
    fireEvent.click(screen.getByRole("button", { name: "New Chat in Project A" }));
    const modelOption = await screen.findByRole("option", { name: "Project default (Qwen 3.5 9B)" });
    expect(modelOption).toBeTruthy();
    const request = await submit(runs) as { conversation_id: string; execution?: unknown };
    expect(request.conversation_id).toBe("project-conversation");
    expect(request).not.toHaveProperty("execution");
  });

  it("lists every configured model by its stable id, not by a provider identity", async () => {
    await setup({ models: CONFIGURED_CATALOG, defaultModelId: "qwen25-coder-7b" });
    const options = (screen.getByLabelText("Select model") as HTMLSelectElement).options;
    expect([...options].map(o => o.value)).toEqual([
      "", "qwen25-coder-7b", "qwen35-9b", "disabled-model", "legacy-model",
    ]);
  });

  it("labels each option with the display name a user configured", async () => {
    await setup({ models: CONFIGURED_CATALOG, defaultModelId: "qwen25-coder-7b" });
    expect(await screen.findByRole("option", { name: "Qwen 2.5 Coder 7B" })).toBeTruthy();
    expect(screen.getByRole("option", { name: "Qwen 3.5 9B" })).toBeTruthy();
  });

  it("keeps two models on one provider as separate choices", async () => {
    const { runs } = await setup({ models: CONFIGURED_CATALOG, defaultModelId: "qwen25-coder-7b" });
    fireEvent.change(screen.getByLabelText("Select model"), { target: { value: "qwen35-9b" } });
    expect((await submit(runs)).execution).toEqual({ model_id: "qwen35-9b" });
  });

  it("addresses a chosen model by model_id rather than model_provider_id", async () => {
    const { runs } = await setup({ models: CONFIGURED_CATALOG, defaultModelId: "qwen25-coder-7b" });
    fireEvent.change(screen.getByLabelText("Select model"), { target: { value: "qwen25-coder-7b" } });
    const body = await submit(runs) as { execution: Record<string, unknown> };
    expect(body.execution).toEqual({ model_id: "qwen25-coder-7b" });
    expect(Object.keys(body.execution)).not.toContain("model_provider_id");
  });

  it("offers a disabled model so selecting it fails explicitly instead of vanishing", async () => {
    await setup({ models: CONFIGURED_CATALOG, defaultModelId: "qwen25-coder-7b" });
    expect(screen.getByRole("option", { name: "Disabled Test Model (disabled)" })).toBeTruthy();
  });

  it("shows an invalid enabled model, leaving the failure to the run", async () => {
    const { runs } = await setup({
      models: [{ model_id: "Bad-model", display_name: "bb1", provider_id: "local", enabled: true }],
      defaultModelId: "qwen25-coder-7b",
    });
    fireEvent.change(screen.getByLabelText("Select model"), { target: { value: "Bad-model" } });
    expect((await submit(runs)).execution).toEqual({ model_id: "Bad-model" });
  });

  it("names the model the application default resolves to", async () => {
    await setup({ models: CONFIGURED_CATALOG, defaultModelId: "qwen25-coder-7b" });
    expect(await screen.findByRole("option", { name: "Application default (Qwen 2.5 Coder 7B)" })).toBeTruthy();
  });

  it("falls back to a plain Application default label when no default is configured", async () => {
    await setup({ models: CONFIGURED_CATALOG, defaultModelId: null });
    const modelOptions = (await screen.findByLabelText("Select model") as HTMLSelectElement).options;
    expect([...modelOptions].map(o => o.text)).toContain("Application default");
  });

  it("still omits the execution field entirely on Application default", async () => {
    const { runs } = await setup({ models: CONFIGURED_CATALOG, defaultModelId: "qwen25-coder-7b" });
    expect(await submit(runs)).not.toHaveProperty("execution");
  });

  it("keeps a profile's provider visible even though the catalog lists models", async () => {
    const { runs } = await setup({ models: CONFIGURED_CATALOG, defaultModelId: "qwen25-coder-7b" });
    fireEvent.change(screen.getByLabelText("Select execution profile"), { target: { value: "openhands-local" } });
    expect(await screen.findByRole("option", { name: "Provider local (from profile)" })).toBeTruthy();
    expect((await submit(runs)).execution).toEqual({ runtime_id: "openhands", model_provider_id: "local" });
  });

  it("combines an explicit runtime with an explicit configured model", async () => {
    const { runs } = await setup({ models: CONFIGURED_CATALOG, defaultModelId: "qwen25-coder-7b" });
    fireEvent.change(screen.getByLabelText("Select runtime"), { target: { value: "openhands" } });
    fireEvent.change(screen.getByLabelText("Select model"), { target: { value: "qwen35-9b" } });
    expect((await submit(runs)).execution).toEqual({ runtime_id: "openhands", model_id: "qwen35-9b" });
  });

  it("drops a selected model that the catalog no longer contains", async () => {
    const { runs } = await setup({ models: CONFIGURED_CATALOG, defaultModelId: "qwen25-coder-7b" });
    fireEvent.change(screen.getByLabelText("Select model"), { target: { value: "qwen35-9b" } });
    fireEvent.change(screen.getByLabelText("Select runtime"), { target: { value: "openhands" } });
    expect((await submit(runs)).execution).toEqual({ runtime_id: "openhands", model_id: "qwen35-9b" });
  });
});

describe("model catalog isolation", () => {
  // A /models failure must not take the rest of discovery with it, or the whole
  // composer goes silent instead of degrading to the legacy provider list.
  it("keeps runtimes and profiles selectable when /models is unavailable", async () => {
    const { runs } = await setup({ models: CONFIGURED_CATALOG, failModels: true });
    expect((screen.getByLabelText("Select runtime") as HTMLSelectElement).options.length).toBeGreaterThan(1);
    expect((screen.getByLabelText("Select execution profile") as HTMLSelectElement).value).toBe("application-default");
    // Degraded to the pre-settings provider list rather than emptied.
    const modelSelect = screen.getByLabelText("Select model") as HTMLSelectElement;
    expect([...modelSelect.options].map(o => o.value)).toEqual(["", "local"]);
    fireEvent.change(screen.getByLabelText("Select model"), { target: { value: "local" } });
    expect((await submit(runs)).execution).toEqual({ model_provider_id: "local" });
  });
});
