import { defaultTheme, useInteraction } from "@ava/ui-core";
import type { CSSProperties } from "react";

export type WorkspaceId = "chat" | "document" | "settings" | "projects";

export interface WorkspaceTabsProps {
  active: WorkspaceId;
  onSelect: (workspace: WorkspaceId) => void;
}

const t = defaultTheme;

interface TabDef {
  id: WorkspaceId;
  label: string;
  panelId: string;
}

const TABS: TabDef[] = [
  { id: "chat", label: "Chat", panelId: "chat-workspace" },
  { id: "document", label: "Documents", panelId: "document-workspace" },
  { id: "settings", label: "Settings", panelId: "settings-workspace" },
  { id: "projects", label: "Projects", panelId: "projects-workspace" },
];

interface TabButtonProps {
  tab: TabDef;
  selected: boolean;
  onSelect: () => void;
}

function TabButton({ tab, selected, onSelect }: TabButtonProps) {
  const interaction = useInteraction(true);

  const style: CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    height: 30,
    padding: `0 ${t.spacing.md}px`,
    borderRadius: t.radius.md,
    borderWidth: t.border.width,
    borderStyle: "solid",
    borderColor: "transparent",
    background: selected ? t.colors.surface : "transparent",
    color: selected ? t.colors.primary : t.colors.mutedText,
    fontWeight: selected ? t.font.weightSemibold : t.font.weightNormal,
    fontSize: t.font.sizeSm,
    fontFamily: t.font.family,
    cursor: "pointer",
    outline: "none",
    boxSizing: "border-box",
    transition:
      "background 120ms ease, color 120ms ease, box-shadow 120ms ease",
    ...(interaction.hovered && !selected
      ? { background: t.colors.ghostHover, color: t.colors.foreground }
      : {}),
    ...(interaction.focused
      ? { boxShadow: `0 0 0 2px ${t.colors.focusRing}33` }
      : {}),
  };

  return (
    <button
      type="button"
      role="tab"
      aria-selected={selected}
      aria-controls={tab.panelId}
      style={style}
      title={tab.label}
      onClick={onSelect}
      onMouseEnter={interaction.onMouseEnter}
      onMouseLeave={interaction.onMouseLeave}
      onFocus={interaction.onFocus}
      onBlur={interaction.onBlur}
    >
      {tab.label}
    </button>
  );
}

export function WorkspaceTabs({ active, onSelect }: WorkspaceTabsProps) {
  return (
    <div
      role="tablist"
      aria-label="Workspace"
      style={{ display: "flex", alignItems: "center", gap: t.spacing.xs }}
    >
      {TABS.map((tab) => (
        <TabButton
          key={tab.id}
          tab={tab}
          selected={active === tab.id}
          onSelect={() => onSelect(tab.id)}
        />
      ))}
    </div>
  );
}
