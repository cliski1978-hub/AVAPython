import {
  EmptyState,
  LoadingIndicator,
  defaultTheme,
  useInteraction,
} from "@ava/ui-core";
import type { CSSProperties, ReactNode } from "react";

/**
 * Loading, error, and empty presentations shared by every Settings section.
 *
 * These are the only three state components the Settings surface has. A
 * provider section and a defaults section that each invented their own
 * spinner and error box would drift, so sections compose these instead.
 *
 * All three keep the section's own heading and navigation intact: they render
 * inside the section body and never replace the Settings shell. That is what
 * stops a slow or failing request from destroying the page.
 *
 * Spinner and empty presentation reuse `@ava/ui-core` primitives rather than
 * restyling them locally.
 */

const t = defaultTheme;

const centered: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  alignItems: "center",
  justifyContent: "center",
  gap: t.spacing.md,
  minHeight: 120,
  padding: t.spacing.lg,
  boxSizing: "border-box",
};

export interface SettingsLoadingProps {
  /** Describes what is loading; also announced to assistive technology. */
  label: string;
}

export function SettingsLoading({ label }: SettingsLoadingProps) {
  return (
    <div data-testid="settings-loading" style={centered}>
      <LoadingIndicator label={label} />
    </div>
  );
}

function RetryButton({ label, onClick }: { label: string; onClick: () => void }) {
  const interaction = useInteraction(true);

  const style: CSSProperties = {
    height: t.control.height,
    padding: `0 ${t.spacing.lg}px`,
    borderRadius: t.control.radius,
    borderWidth: t.border.width,
    borderStyle: "solid",
    borderColor: t.colors.borderStrong,
    background: t.colors.background,
    color: t.colors.foreground,
    fontSize: t.control.fontSize,
    fontWeight: t.font.weightSemibold,
    fontFamily: t.font.family,
    cursor: "pointer",
    outline: "none",
    ...(interaction.hovered
      ? { borderColor: t.colors.primary, color: t.colors.primary }
      : {}),
    ...(interaction.focused
      ? { boxShadow: `0 0 0 2px ${t.colors.focusRing}33` }
      : {}),
  };

  return (
    <button
      type="button"
      onClick={onClick}
      style={style}
      onMouseEnter={interaction.onMouseEnter}
      onMouseLeave={interaction.onMouseLeave}
      onFocus={interaction.onFocus}
      onBlur={interaction.onBlur}
    >
      {label}
    </button>
  );
}

export interface SettingsErrorProps {
  /** Already sanitized by settingsErrorMessage. */
  message: string;
  onRetry: () => void;
  /** Describes the retry for assistive technology, e.g. "Retry loading providers". */
  retryLabel?: string;
}

export function SettingsError({
  message,
  onRetry,
  retryLabel = "Retry",
}: SettingsErrorProps) {
  return (
    <div
      role="alert"
      data-testid="settings-error"
      style={{ ...centered, textAlign: "center" }}
    >
      <p
        style={{
          margin: 0,
          maxWidth: 420,
          color: t.colors.foreground,
          fontSize: t.font.sizeSm,
          lineHeight: 1.6,
        }}
      >
        {message}
      </p>
      <RetryButton label={retryLabel} onClick={onRetry} />
    </div>
  );
}

export interface SettingsEmptyProps {
  title: string;
  description?: string;
  children?: ReactNode;
}

export function SettingsEmpty({
  title,
  description,
  children,
}: SettingsEmptyProps) {
  return (
    <div data-testid="settings-empty" style={centered}>
      <EmptyState title={title} description={description} action={children} />
    </div>
  );
}
