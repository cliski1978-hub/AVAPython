import type { RuntimeDiscoveryItem, ModelProviderDiscoveryItem, ExecutionProfile, WorkspaceInfo } from "@ava/contracts";

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
}: ExecutionControlsProps) {
  const selectStyle = { background: "transparent", color: "inherit", border: 0, fontSize: 12, maxWidth: 180 };
  const labelStyle = { fontSize: 12, color: "#a1a1aa" } as const;

  return <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
    {(profiles.length > 0 || onDefaultChange) && <label style={labelStyle}>Profile <select aria-label="Select execution profile" disabled={disabled} value={selectedProfileId ?? "custom"} onChange={e => { if (e.target.value === "application-default") return onDefaultChange?.(); if (e.target.value === "auto") return onAutoChange?.(); const p = profiles.find(x => x.id === e.target.value); if (p) onProfileChange?.(p); }}>{onDefaultChange && <option value="application-default">Application default</option>}<option value="auto">Auto</option><option value="custom" disabled>Custom</option>{profiles.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>}
    <label style={labelStyle}>Runtime <select style={selectStyle} aria-label="Select runtime" disabled={disabled} value={selectedRuntimeId ?? ""} onChange={e => onRuntimeChange(e.target.value)}>
      {onDefaultChange && <option value="">{selectedProfileId === "application-default" ? "Application default" : "Legacy default"}</option>}
      {!onDefaultChange && !runtimes.length && <option value="">No runtimes available</option>}
      {runtimes.map(r => <option key={r.runtime_info.runtime_id} value={r.runtime_info.runtime_id}>{r.runtime_info.display_name ?? r.runtime_info.runtime_id}</option>)}
    </select></label>
    <label style={labelStyle}>Model <select style={selectStyle} aria-label="Select model" disabled={disabled} value={selectedModelProviderId ?? ""} onChange={e => onModelProviderChange(e.target.value)}>
      {onDefaultChange && <option value="">{selectedProfileId === "application-default" ? "Application default" : "Legacy default"}</option>}
      {!onDefaultChange && !modelProviders.length && <option value="">No models available</option>}
      {modelProviders.map(p => <option key={p.provider_id} value={p.provider_id}>{p.model_info.model_id}</option>)}
    </select></label>
    <label style={labelStyle}>Workspace <select style={selectStyle} aria-label="Select workspace" disabled={disabled || workspacesUnavailable} value={selectedWorkspaceId ?? ""} onChange={e => onWorkspaceChange?.(e.target.value === "" ? null : e.target.value)}>
      {workspacesUnavailable
        ? <option value="">Workspace options unavailable</option>
        : <option value="">None</option>}
      {!workspacesUnavailable && workspaces.map(w => <option key={w.workspace_id} value={w.workspace_id}>{w.display_name}</option>)}
    </select></label>
  </div>;
}
