import { PrimaryNav, type PrimaryDestination } from "@ava/ui-core";

export type WorkspaceId = "chat" | "document" | "settings" | "projects" | "approvals";

export interface WorkspaceTabsProps {
  active: WorkspaceId;
  onSelect: (workspace: WorkspaceId) => void;
}

const destinationForWorkspace: Record<WorkspaceId, PrimaryDestination> = {
  chat: "chat",
  projects: "projects",
  document: "documents",
  settings: "settings",
  approvals: "approvals",
};

const workspaceForDestination: Record<PrimaryDestination, WorkspaceId> = {
  chat: "chat",
  projects: "projects",
  documents: "document",
  settings: "settings",
  approvals: "approvals",
};

/** Backward-compatible workspace adapter over the shared primary navigation. */
export function WorkspaceTabs({ active, onSelect }: WorkspaceTabsProps) {
  return (
    <PrimaryNav
      active={destinationForWorkspace[active]}
      onSelect={(destination) => onSelect(workspaceForDestination[destination])}
    />
  );
}
