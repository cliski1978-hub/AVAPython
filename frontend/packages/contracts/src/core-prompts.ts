import type { ContractVersion } from "./version";
import type { CapabilityName } from "./capabilities";

export type CorePromptScopeType =
  | "global" | "application" | "project" | "folder" | "conversation"
  | "runtime" | "capability" | "model_compatibility";
export type CorePromptAssignmentMode = "enable" | "disable";
export type CorePromptAssignmentState = CorePromptAssignmentMode | "inherit";

export interface CorePromptAssignment {
  core_prompt_id: string;
  scope_type: CorePromptScopeType;
  scope_id: string | null;
  state: CorePromptAssignmentState;
  assignment_id: string | null;
  created_at: string | null;
  updated_at: string | null;
  contract_version: ContractVersion;
}

export interface CorePromptAssignmentListResponse {
  assignments: CorePromptAssignment[];
  contract_version: ContractVersion;
}

export interface SetCorePromptAssignmentRequest {
  scope_type: CorePromptScopeType;
  scope_id?: string | null;
  state: CorePromptAssignmentState;
  contract_version?: ContractVersion;
}

/** Organizational topic for a reusable CORE prompt; it does not describe scope. */
export type CorePromptCategory =
  | "core"
  | "engineering"
  | "research"
  | "safety"
  | "style"
  | "tool_use"
  | "architecture"
  | "organization"
  | "general";

/** Reusable AVA-owned prompt definition, inert until future execution integration. */
export interface CorePrompt {
  id: string;
  name: string;
  description: string | null;
  prompt_text: string;
  category: CorePromptCategory;
  is_enabled: boolean;
  created_at: string;
  updated_at: string;
  contract_version: ContractVersion;
}

export interface CreateCorePromptRequest {
  name: string;
  description?: string | null;
  prompt_text: string;
  category: CorePromptCategory;
  contract_version?: ContractVersion;
}

export interface CorePromptListResponse {
  core_prompts: CorePrompt[];
  contract_version: ContractVersion;
}

export interface SetCorePromptEnabledRequest {
  is_enabled: boolean;
  contract_version?: ContractVersion;
}

export interface UpdateCorePromptRequest {
  name: string;
  description?: string | null;
  prompt_text: string;
  category: CorePromptCategory;
  contract_version?: ContractVersion;
}

export interface ResolveCorePromptsRequest {
  conversation_id?: string | null;
  runtime_key?: string | null;
  capabilities?: CapabilityName[];
  contract_version?: ContractVersion;
}

export interface PromptResolutionContext {
  conversation_id: string | null;
  project_id: string | null;
  folder_id: string | null;
  runtime_key: string | null;
  capabilities: string[];
}

export interface ResolvedCorePrompt {
  core_prompt_id: string;
  name: string;
  category: CorePromptCategory;
  prompt_text: string;
  effective_state: "enabled" | "disabled";
  definition_enabled: boolean;
  reason: "definition_disabled" | "no_matching_assignment" | "explicit_disable" | "explicit_enable";
  winning_scope_type: CorePromptScopeType | null;
  winning_scope_id: string | null;
  winning_assignment_mode: CorePromptAssignmentMode | null;
  winning_assignment_id: string | null;
}

export interface EffectivePromptSet {
  context: PromptResolutionContext;
  enabled_prompts: ResolvedCorePrompt[];
  excluded_prompts: ResolvedCorePrompt[];
  contract_version: ContractVersion;
}
