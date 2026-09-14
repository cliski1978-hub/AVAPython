import { useId, type KeyboardEvent, type CSSProperties } from "react";
import { defaultTheme } from "../theme";
import { useInteraction } from "../hooks/useInteraction";

export interface TextareaProps {
  value?: string;
  onChange?: (value: string) => void;
  onKeyDown?: (event: KeyboardEvent<HTMLTextAreaElement>) => void;
  placeholder?: string;
  disabled?: boolean;
  readOnly?: boolean;
  rows?: number;
  label?: string;
  ariaLabel?: string;
}

const t = defaultTheme;

export function Textarea({
  value,
  onChange,
  onKeyDown,
  placeholder,
  disabled = false,
  readOnly = false,
  rows = 3,
  label,
  ariaLabel,
}: TextareaProps) {
  const interaction = useInteraction(!disabled && !readOnly);
  const id = useId();

  const controlStyle: CSSProperties = {
    minHeight: "44px",
    padding: `${t.spacing.sm}px ${t.spacing.md}px`,
    fontSize: t.control.fontSize,
    fontFamily: t.font.family,
    color: t.colors.foreground,
    background:
      disabled || readOnly ? t.colors.disabledBg : t.colors.background,
    borderWidth: t.border.width,
    borderStyle: "solid",
    borderColor: t.colors.borderStrong,
    borderRadius: t.control.radius,
    outline: "none",
    boxSizing: "border-box",
    width: "100%",
    resize: "none",
    lineHeight: 1.5,
    transition:
      "border-color 120ms ease, box-shadow 120ms ease, background 120ms ease",
    ...(interaction.hovered ? { borderColor: t.colors.primary } : {}),
    ...(interaction.focused
      ? {
          borderColor: t.colors.primary,
          boxShadow: `0 0 0 2px ${t.colors.focusRing}33`,
        }
      : {}),
    ...(disabled || readOnly ? { color: t.colors.disabledText } : {}),
  };

  const textarea = (
    <textarea
      id={label != null ? id : undefined}
      value={value}
      placeholder={placeholder}
      disabled={disabled}
      readOnly={readOnly}
      rows={rows}
      aria-label={ariaLabel}
      style={controlStyle}
      onChange={onChange != null ? (e) => onChange(e.target.value) : undefined}
      onKeyDown={onKeyDown}
      onMouseEnter={interaction.onMouseEnter}
      onMouseLeave={interaction.onMouseLeave}
      onFocus={interaction.onFocus}
      onBlur={interaction.onBlur}
    />
  );

  if (label == null) {
    return textarea;
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
      {textarea}
    </label>
  );
}