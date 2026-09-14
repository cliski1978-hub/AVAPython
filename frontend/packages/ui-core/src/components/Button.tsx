import { type CSSProperties, type ReactNode } from "react";
import { defaultTheme } from "../theme";
import { useInteraction } from "../hooks/useInteraction";
import { LoadingIndicator } from "./LoadingIndicator";

export type ButtonVariant =
  | "default"
  | "primary"
  | "secondary"
  | "danger"
  | "ghost";

export interface ButtonProps {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  loading?: boolean;
  type?: "button" | "submit" | "reset";
  variant?: ButtonVariant;
  ariaLabel?: string;
  title?: string;
  /** Communicates pressed (active) state for toggle-style buttons. */
  ariaPressed?: boolean;
}

const t = defaultTheme;

interface VariantStyle {
  base: CSSProperties;
  hover: CSSProperties;
}

const variants: Record<ButtonVariant, VariantStyle> = {
  default: {
    base: {
      background: t.colors.background,
      color: t.colors.foreground,
      borderColor: t.colors.borderStrong,
    },
    hover: { background: t.colors.surface },
  },
  primary: {
    base: {
      background: t.colors.primary,
      color: t.colors.onPrimary,
      borderColor: t.colors.primary,
    },
    hover: { background: t.colors.primaryHover },
  },
  secondary: {
    base: {
      background: t.colors.surface,
      color: t.colors.foreground,
      borderColor: t.colors.borderStrong,
    },
    hover: { borderColor: t.colors.primary, color: t.colors.primary },
  },
  danger: {
    base: {
      background: t.colors.danger,
      color: t.colors.onPrimary,
      borderColor: t.colors.danger,
    },
    hover: { background: t.colors.dangerHover },
  },
  ghost: {
    base: {
      background: "transparent",
      color: t.colors.foreground,
      borderColor: "transparent",
    },
    hover: { background: t.colors.ghostHover },
  },
};

export function Button({
  children,
  onClick,
  disabled = false,
  loading = false,
  type = "button",
  variant = "default",
  ariaLabel,
  title,
  ariaPressed,
}: ButtonProps) {
  const interactive = !disabled && !loading;
  const interaction = useInteraction(interactive);
  const variantStyle = variants[variant];

  const style: CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    gap: t.spacing.sm,
    height: t.control.height,
    padding: `0 ${t.spacing.lg}px`,
    borderRadius: t.control.radius,
    borderWidth: t.border.width,
    borderStyle: "solid",
    borderColor: variantStyle.base.borderColor,
    fontSize: t.control.fontSize,
    fontWeight: t.font.weightSemibold,
    fontFamily: t.font.family,
    cursor: interactive ? "pointer" : "not-allowed",
    outline: "none",
    boxSizing: "border-box",
    transition:
      "background 120ms ease, border-color 120ms ease, color 120ms ease, box-shadow 120ms ease",
    ...variantStyle.base,
    ...(interaction.hovered ? variantStyle.hover : {}),
    ...(interaction.focused
      ? { boxShadow: `0 0 0 2px ${t.colors.focusRing}33` }
      : {}),
    ...(interactive
      ? {}
      : {
          background: t.colors.disabledBg,
          color: t.colors.disabledText,
          borderColor: t.colors.border,
        }),
  };

  return (
    <button
      type={type}
      style={style}
      onClick={onClick}
      disabled={disabled || loading}
      aria-label={ariaLabel}
      aria-busy={loading || undefined}
      aria-disabled={disabled || loading || undefined}
      aria-pressed={ariaPressed ?? undefined}
      data-variant={variant}
      title={title}
      onMouseEnter={interaction.onMouseEnter}
      onMouseLeave={interaction.onMouseLeave}
      onFocus={interaction.onFocus}
      onBlur={interaction.onBlur}
    >
      {loading && <LoadingIndicator size="sm" />}
      <span>{children}</span>
    </button>
  );
}