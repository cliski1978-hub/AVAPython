import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { readAppearancePreferences, writeAppearancePreferences } from "./persistence";
import type {
  AppearancePreferences,
  ResolvedThemeMode,
  TemplateId,
  ThemeMode,
  ThemeName,
  FontFamilyId,
} from "./types";
import { FontFamilyRegistry } from "./fonts";

export interface AppearanceContextValue extends AppearancePreferences {
  resolvedThemeMode: ResolvedThemeMode;
  setTemplateId: (templateId: TemplateId) => void;
  setThemeName: (themeName: ThemeName) => void;
  setThemeMode: (themeMode: ThemeMode) => void;
  setFontFamily: (fontFamily: FontFamilyId) => void;
  setFontSize: (fontSize: number) => void;
}

const AppearanceContext = createContext<AppearanceContextValue | null>(null);

function readSystemMode(): ResolvedThemeMode {
  try {
    return typeof window !== "undefined" &&
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  } catch {
    return "light";
  }
}

export function AppearanceProvider({ children }: { children: ReactNode }) {
  const [preferences, setPreferences] = useState<AppearancePreferences>(
    readAppearancePreferences,
  );
  const [systemMode, setSystemMode] = useState<ResolvedThemeMode>(readSystemMode);
  const resolvedThemeMode =
    preferences.themeMode === "system" ? systemMode : preferences.themeMode;

  const setTemplateId = useCallback((templateId: TemplateId) => {
    setPreferences((current) => ({ ...current, templateId }));
  }, []);
  const setThemeName = useCallback((themeName: ThemeName) => {
    setPreferences((current) => ({ ...current, themeName }));
  }, []);
  const setThemeMode = useCallback((themeMode: ThemeMode) => {
    setPreferences((current) => ({ ...current, themeMode }));
  }, []);
  const setFontFamily = useCallback((fontFamily: FontFamilyId) => {
    setPreferences((current) => ({ ...current, fontFamily }));
  }, []);
  const setFontSize = useCallback((fontSize: number) => {
    setPreferences((current) => ({ ...current, fontSize }));
  }, []);

  useEffect(() => {
    writeAppearancePreferences(preferences);
  }, [preferences]);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return;
    }
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const update = (event: MediaQueryListEvent | MediaQueryList) => {
      setSystemMode(event.matches ? "dark" : "light");
    };
    update(query);
    query.addEventListener?.("change", update);
    return () => query.removeEventListener?.("change", update);
  }, []);

  useLayoutEffect(() => {
    if (typeof document === "undefined") return;
    const root = document.documentElement;
    root.dataset.template = preferences.templateId;
    root.dataset.theme = preferences.themeName;
    root.dataset.fontFamily = preferences.fontFamily;
    root.style.setProperty("--ava-font-family", FontFamilyRegistry[preferences.fontFamily].family);
    root.style.setProperty("--ava-font-scale", String(preferences.fontSize / 14));
    root.classList.toggle("dark", resolvedThemeMode === "dark");
  }, [preferences.templateId, preferences.themeName, preferences.fontFamily, preferences.fontSize, resolvedThemeMode]);

  const value = useMemo<AppearanceContextValue>(
    () => ({
      ...preferences,
      resolvedThemeMode,
      setTemplateId,
      setThemeName,
      setThemeMode,
      setFontFamily,
      setFontSize,
    }),
    [preferences, resolvedThemeMode, setTemplateId, setThemeName, setThemeMode, setFontFamily, setFontSize],
  );

  return <AppearanceContext.Provider value={value}>{children}</AppearanceContext.Provider>;
}

export function useAppearance(): AppearanceContextValue {
  const value = useContext(AppearanceContext);
  if (value == null) {
    throw new Error("useAppearance must be used within an AppearanceProvider");
  }
  return value;
}
