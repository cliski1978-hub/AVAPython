import { defaultTheme } from "@ava/ui-core";

export interface ConversationHeaderProps {
  title?: string;
}

const t = defaultTheme;

/** Minimal conversation header. Model/provider and action areas come later. */
export function ConversationHeader({ title }: ConversationHeaderProps) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: t.spacing.md,
        padding: `${t.spacing.md}px ${t.spacing.lg}px`,
        borderBottom: `${t.border.width}px solid ${t.colors.border}`,
        background: t.colors.background,
        flexShrink: 0,
        boxSizing: "border-box",
        minHeight: 40,
      }}
    >
      <h2
        style={{
          margin: 0,
          fontSize: t.font.sizeSm,
          fontWeight: t.font.weightSemibold,
          color: t.colors.foreground,
          whiteSpace: "nowrap",
          overflow: "hidden",
          textOverflow: "ellipsis",
        }}
      >
        {title ?? "New Conversation"}
      </h2>
    </div>
  );
}