import { type ReactNode } from "react";
import { defaultTheme } from "../theme";

export interface HeaderProps {
  title?: string;
  actions?: ReactNode;
}

const t = defaultTheme;

export function Header({ title = "AVA", actions }: HeaderProps) {
  return (
    <header
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: t.spacing.md,
        padding: `0 ${t.spacing.lg}px`,
        borderBottom: `${t.border.width}px solid ${t.colors.border}`,
        background: t.colors.background,
        height: 48,
        flexShrink: 0,
        boxSizing: "border-box",
      }}
    >
      <h1
        style={{
          margin: 0,
          fontSize: t.font.sizeMd,
          fontWeight: t.font.weightSemibold,
          color: t.colors.foreground,
        }}
      >
        {title}
      </h1>
      {actions != null && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: t.spacing.md,
          }}
        >
          {actions}
        </div>
      )}
    </header>
  );
}