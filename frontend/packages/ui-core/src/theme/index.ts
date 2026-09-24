export interface ThemeTokens {
  colors: {
    background: string;
    surface: string;
    foreground: string;
    mutedText: string;
    border: string;
    borderStrong: string;
    primary: string;
    primaryHover: string;
    primaryActive: string;
    onPrimary: string;
    danger: string;
    dangerHover: string;
    dangerText: string;
    ghostHover: string;
    disabledBg: string;
    disabledText: string;
    focusRing: string;
    success: string;
    warning: string;
    error: string;
    working: string;
    neutral: string;
  };
  spacing: {
    unit: number;
    xs: number;
    sm: number;
    md: number;
    lg: number;
    xl: number;
  };
  radius: {
    sm: number;
    md: number;
    lg: number;
  };
  border: {
    width: number;
  };
  font: {
    family: string;
    sizeXs: number;
    sizeSm: number;
    sizeMd: number;
    weightNormal: number;
    weightSemibold: number;
    weightBold: number;
  };
  control: {
    height: number;
    fontSize: number;
    radius: number;
  };
}

export const defaultTheme: ThemeTokens = {
  colors: {
    background: "#ffffff",
    surface: "#f9fafb",
    foreground: "#111827",
    mutedText: "#6b7280",
    border: "#e5e7eb",
    borderStrong: "#d1d5db",
    primary: "#2563eb",
    primaryHover: "#1d4ed8",
    primaryActive: "#1e40af",
    onPrimary: "#ffffff",
    danger: "#dc2626",
    dangerHover: "#b91c1c",
    dangerText: "#dc2626",
    ghostHover: "#f3f4f6",
    disabledBg: "#f3f4f6",
    disabledText: "#4b5563",
    focusRing: "#2563eb",
    success: "#16a34a",
    warning: "#f59e0b",
    error: "#dc2626",
    working: "#2563eb",
    neutral: "#9ca3af",
  },
  spacing: {
    unit: 8,
    xs: 4,
    sm: 8,
    md: 12,
    lg: 16,
    xl: 24,
  },
  radius: {
    sm: 4,
    md: 6,
    lg: 8,
  },
  border: {
    width: 1,
  },
  font: {
    family: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
    sizeXs: 12,
    sizeSm: 13,
    sizeMd: 14,
    weightNormal: 400,
    weightSemibold: 600,
    weightBold: 700,
  },
  control: {
    height: 36,
    fontSize: 14,
    radius: 6,
  },
};