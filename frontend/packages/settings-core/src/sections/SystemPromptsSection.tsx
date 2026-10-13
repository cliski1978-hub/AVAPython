import {
  createCorePrompt,
  deleteCorePrompt,
  getCapabilities,
  getRuntimes,
  listCorePromptAssignments,
  listCorePrompts,
  setCorePromptEnabled,
  updateCorePrompt,
  type ApiClient,
} from "@ava/api-client";
import type { CorePrompt, CorePromptCategory } from "@ava/contracts";
import { Button, Input, Select, Textarea, defaultTheme } from "@ava/ui-core";
import { useEffect, useMemo, useState } from "react";

import { CorePromptScopeAssignments, type AssignablePromptScope } from "../prompts/CorePromptScopeAssignments";
import { SettingsModal } from "../modal/SettingsModal";
import { SettingsEmpty, SettingsError, SettingsLoading } from "../settings/SettingsSectionState";

const t = defaultTheme;
const categories: { value: CorePromptCategory; label: string }[] = [
  { value: "core", label: "Core" }, { value: "engineering", label: "Engineering" },
  { value: "research", label: "Research" }, { value: "safety", label: "Safety" },
  { value: "style", label: "Style" }, { value: "tool_use", label: "Tool Use" },
  { value: "architecture", label: "Architecture" }, { value: "organization", label: "Organization" },
  { value: "general", label: "General" },
];
const scopeOptions: { value: AssignablePromptScope; label: string }[] = [
  { value: "global", label: "Global" }, { value: "runtime", label: "Runtime" }, { value: "capability", label: "Capability" },
];

type PromptDraft = { name: string; description: string; category: CorePromptCategory; promptText: string };
const emptyDraft: PromptDraft = { name: "", description: "", category: "general", promptText: "" };

function safeError(error: unknown, fallback: string) {
  if (typeof error === "object" && error !== null && "status" in error && typeof error.status === "number" && error.status >= 500) {
    return "AVA could not complete this request. Try again.";
  }
  return fallback;
}

