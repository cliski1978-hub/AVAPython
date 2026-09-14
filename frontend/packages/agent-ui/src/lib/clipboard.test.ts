import { afterEach, describe, expect, it, vi } from "vitest";

import { copyTextToClipboard } from "./clipboard";

const originalNavigator = globalThis.navigator;

afterEach(() => {
  Object.defineProperty(globalThis, "navigator", {
    value: originalNavigator,
    configurable: true,
  });
});

describe("copyTextToClipboard", () => {
  it("copies text when the clipboard API is available", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(globalThis, "navigator", {
      value: { clipboard: { writeText } },
      configurable: true,
    });

    const ok = await copyTextToClipboard("hello");
    expect(ok).toBe(true);
    expect(writeText).toHaveBeenCalledWith("hello");
  });

  it("reports false (without throwing) when the API is unavailable", async () => {
    Object.defineProperty(globalThis, "navigator", {
      value: {},
      configurable: true,
    });

    await expect(copyTextToClipboard("hello")).resolves.toBe(false);
  });

  it("reports false when the write fails", async () => {
    const writeText = vi.fn().mockRejectedValue(new Error("denied"));
    Object.defineProperty(globalThis, "navigator", {
      value: { clipboard: { writeText } },
      configurable: true,
    });

    await expect(copyTextToClipboard("hello")).resolves.toBe(false);
  });
});