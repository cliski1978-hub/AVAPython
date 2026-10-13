import { defaultTheme } from "../theme";

export interface LoadingIndicatorProps {
  label?: string;
  size?: "sm" | "md";
}

const t = defaultTheme;

const SPIN_KEYFRAMES = "@keyframes ava-spin { to { transform: rotate(360deg); } }";

export function LoadingIndicator({
  label,
  size = "md",
}: LoadingIndicatorProps) {
  const dimension = size === "sm" ? 14 : 20;

  return (
    <span
      role="status"
      aria-label={label ?? "Loading"}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: t.spacing.sm,
      }}
      className="text-muted-foreground"
    >
      <style>{SPIN_KEYFRAMES}</style>
      <span
        aria-hidden="true"
        style={{
          display: "inline-block",
          width: dimension,
          height: dimension,
          borderWidth: 2,
          borderStyle: "solid",
          borderColor: "hsl(var(--border))",
          borderTopColor: "hsl(var(--primary))",
          borderRadius: "50%",
          boxSizing: "border-box",
          animation: "ava-spin 0.8s linear infinite",
        }}
      />
      {label != null && <span>{label}</span>}
    </span>
  );
}
