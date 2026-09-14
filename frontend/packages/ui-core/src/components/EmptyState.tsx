import { type ReactNode } from "react";
import { defaultTheme } from "../theme";

export interface EmptyStateProps {
  title: string;
  description?: string;
  action?: ReactNode;
  visual?: ReactNode;
}

const t = defaultTheme;

export function EmptyState({
  title,
  description,
  action,
  visual,
}: EmptyStateProps) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        textAlign: "center",
        gap: t.spacing.md,
        padding: t.spacing.xl,
      }}
    >
      {visual != null && <div style={{ flexShrink: 0 }}>{visual}</div>}
      <h3
        style={{
          margin: 0,
          fontSize: t.font.sizeMd,
          fontWeight: t.font.weightSemibold,
          color: t.colors.foreground,
        }}
      >
        {title}
      </h3>
      {description != null && (
        <p
          style={{
            margin: 0,
            color: t.colors.mutedText,
            fontSize: t.font.sizeSm,
            lineHeight: 1.6,
            maxWidth: 400,
          }}
        >
          {description}
        </p>
      )}
      {action != null && <div style={{ marginTop: t.spacing.xs }}>{action}</div>}
    </div>
  );
}