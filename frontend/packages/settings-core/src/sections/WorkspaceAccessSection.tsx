import { createWorkspaceAccess, getWorkspaceAccess, updateWorkspaceAccess, type ApiClient } from "@ava/api-client";
import type { CreateWorkspaceAccessRequest, ToolCapability, UpdateWorkspaceAccessRequest, WorkspaceAccessItem, WorkspaceKind, WorkspaceAccessResponse } from "@ava/contracts";
import { useCallback, useEffect, useRef, useState } from "react";

import { settingsErrorMessage } from "../state/settingsErrorMessage";
import { SettingsError, SettingsLoading } from "../settings/SettingsSectionState";

const CAPABILITIES: { id: ToolCapability; label: string }[] = [
  { id: "file_read", label: "Read files" }, { id: "file_write", label: "Write files" },
  { id: "file_delete", label: "Delete files" }, { id: "command_execution", label: "Run controlled commands" },
  { id: "network_access", label: "Network access" },
];

export function WorkspaceAccessSection({ client }: { client: ApiClient }) {
  const [data, setData] = useState<WorkspaceAccessResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [generation, setGeneration] = useState(0);
  const current = useRef(0);
  const load = useCallback(() => getWorkspaceAccess(client), [client]);
  useEffect(() => {
    const request = ++current.current;
    setLoading(true); setError(null);
    void load().then((result) => {
      if (current.current === request) { setData(result); setLoading(false); }
    }).catch((cause: unknown) => {
      if (current.current === request) { setError(settingsErrorMessage(cause)); setLoading(false); }
    });
    return () => { current.current += 1; };
  }, [load, attempt, generation]);
  const refresh = () => setGeneration((value) => value + 1);
  if (loading && !data) return <SettingsLoading label="Loading Workspace Access…" />;
  if (!data) return <SettingsError message={error ?? "Workspace configuration is unavailable."} onRetry={() => setAttempt((value) => value + 1)} />;
  return <section aria-label="Workspace Access" className="min-w-0 w-full max-w-3xl space-y-4 text-foreground">
    <p className="text-sm text-muted-foreground">Execution Workspaces are administrator-configured roots. Conversation Projects and Folders remain separate. Registering a Workspace does not authorize a caller or grant tool capabilities.</p>
    {!data.can_manage && <p role="status" className="rounded-md border border-border bg-muted p-3 text-sm">Read-only: trusted Workspace administration is unavailable on this deployment. Root paths are hidden.</p>}
    {data.configuration_status === "invalid" && <p role="alert">Workspace configuration is invalid. Workspace resolution fails closed until it is repaired by a trusted administrator.</p>}
    {error && <p role="alert" className="text-destructive">{error}</p>}
    {data.can_manage && <CreateWorkspaceForm client={client} onSaved={refresh} />}
    {data.workspaces.length === 0 ? <p className="text-sm text-muted-foreground">No execution Workspaces are configured.</p> :
      <div className="space-y-3">{data.workspaces.map((item) => <WorkspaceCard key={item.workspace_id} item={item} canManage={data.can_manage} client={client} onSaved={refresh} />)}</div>}
    <button type="button" className="rounded-md border border-border px-3 py-2 text-sm" onClick={() => setAttempt((value) => value + 1)}>Reload Workspace settings</button>
  </section>;
}

function CreateWorkspaceForm({ client, onSaved }: { client: ApiClient; onSaved: () => void }) {
  const [id, setId] = useState(""); const [name, setName] = useState(""); const [root, setRoot] = useState("");
  const [kind, setKind] = useState<WorkspaceKind>("local"); const [caps, setCaps] = useState<ToolCapability[]>([]);
  const [reviewed, setReviewed] = useState(false); const [error, setError] = useState<string | null>(null); const [saving, setSaving] = useState(false);
  async function submit() {
    if (!reviewed || saving) return;
    setSaving(true); setError(null);
    const body: CreateWorkspaceAccessRequest = { workspace_id: id, name: name || null, kind, root_path: root, allowed_capabilities: caps };
    try { await createWorkspaceAccess(client, body); onSaved(); setId(""); setName(""); setRoot(""); setCaps([]); setReviewed(false); }
    catch (cause) { setError(settingsErrorMessage(cause, "Workspace could not be created.")); }
    finally { setSaving(false); }
  }
  return <details className="rounded-md border border-border bg-card p-4 text-card-foreground"><summary className="cursor-pointer font-medium">Create Workspace</summary>
    <div className="mt-4 grid gap-3">
      <label className="grid gap-1 text-sm">Stable Workspace ID<input className="rounded border border-input bg-background px-2 py-1" value={id} onChange={(event) => setId(event.target.value)} /></label>
      <label className="grid gap-1 text-sm">Name<input className="rounded border border-input bg-background px-2 py-1" value={name} onChange={(event) => setName(event.target.value)} /></label>
      <label className="grid gap-1 text-sm">Canonical absolute root path<input className="rounded border border-input bg-background px-2 py-1" value={root} onChange={(event) => setRoot(event.target.value)} autoComplete="off" /></label>
      <KindSelect value={kind} onChange={setKind} /><CapabilityChoices value={caps} onChange={setCaps} />
      <label className="text-sm text-muted-foreground"><input type="checkbox" checked={reviewed} onChange={(event) => setReviewed(event.target.checked)} /> I reviewed the selected host root and capability restrictions.</label>
      {error && <p role="alert">{error}</p>}<button type="button" disabled={!reviewed || saving || !id || !root} onClick={() => void submit()} className="w-fit rounded-md border border-border px-3 py-2 text-sm disabled:opacity-50">{saving ? "Creating…" : "Create Workspace"}</button>
    </div>
  </details>;
}

