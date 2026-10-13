import { defaultTheme, EmptyState, shadcn } from "@ava/ui-core";

const STARTER_PROMPTS = [
  "Explain a technical concept",
  "Summarize a document",
  "Help me solve an engineering problem",
];

const t = defaultTheme;
const avaHeroImage = new URL("../assets/ava-hero.png", import.meta.url).href;

/** Visual starter prompts only — never wired to submission or state. */
export function ConversationEmptyState() {
  return (
    <div
      className="text-foreground"
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: t.spacing.lg,
        padding: t.spacing.xl,
        boxSizing: "border-box",
      }}
    >
      <EmptyState
        title="How can I help?"
        visual={(
          <img
            data-ava-hero=""
            src={avaHeroImage}
            alt="AVA"
            style={{
              display: "block",
              width: "clamp(180px, 28vw, 280px)",
              maxWidth: "100%",
              height: "auto",
              borderRadius: t.radius.md,
            }}
          />
        )}
      />
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
            <span className={`${shadcn.buttonVariants({ variant: "outline", size: "sm" })} pointer-events-none cursor-default`}>
              {prompt}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
