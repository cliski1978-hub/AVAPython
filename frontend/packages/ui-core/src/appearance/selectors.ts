import { TemplateRegistry } from "../templates";
import { ThemeRegistry } from "../themes";
import type { AppearanceStatus } from "./types";

export function selectAppearanceLabels(status: AppearanceStatus) {
  return {
    templateLabel: TemplateRegistry[status.templateId].label,
    themeLabel: ThemeRegistry[status.themeName].label,
    modeLabel: status.themeMode[0].toUpperCase() + status.themeMode.slice(1),
    resolvedModeLabel:
      status.resolvedThemeMode[0].toUpperCase() + status.resolvedThemeMode.slice(1),
  };
}
