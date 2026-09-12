/** AVA theme definitions. */

export interface ThemeTokens {
  colors: {
    background: string;
    foreground: string;
    primary: string;
    muted: string;
  };
  spacing: {
    unit: number;
  };
}

export const defaultTheme: ThemeTokens = {
  colors: {
    background: "#ffffff",
    foreground: "#111111",
    primary: "#2563eb",
    muted: "#6b7280",
  },
  spacing: {
    unit: 8,
  },
};
