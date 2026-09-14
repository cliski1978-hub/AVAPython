import { defaultTheme, EmptyState } from "@ava/ui-core";

const STARTER_PROMPTS = [
  "Explain a technical concept",
  "Summarize a document",
  "Help me solve an engineering problem",
];

const t = defaultTheme;

/** Visual starter prompts only — never wired to submission or state. */
export function ConversationEmptyState() {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: t.spacing.lg,
        padding: t.spacing.xl,
        boxSizing: "border-box",
      }}
    >
      <EmptyState title="AVA" description="How can I help?" />
      <ul
        style={{
          listStyle: "none",
          display: "flex",
          flexWrap: "wrap",
          gap: t.spacing.sm,
          justifyContent: "center",
          padding: 0,
          margin: 0,
        }}
      >
        {STARTER_PROMPTS.map((prompt) => (
          <li key={prompt}>
            <span
              style={{
                display: "inline-block",
                padding: `${t.spacing.xs + 2}px ${t.spacing.md}px`,
                border: `${t.border.width}px solid ${t.colors.borderStrong}`,
                borderRadius: "999px",
                fontSize: t.font.sizeSm,
                color: t.colors.mutedText,
              }}
            >
              {prompt}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}