// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, beforeEach, afterEach, vi } from "vitest";

import { DesignSystemPreview } from "../components/ava/DesignSystemPreview";
import { AppearanceProvider, useAppearance } from "./AppearanceProvider";
import { AppearanceModeSelector } from "./AppearanceModeSelector";
import { APPEARANCE_STORAGE_KEYS } from "./persistence";
import { TemplateRegistry, isTemplateId } from "../templates";
import { ThemeRegistry, isThemeName } from "../themes";

function StateProbe() {
  const value = useAppearance();
  return <div>
    <output data-testid="state">{`${value.templateId}|${value.themeName}|${value.themeMode}|${value.resolvedThemeMode}|${value.fontFamily}|${value.fontSize}`}</output>
    <button onClick={() => value.setThemeMode("dark")}>Set dark</button>
    <button onClick={() => value.setThemeMode("system")}>Set system</button>
    <button onClick={() => value.setThemeName("ava")}>Set theme</button>
    <button onClick={() => value.setFontFamily("lato")}>Set Lato</button>
    <button onClick={() => value.setFontSize(18)}>Set large text</button>
  </div>;
}

describe("AppearanceProvider", () => {
  beforeEach(() => {
    HTMLElement.prototype.scrollIntoView = vi.fn();
    localStorage.clear();
    document.documentElement.className = "";
    delete document.documentElement.dataset.template;
    delete document.documentElement.dataset.theme;
    delete document.documentElement.dataset.fontFamily;
    document.documentElement.style.removeProperty("--ava-font-family");
    document.documentElement.style.removeProperty("--ava-font-scale");
  });

  it("registers the initial theme and template and rejects unknown identities", () => {
    expect(ThemeRegistry.ava.label).toBe("AVA");
    expect(TemplateRegistry["ava-default"].label).toBe("AVA Default");
    expect(isThemeName("missing-theme")).toBe(false);
    expect(isTemplateId("missing-template")).toBe(false);
  });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  it("provides independent defaults and DOM markers", () => {
    render(<AppearanceProvider><StateProbe /></AppearanceProvider>);
    expect(screen.getByTestId("state").textContent).toBe("ava-default|ava|system|light|system|14");
    expect(document.documentElement.dataset.template).toBe("ava-default");
    expect(document.documentElement.dataset.theme).toBe("ava");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it("persists selected mode and restores it after remount", async () => {
    const view = render(<AppearanceProvider><StateProbe /></AppearanceProvider>);
    fireEvent.click(screen.getByText("Set dark"));
    await waitFor(() => expect(localStorage.getItem(APPEARANCE_STORAGE_KEYS.themeMode)).toBe("dark"));
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    view.unmount();
    render(<AppearanceProvider><StateProbe /></AppearanceProvider>);
    expect(screen.getByTestId("state").textContent).toBe("ava-default|ava|dark|dark|system|14");
  });

  it("persists the font family and size and restores their root appearance values", async () => {
    const view = render(<AppearanceProvider><StateProbe /></AppearanceProvider>);
    fireEvent.click(screen.getByText("Set Lato"));
    fireEvent.click(screen.getByText("Set large text"));
    await waitFor(() => {
      expect(localStorage.getItem(APPEARANCE_STORAGE_KEYS.fontFamily)).toBe("lato");
      expect(localStorage.getItem(APPEARANCE_STORAGE_KEYS.fontSize)).toBe("18");
    });
    expect(document.documentElement.dataset.fontFamily).toBe("lato");
    expect(document.documentElement.style.getPropertyValue("--ava-font-family")).toBe('"Lato", sans-serif');
    expect(document.documentElement.style.getPropertyValue("--ava-font-scale")).toBe(String(18 / 14));

    view.unmount();
    render(<AppearanceProvider><StateProbe /></AppearanceProvider>);
    expect(screen.getByTestId("state").textContent).toBe("ava-default|ava|system|light|lato|18");
  });

  it("keeps system mode stored while reflecting the current OS mode", async () => {
    localStorage.setItem(APPEARANCE_STORAGE_KEYS.themeMode, "system");
    const listeners = new Set<(event: MediaQueryListEvent) => void>();
    vi.stubGlobal("matchMedia", () => ({
      matches: false,
      media: "(prefers-color-scheme: dark)",
      addEventListener: (_: string, listener: (event: MediaQueryListEvent) => void) => listeners.add(listener),
      removeEventListener: (_: string, listener: (event: MediaQueryListEvent) => void) => listeners.delete(listener),
    }));
    render(<AppearanceProvider><StateProbe /></AppearanceProvider>);
    for (const listener of listeners) listener({ matches: true } as MediaQueryListEvent);
    await waitFor(() => expect(screen.getByTestId("state").textContent).toBe("ava-default|ava|system|dark|system|14"));
    expect(localStorage.getItem(APPEARANCE_STORAGE_KEYS.themeMode)).toBe("system");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("follows both dark and light system preference changes", async () => {
    localStorage.setItem(APPEARANCE_STORAGE_KEYS.themeMode, "system");
    let listener: ((event: MediaQueryListEvent) => void) | undefined;
    vi.stubGlobal("matchMedia", () => ({
      matches: false,
      media: "(prefers-color-scheme: dark)",
      addEventListener: (_: string, callback: (event: MediaQueryListEvent) => void) => { listener = callback; },
      removeEventListener: () => { listener = undefined; },
    }));
    render(<AppearanceProvider><StateProbe /></AppearanceProvider>);

    listener?.({ matches: true } as MediaQueryListEvent);
    await waitFor(() => {
      expect(screen.getByTestId("state").textContent).toBe("ava-default|ava|system|dark|system|14");
      expect(document.documentElement.classList.contains("dark")).toBe(true);
    });

    listener?.({ matches: false } as MediaQueryListEvent);
    await waitFor(() => {
      expect(screen.getByTestId("state").textContent).toBe("ava-default|ava|system|light|system|14");
      expect(document.documentElement.classList.contains("dark")).toBe(false);
    });
  });

  it("uses safe defaults for invalid stored values", () => {
    localStorage.setItem(APPEARANCE_STORAGE_KEYS.templateId, "missing-template");
    localStorage.setItem(APPEARANCE_STORAGE_KEYS.themeName, "missing-theme");
    localStorage.setItem(APPEARANCE_STORAGE_KEYS.themeMode, "sepia");
    localStorage.setItem(APPEARANCE_STORAGE_KEYS.fontFamily, "missing-font");
    localStorage.setItem(APPEARANCE_STORAGE_KEYS.fontSize, "99");
    render(<AppearanceProvider><StateProbe /></AppearanceProvider>);
    expect(screen.getByTestId("state").textContent).toBe("ava-default|ava|system|light|system|14");
  });

  it("lets the accessible selector choose all appearance modes", async () => {
    render(<AppearanceProvider><AppearanceModeSelector /><StateProbe /></AppearanceProvider>);
    const trigger = screen.getByRole("combobox", { name: "Appearance mode" });
    fireEvent.change(trigger, { target: { value: "light" } });
    await waitFor(() => expect(screen.getByTestId("state").textContent).toBe("ava-default|ava|light|light|system|14"));
    fireEvent.change(trigger, { target: { value: "system" } });
    await waitFor(() => expect(screen.getByTestId("state").textContent).toBe("ava-default|ava|system|light|system|14"));
    fireEvent.change(trigger, { target: { value: "dark" } });
    await waitFor(() => expect(screen.getByTestId("state").textContent).toBe("ava-default|ava|dark|dark|system|14"));
    expect(trigger.getAttribute("aria-label")).toBe("Appearance mode");
  });

  it("renders the preview and its semantic token inventory", async () => {
    render(<AppearanceProvider><DesignSystemPreview /></AppearanceProvider>);
    expect(screen.getByRole("heading", { name: "AVA Design System Preview" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Buttons" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Icon Actions" })).toBeTruthy();
    expect(screen.getByText(/AVA Button Standard/)).toBeTruthy();
    expect(screen.getByText(/AVA Action Standard/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Archive" }).querySelector("svg")).toBeTruthy();
    expect(screen.getByText("chart-5")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Open dialog" }));
    expect(screen.getByRole("dialog")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.mouseDown(screen.getByRole("tab", { name: "Second" }), { button: 0 });
    await waitFor(() => expect(screen.getByRole("tabpanel").textContent).toContain("Second tab content"));
    expect(screen.getByRole("switch", { name: "Preview switch" }).getAttribute("aria-checked")).toBe("true");
  });
});
