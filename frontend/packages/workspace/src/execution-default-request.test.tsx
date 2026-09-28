// @vitest-environment jsdom
import { ApiClient } from "@ava/api-client";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AppWorkspace } from "./AppWorkspace";

// Real workspace, providers, and API client. Only the HTTP boundary is replaced.
function transport() {
  const runs: Record<string, unknown>[] = [];
  const conversation = {
    conversation_id: "conversation", title: "Chat", created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z", contract_version: "v1",
  };
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
    else if (path === "/execution-profiles") body = {
      default_profile_id: "local-default", profiles: [
        { id: "local-default", name: "Local Coding", runtime_id: "native", model_provider_id: "local" },
        { id: "openhands-local", name: "OpenHands Local", runtime_id: "openhands", model_provider_id: "local" },
      ],
    };
    else if (path === "/workspaces") body = { workspaces: [] };
    else if (path === "/conversations") body = method === "POST" ? conversation : { conversations: [] };
    else if (path === "/conversations/conversation/messages") {
      body = method === "POST" ? {
        ...JSON.parse(String(init?.body)), message_id: "message", conversation_id: "conversation", status: "complete",
        created_at: conversation.created_at, updated_at: conversation.updated_at, contract_version: "v1",
      } : { conversation_id: "conversation", messages: [] };
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

async function setup() {
  const fixture = transport();
  render(<AppWorkspace client={fixture.client} />);
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
});
