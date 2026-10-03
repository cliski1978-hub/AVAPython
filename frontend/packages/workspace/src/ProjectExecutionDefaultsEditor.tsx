import {
  ApiError,
  getProjectExecutionDefaults,
  getRuntimes,
  listModelConfigurations,
  listProviderConnections,
  updateProjectExecutionDefaults,
  type ApiClient,
} from "@ava/api-client";
import { Button, LoadingIndicator, Select, defaultTheme, type SelectOption } from "@ava/ui-core";
import { useEffect, useRef, useState } from "react";

const t = defaultTheme;

type Model = Awaited<ReturnType<typeof listModelConfigurations>>["models"][number];
type ProviderConnection = Awaited<ReturnType<typeof listProviderConnections>>["provider_connections"][number];
type Runtime = Awaited<ReturnType<typeof getRuntimes>>["runtimes"][number]["runtime_info"];
type ProjectDefaults = Awaited<ReturnType<typeof getProjectExecutionDefaults>>;

function validationMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError && error.status >= 500) {
    return "AVA could not complete this request. Try again.";
  }
  if (error instanceof ApiError && error.status === 422) {
    const body = error.body;
    if (typeof body === "object" && body !== null && "message" in body && typeof body.message === "string") {
      return body.message;
    }
  }
  return fallback;
}

function modelLabel(model: Model, connections: Map<string, ProviderConnection>): string {
  const connection = connections.get(model.provider_connection_id);
  const connectionName = connection?.display_name ?? model.provider_connection_id;
  return `${model.display_name} (${model.model_id}) · ${connectionName}`;
}

