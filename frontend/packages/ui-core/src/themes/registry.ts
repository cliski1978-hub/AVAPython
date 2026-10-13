export const ThemeRegistry = {
  ava: {
    id: "ava",
    label: "AVA",
    description: "AVA's semantic color and typography tokens.",
  },
} as const;

export type ThemeName = keyof typeof ThemeRegistry;

export function isThemeName(value: unknown): value is ThemeName {
  return typeof value === "string" && value in ThemeRegistry;
}
