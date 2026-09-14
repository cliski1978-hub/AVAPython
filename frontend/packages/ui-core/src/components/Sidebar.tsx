import { type ReactNode } from "react";
import { defaultTheme } from "../theme";
import { IconButton } from "./IconButton";

export interface SidebarProps {
  collapsed?: boolean;
  onToggle?: () => void;
  children?: ReactNode;
}

const t = defaultTheme;

const EXPANDED_WIDTH = 260;
const COLLAPSED_WIDTH = 40;

export function Sidebar({ collapsed = false, onToggle, children }: SidebarProps) {
  const expanded = !collapsed;

  return (
    <aside
      style={{
        display: "flex",
        flexDirection: "column",
        borderRight: `${t.border.width}px solid ${t.colors.border}`,
        background: t.colors.surface,
        overflow: "hidden",
        flexShrink: 0,
        transition: "width 200ms ease",
        width: expanded ? EXPANDED_WIDTH : COLLAPSED_WIDTH,
        boxSizing: "border-box",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: expanded ? "space-between" : "center",
          padding: expanded ? `0 ${t.spacing.md}px` : 0,
          height: 40,
          borderBottom: `${t.border.width}px solid ${t.colors.border}`,
          boxSizing: "border-box",
          flexShrink: 0,
        }}
      >
        {expanded && (
          <span
            style={{
              fontSize: t.font.sizeXs,
              fontWeight: t.font.weightSemibold,
              color: t.colors.mutedText,
              textTransform: "uppercase",
              letterSpacing: "0.05em",
              whiteSpace: "nowrap",
            }}
          >
            Conversations
          </span>
        )}
        <IconButton
          size="sm"
          ariaLabel={expanded ? "Collapse sidebar" : "Expand sidebar"}
          title={expanded ? "Collapse sidebar" : "Expand sidebar"}
          onClick={onToggle}
          disabled={onToggle == null}
        >
          {expanded ? "«" : "»"}
        </IconButton>
      </div>
      {expanded && (
        <div
          style={{
            flex: 1,
            overflow: "auto",
            padding: t.spacing.sm,
          }}
        >
          {children ?? (
            <p
              style={{
                margin: 0,
                padding: t.spacing.md,
                color: t.colors.mutedText,
                fontSize: t.font.sizeSm,
                textAlign: "center",
                fontStyle: "italic",
              }}
            >
              No conversations yet
            </p>
          )}
        </div>
      )}
    </aside>
  );
}