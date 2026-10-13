import type { ToolDefinition } from "./tools";

export interface ToolFeatureConfiguration {
  framework_enabled: boolean;
  enabled_tool_ids: string[];
  configuration_version: number;
  contract_version: "v1";
}
export interface UpdateToolFeaturesRequest {
  framework_enabled: boolean;
  enabled_tool_ids: string[];
  expected_version: number;
  contract_version?: "v1";
}
export interface ToolFeaturesResponse {
  configuration: ToolFeatureConfiguration;
  configuration_status: "missing" | "valid" | "invalid";
  framework_effective_enabled: boolean;
  can_manage: boolean;
  tools: {
    definition: ToolDefinition;
    configured_enabled: boolean;
    effective_enabled: boolean;
    reason: "configuration_invalid" | "framework_disabled" | "tool_disabled" | "feature_enabled";
  }[];
  contract_version: "v1";
}
