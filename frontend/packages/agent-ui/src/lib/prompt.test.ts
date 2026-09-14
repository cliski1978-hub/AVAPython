import { describe, expect, it } from "vitest";

import {
  enterShouldSubmit,
  isMeaningfulPrompt,
  rowsForPrompt,
} from "./prompt";

describe("isMeaningfulPrompt", () => {
  it("rejects an empty string", () => {
    expect(isMeaningfulPrompt("")).toBe(false);
  });

  it("rejects whitespace-only content", () => {
    expect(isMeaningfulPrompt("   ")).toBe(false);
    expect(isMeaningfulPrompt("\t\n ")).toBe(false);
  });

  it("accepts content with surrounding whitespace", () => {
    expect(isMeaningfulPrompt("  hello  ")).toBe(true);
  });
});

describe("rowsForPrompt", () => {
  it("uses a minimum of one row for a single line", () => {
    expect(rowsForPrompt("hello")).toBe(1);
  });

  it("grows with the number of lines", () => {
    expect(rowsForPrompt("a\nb")).toBe(2);
    expect(rowsForPrompt("a\nb\nc\nd")).toBe(4);
  });

  it("clamps to the minimum", () => {
    expect(rowsForPrompt("short", 2)).toBe(2);
  });

  it("clamps to the maximum so the composer cannot consume the screen", () => {
    const text = Array.from({ length: 20 }, (_, i) => `line ${i}`).join("\n");
    expect(rowsForPrompt(text, 1, 6)).toBe(6);
    expect(rowsForPrompt("a\nb\nc\nd\ne\nf\ng", 1, 6)).toBe(6);
  });
});

describe("enterShouldSubmit", () => {
  it("submits on plain Enter", () => {
    expect(enterShouldSubmit({ key: "Enter" })).toBe(true);
  });

  it("does not submit on Shift+Enter", () => {
    expect(enterShouldSubmit({ key: "Enter", shiftKey: true })).toBe(false);
  });

  it("does not submit while IME composition is active", () => {
    expect(enterShouldSubmit({ key: "Enter", isComposing: true })).toBe(false);
  });

  it("does not submit for any other key", () => {
    expect(enterShouldSubmit({ key: "a" })).toBe(false);
    expect(enterShouldSubmit({ key: "ArrowDown" })).toBe(false);
  });
});