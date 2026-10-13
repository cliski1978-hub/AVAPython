import { type ReactNode } from "react";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { IconButton } from "./ui/icon-button";

export interface SidebarProps {
  collapsed?: boolean;
  width?: number;
  onToggle?: () => void;
  children?: ReactNode;
}

export function Sidebar({ collapsed = false, width, onToggle, children }: SidebarProps) {
  const expanded = !collapsed;

  return (
    <aside
      aria-label="Conversation sidebar"
      className="flex shrink-0 flex-col overflow-hidden border-r border-border bg-card text-card-foreground transition-[width] duration-200"
      style={{ width: expanded ? width ?? "var(--ava-sidebar-width)" : "var(--ava-sidebar-collapsed-width)" }}
    >
      <div
        className={`flex h-11 shrink-0 items-center border-b border-border ${expanded ? "justify-between px-3" : "justify-center"}`}
      >
        {expanded && (
          <span className="truncate text-xs font-semibold tracking-[0.06em] text-muted-foreground">
            Conversations
          </span>
        )}
        <IconButton
          size="compact"
          icon={expanded ? PanelLeftClose : PanelLeftOpen}
          label={expanded ? "Collapse conversation sidebar" : "Expand conversation sidebar"}
          appearance="row-action"
          className="shrink-0 bg-transparent hover:bg-transparent hover:text-foreground dark:hover:bg-black dark:hover:text-white"
          onClick={onToggle}
          disabled={onToggle == null}
        />
      </div>
      {expanded && (
        <div
          className="min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto p-2"
        >
          {children ?? (
            <p className="m-0 p-3 text-center text-sm italic text-muted-foreground">
              No conversations yet
            </p>
          )}
        </div>
      )}
    </aside>
  );
}
