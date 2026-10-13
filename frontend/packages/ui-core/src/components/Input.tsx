import { useId, type CSSProperties } from "react";
import { defaultTheme } from "../theme";
import { useInteraction } from "../hooks/useInteraction";

export interface InputProps {
  value?: string;
  onChange?: (value: string) => void;
  placeholder?: string;
  disabled?: boolean;
  /**
   * Value is shown but not editable. Distinct from `disabled`: a read-only
   * field still displays real data and still submits, whereas a disabled field
   * is presented as unavailable. Use this for a value the domain owns and the
   * user must not change.
   */
  readOnly?: boolean;
  label?: string;
  ariaLabel?: string;
  type?: "text" | "search" | "email" | "password" | "number";
  /** Guidance shown below the control and associated via aria-describedby. */
  helpText?: string;
  /** Validation message. Replaces the help text and sets aria-invalid. */
  error?: string;
}

const t = defaultTheme;

export function Input({
  value,
  onChange,
  placeholder,
  disabled = false,
  readOnly = false,
  label,
  ariaLabel,
  type = "text",
  helpText,
  error,
}: InputProps) {
  const interaction = useInteraction(!disabled);
  const id = useId();
  const messageId = `${id}-message`;
  const hasMessage = error != null || helpText != null;
  const interactive = !disabled && !readOnly;

  const controlStyle: CSSProperties = {
    height: t.control.height,
    padding: `0 ${t.spacing.md}px`,
    fontSize: t.control.fontSize,
    fontFamily: t.font.family,
    color: t.colors.foreground,
    background: disabled || readOnly ? t.colors.disabledBg : t.colors.background,
    borderWidth: t.border.width,
    borderStyle: "solid",
    borderColor: error != null ? t.colors.error : t.colors.borderStrong,
    borderRadius: t.control.radius,
    outline: "none",
    boxSizing: "border-box",
    width: "100%",
    transition:
      "border-color 120ms ease, box-shadow 120ms ease, background 120ms ease",
    ...(interactive && interaction.hovered ? { borderColor: t.colors.primary } : {}),
    ...(interactive && interaction.focused
      ? {
          borderColor: t.colors.primary,
          boxShadow: `0 0 0 2px ${t.colors.focusRing}33`,
        }
      : {}),
    ...(disabled ? { color: t.colors.disabledText } : {}),
    ...(readOnly ? { color: t.colors.disabledText, cursor: "default" } : {}),
  };

  const input = (
    <input
      id={label != null ? id : undefined}
      type={type}
      value={value}
      placeholder={placeholder}
      disabled={disabled}
      readOnly={readOnly}
      aria-label={ariaLabel}
      aria-invalid={error != null ? true : undefined}
      aria-describedby={hasMessage ? messageId : undefined}
      style={controlStyle}
      onChange={onChange != null ? (e) => onChange(e.target.value) : undefined}
      onMouseEnter={interaction.onMouseEnter}
      onMouseLeave={interaction.onMouseLeave}
      onFocus={interaction.onFocus}
      onBlur={interaction.onBlur}
    />
  );

  const message =
    error != null || helpText != null ? (
      <span
        id={messageId}
        style={{
          fontSize: t.font.sizeXs,
          color: error != null ? t.colors.error : t.colors.mutedText,
          lineHeight: 1.5,
        }}
      >
        {error ?? helpText}
      </span>
    ) : null;

  if (label == null) {
    return (
      <>
        {input}
        {message}
      </>
    );
  }

  // The label element holds only the label text. Help and error text sit
  // outside it and are linked with aria-describedby, so a screen reader
  // announces the field's name as "Display name" rather than "Display name
  // How this connection appears in Settings".
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "stretch",
        gap: t.spacing.xs,
        width: "100%",
      }}
    >
      <label
        htmlFor={id}
        style={{
          fontSize: t.font.sizeXs,
          fontWeight: t.font.weightSemibold,
          color: t.colors.mutedText,
        }}
      >
        {label}
      </label>
      {input}
      {message}
    </div>
  );
}