export function SystemPromptsSection({ client }: { client: ApiClient }) {
  const [prompts, setPrompts] = useState<CorePrompt[]>([]);
  const [assignmentSummary, setAssignmentSummary] = useState<Record<string, Awaited<ReturnType<typeof listCorePromptAssignments>>["assignments"]>>({});
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [enabledFilter, setEnabledFilter] = useState("");
  const [draftTarget, setDraftTarget] = useState<CorePrompt | "new" | null>(null);
  const [draft, setDraft] = useState<PromptDraft>(emptyDraft);
  const [savePending, setSavePending] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<CorePrompt | null>(null);
  const [deletePending, setDeletePending] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [pendingPromptId, setPendingPromptId] = useState<string | null>(null);
  const [definitionError, setDefinitionError] = useState<string | null>(null);
  const [selectedScope, setSelectedScope] = useState<AssignablePromptScope>("global");
  const [targetId, setTargetId] = useState("");
  const [runtimeIds, setRuntimeIds] = useState<string[]>([]);
  const [capabilities, setCapabilities] = useState<string[]>([]);
  const [targetError, setTargetError] = useState<string | null>(null);

  async function reload() {
    setLoading(true);
    setLoadError(null);
    try {
      const response = await listCorePrompts(client);
      setPrompts(response.core_prompts);
      const assignments = await Promise.all(response.core_prompts.map(async (prompt) => [prompt.id, (await listCorePromptAssignments(client, prompt.id)).assignments] as const));
      setAssignmentSummary(Object.fromEntries(assignments));
    } catch {
      setLoadError("System Prompts could not be loaded. Try again.");
    } finally {
      setLoading(false);
    }
  }

  async function refreshAssignmentSummary() {
    try {
      const assignments = await Promise.all(prompts.map(async (prompt) => [prompt.id, (await listCorePromptAssignments(client, prompt.id)).assignments] as const));
      setAssignmentSummary(Object.fromEntries(assignments));
    } catch {
      setTargetError("Assignments changed, but the summary could not be refreshed. Reload System Prompts to check current state.");
    }
  }

  useEffect(() => { void reload(); }, [client]);
  useEffect(() => {
    let cancelled = false;
    Promise.allSettled([getRuntimes(client), getCapabilities(client)]).then(([runtimeResult, capabilityResult]) => {
      if (cancelled) return;
      if (runtimeResult.status === "fulfilled") setRuntimeIds(runtimeResult.value.runtimes.map((item) => item.runtime_info.runtime_id));
      if (capabilityResult.status === "fulfilled") setCapabilities(Object.keys(capabilityResult.value.capabilities));
      if (runtimeResult.status === "rejected" || capabilityResult.status === "rejected") setTargetError("Some assignment targets are unavailable. Global prompt management remains available.");
    });
    return () => { cancelled = true; };
  }, [client]);

  const filtered = useMemo(() => prompts.filter((prompt) =>
    (search.trim() === "" || `${prompt.name} ${prompt.description ?? ""}`.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase())) &&
    (categoryFilter === "" || prompt.category === categoryFilter) &&
    (enabledFilter === "" || String(prompt.is_enabled) === enabledFilter),
  ), [prompts, search, categoryFilter, enabledFilter]);

  function openEditor(prompt: CorePrompt | "new") {
    setDraftTarget(prompt);
    setDraft(prompt === "new" ? emptyDraft : { name: prompt.name, description: prompt.description ?? "", category: prompt.category, promptText: prompt.prompt_text });
    setSaveError(null);
  }

  async function saveDefinition() {
    if (savePending || draft.name.trim() === "" || draft.promptText.trim() === "") {
      setSaveError("Enter a name and prompt text.");
      return;
    }
    setSavePending(true);
    setSaveError(null);
    try {
      if (draftTarget === "new") {
        await createCorePrompt(client, { name: draft.name, description: draft.description === "" ? null : draft.description, category: draft.category, prompt_text: draft.promptText });
      } else if (draftTarget != null) {
        await updateCorePrompt(client, draftTarget.id, { name: draft.name, description: draft.description === "" ? null : draft.description, category: draft.category, prompt_text: draft.promptText });
      }
      setDraftTarget(null);
      await reload();
    } catch (error) {
      setSaveError(safeError(error, "System Prompt could not be saved. Your text is still here."));
    } finally {
      setSavePending(false);
    }
  }

  async function toggleDefinition(prompt: CorePrompt) {
    if (pendingPromptId != null) return;
    setPendingPromptId(prompt.id);
    setDefinitionError(null);
    try {
      const updated = await setCorePromptEnabled(client, prompt.id, { is_enabled: !prompt.is_enabled });
      setPrompts((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (error) {
      setDefinitionError(safeError(error, `“${prompt.name}” definition status could not be changed.`));
    } finally {
      setPendingPromptId(null);
    }
  }

  async function deleteDefinition() {
    if (deleteTarget == null || deletePending) return;
    setDeletePending(true);
    setDeleteError(null);
    try {
      await deleteCorePrompt(client, deleteTarget.id);
      setPrompts((current) => current.filter((item) => item.id !== deleteTarget.id));
      setAssignmentSummary((current) => { const next = { ...current }; delete next[deleteTarget.id]; return next; });
      setDeleteTarget(null);
    } catch (error) {
      setDeleteError(safeError(error, "System Prompt could not be deleted. Try again."));
    } finally {
      setDeletePending(false);
    }
  }

  if (loading) return <SettingsLoading label="Loading System Prompts…" />;
  if (loadError != null) return <SettingsError message={loadError} onRetry={() => void reload()} retryLabel="Retry loading System Prompts" />;

  const targetOptions = selectedScope === "runtime" ? runtimeIds : capabilities;
  const selectedTargetName = targetOptions.includes(targetId) ? targetId : (targetOptions[0] ?? "");
  const targetLabel = selectedScope === "runtime" ? "Runtime" : "Capability";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: t.spacing.lg }}>
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: t.spacing.md }}>
        <div><h2 style={{ margin: 0 }}>System Prompts</h2><p style={{ margin: `${t.spacing.xs}px 0 0`, color: t.colors.mutedText }}>Manage reusable CORE prompt definitions and inspect explicit assignments.</p></div>
        <Button variant="primary" onClick={() => openEditor("new")}>New System Prompt</Button>
      </header>

      <section aria-label="Assignment management" style={{ display: "flex", flexDirection: "column", gap: t.spacing.md }}>
        <h3 style={{ margin: 0 }}>Assignments</h3>
        <p style={{ margin: 0, color: t.colors.mutedText }}>Only explicit state is shown. Inherit means no assignment row exists at this scope; this page does not calculate effective prompts.</p>
        <div style={{ display: "grid", gridTemplateColumns: "minmax(150px, 220px) minmax(180px, 260px)", gap: t.spacing.md }}>
          <Select label="Scope type" value={selectedScope} options={scopeOptions} onChange={(value) => { const next = value as AssignablePromptScope; setSelectedScope(next); setTargetId(""); }} />
          {selectedScope !== "global" && <Select label="Target" value={selectedTargetName} options={targetOptions.map((id) => ({ value: id, label: id }))} onChange={setTargetId} placeholder={targetOptions.length ? undefined : `${targetLabel} targets unavailable`} disabled={targetOptions.length === 0} />}
        </div>
        {targetError != null && <p role="status" style={{ margin: 0, color: t.colors.mutedText }}>{targetError}</p>}
        <CorePromptScopeAssignments client={client} scopeType={selectedScope} scopeId={selectedScope === "global" ? null : selectedTargetName || null} scopeLabel={selectedScope === "global" ? "Global" : `${targetLabel}: ${selectedTargetName || "Unavailable"}`} prompts={prompts} active={selectedScope === "global" || selectedTargetName !== ""} onAssignmentChanged={() => void refreshAssignmentSummary()} />
      </section>

      <section aria-label="Prompt profiles" style={{ display: "flex", flexDirection: "column", gap: t.spacing.md }}>
        <h3 style={{ margin: 0 }}>Prompt Profiles</h3>
        <div style={{ display: "grid", gridTemplateColumns: "minmax(180px, 1fr) minmax(150px, 220px) minmax(150px, 220px)", gap: t.spacing.md }}>
          <Input label="Search prompts" type="search" value={search} onChange={setSearch} />
          <Select label="Category" value={categoryFilter} options={[{ value: "", label: "All categories" }, ...categories]} onChange={setCategoryFilter} />
          <Select label="Definition status" value={enabledFilter} options={[{ value: "", label: "All statuses" }, { value: "true", label: "Enabled" }, { value: "false", label: "Disabled" }]} onChange={setEnabledFilter} />
        </div>
        {definitionError != null && <p role="alert">{definitionError}</p>}
        {filtered.length === 0 ? <SettingsEmpty title={prompts.length === 0 ? "No System Prompts yet." : "No matching System Prompts."} description={prompts.length === 0 ? "Create a reusable CORE prompt to make it available for scoped assignment." : "Adjust the search or filters to see other prompts."} /> : filtered.map((prompt) => (
          <article key={prompt.id} data-core-prompt={prompt.id} className="border border-border bg-card text-card-foreground" style={{ display: "flex", flexDirection: "column", gap: t.spacing.sm, padding: t.spacing.md, borderRadius: t.radius.md }}>
            <header style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: t.spacing.md }}>
            <div><strong>{prompt.name}</strong><div className="text-muted-foreground">{categories.find((item) => item.value === prompt.category)?.label ?? prompt.category}</div>{prompt.description && <p style={{ margin: `${t.spacing.xs}px 0 0` }}>{prompt.description}</p>}<div className="text-muted-foreground" style={{ fontSize: t.font.sizeSm }}>{prompt.is_enabled ? "Prompt enabled" : "Prompt definition disabled"}</div></div>
              <div style={{ display: "flex", gap: t.spacing.xs, flexWrap: "wrap" }}>
                <Button variant="secondary" size="sm" onClick={() => openEditor(prompt)}>Edit</Button>
                <Button variant="secondary" size="sm" disabled={pendingPromptId === prompt.id} onClick={() => void toggleDefinition(prompt)}>{pendingPromptId === prompt.id ? "Saving…" : prompt.is_enabled ? "Disable definition" : "Enable definition"}</Button>
                <Button variant="danger" size="sm" onClick={() => { setDeleteTarget(prompt); setDeleteError(null); }}>Delete</Button>
              </div>
            </header>
            <div aria-label={`Explicit assignments for ${prompt.name}`} className="text-muted-foreground" style={{ fontSize: t.font.sizeSm }}>
              Assignments: {(assignmentSummary[prompt.id] ?? []).length === 0 ? "None" : (assignmentSummary[prompt.id] ?? []).map((assignment) => `${assignment.scope_type}${assignment.scope_id == null ? "" : ` ${assignment.scope_id}`} — ${assignment.state.toUpperCase()}`).join(" · ")}
            </div>
          </article>
        ))}
      </section>

      <SettingsModal open={draftTarget != null} title={draftTarget === "new" ? "New System Prompt" : "Edit System Prompt"} onClose={() => { if (!savePending) setDraftTarget(null); }} onSecondaryAction={() => setDraftTarget(null)} secondaryAction="Cancel" primaryAction={draftTarget === "new" ? "Create" : "Save"} onPrimaryAction={() => void saveDefinition()} primaryBusy={savePending} primaryDisabled={savePending || !draft.name.trim() || !draft.promptText.trim()} error={saveError}>
        <div style={{ display: "flex", flexDirection: "column", gap: t.spacing.md }}>
          <Input label="Name" value={draft.name} onChange={(name) => setDraft((current) => ({ ...current, name }))} disabled={savePending} />
          <Select label="Category" value={draft.category} options={categories} onChange={(category) => setDraft((current) => ({ ...current, category: category as CorePromptCategory }))} disabled={savePending} />
          <Textarea label="Description" value={draft.description} onChange={(description) => setDraft((current) => ({ ...current, description }))} disabled={savePending} rows={2} />
          <Textarea label="Prompt text" value={draft.promptText} onChange={(promptText) => setDraft((current) => ({ ...current, promptText }))} disabled={savePending} rows={10} />
        </div>
      </SettingsModal>
      <SettingsModal open={deleteTarget != null} title="Delete System Prompt" onClose={() => { if (!deletePending) setDeleteTarget(null); }} onSecondaryAction={() => setDeleteTarget(null)} secondaryAction="Cancel" primaryAction="Delete permanently" onPrimaryAction={() => void deleteDefinition()} primaryBusy={deletePending} primaryDisabled={deletePending} error={deleteError}>
        <p>Deleting this prompt permanently removes the reusable definition and its scoped assignments.</p>
        <p>This does not delete any Project, Folder, or Conversation.</p>
      </SettingsModal>
    </div>
  );
}
