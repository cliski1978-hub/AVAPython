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
        flexShrink: 0,
        boxSizing: "border-box",
        minHeight: 40,
      }}
      className="border-b border-border bg-background text-foreground"
    >
      <h2
        style={{
          margin: 0,
          fontSize: t.font.sizeSm,
          fontWeight: t.font.weightSemibold,
          whiteSpace: "nowrap",
          overflow: "hidden",
          textOverflow: "ellipsis",
        }}
        className="text-foreground"
      >
        {title ?? "New Conversation"}
      </h2>
    </div>
  );
}
