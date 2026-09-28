import { useId, type CSSProperties } from "react";
import { defaultTheme } from "../theme";
import { useInteraction } from "../hooks/useInteraction";

/**
 * A native select styled with the AVA control language.
 *
 * Deliberately built on the platform element rather than a custom listbox: it
 * inherits keyboard behaviour, screen-reader support, and mobile pickers for
 * free, and it keeps the frontend free of another UI dependency. Styling is
 * inline, matching every other primitive in this package.
 */

export interface SelectOption {
  value: string;
  label: string;
  disabled?: boolean;
}

export interface SelectProps {
  /** Controlled value. */
  value: string;
  onChange: (value: string) => void;
  options: SelectOption[];
  label?: string;
  ariaLabel?: string;
  placeholder?: string;
  disabled?: boolean;
  /** Guidance shown below the control and associated via aria-describedby. */
  helpText?: string;
  /** Validation message. Replaces the help text and sets aria-invalid. */
  error?: string;
  /** Width of the control; defaults to filling its container. */
  width?: number | string;
}

const t = defaultTheme;

export function Select({
  value,
  onChange,
  options,
  label,
  ariaLabel,
  placeholder,
  disabled = false,
  helpText,
  error,
  width = "100%",
}: SelectProps) {
  const interaction = useInteraction(!disabled);
  const id = useId();
  const messageId = `${id}-message`;
  const hasMessage = error != null || helpText != null;

  const controlStyle: CSSProperties = {
    height: t.control.height,
    padding: `0 ${t.spacing.sm}px`,
    fontSize: t.control.fontSize,
    fontFamily: t.font.family,
    color: value === "" ? t.colors.mutedText : t.colors.foreground,
    background: disabled ? t.colors.disabledBg : t.colors.background,
    borderWidth: t.border.width,
    borderStyle: "solid",
    borderColor: error != null ? t.colors.error : t.colors.borderStrong,
    borderRadius: t.control.radius,
    outline: "none",
    boxSizing: "border-box",
    width,
    cursor: disabled ? "not-allowed" : "pointer",
    transition:
      "border-color 120ms ease, box-shadow 120ms ease, background 120ms ease",
    ...(!disabled && interaction.hovered ? { borderColor: t.colors.primary } : {}),
    ...(!disabled && interaction.focused
      ? {
          borderColor: t.colors.primary,
          boxShadow: `0 0 0 2px ${t.colors.focusRing}33`,
        }
      : {}),
    ...(disabled ? { color: t.colors.disabledText } : {}),
  };

  const select = (
    <select
      id={label != null ? id : undefined}
      value={value}
      disabled={disabled}
      aria-label={ariaLabel}
      aria-invalid={error != null ? true : undefined}
      aria-describedby={hasMessage ? messageId : undefined}
      style={controlStyle}
      onChange={(event) => onChange(event.target.value)}
      onMouseEnter={interaction.onMouseEnter}
      onMouseLeave={interaction.onMouseLeave}
      onFocus={interaction.onFocus}
      onBlur={interaction.onBlur}
    >
      {placeholder != null && (
        <option value="" disabled>
          {placeholder}
        </option>
      )}
      {options.map((option) => (
        <option
          key={option.value}
          value={option.value}
          disabled={option.disabled ?? false}
        >
          {option.label}
        </option>
      ))}
    </select>
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
        {select}
        {message}
      </>
    );
  }

  // Label text only; help and error text live outside the label element and
  // are linked with aria-describedby, so the control's accessible name is the
  // label and not the label plus its guidance.
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
      {select}
      {message}
    </div>
  );
}