function WorkspaceCard({ item, canManage, client, onSaved }: { item: WorkspaceAccessItem; canManage: boolean; client: ApiClient; onSaved: () => void }) {
  const [name, setName] = useState(item.name ?? ""); const [root, setRoot] = useState(item.root_path ?? "");
  const [kind, setKind] = useState(item.kind); const [caps, setCaps] = useState(item.allowed_capabilities);
  const [status, setStatus] = useState(item.status); const [reviewed, setReviewed] = useState(false);
  const [error, setError] = useState<string | null>(null); const [saving, setSaving] = useState(false);
  useEffect(() => { setName(item.name ?? ""); setRoot(item.root_path ?? ""); setKind(item.kind); setCaps(item.allowed_capabilities); setStatus(item.status); setReviewed(false); }, [item]);
  async function submit() {
    if (!canManage || !reviewed || saving) return;
    setSaving(true); setError(null);
    const body: UpdateWorkspaceAccessRequest = { name: name || null, root_path: root, kind, allowed_capabilities: caps, status, expected_revision: item.revision };
    try { await updateWorkspaceAccess(client, item.workspace_id, body); onSaved(); }
    catch (cause) { setError(settingsErrorMessage(cause, "Workspace settings could not be saved.")); }
    finally { setSaving(false); }
  }
  return <article className="min-w-0 rounded-md border border-border bg-card p-4 text-card-foreground">
    <div className="flex flex-wrap items-start justify-between gap-2"><div><h3 className="break-all font-medium">{item.name || item.workspace_id}</h3><p className="break-all text-xs text-muted-foreground">{item.workspace_id}</p></div><span className="rounded bg-muted px-2 py-1 text-xs">{item.status}</span></div>
    <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-2"><div><dt className="text-muted-foreground">Kind</dt><dd>{item.kind}</dd></div><div><dt className="text-muted-foreground">Configuration revision</dt><dd>{item.revision}</dd></div><div className="min-w-0"><dt className="text-muted-foreground">Authorized root</dt><dd className="break-all">{item.root_path ?? "Hidden without trusted administrative access"}</dd></div><div><dt className="text-muted-foreground">Configured capability restrictions</dt><dd>{item.allowed_capabilities.length ? item.allowed_capabilities.join(", ") : "None"}</dd></div></dl>
    {canManage && <details className="mt-4 border-t border-border pt-3"><summary className="cursor-pointer text-sm font-medium">Edit Workspace settings</summary><div className="mt-3 grid gap-3">
      <label className="grid gap-1 text-sm">Name<input className="rounded border border-input bg-background px-2 py-1" value={name} onChange={(event) => setName(event.target.value)} /></label>
      <label className="grid gap-1 text-sm">Canonical absolute root path<input className="rounded border border-input bg-background px-2 py-1" value={root} onChange={(event) => setRoot(event.target.value)} autoComplete="off" /></label>
      <KindSelect value={kind} onChange={setKind} /><CapabilityChoices value={caps} onChange={setCaps} />
      {item.status === "active" && <label className="text-sm"><input type="checkbox" checked={status === "revoked"} onChange={(event) => setStatus(event.target.checked ? "revoked" : "active")} /> Revoke Workspace access</label>}
      <p className="text-sm text-muted-foreground">Changing the root or capabilities increments the configuration revision and invalidates existing Workspace authority. Revocation is permanent for this identity.</p>
      <label className="text-sm text-muted-foreground"><input type="checkbox" checked={reviewed} onChange={(event) => setReviewed(event.target.checked)} /> I reviewed the root and access changes.</label>
      {error && <p role="alert">{error}</p>}<button type="button" disabled={!reviewed || saving || item.status === "revoked"} onClick={() => void submit()} className="w-fit rounded-md border border-border px-3 py-2 text-sm disabled:opacity-50">{saving ? "Saving…" : "Save Workspace settings"}</button>
    </div></details>}
  </article>;
}

function KindSelect({ value, onChange }: { value: WorkspaceKind; onChange: (value: WorkspaceKind) => void }) {
  return <label className="grid gap-1 text-sm">Workspace kind<select className="rounded border border-input bg-background px-2 py-1" value={value} onChange={(event) => onChange(event.target.value as WorkspaceKind)}><option value="local">Local</option><option value="ephemeral">Ephemeral</option></select></label>;
}

function CapabilityChoices({ value, onChange }: { value: ToolCapability[]; onChange: (value: ToolCapability[]) => void }) {
  return <fieldset className="grid gap-2"><legend className="text-sm font-medium">Capability restrictions</legend>{CAPABILITIES.map((capability) => <label key={capability.id} className="text-sm"><input type="checkbox" checked={value.includes(capability.id)} onChange={(event) => onChange(event.target.checked ? [...value, capability.id] : value.filter((item) => item !== capability.id))} /> {capability.label}</label>)}</fieldset>;
}

