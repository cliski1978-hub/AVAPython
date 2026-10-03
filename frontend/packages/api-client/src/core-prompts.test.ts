import { describe, expect, it, vi } from "vitest";
import {
  ApiClient,
  ApiError,
  createCorePrompt,
  deleteCorePrompt,
  getCorePrompt,
  listCorePrompts,
  listCorePromptAssignments,
  listCorePromptAssignmentsForScope,
  setCorePromptAssignment,
  setCorePromptEnabled,
  updateCorePrompt,
  resolveCorePrompts,
} from "./index";

const prompt = {
  id: "cp/1",
  name: "Engineering",
  description: null,
  prompt_text: "# Preserve\n\n- indentation\n- 日本語 → 🧭",
  category: "engineering" as const,
  is_enabled: true,
  created_at: "2026-10-02T00:00:00Z",
  updated_at: "2026-10-02T00:00:00Z",
  contract_version: "v1" as const,
};

describe("CORE prompt API client", () => {
  it("supports explicit assignment lists, scoped lists, and inherit removal", async () => {
    const assignment = {
      core_prompt_id: "cp/1", scope_type: "global", scope_id: null, state: "enable",
      assignment_id: "as_1", created_at: "2026-10-02T00:00:00Z", updated_at: "2026-10-02T00:00:00Z",
      contract_version: "v1",
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ assignments: [assignment], contract_version: "v1" })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ assignments: [assignment], contract_version: "v1" })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ...assignment, state: "inherit", assignment_id: null, created_at: null, updated_at: null })));
    const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
    await expect(listCorePromptAssignments(client, "cp/1")).resolves.toMatchObject({ assignments: [assignment] });
    await expect(listCorePromptAssignmentsForScope(client, "project", "p/1")).resolves.toMatchObject({ assignments: [assignment] });
    await expect(setCorePromptAssignment(client, "cp/1", { scope_type: "global", scope_id: null, state: "inherit" }))
      .resolves.toMatchObject({ state: "inherit", assignment_id: null });
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "http://localhost:8000/core-prompts/cp%2F1/assignments",
      "http://localhost:8000/core-prompt-assignments?scope_type=project&scope_id=p%2F1",
      "http://localhost:8000/core-prompts/cp%2F1/assignments",
    ]);
    expect(fetchMock.mock.calls[2][1]).toMatchObject({ method: "PUT" });
  });
  it("uses all six typed operations and preserves request serialization", async () => {
    const disabled = { ...prompt, is_enabled: false, updated_at: "2026-10-02T00:01:00Z" };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ core_prompts: [prompt], contract_version: "v1" })))
      .mockResolvedValueOnce(new Response(JSON.stringify(prompt)))
      .mockResolvedValueOnce(new Response(JSON.stringify(prompt), { status: 201 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(prompt)))
      .mockResolvedValueOnce(new Response(JSON.stringify(prompt)))
      .mockResolvedValueOnce(new Response(JSON.stringify(disabled)))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
    const text = "  # Exact\n\n- Keep  spaces\n- 日本語 → 🧭\n";

    await expect(listCorePrompts(client)).resolves.toEqual({ core_prompts: [prompt], contract_version: "v1" });
    await expect(getCorePrompt(client, "cp/1")).resolves.toEqual(prompt);
    await expect(createCorePrompt(client, { name: "Engineering", prompt_text: text, category: "engineering" }))
      .resolves.toEqual(prompt);
    await expect(updateCorePrompt(client, "cp/1", { name: "Engineering", prompt_text: text, category: "engineering" }))
      .resolves.toEqual(prompt);
    await expect(updateCorePrompt(client, "cp/1", {
      name: "Engineering", description: null, prompt_text: text, category: "engineering",
    })).resolves.toEqual(prompt);
    await expect(setCorePromptEnabled(client, "cp/1", { is_enabled: false })).resolves.toEqual(disabled);
    await expect(deleteCorePrompt(client, "cp/1")).resolves.toBeUndefined();

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "http://localhost:8000/core-prompts",
      "http://localhost:8000/core-prompts/cp%2F1",
      "http://localhost:8000/core-prompts",
      "http://localhost:8000/core-prompts/cp%2F1",
      "http://localhost:8000/core-prompts/cp%2F1",
      "http://localhost:8000/core-prompts/cp%2F1/enabled",
      "http://localhost:8000/core-prompts/cp%2F1",
    ]);
    expect(fetchMock.mock.calls.map(([, init]) => init?.method ?? "GET")).toEqual([
      "GET", "GET", "POST", "PATCH", "PATCH", "PATCH", "DELETE",
    ]);
    expect(JSON.parse(fetchMock.mock.calls[2][1]?.body as string)).toEqual({
      name: "Engineering", prompt_text: text, category: "engineering",
    });
    expect(JSON.parse(fetchMock.mock.calls[3][1]?.body as string)).toEqual({
      name: "Engineering", prompt_text: text, category: "engineering",
    });
    expect(JSON.parse(fetchMock.mock.calls[4][1]?.body as string)).toEqual({
      name: "Engineering", description: null, prompt_text: text, category: "engineering",
    });
    expect(JSON.parse(fetchMock.mock.calls[5][1]?.body as string)).toEqual({ is_enabled: false });
    expect(fetchMock.mock.calls[6][1]?.body).toBeUndefined();
  });

  it("propagates not-found API errors", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(
      new Response(JSON.stringify({ error_code: "core_prompt_not_found" }), { status: 404 }),
    );
    const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
    await expect(getCorePrompt(client, "missing")).rejects.toMatchObject({
      name: "ApiError",
      status: 404,
      body: { error_code: "core_prompt_not_found" },
    } satisfies Partial<ApiError>);
  });

  it("posts a typed resolution preview context and returns structured provenance", async () => {
    const resolved = {
      context: { conversation_id: "c1", project_id: "p1", folder_id: "f1", runtime_key: "native", capabilities: ["runs"] },
      enabled_prompts: [],
      excluded_prompts: [{
        core_prompt_id: "cp/1", name: "Engineering", category: "engineering", prompt_text: "Text",
        effective_state: "disabled", definition_enabled: true, reason: "explicit_disable", winning_scope_type: "folder",
        winning_scope_id: "f1", winning_assignment_mode: "disable", winning_assignment_id: "as_1",
      }],
      contract_version: "v1",
    };
    const fetchMock = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(resolved)));
    const client = new ApiClient({ baseUrl: "http://localhost:8000", fetchImpl: fetchMock });
    await expect(resolveCorePrompts(client, {
      conversation_id: "c1", runtime_key: "native", capabilities: ["runs"],
    })).resolves.toEqual(resolved);
    expect(fetchMock.mock.calls[0][0]).toBe("http://localhost:8000/core-prompts/resolve");
    expect(fetchMock.mock.calls[0][1]).toMatchObject({
      method: "POST",
      body: JSON.stringify({ conversation_id: "c1", runtime_key: "native", capabilities: ["runs"] }),
    });
  });
});
