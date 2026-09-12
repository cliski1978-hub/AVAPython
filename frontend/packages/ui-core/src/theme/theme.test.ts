import { describe, expect, it } from "vitest";

import { defaultTheme } from "./index";

describe("default theme", () => {
  it("exposes coherent theme tokens", () => {
    expect(defaultTheme.colors).toBeDefined();
    expect(defaultTheme.colors.background).toBe("#ffffff");
    expect(defaultTheme.spacing.unit).toBeGreaterThan(0);
  });
});