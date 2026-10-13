import { getToolFeatures, updateToolFeatures, type ApiClient } from "@ava/api-client";
import type { ToolFeaturesResponse, UpdateToolFeaturesRequest } from "@ava/contracts";
import { shadcn } from "@ava/ui-core";
import { useEffect, useRef, useState } from "react";

import { settingsErrorMessage } from "../state/settingsErrorMessage";
import { SettingsError, SettingsLoading } from "../settings/SettingsSectionState";
import { ToolManagementPanel } from "./ToolManagementPanel";

const { Button, Switch, Dialog, DialogContent, DialogTitle, DialogDescription } = shadcn;

export function ToolFeaturesSection({ client }: { client: ApiClient }) {
  const [response, setResponse] = useState<ToolFeaturesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const generation = useRef(0);
  const inFlight = useRef(false);

  useEffect(() => {
    const query = ++generation.current;
    inFlight.current = false;
    setLoading(true); setSaving(false); setResponse(null); setError(null); setSaved(false);
    void getToolFeatures(client).then((data) => {
      if (query === generation.current) { setResponse(data); setLoading(false); }
    }).catch((cause: unknown) => {
      if (query === generation.current) { setError(settingsErrorMessage(cause)); setLoading(false); }
    });
    return () => { generation.current += 1; };
  }, [client, attempt]);

  async function save(body: UpdateToolFeaturesRequest) {
    if (inFlight.current || !response?.can_manage) return;
    inFlight.current = true;
    const query = ++generation.current;
    setSaving(true); setError(null); setSaved(false);
    try {
      const data = await updateToolFeatures(client, body);
      if (query === generation.current) { setResponse(data); setSaved(true); }
    } catch (cause) {
      if (query === generation.current) setError(settingsErrorMessage(cause, "Feature settings could not be saved."));
    } finally {
      if (query === generation.current) { inFlight.current = false; setSaving(false); }
    }
  }

  if (loading) return <SettingsLoading label="Loading Features & Tools…" />;
  if (!response) return <SettingsError message={error ?? "Feature settings are unavailable."} onRetry={() => setAttempt((n) => n + 1)} />;
  return <section className="min-w-0 w-full max-w-3xl space-y-4 text-foreground" aria-label="Features & Tools">
    <p className="text-sm text-muted-foreground">Feature gates control availability. Enabling a feature does not grant Workspace access, tool execution permission, or human approval.</p>
    {!response.can_manage && <p role="status" className="rounded-md border border-border bg-muted p-3 text-sm">Read-only: authenticated feature administration is unavailable on this deployment.</p>}
    {response.configuration_status === "invalid" && <p role="alert">Configuration is invalid. All normalized tool feature gates are disabled.</p>}
    {error && <p role="alert" className="text-destructive">{error}</p>}
    {saved && <p role="status">Feature settings saved.</p>}
    <FeatureEditor key={response.configuration.configuration_version} response={response} saving={saving} onSave={save} />
    <Button variant="outline" disabled={saving} onClick={() => setAttempt((n) => n + 1)}>Reload feature settings</Button>
  </section>;
}

function FeatureEditor({ response, saving, onSave }: {
  response: ToolFeaturesResponse; saving: boolean; onSave: (request: UpdateToolFeaturesRequest) => Promise<void>;
}) {
  const [framework, setFramework] = useState(response.configuration.framework_enabled);
  const [enabled, setEnabled] = useState(response.configuration.enabled_tool_ids);
  const [confirmation, setConfirmation] = useState<{ label: string; apply: () => void } | null>(null);
  const disabled = saving || !response.can_manage;
  const dirty = framework !== response.configuration.framework_enabled ||
    [...enabled].sort().join("\n") !== [...response.configuration.enabled_tool_ids].sort().join("\n");
  return <>
    <div className="rounded-md border border-border bg-card p-4 text-card-foreground">
      <label className="flex items-center justify-between gap-3" htmlFor="tool-framework">Tool framework
        <Switch id="tool-framework" checked={framework} disabled={disabled} onCheckedChange={(value) => {
          if (value) setConfirmation({ label: "Enable tool framework", apply: () => setFramework(true) });
          else setFramework(false);
        }} />
      </label>
      <p className="mt-2 text-sm text-muted-foreground">Saved framework gate: {response.configuration.framework_enabled ? "Enabled" : "Disabled"}. Changes take effect after saving.</p>
      <p className="text-sm text-muted-foreground">Effective framework gate: {response.framework_effective_enabled ? "Enabled" : "Disabled"}.</p>
    </div>
    {framework && enabled.length === 0 && <p role="status">The framework is enabled in this configuration, but no tools are enabled.</p>}
    <ToolManagementPanel tools={response.tools} enabledIds={enabled} controlsDisabled={disabled || !framework} onToggle={(toolId, value) => {
      const definition = response.tools.find((tool) => tool.definition.tool_id === toolId)?.definition;
      if (!definition) return;
      const setTool = (value: boolean) => setEnabled((ids) => value ? [...ids, definition.tool_id] : ids.filter((id) => id !== definition.tool_id));
      if (value && definition.risk !== "low") setConfirmation({ label: `Enable ${definition.name}`, apply: () => setTool(true) });
      else setTool(value);
    }} />
    <Button disabled={disabled || !dirty} onClick={() => void onSave({
      framework_enabled: framework, enabled_tool_ids: enabled, expected_version: response.configuration.configuration_version,
    })}>{saving ? "Saving…" : "Save feature settings"}</Button>
    <Dialog open={confirmation !== null} onOpenChange={(open) => { if (!open) setConfirmation(null); }}>
      <DialogContent><DialogTitle>{confirmation?.label}?</DialogTitle>
        <DialogDescription>This changes feature configuration only. Workspace authorization, execution policy, and required approvals remain mandatory.</DialogDescription>
        <div className="flex gap-2"><Button variant="outline" onClick={() => setConfirmation(null)}>Cancel</Button>
          <Button onClick={() => { confirmation?.apply(); setConfirmation(null); }}>Confirm enable</Button></div>
      </DialogContent>
    </Dialog>
  </>;
}
