import { type CSSProperties, type ReactNode } from "react";
import { defaultTheme } from "../theme";
import { useInteraction } from "../hooks/useInteraction";

export interface IconButtonProps {
  /** Required for accessibility. Describes the button's action for AT. */
  ariaLabel: string;
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  /** Native tooltip text. */
  title?: string;
  size?: "sm" | "md";
  /** Communicates pressed (active) state for toggle-style buttons. */
  ariaPressed?: boolean;
}

const t = defaultTheme;

export function IconButton({
  ariaLabel,
  children,
  onClick,
  disabled = false,
  title,
  size = "md",
  ariaPressed,
}: IconButtonProps) {
  const interaction = useInteraction(!disabled);
  const dimension = size === "sm" ? 24 : 32;

  const style: CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    width: dimension,
    height: dimension,
    borderRadius: t.radius.sm,
    border: "none",
    background: ariaPressed ? t.colors.ghostHover : "transparent",
    color: ariaPressed ? t.colors.primary : t.colors.mutedText,
    cursor: disabled ? "not-allowed" : "pointer",
    outline: "none",
    flexShrink: 0,
    transition:
      "background 120ms ease, color 120ms ease, box-shadow 120ms ease",
    ...(interaction.hovered
      ? { background: t.colors.ghostHover, color: t.colors.foreground }
      : {}),
    ...(interaction.focused
      ? { boxShadow: `0 0 0 2px ${t.colors.focusRing}33` }
      : {}),
    ...(disabled ? { color: t.colors.disabledText } : {}),
  };

  return (
    <button
      type="button"
      style={style}
      onClick={onClick}
      disabled={disabled}
      aria-label={ariaLabel}
      aria-pressed={ariaPressed ?? undefined}
      title={title}
      onMouseEnter={interaction.onMouseEnter}
      onMouseLeave={interaction.onMouseLeave}
      onFocus={interaction.onFocus}
      onBlur={interaction.onBlur}
    >
      {children}
    </button>
  );
}