export function ProjectExecutionDefaultsEditor({
  client,
  projectId,
}: {
  client: ApiClient;
  projectId: string;
}) {
  const [persisted, setPersisted] = useState<ProjectDefaults | null>(null);
  const [runtimeDraft, setRuntimeDraft] = useState("");
  const [modelDraft, setModelDraft] = useState("");
  const [runtimes, setRuntimes] = useState<Runtime[]>([]);
  const [models, setModels] = useState<Model[]>([]);
  const [connections, setConnections] = useState<ProviderConnection[]>([]);
  const [runtimeChoicesKnown, setRuntimeChoicesKnown] = useState(false);
  const [modelChoicesKnown, setModelChoicesKnown] = useState(false);
  const [runtimeChoicesError, setRuntimeChoicesError] = useState<string | null>(null);
  const [modelChoicesError, setModelChoicesError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [choicesAttempt, setChoicesAttempt] = useState(0);
  const dirtyRef = useRef(false);
  const savingRef = useRef(false);
  const priorProjectId = useRef(projectId);

  if (priorProjectId.current !== projectId) {
    // Project identity is a hard draft boundary. A new Project never inherits
    // pending state from the previously displayed Project.
    priorProjectId.current = projectId;
    dirtyRef.current = false;
  }

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    setSaveError(null);
    void getProjectExecutionDefaults(client, projectId)
      .then((value) => {
        if (cancelled) return;
        setPersisted(value);
        if (!dirtyRef.current) {
          setRuntimeDraft(value.runtime_key ?? "");
          setModelDraft(value.model_id ?? "");
        }
      })
      .catch(() => {
        if (!cancelled) setLoadError("Project execution defaults could not be loaded. Try again.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [client, loadAttempt, projectId]);

  useEffect(() => {
    let cancelled = false;
    setRuntimeChoicesError(null);
    setModelChoicesError(null);
    void Promise.allSettled([
      getRuntimes(client),
      listModelConfigurations(client),
      listProviderConnections(client),
    ]).then(([runtimeResult, modelResult, connectionResult]) => {
      if (cancelled) return;
      if (runtimeResult.status === "fulfilled") {
        setRuntimeChoicesKnown(true);
        const unique = new Map<string, Runtime>();
        for (const item of runtimeResult.value.runtimes) {
          if (!unique.has(item.runtime_info.runtime_id)) unique.set(item.runtime_info.runtime_id, item.runtime_info);
        }
        setRuntimes([...unique.values()].sort((left, right) => left.runtime_id.localeCompare(right.runtime_id)));
      } else {
        setRuntimeChoicesKnown(false);
        setRuntimeChoicesError("Runtime choices could not be refreshed.");
      }
      if (modelResult.status === "fulfilled") {
        setModelChoicesKnown(true);
        setModels(modelResult.value.models);
      } else {
        setModelChoicesKnown(false);
        setModelChoicesError("Model choices could not be refreshed.");
      }
      if (connectionResult.status === "fulfilled") setConnections(connectionResult.value.provider_connections);
    });
    return () => { cancelled = true; };
  }, [client, choicesAttempt, projectId]);

  const runtimeById = new Map(runtimes.map((runtime) => [runtime.runtime_id, runtime]));
  const connectionById = new Map(connections.map((connection) => [connection.provider_connection_id, connection]));
  const runtimeUnavailable = persisted?.runtime_key != null && (
    persisted.runtime_available === false ||
    (runtimeChoicesKnown && !runtimeById.has(persisted.runtime_key))
  );
  const storedModel = persisted?.model_id == null ? null : models.find((model) => model.model_id === persisted.model_id) ?? null;
  const modelUnavailable = persisted?.model_id != null && (
    storedModel != null ? !storedModel.enabled : modelChoicesKnown
  );
  const runtimeOptions: SelectOption[] = [
    { value: "", label: "Use application default" },
    ...runtimes.map((runtime) => ({
      value: runtime.runtime_id,
      label: runtime.display_name ? `${runtime.runtime_id} — ${runtime.display_name}` : runtime.runtime_id,
      disabled: persisted?.runtime_available === false && persisted.runtime_key === runtime.runtime_id,
    })),
  ];
  if (runtimeUnavailable && persisted?.runtime_key != null && !runtimeById.has(persisted.runtime_key)) {
    runtimeOptions.push({ value: persisted.runtime_key, label: `${persisted.runtime_key} (unavailable)`, disabled: true });
  }
  const modelOptions: SelectOption[] = [
    { value: "", label: "Use application default" },
    ...models.filter((model) => model.enabled).map((model) => ({
      value: model.model_id,
      label: modelLabel(model, connectionById),
    })),
  ];
  if (modelUnavailable && persisted?.model_id != null) {
    const staleLabel = storedModel == null
      ? `${persisted.model_id} (unavailable)`
      : `${modelLabel(storedModel, connectionById)} (disabled)`;
    modelOptions.push({ value: persisted.model_id, label: staleLabel, disabled: true });
  }

  const dirty = persisted != null && (
    runtimeDraft !== (persisted.runtime_key ?? "") || modelDraft !== (persisted.model_id ?? "")
  );
  const pending = saving || loading;

  useEffect(() => {
    dirtyRef.current = dirty;
  }, [dirty]);

  function editRuntime(value: string): void {
    dirtyRef.current = value !== (persisted?.runtime_key ?? "") || modelDraft !== (persisted?.model_id ?? "");
    setRuntimeDraft(value);
    setSaveError(null);
  }

  function editModel(value: string): void {
    dirtyRef.current = runtimeDraft !== (persisted?.runtime_key ?? "") || value !== (persisted?.model_id ?? "");
    setModelDraft(value);
    setSaveError(null);
  }

  function cancel(): void {
    if (persisted == null) return;
    dirtyRef.current = false;
    setRuntimeDraft(persisted.runtime_key ?? "");
    setModelDraft(persisted.model_id ?? "");
    setSaveError(null);
  }

  function useApplicationDefaults(): void {
    editRuntime("");
    editModel("");
  }

  async function save(): Promise<void> {
    if (savingRef.current || persisted == null || !dirty) return;
    const request: { runtime_key?: string | null; model_id?: string | null } = {};
    if (runtimeDraft !== (persisted.runtime_key ?? "")) request.runtime_key = runtimeDraft || null;
    if (modelDraft !== (persisted.model_id ?? "")) request.model_id = modelDraft || null;
    if (Object.keys(request).length === 0) return;
    savingRef.current = true;
    setSaving(true);
    setSaveError(null);
    try {
      const updated = await updateProjectExecutionDefaults(client, projectId, request);
      setPersisted(updated);
      setRuntimeDraft(updated.runtime_key ?? "");
      setModelDraft(updated.model_id ?? "");
      dirtyRef.current = false;
    } catch (error) {
      setSaveError(validationMessage(error, "Project execution defaults could not be saved. Your draft is still here."));
      if (error instanceof ApiError && error.status === 422) setChoicesAttempt((value) => value + 1);
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }

  const panelStyle = {
    display: "flex",
    flexDirection: "column" as const,
    gap: t.spacing.md,
    padding: t.spacing.lg,
    border: `${t.border.width}px solid ${t.colors.border}`,
    borderRadius: t.radius.md,
    background: t.colors.surface,
  };

  if (loading && persisted == null) return <LoadingIndicator label="Loading Project execution defaults…" />;
  if (loadError != null && persisted == null) {
    return (
      <div role="alert" style={panelStyle}>
        <h2 style={{ margin: 0 }}>Execution Defaults</h2>
        <p style={{ margin: 0 }}>{loadError}</p>
        <Button onClick={() => setLoadAttempt((value) => value + 1)}>Retry</Button>
      </div>
    );
  }

  return (
    <section aria-labelledby="project-execution-defaults-heading" style={panelStyle}>
      <h2 id="project-execution-defaults-heading" style={{ margin: 0 }}>Execution Defaults</h2>
      <p style={{ margin: 0, color: t.colors.mutedText }}>Runtime and model are resolved independently. Some combinations may be incompatible at execution time.</p>
      <p style={{ margin: 0, color: t.colors.mutedText }}>
        Execution selection precedence: Explicit run choice → Project default → Application default → System fallback.
      </p>
      {persisted?.runtime_available === false && runtimeDraft === persisted.runtime_key && (
        <p role="status" aria-live="polite">Configured runtime is no longer available. Execution currently falls back to the next default.</p>
      )}
      {modelUnavailable && modelDraft === persisted?.model_id && (
        <p role="status" aria-live="polite">Previously selected model unavailable. Execution currently falls back to the next default.</p>
      )}
      {loadError != null && <p role="alert">{loadError}</p>}
      {runtimeChoicesError != null && <p role="status" aria-live="polite">{runtimeChoicesError}</p>}
      {modelChoicesError != null && <p role="status" aria-live="polite">{modelChoicesError} Stored Project values are preserved.</p>}
      <Select
        label="Preferred Runtime"
        value={runtimeDraft}
        options={runtimeOptions}
        disabled={pending || (runtimes.length === 0 && !runtimeUnavailable)}
        onChange={editRuntime}
        helpText="Choose a registered runtime key, or inherit the application default."
      />
      <Select
        label="Preferred Model"
        value={modelDraft}
        options={modelOptions}
        disabled={pending || (models.length === 0 && !modelUnavailable)}
        onChange={editModel}
        helpText="Choose an enabled configured model by its stable model ID, or inherit the application default."
      />
      <div style={{ display: "flex", flexWrap: "wrap", gap: t.spacing.sm }}>
        <Button variant="primary" disabled={!dirty || pending} onClick={() => void save()}>
          {saving ? "Saving…" : "Save"}
        </Button>
        <Button disabled={!dirty || pending} onClick={cancel}>Cancel</Button>
        <Button disabled={pending || (runtimeDraft === "" && modelDraft === "")} onClick={useApplicationDefaults}>
          Use application defaults
        </Button>
        <Button disabled={pending} onClick={() => setLoadAttempt((value) => value + 1)}>Refresh stored values</Button>
        {(runtimeChoicesError != null || modelChoicesError != null) && (
          <Button disabled={pending} onClick={() => setChoicesAttempt((value) => value + 1)}>Refresh choices</Button>
        )}
      </div>
      {saving && <p role="status" aria-live="polite">Saving Project execution defaults…</p>}
      {saveError != null && <p role="alert">{saveError}</p>}
    </section>
  );
}
