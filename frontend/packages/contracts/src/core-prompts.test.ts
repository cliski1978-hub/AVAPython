import { describe, expect, it } from "vitest";
import type {
  CorePrompt,
  CorePromptCategory,
  CorePromptListResponse,
  CreateCorePromptRequest,
  SetCorePromptEnabledRequest,
  UpdateCorePromptRequest,
  CorePromptAssignmentState,
  CorePromptScopeType,
  EffectivePromptSet,
  ResolveCorePromptsRequest,
} from "./core-prompts";

describe("CORE prompt contracts", () => {
  it("keeps scope and three-state assignment vocabularies exact", () => {
    const scopes: CorePromptScopeType[] = ["global", "application", "project", "folder", "conversation", "runtime", "capability", "model_compatibility"];
    const states: CorePromptAssignmentState[] = ["inherit", "enable", "disable"];
    expect(scopes).toHaveLength(8);
    expect(states).toEqual(["inherit", "enable", "disable"]);
  });
  it("matches the backend category vocabulary", () => {
    const categories: CorePromptCategory[] = [
      "core",
      "engineering",
      "research",
      "safety",
      "style",
      "tool_use",
      "architecture",
      "organization",
      "general",
    ];
    expect(categories).toEqual([
      "core",
      "engineering",
      "research",
      "safety",
      "style",
      "tool_use",
      "architecture",
      "organization",
      "general",
    ]);
  });

  it("models nullable description, enabled state, timestamps, and exact prompt content", () => {
    const prompt: CorePrompt = {
      id: "cp_1",
      name: "AVA Core",
      description: null,
      prompt_text: "# Rules\n\n- Keep  spacing\n- 日本語 → 🧭",
      category: "core",
      is_enabled: true,
      created_at: "2026-10-02T00:00:00Z",
      updated_at: "2026-10-02T00:00:00Z",
      contract_version: "v1",
    };
    const create: CreateCorePromptRequest = {
      name: "AVA Core",
      prompt_text: prompt.prompt_text,
      category: prompt.category,
    };
    const update: UpdateCorePromptRequest = {
      name: "AVA Core",
      description: null,
      prompt_text: prompt.prompt_text,
      category: prompt.category,
    };
    const list: CorePromptListResponse = { core_prompts: [prompt], contract_version: "v1" };
    const enabled: SetCorePromptEnabledRequest = { is_enabled: false };

    expect(prompt.prompt_text).toContain("日本語 → 🧭");
    expect(prompt.description).toBeNull();
    expect(prompt.is_enabled).toBe(true);
    expect(prompt.created_at).toContain("Z");
    expect(create.prompt_text).toBe(update.prompt_text);
    expect("description" in create).toBe(false);
    expect(update.description).toBeNull();
    expect(list.core_prompts).toEqual([prompt]);
    expect(enabled.is_enabled).toBe(false);
  });

  it("describes a derived resolution context and per-prompt provenance", () => {
    const request: ResolveCorePromptsRequest = {
      conversation_id: "c1", runtime_key: "native", capabilities: ["runs"],
    };
    const result: EffectivePromptSet = {
      context: {
        conversation_id: request.conversation_id ?? null,
        project_id: "p1",
        folder_id: "f1",
        runtime_key: request.runtime_key ?? null,
        capabilities: request.capabilities ?? [],
      },
      enabled_prompts: [],
      excluded_prompts: [{
        core_prompt_id: "cp1", name: "Rules", category: "core", prompt_text: "Text",
        effective_state: "disabled", definition_enabled: true, reason: "explicit_disable",
        winning_scope_type: "folder", winning_scope_id: "f1", winning_assignment_mode: "disable",
        winning_assignment_id: "a1",
      }],
      contract_version: "v1",
    };
    expect(request.conversation_id).toBe("c1");
    expect(result.excluded_prompts[0].winning_scope_type).toBe("folder");
  });
});
