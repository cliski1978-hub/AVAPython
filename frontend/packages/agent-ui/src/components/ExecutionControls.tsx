import type { RuntimeDiscoveryItem, ModelInfo, ModelProviderDiscoveryItem, ExecutionProfile, WorkspaceInfo } from "@ava/contracts";

export interface ExecutionControlsProps {
  runtimes: RuntimeDiscoveryItem[];
  modelProviders: ModelProviderDiscoveryItem[];
  selectedRuntimeId?: string;
  selectedModelProviderId?: string;
  onRuntimeChange: (id: string) => void;
  onModelProviderChange: (id: string) => void;
  disabled?: boolean;
  profiles?: ExecutionProfile[];
  selectedProfileId?: string;
  onProfileChange?: (profile: ExecutionProfile) => void;
  onAutoChange?: () => void;
  onDefaultChange?: () => void;
  workspaces?: WorkspaceInfo[];
  selectedWorkspaceId?: string | null;
  onWorkspaceChange?: (workspaceId: string | null) => void;
  workspacesUnavailable?: boolean;
  /**
   * Configured models offered by the Model control, from `GET /models`.
   *
   * The option value is the stable AVA `model_id`, never a display name and
   * never a provider identity: a provider can expose several configured
   * models, so a provider-keyed control cannot represent them. When omitted the
   * control falls back to provider identities, which is the pre-settings
   * behaviour and cannot address a configured model.
   */
  configuredModels?: ModelInfo[];
  /** Model the application default resolves to, used to label that option. */
  defaultModelDisplayName?: string;
  /** Scope supplying the inherited model displayed in the empty option. */
  defaultModelScopeLabel?: string;
  /** Layout used when controls are shown in the composer settings popover. */
  layout?: "inline" | "popover";
}

export function ExecutionControls({
  runtimes,
  modelProviders,
  selectedRuntimeId,
  selectedModelProviderId,
  onRuntimeChange,
  onModelProviderChange,
  disabled = false,
  profiles = [],
  selectedProfileId,
  onProfileChange,
  onAutoChange,
  onDefaultChange,
  workspaces = [],
  selectedWorkspaceId = null,
  onWorkspaceChange,
  workspacesUnavailable = false,
  configuredModels = [],
  defaultModelDisplayName,
  defaultModelScopeLabel = "Application default",
  layout = "inline",
}: ExecutionControlsProps) {
  const labelClassName = layout === "popover"
    ? "flex min-w-0 flex-col gap-1.5 text-xs font-medium text-foreground"
    : "inline-flex items-center gap-2 text-xs text-muted-foreground";
  const selectClassName = layout === "popover"
    ? "h-9 w-full min-w-0 rounded-md border border-input bg-background px-2 text-sm text-foreground shadow-sm outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-50 [color-scheme:inherit]"
    : "h-8 max-w-48 rounded-md border border-input bg-background px-2 text-xs text-foreground shadow-sm outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-50 [color-scheme:inherit]";

  // Configured models are the catalog a user actually configured, so they win
  // whenever discovery reports any. Disabled records stay listed: selecting one
  // must fail on its own explicit terms rather than vanish from the UI.
  const hasConfiguredModels = configuredModels.length > 0;
  const unsetLabel = selectedProfileId === "application-default"
    ? defaultModelDisplayName
      ? `${defaultModelScopeLabel} (${defaultModelDisplayName})`
      : defaultModelScopeLabel
    : "Legacy default";

  // An execution profile pins a provider, not a configured model, so its value
  // can be absent from the catalog. Render it explicitly instead of letting the
  // select fall back to a blank option: the profile's choice stays visible and
  // the request keeps carrying it.
  const selectedIsListed = selectedModelProviderId == null || selectedModelProviderId === ""
    ? true
    : hasConfiguredModels
      ? configuredModels.some(m => m.model_id === selectedModelProviderId)
      : modelProviders.some(p => p.provider_id === selectedModelProviderId);
  const unlistedSelection = selectedModelProviderId && !selectedIsListed
    ? selectedModelProviderId
    : null;

  return <div className={layout === "popover" ? "grid grid-cols-1 gap-3 sm:grid-cols-2" : "flex flex-wrap items-center gap-x-3 gap-y-2"}>
    {(profiles.length > 0 || onDefaultChange) && <label className={labelClassName}>Profile <select className={selectClassName} aria-label="Select execution profile" disabled={disabled} value={selectedProfileId ?? "custom"} onChange={e => { if (e.target.value === "application-default") return onDefaultChange?.(); if (e.target.value === "auto") return onAutoChange?.(); const p = profiles.find(x => x.id === e.target.value); if (p) onProfileChange?.(p); }}>{onDefaultChange && <option value="application-default">Application default</option>}<option value="auto">Auto</option><option value="custom" disabled>Custom</option>{profiles.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>}
    <label className={labelClassName}>Runtime <select className={selectClassName} aria-label="Select runtime" disabled={disabled} value={selectedRuntimeId ?? ""} onChange={e => onRuntimeChange(e.target.value)}>
      {onDefaultChange && <option value="">{selectedProfileId === "application-default" ? "Application default" : "Legacy default"}</option>}
      {!onDefaultChange && !runtimes.length && <option value="">No runtimes available</option>}
      {runtimes.map(r => <option key={r.runtime_info.runtime_id} value={r.runtime_info.runtime_id}>{r.runtime_info.display_name ?? r.runtime_info.runtime_id}</option>)}
    </select></label>
    <label className={labelClassName}>Model <select className={selectClassName} aria-label="Select model" disabled={disabled} value={selectedModelProviderId ?? ""} onChange={e => onModelProviderChange(e.target.value)}>
      {onDefaultChange && <option value="">{unsetLabel}</option>}
      {!hasConfiguredModels && !onDefaultChange && !modelProviders.length && <option value="">No models available</option>}
      {unlistedSelection && <option value={unlistedSelection}>Provider {unlistedSelection} (from profile)</option>}
      {hasConfiguredModels
        ? configuredModels.map(m => <option key={m.model_id} value={m.model_id}>{m.display_name ?? m.model_id}{m.enabled ? "" : " (disabled)"}</option>)
        : modelProviders.map(p => <option key={p.provider_id} value={p.provider_id}>{p.model_info.model_id}</option>)}
    </select></label>
    <label className={labelClassName}>Workspace <select className={selectClassName} aria-label="Select workspace" disabled={disabled || workspacesUnavailable} value={selectedWorkspaceId ?? ""} onChange={e => onWorkspaceChange?.(e.target.value === "" ? null : e.target.value)}>
      {workspacesUnavailable
        ? <option value="">Workspace options unavailable</option>
        : <option value="">None</option>}
      {!workspacesUnavailable && workspaces.map(w => <option key={w.workspace_id} value={w.workspace_id}>{w.display_name}</option>)}
    </select></label>
  </div>;
}
