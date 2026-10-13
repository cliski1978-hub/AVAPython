import type { JsonValue, ToolFeaturesResponse } from "@ava/contracts";
import { shadcn } from "@ava/ui-core";
import { useState } from "react";

const { Input, Switch } = shadcn;
const reasons = {
  configuration_invalid: "Configuration is invalid; administrator repair is required.",
  framework_disabled: "Tool framework is disabled.",
  tool_disabled: "Tool is disabled.",
  feature_enabled: "Feature gate enabled; execution authorization is still required.",
};
const selectClass = "h-9 min-w-0 w-full rounded-md border border-input bg-background px-2 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

function schemaSummary(schema: Record<string, JsonValue>): string {
  const properties = schema.properties;
  const count = properties !== null && typeof properties === "object" && !Array.isArray(properties)
    ? Object.keys(properties).length : 0;
  const required = Array.isArray(schema.required) ? schema.required.length : 0;
  return `${count} declared fields · ${required} required fields`;
}

function schemaFields(schema: Record<string, JsonValue>): string {
  const properties = schema.properties;
  if (properties === null || typeof properties !== "object" || Array.isArray(properties)) return "No declared fields.";
  const fields = Object.entries(properties);
  if (!fields.length) return "No declared fields.";
  const summary = fields.slice(0, 6).map(([name, value]) => {
    const type = value !== null && typeof value === "object" && !Array.isArray(value) && typeof value.type === "string" ? value.type : "schema";
    return `${name.slice(0, 64)}: ${type}`;
  }).join(", ");
  return fields.length > 6 ? `${summary} · ${fields.length - 6} more fields` : summary;
}

/** Descriptive view and draft controls over the existing feature controller. */
export function ToolManagementPanel({ tools, enabledIds, controlsDisabled, onToggle }: {
  tools: ToolFeaturesResponse["tools"];
  enabledIds: string[];
  controlsDisabled: boolean;
  onToggle: (toolId: string, enabled: boolean) => void;
}) {
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("all");
  const [configured, setConfigured] = useState("all");
  const [risk, setRisk] = useState("all");
  const query = search.trim().toLowerCase();
  const visible = tools.filter((tool) => {
    const definition = tool.definition;
    return (!query || `${definition.name} ${definition.tool_id}`.toLowerCase().includes(query)) &&
      (category === "all" || definition.execution_category === category) &&
      (risk === "all" || definition.risk === risk) &&
      (configured === "all" || tool.configured_enabled === (configured === "enabled"));
  });

  return <section aria-label="Tool Management" className="min-w-0 space-y-3">
    <h2 className="text-lg font-semibold">Tool Management</h2>
    <p className="text-sm text-muted-foreground">Registered definitions describe requirements. Availability is a feature gate, not execution permission or a guarantee of runtime support.</p>
    <div className="grid min-w-0 grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
      <label className="min-w-0 text-sm">Search tools
        <Input aria-label="Search tools" placeholder="Name or tool ID" value={search} onChange={(event) => setSearch(event.currentTarget.value)} />
      </label>
      <label className="min-w-0 text-sm">Category
        <select aria-label="Tool category" className={selectClass} value={category} onChange={(event) => setCategory(event.currentTarget.value)}>
          <option value="all">All categories</option>
          <option value="deterministic">Deterministic</option><option value="agentic">Agentic</option><option value="hybrid">Hybrid</option>
        </select>
      </label>
      <label className="min-w-0 text-sm">Saved configuration
        <select aria-label="Tool configured state" className={selectClass} value={configured} onChange={(event) => setConfigured(event.currentTarget.value)}>
          <option value="all">All states</option><option value="enabled">Enabled</option><option value="disabled">Disabled</option>
        </select>
      </label>
      <label className="min-w-0 text-sm">Risk
        <select aria-label="Tool risk" className={selectClass} value={risk} onChange={(event) => setRisk(event.currentTarget.value)}>
          <option value="all">All risks</option><option value="low">Low</option><option value="medium">Medium</option>
          <option value="high">High</option><option value="critical">Critical</option>
        </select>
      </label>
    </div>
    <p role="status" className="text-xs text-muted-foreground">{visible.length} of {tools.length} registered tools. Filters use saved configuration; unsaved changes remain drafts.</p>
    {tools.length === 0 ? <p>No normalized tools are registered yet.</p> : visible.length === 0 ? <p>No tools match these filters.</p> : null}
    {visible.map((tool) => {
      const definition = tool.definition;
      const draftEnabled = enabledIds.includes(definition.tool_id);
      return <article aria-label={definition.name} key={definition.tool_id} className="min-w-0 rounded-md border border-border bg-card p-3 text-card-foreground">
        <div className="flex min-w-0 items-start justify-between gap-3">
          <div className="min-w-0"><h3 className="break-words font-medium">{definition.name}</h3><p className="break-all font-mono text-xs text-muted-foreground">{definition.tool_id}</p></div>
          <Switch aria-label={`Enable ${definition.name}`} checked={draftEnabled} disabled={controlsDisabled} onCheckedChange={(value) => onToggle(definition.tool_id, value)} />
        </div>
        <p className="break-words text-sm">{definition.description}</p>
        <p className="text-xs text-muted-foreground">Category: {definition.execution_category} · Risk: {definition.risk} · Approval requirement: {definition.approval_requirement}</p>
        <p className="break-words text-xs text-muted-foreground">Declared capabilities: {definition.required_capabilities.length ? definition.required_capabilities.join(", ") : "None declared"}</p>
        <p className="text-sm">Saved: {tool.configured_enabled ? "Enabled" : "Disabled"}{draftEnabled !== tool.configured_enabled ? ` · Unsaved: ${draftEnabled ? "Enabled" : "Disabled"}` : ""}</p>
        <p className="text-sm">Effective feature availability: {tool.effective_enabled ? "Enabled" : "Unavailable"}. {reasons[tool.reason]}</p>
        <details className="mt-2 rounded-md border border-border p-2">
          <summary className="cursor-pointer text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">Details for {definition.name}</summary>
          <dl className="mt-2 space-y-1 break-words text-sm">
            <dt className="font-medium">Identity and version</dt><dd className="break-all">{definition.tool_id} · Definition {definition.tool_version} · Contract {definition.contract_version}</dd>
            <dt className="font-medium">Input schema</dt><dd>{schemaSummary(definition.input_schema)}</dd>
            <dd className="text-xs text-muted-foreground">{schemaFields(definition.input_schema)}</dd>
            <dt className="font-medium">Output schema</dt><dd>{schemaSummary(definition.output_schema)}</dd>
            <dd className="text-xs text-muted-foreground">{schemaFields(definition.output_schema)}</dd>
            <dt className="font-medium">Required authorization</dt><dd>Backend execution policy, authorized Workspace/resource scope, and applicable human approval are required separately. No authorization or runtime compatibility result is reported by this inventory.</dd>
            <dt className="font-medium">Approval metadata</dt><dd>{definition.approval_requirement === "required" ? "Approval required; a feature switch cannot satisfy it." : "Determined by backend approval policy; no approval bypass is implied."}</dd>
          </dl>
        </details>
      </article>;
    })}
  </section>;
}
