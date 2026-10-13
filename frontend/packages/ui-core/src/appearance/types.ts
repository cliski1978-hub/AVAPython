import type { TemplateId } from "../templates";
import type { ThemeName } from "../themes";

export type { TemplateId } from "../templates";
export type { ThemeName } from "../themes";

export type ThemeMode = "system" | "light" | "dark";
export type ResolvedThemeMode = "light" | "dark";
export type FontFamilyId =
  | "system"
  | "lato"
  | "noto-serif"
  | "noto-sans"
  | "dejavu-sans"
  | "liberation-serif";

export interface AppearancePreferences {
  templateId: TemplateId;
  themeName: ThemeName;
  themeMode: ThemeMode;
  fontFamily: FontFamilyId;
  fontSize: number;
}

export interface AppearanceStatus extends AppearancePreferences {
  resolvedThemeMode: ResolvedThemeMode;
}

export const DEFAULT_APPEARANCE_PREFERENCES: AppearancePreferences = {
  templateId: "ava-default",
  themeName: "ava",
  themeMode: "system",
  fontFamily: "system",
  fontSize: 14,
};
