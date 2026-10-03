import { defaultTheme, useInteraction } from "@ava/ui-core";
import type { SettingsSectionId } from "@ava/ui-core";
import type { CSSProperties } from "react";

/**
 * Section navigation for the Settings area.
 *
 * Uses the same segmented `role="tablist"` pattern as the application's
 * workspace tabs, rather than introducing router or sidebar machinery. There
 * is no router in this frontend — view selection is a state enum in
 * `AppWorkspace` — so nested routes would have been a second navigation
 * framework to maintain for four panels.
 *
 * Every section is a real tab: `role="tab"` with `aria-selected` and
 * `aria-controls`, and each body is a `role="tabpanel"`. That gives
 * assistive technology the selected state and the relationship between control
 * and content without inventing anything.
 */

export type { SettingsSectionId } from "@ava/ui-core";

export interface SettingsSectionDefinition {
  id: SettingsSectionId;
  label: string;
  /** Sentence describing what this section will show. */
  summary: string;
}

export const SETTINGS_SECTIONS: SettingsSectionDefinition[] = [
  {
    id: "providers",
    label: "Providers",
    summary: "Provider connections, including their credential references.",
  },
  {
    id: "models",
    label: "Models",
    summary: "Models bound to a provider connection.",
  },
  {
    id: "runtimes",
    label: "Runtimes",
    summary: "Configured runtime adapter kinds.",
  },
  {
    id: "defaults",
    label: "Defaults",
    summary: "The provider connection, model, and runtime AVA uses by default.",
  },
  {
    id: "system-prompts",
    label: "System Prompts",
    summary: "Reusable CORE prompt definitions and explicit scope assignments.",
  },
];

export const DEFAULT_SETTINGS_SECTION: SettingsSectionId = "providers";

export const settingsSectionPanelId = (id: SettingsSectionId) =>
  `settings-section-${id}`;

const t = defaultTheme;

export interface SettingsSectionNavProps {
  active: SettingsSectionId;
  onSelect: (section: SettingsSectionId) => void;
}

function SectionTab({
  section,
  selected,
  onSelect,
}: {
  section: SettingsSectionDefinition;
  selected: boolean;
  onSelect: () => void;
}) {
  const interaction = useInteraction(true);

  const style: CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    height: 30,
    padding: `0 ${t.spacing.md}px`,
    borderRadius: t.radius.md,
    borderWidth: t.border.width,
    borderStyle: "solid",
    borderColor: "transparent",
    background: selected ? t.colors.surface : "transparent",
    color: selected ? t.colors.primary : t.colors.mutedText,
    fontWeight: selected ? t.font.weightSemibold : t.font.weightNormal,
    fontSize: t.font.sizeSm,
    fontFamily: t.font.family,
    cursor: "pointer",
    outline: "none",
    boxSizing: "border-box",
    transition: "background 120ms ease, color 120ms ease, box-shadow 120ms ease",
    ...(interaction.hovered && !selected
      ? { background: t.colors.ghostHover, color: t.colors.foreground }
      : {}),
    ...(interaction.focused
      ? { boxShadow: `0 0 0 2px ${t.colors.focusRing}33` }
      : {}),
  };

  return (
    <button
      type="button"
      role="tab"
      aria-selected={selected}
      aria-controls={settingsSectionPanelId(section.id)}
      style={style}
      title={section.summary}
      onClick={onSelect}
      onMouseEnter={interaction.onMouseEnter}
      onMouseLeave={interaction.onMouseLeave}
      onFocus={interaction.onFocus}
      onBlur={interaction.onBlur}
    >
      {section.label}
    </button>
  );
}

export function SettingsSectionNav({ active, onSelect }: SettingsSectionNavProps) {
  return (
    <div
      role="tablist"
      aria-label="Settings sections"
      style={{
        display: "flex",
        alignItems: "center",
        gap: t.spacing.xs,
        flexWrap: "wrap",
      }}
    >
      {SETTINGS_SECTIONS.map((section) => (
        <SectionTab
          key={section.id}
          section={section}
          selected={active === section.id}
          onSelect={() => onSelect(section.id)}
        />
      ))}
    </div>
  );
}
