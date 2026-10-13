import { isTemplateId } from "../templates";
import { isThemeName } from "../themes";
import { isFontFamilyId } from "./fonts";
import {
  DEFAULT_APPEARANCE_PREFERENCES,
  type AppearancePreferences,
  type ThemeMode,
} from "./types";

export const APPEARANCE_STORAGE_KEYS = {
  templateId: "ava.appearance.template",
  themeName: "ava.appearance.theme",
  themeMode: "ava.appearance.mode",
  fontFamily: "ava.appearance.font-family",
  fontSize: "ava.appearance.font-size",
} as const;

const isThemeMode = (value: string | null): value is ThemeMode =>
  value === "system" || value === "light" || value === "dark";

function browserStorage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

/** Read each preference independently; inaccessible or malformed storage is safe. */
export function readAppearancePreferences(
  storage: Storage | null = browserStorage(),
): AppearancePreferences {
  if (storage == null) return { ...DEFAULT_APPEARANCE_PREFERENCES };

  try {
    const templateId = storage.getItem(APPEARANCE_STORAGE_KEYS.templateId);
    const themeName = storage.getItem(APPEARANCE_STORAGE_KEYS.themeName);
    const themeMode = storage.getItem(APPEARANCE_STORAGE_KEYS.themeMode);
    const fontFamily = storage.getItem(APPEARANCE_STORAGE_KEYS.fontFamily);
    const fontSize = Number(storage.getItem(APPEARANCE_STORAGE_KEYS.fontSize));
    return {
      templateId: isTemplateId(templateId)
        ? templateId
        : DEFAULT_APPEARANCE_PREFERENCES.templateId,
      themeName: isThemeName(themeName)
        ? themeName
        : DEFAULT_APPEARANCE_PREFERENCES.themeName,
      themeMode: isThemeMode(themeMode)
        ? themeMode
        : DEFAULT_APPEARANCE_PREFERENCES.themeMode,
      fontFamily: isFontFamilyId(fontFamily)
        ? fontFamily
        : DEFAULT_APPEARANCE_PREFERENCES.fontFamily,
      fontSize: Number.isInteger(fontSize) && fontSize >= 12 && fontSize <= 20
        ? fontSize
        : DEFAULT_APPEARANCE_PREFERENCES.fontSize,
    };
  } catch {
    return { ...DEFAULT_APPEARANCE_PREFERENCES };
  }
}

/** Persist the preference values, never their resolved system appearance. */
export function writeAppearancePreferences(
  preferences: AppearancePreferences,
  storage: Storage | null = browserStorage(),
): void {
  if (storage == null) return;
  try {
    storage.setItem(APPEARANCE_STORAGE_KEYS.templateId, preferences.templateId);
    storage.setItem(APPEARANCE_STORAGE_KEYS.themeName, preferences.themeName);
    storage.setItem(APPEARANCE_STORAGE_KEYS.themeMode, preferences.themeMode);
    storage.setItem(APPEARANCE_STORAGE_KEYS.fontFamily, preferences.fontFamily);
    storage.setItem(APPEARANCE_STORAGE_KEYS.fontSize, String(preferences.fontSize));
  } catch {
    // Appearance is a preference; blocked storage must not prevent startup.
  }
}
