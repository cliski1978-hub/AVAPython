import { describe, expect, it } from "vitest";

import { defaultTheme } from "./index";

function luminance(hex: string): number {
  const raw = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(raw.slice(i, i + 2), 16) / 255);
  const channel = (c: number) =>
    c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  const [lr, lg, lb] = [r, g, b].map(channel);
  return 0.2126 * lr + 0.7152 * lg + 0.0722 * lb;
}

function contrastRatio(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

describe("default theme", () => {
  it("exposes coherent theme tokens", () => {
    expect(defaultTheme.colors).toBeDefined();
    expect(defaultTheme.colors.background).toBe("#ffffff");
    expect(defaultTheme.spacing.unit).toBeGreaterThan(0);
  });

  it("keeps disabled foreground readable against the disabled background", () => {
    const ratio = contrastRatio(
      defaultTheme.colors.disabledText,
      defaultTheme.colors.disabledBg,
    );
    expect(ratio).toBeGreaterThanOrEqual(4.5);
  });

  it("keeps the primary foreground readable on primary and danger fills", () => {
    expect(
      contrastRatio(defaultTheme.colors.onPrimary, defaultTheme.colors.primary),
    ).toBeGreaterThanOrEqual(4.5);
    expect(
      contrastRatio(defaultTheme.colors.onPrimary, defaultTheme.colors.danger),
    ).toBeGreaterThanOrEqual(4.5);
  });
});