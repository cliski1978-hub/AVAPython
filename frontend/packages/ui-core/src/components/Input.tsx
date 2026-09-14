import { useId, type CSSProperties } from "react";
import { defaultTheme } from "../theme";
import { useInteraction } from "../hooks/useInteraction";

export interface InputProps {
  value?: string;
  onChange?: (value: string) => void;
  placeholder?: string;
  disabled?: boolean;
  label?: string;
  ariaLabel?: string;
  type?: "text" | "search" | "email" | "password";
}

const t = defaultTheme;

export function Input({
  value,
  onChange,
  placeholder,
  disabled = false,
  label,
  ariaLabel,
  type = "text",
}: InputProps) {
  const interaction = useInteraction(!disabled);
  const id = useId();

  const controlStyle: CSSProperties = {
    height: t.control.height,
    padding: `0 ${t.spacing.md}px`,
    fontSize: t.control.fontSize,
    fontFamily: t.font.family,
    color: t.colors.foreground,
    background: disabled ? t.colors.disabledBg : t.colors.background,
    borderWidth: t.border.width,
    borderStyle: "solid",
    borderColor: t.colors.borderStrong,
    borderRadius: t.control.radius,
    outline: "none",
    boxSizing: "border-box",
    width: "100%",
    transition:
      "border-color 120ms ease, box-shadow 120ms ease, background 120ms ease",
    ...(interaction.hovered
      ? { borderColor: t.colors.primary }
      : {}),
    ...(interaction.focused
      ? {
          borderColor: t.colors.primary,
          boxShadow: `0 0 0 2px ${t.colors.focusRing}33`,
        }
      : {}),
    ...(disabled ? { color: t.colors.disabledText } : {}),
  };

  const input = (
    <input
      id={label != null ? id : undefined}
      type={type}
      value={value}
      placeholder={placeholder}
      disabled={disabled}
      aria-label={ariaLabel}
      style={controlStyle}
      onChange={onChange != null ? (e) => onChange(e.target.value) : undefined}
      onMouseEnter={interaction.onMouseEnter}
      onMouseLeave={interaction.onMouseLeave}
      onFocus={interaction.onFocus}
      onBlur={interaction.onBlur}
    />
  );

  if (label == null) {
    return input;
  }

  return (
    <label
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "flex-start",
        gap: t.spacing.xs,
        width: "100%",
      }}
    >
      <span
        style={{
          fontSize: t.font.sizeXs,
          fontWeight: t.font.weightSemibold,
          color: t.colors.mutedText,
        }}
      >
        {label}
      </span>
      {input}
    </label>
  );
}