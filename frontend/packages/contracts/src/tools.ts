import type { JsonValue } from "./json_types";

/** Descriptive registry metadata, never authorization or execution support. */
export interface ToolDefinition {
  tool_id: string;
  name: string;
  description: string;
  tool_version: string;
  input_schema: Record<string, JsonValue>;
  output_schema: Record<string, JsonValue>;
  required_capabilities: ("file_read" | "file_write" | "file_delete" | "command_execution" | "network_access")[];
  risk: "low" | "medium" | "high" | "critical";
  approval_requirement: "policy" | "required";
  execution_category: "deterministic" | "agentic" | "hybrid";
  contract_version: "v1";
}
