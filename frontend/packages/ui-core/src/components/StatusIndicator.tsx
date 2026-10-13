import { defaultTheme } from "../theme";
import { LoadingIndicator } from "./LoadingIndicator";

export type StatusState =
  | "neutral"
  | "success"
  | "warning"
  | "error"
  | "working";

export interface StatusIndicatorProps {
  state: StatusState;
  /** Display label. Application-specific text lives at the call site. */
  label: string;
  showLabel?: boolean;
}

const t = defaultTheme;

export function statusColor(state: StatusState): string {
  switch (state) {
    case "success":
      return t.colors.success;
    case "warning":
      return t.colors.warning;
    case "error":
      return t.colors.error;
    case "working":
      return t.colors.working;
    case "neutral":
      return t.colors.neutral;
  }
}

export function StatusIndicator({
  state,
  label,
  showLabel = true,
}: StatusIndicatorProps) {
  return (
    <span
      data-status-state={state}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: t.spacing.sm,
        fontSize: t.font.sizeSm,
      }}
      className="text-muted-foreground"
    >
      {state === "working" ? (
        <LoadingIndicator size="sm" />
      ) : (
        <span
          aria-hidden="true"
          style={{
            display: "inline-block",
            width: 8,
            height: 8,
            borderRadius: "999px",
            background: statusColor(state),
            flexShrink: 0,
          }}
        />
      )}
      {showLabel && <span>{label}</span>}
    </span>
  );
}
