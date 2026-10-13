import type { ApiClient } from "@ava/api-client";
import { AppearanceModeSelector, defaultTheme, FontFamilyRegistry, useAppearance } from "@ava/ui-core";
import { useState, type CSSProperties, type ReactNode } from "react";

import { ToolFeaturesSection } from "../sections/ToolFeaturesSection";
import { WorkspaceAccessSection } from "../sections/WorkspaceAccessSection";
import { ExecutionDefaultsSection } from "../sections/ExecutionDefaultsSection";
import { ModelConfigurationsSection } from "../sections/ModelConfigurationsSection";
import { ProviderConnectionsSection } from "../sections/ProviderConnectionsSection";
import { RuntimeConfigurationsSection } from "../sections/RuntimeConfigurationsSection";
import { SystemPromptsSection } from "../sections/SystemPromptsSection";
import {
  DEFAULT_SETTINGS_SECTION,
  SettingsSectionNav,
  settingsSectionPanelId,
  type SettingsSectionId,
} from "./SettingsSectionNav";

/**
 * The Settings area: a shared surface composed by both Web and Desktop.
 *
 * The shell (heading, section navigation, section frame) is rendered
 * unconditionally and only the section body is data-driven, so a loading,
 * failed, or empty section never removes the navigation the user needs to
 * leave. That is the whole reason the shell and the body are separate.
 *
 * Section selection is local state, stable and directly testable: the four
 * sections have no route, no URL, and no cross-component coordination, so a
 * test can assert the selected tab and the rendered panel without a router.
 *
 * Every section is read-only in Phase 5.11. No create, edit, enable, or
 * delete control is rendered — a dead button that looks like a feature is
 * worse than no button, and the management phases will add real actions
 * behind modals.
 *
 * Configuration here is *persisted settings* (`/settings/*`). Discovery
 * endpoints are a different concept and are not used as a source of truth
 * here; a section never merges the two.
 */

export interface SettingsWorkspaceProps {
  client: ApiClient;
  /** Initial section, for tests and deep links added later. */
  initialSection?: SettingsSectionId;
  /** Renders an open Settings modal, owned by the host that provides it. */
  children?: ReactNode;
}

const t = defaultTheme;

function sectionBody(
  section: SettingsSectionId,
  client: ApiClient,
): ReactNode {
  switch (section) {
    case "features-tools": return <ToolFeaturesSection client={client} />;
    case "workspace-access": return <WorkspaceAccessSection client={client} />;
    case "providers":
      return <ProviderConnectionsSection client={client} />;
    case "models":
      return <ModelConfigurationsSection client={client} />;
    case "runtimes":
      return <RuntimeConfigurationsSection client={client} />;
    case "defaults":
      return <ExecutionDefaultsSection client={client} />;
    case "system-prompts":
      return <SystemPromptsSection client={client} />;
    case "appearance":
      return <AppearanceSettingsSection />;
  }
}

function AppearanceSettingsSection() {
  const appearance = useAppearance();
  const foreground = "hsl(var(--foreground))";
  const mutedForeground = "hsl(var(--muted-foreground))";
  return (
    <section aria-label="Appearance settings" style={{ display: "flex", flexDirection: "column", gap: 12, maxWidth: 420 }}>
      <div>
        <h3 style={{ margin: 0, color: foreground }}>Mode</h3>
        <p style={{ margin: "4px 0 12px", color: mutedForeground }}>Choose light, dark, or follow your system setting.</p>
        <AppearanceModeSelector />
      </div>
      <div style={{ display: "grid", gap: 8 }}>
        <label htmlFor="appearance-font-family" style={{ color: foreground, fontWeight: 600 }}>Font</label>
        <select
          id="appearance-font-family"
          aria-label="Font family"
          value={appearance.fontFamily}
          onChange={(event) => appearance.setFontFamily(event.currentTarget.value as typeof appearance.fontFamily)}
          className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm text-foreground shadow-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {Object.entries(FontFamilyRegistry).map(([id, font]) => (
            <option key={id} value={id}>{font.label}</option>
          ))}
        </select>
      </div>
      <div style={{ display: "grid", gap: 8 }}>
        <label htmlFor="appearance-font-size" style={{ color: foreground, fontWeight: 600 }}>Font size</label>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <input
            id="appearance-font-size"
            aria-label="Font size"
            type="range"
            min={12}
            max={20}
            step={1}
            value={appearance.fontSize}
            onChange={(event) => appearance.setFontSize(Number(event.currentTarget.value))}
            className="min-w-0 flex-1 accent-primary"
          />
          <output htmlFor="appearance-font-size" aria-live="polite" style={{ minWidth: 46, color: foreground, textAlign: "right" }}>
            {appearance.fontSize} px
          </output>
        </div>
        <p style={{ margin: 0, color: mutedForeground, fontSize: "calc(12px * var(--ava-font-scale, 1))" }}>Adjust text size without changing layout spacing.</p>
      </div>
      <p aria-live="polite" style={{ margin: 0, color: mutedForeground }}>
        Current appearance: {appearance.themeMode} ({appearance.resolvedThemeMode})
      </p>
    </section>
  );
}

export function SettingsWorkspace({
  client,
  initialSection = DEFAULT_SETTINGS_SECTION,
  children,
}: SettingsWorkspaceProps) {
  const [section, setSection] = useState<SettingsSectionId>(initialSection);

  const rootStyle: CSSProperties = {
    flex: 1,
    display: "flex",
    flexDirection: "column",
    overflow: "auto",
    minWidth: 0,
    background: "hsl(var(--background))",
    color: "hsl(var(--foreground))",
  };

  const headerStyle: CSSProperties = {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: t.spacing.md,
    padding: `${t.spacing.lg}px ${t.spacing.xl}px`,
    borderBottom: `${t.border.width}px solid hsl(var(--border))`,
    flexShrink: 0,
  };

  const bodyStyle: CSSProperties = {
    display: "flex",
    flexDirection: "column",
    gap: t.spacing.lg,
    padding: t.spacing.xl,
    flex: 1,
  };

  return (
    <div
      data-testid="settings-workspace"
      style={rootStyle}
      aria-label="Settings"
    >
      <div style={headerStyle}>
        <h2
          style={{
            margin: 0,
            fontSize: t.font.sizeMd,
            fontWeight: t.font.weightSemibold,
            color: "hsl(var(--foreground))",
          }}
        >
          Settings
        </h2>
        <SettingsSectionNav active={section} onSelect={setSection} />
      </div>

      <div style={bodyStyle}>
        <div
          role="tabpanel"
          id={settingsSectionPanelId(section)}
          aria-label={section}
          style={{ display: "flex", flexDirection: "column" }}
        >
          {sectionBody(section, client)}
        </div>
      </div>

      {children}
    </div>
  );
}
