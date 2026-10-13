import {
  listCorePromptAssignmentsForScope,
  listCorePrompts,
  setCorePromptAssignment,
  type ApiClient,
} from "@ava/api-client";
import type {
  CorePrompt,
  CorePromptAssignmentState,
  CorePromptScopeType,
} from "@ava/contracts";
import { Select, defaultTheme } from "@ava/ui-core";
import { useEffect, useState } from "react";

export type AssignablePromptScope = "global" | "project" | "folder" | "conversation" | "runtime" | "capability";

export interface CorePromptScopeAssignmentsProps {
  client: ApiClient;
  scopeType: AssignablePromptScope;
  scopeId: string | null;
  scopeLabel: string;
  active?: boolean;
  prompts?: CorePrompt[];
  onPromptsChange?: (prompts: CorePrompt[]) => void;
  onAssignmentChanged?: () => void;
}

const t = defaultTheme;
const states: { value: CorePromptAssignmentState; label: string; meaning: string }[] = [
  { value: "inherit", label: "Inherit", meaning: "No explicit override here." },
  { value: "enable", label: "Enable", meaning: "Explicitly apply this CORE prompt at this scope." },
  { value: "disable", label: "Disable", meaning: "Explicitly suppress this CORE prompt at this scope." },
];

export function CorePromptScopeAssignments({
  client, scopeType, scopeId, scopeLabel, active = true, prompts: suppliedPrompts, onPromptsChange, onAssignmentChanged,
}: CorePromptScopeAssignmentsProps) {
  const [loadedPrompts, setLoadedPrompts] = useState<CorePrompt[]>([]);
  const [stateByPrompt, setStateByPrompt] = useState<Record<string, CorePromptAssignmentState>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingIds, setPendingIds] = useState<Set<string>>(() => new Set());
  const prompts = suppliedPrompts ?? loadedPrompts;
  const setPrompts = onPromptsChange ?? setLoadedPrompts;

  useEffect(() => {
    if (!active || (scopeType !== "global" && scopeId == null)) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    const loadDefinitions = suppliedPrompts == null ? listCorePrompts(client) : Promise.resolve(null);
    void Promise.all([loadDefinitions, listCorePromptAssignmentsForScope(client, scopeType, scopeId)])
      .then(([definitions, assignments]) => {
        if (cancelled) return;
        if (definitions != null) setPrompts(definitions.core_prompts);
        const next: Record<string, CorePromptAssignmentState> = {};
        for (const assignment of assignments.assignments) next[assignment.core_prompt_id] = assignment.state;
        setStateByPrompt(next);
      })
      .catch(() => { if (!cancelled) setError("System Prompt assignments could not be loaded. Try again."); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [active, client, scopeType, scopeId, suppliedPrompts, setPrompts]);

  async function changeState(prompt: CorePrompt, state: CorePromptAssignmentState) {
    if (pendingIds.has(prompt.id) || (scopeType !== "global" && scopeId == null)) return;
    const previous = stateByPrompt[prompt.id] ?? "inherit";
    if (previous === state) return;
    setPendingIds((current) => new Set(current).add(prompt.id));
    setError(null);
    try {
      await setCorePromptAssignment(client, prompt.id, { scope_type: scopeType as CorePromptScopeType, scope_id: scopeId, state });
      setStateByPrompt((current) => ({ ...current, [prompt.id]: state }));
      onAssignmentChanged?.();
    } catch {
      setError("Assignment could not be saved. The previous state is unchanged; choose the state again to retry.");
    } finally {
      setPendingIds((current) => {
        const next = new Set(current);
        next.delete(prompt.id);
        return next;
      });
    }
  }

  return (
    <section aria-label={`System Prompts for ${scopeLabel}`} style={{ display: "flex", flexDirection: "column", gap: t.spacing.md }}>
      <header>
        <h2 style={{ margin: 0 }}>System Prompts</h2>
        <p style={{ margin: `${t.spacing.xs}px 0 0`, color: t.colors.mutedText }}>{scopeLabel}</p>
        <p style={{ margin: `${t.spacing.xs}px 0 0`, color: t.colors.mutedText }}>
          Assignment state is explicit only. Inherit means no override at this scope; AVA does not calculate inherited or effective prompts here.
        </p>
      </header>
      {error != null && <p role="alert" style={{ margin: 0, color: t.colors.dangerText }}>{error}</p>}
      {loading ? <p role="status">Loading System Prompts…</p> : prompts.length === 0 ? (
        <p style={{ margin: 0 }}>No System Prompts are available yet.</p>
      ) : prompts.map((prompt) => {
        const state = stateByPrompt[prompt.id] ?? "inherit";
        return (
          <article key={prompt.id} data-prompt-assignment={prompt.id} className="border border-border bg-card text-card-foreground" style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(150px, 220px)", alignItems: "center", gap: t.spacing.md, padding: t.spacing.md, borderRadius: t.radius.md }}>
            <div>
              <strong>{prompt.name}</strong>
              <div className="text-muted-foreground" style={{ fontSize: t.font.sizeSm }}>{prompt.category}</div>
              {!prompt.is_enabled && <div aria-label="Definition disabled" className="text-muted-foreground" style={{ fontSize: t.font.sizeSm }}>Definition disabled</div>}
              <div className="text-muted-foreground" style={{ fontSize: t.font.sizeXs }}>{states.find((item) => item.value === state)?.meaning}</div>
            </div>
            <Select
              ariaLabel={`Assignment for ${prompt.name} at ${scopeLabel}`}
              value={state}
              disabled={pendingIds.has(prompt.id) || loading}
              options={states.map(({ value, label }) => ({ value, label }))}
              onChange={(value) => void changeState(prompt, value as CorePromptAssignmentState)}
            />
          </article>
        );
      })}
    </section>
  );
}
