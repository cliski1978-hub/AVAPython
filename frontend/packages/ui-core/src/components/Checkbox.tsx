import { useId, type CSSProperties } from "react";
import { defaultTheme } from "../theme";
import { useInteraction } from "../hooks/useInteraction";

/**
 * A labelled checkbox for boolean configuration.
 *
 * The whole row is the label, so the accessible name is the visible text and
 * clicking the text toggles the control. The native input is kept in the
 * accessibility tree (not replaced by a styled `div` or a `role="switch"`
 * custom widget) so keyboard, screen-reader, and form semantics stay correct.
 *
 * This is a checkbox, not a switch: use it for plain on/off configuration.
 */

export interface CheckboxProps {
  /** Controlled checked state. */
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  disabled?: boolean;
  /** Guidance shown beside/below the label and linked via aria-describedby. */
  helpText?: string;
  /** Overrides the accessible name when no visible label is desired. */
  ariaLabel?: string;
  id?: string;
}

const t = defaultTheme;

export function Checkbox({
  checked,
  onChange,
  label,
  disabled = false,
  helpText,
  ariaLabel,
  id,
}: CheckboxProps) {
  const interaction = useInteraction(!disabled);
  const generatedId = useId();
  const inputId = id ?? generatedId;
  const helpId = `${inputId}-help`;

  const rowStyle: CSSProperties = {
    display: "flex",
    alignItems: "flex-start",
    gap: t.spacing.md,
    cursor: disabled ? "not-allowed" : "pointer",
    opacity: disabled ? 0.6 : 1,
  };

  const boxStyle: CSSProperties = {
    width: 16,
    height: 16,
    margin: 0,
    flex: "0 0 auto",
    accentColor: t.colors.primary,
    cursor: disabled ? "not-allowed" : "pointer",
    outline: "none",
    ...(!disabled && interaction.focused
      ? { boxShadow: `0 0 0 2px ${t.colors.focusRing}66` }
      : {}),
  };

  const textStyle: CSSProperties = {
    display: "flex",
    flexDirection: "column",
    gap: 2,
  };

  // The label element contains only the label text; the help text is a sibling
  // linked with aria-describedby. Clicking the label still toggles the box,
  // because htmlFor associates it.
  return (
    <div style={rowStyle}>
      <input
        id={inputId}
        type="checkbox"
        checked={checked}
        disabled={disabled}
        aria-label={ariaLabel}
        aria-describedby={helpText != null ? helpId : undefined}
        style={boxStyle}
        onChange={(event) => onChange(event.target.checked)}
        onFocus={interaction.onFocus}
        onBlur={interaction.onBlur}
      />
      <span style={textStyle}>
        <label
          htmlFor={inputId}
          style={{
            fontSize: t.font.sizeSm,
            fontWeight: t.font.weightSemibold,
            color: "hsl(var(--foreground))",
            lineHeight: 1.4,
          }}
        >
          {label}
        </label>
        {helpText != null && (
          <span
            id={helpId}
            style={{ fontSize: t.font.sizeXs, color: "hsl(var(--muted-foreground))", lineHeight: 1.5 }}
          >
            {helpText}
          </span>
        )}
      </span>
    </div>
  );
}
