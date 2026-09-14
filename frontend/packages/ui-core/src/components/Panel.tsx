import { type CSSProperties, type ReactNode } from "react";
import { defaultTheme } from "../theme";

export interface PanelProps {
  children: ReactNode;
  title?: ReactNode;
  actions?: ReactNode;
  variant?: "default" | "subtle";
  padding?: "none" | "sm" | "md";
}

const t = defaultTheme;

export function Panel({
  children,
  title,
  actions,
  variant = "default",
  padding = "md",
}: PanelProps) {
  const bodyPadding =
    padding === "none" ? 0 : padding === "sm" ? t.spacing.sm : t.spacing.lg;

  const style: CSSProperties = {
    background:
      variant === "subtle" ? t.colors.surface : t.colors.background,
    border: `${t.border.width}px solid ${t.colors.border}`,
    borderRadius: t.radius.lg,
    boxSizing: "border-box",
  };

  return (
    <section style={style}>
      {(title != null || actions != null) && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: t.spacing.sm,
            padding: `${t.spacing.sm}px ${t.spacing.lg}px`,
            borderBottom: `${t.border.width}px solid ${t.colors.border}`,
          }}
        >
          {title != null && (
            <h2
              style={{
                margin: 0,
                fontSize: t.font.sizeSm,
                fontWeight: t.font.weightSemibold,
                color: t.colors.foreground,
              }}
            >
              {title}
            </h2>
          )}
          {actions != null && <div>{actions}</div>}
        </div>
      )}
      <div style={{ padding: bodyPadding }}>{children}</div>
    </section>
  );
}