// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { AppShell } from "./AppShell";

const STORAGE_KEY = "ava.ui.sidebar-width";

function renderShell() {
  return render(
    <AppShell sidebarChildren={<p>Conversations</p>} mainContent={<p>Main</p>} />,
  );
}

function sidebarWidth(): number {
  return Number(screen.getByRole("complementary", { name: "Conversation sidebar" }).getAttribute("style")?.match(/width: (\d+)px/)?.[1]);
}

function dragDividerTo(clientX: number) {
  const divider = screen.getByRole("separator", { name: "Resize conversation sidebar" });
  fireEvent.pointerDown(divider, { button: 0, clientX: sidebarWidth(), pointerId: 1 });
  fireEvent.pointerMove(divider, { clientX, pointerId: 1 });
  fireEvent.pointerUp(divider, { clientX, pointerId: 1 });
}

beforeEach(() => {
  localStorage.clear();
  window.innerWidth = 1024;
  if (window.PointerEvent == null) {
    Object.defineProperty(window, "PointerEvent", { configurable: true, value: window.MouseEvent });
  }
});

afterEach(() => cleanup());

describe("AppShell sidebar resize", () => {
  it("preserves the existing default width and resizes within the minimum and maximum", () => {
    renderShell();
    expect(sidebarWidth()).toBe(272);
    expect(screen.getByRole("complementary", { name: "Conversation sidebar" }).querySelector(".overflow-x-hidden")).not.toBeNull();

    dragDividerTo(430);
    expect(sidebarWidth()).toBe(430);
    expect(screen.getByRole("separator", { name: "Resize conversation sidebar" }).getAttribute("aria-valuenow")).toBe("430");

    dragDividerTo(700);
    expect(sidebarWidth()).toBe(500);

    dragDividerTo(100);
    expect(sidebarWidth()).toBe(240);
  });

  it("restores a saved width and persists changes for the next app mount", () => {
    localStorage.setItem(STORAGE_KEY, "360");
    const first = renderShell();
    expect(sidebarWidth()).toBe(360);

    dragDividerTo(410);
    expect(localStorage.getItem(STORAGE_KEY)).toBe("410");
    first.unmount();

    renderShell();
    expect(sidebarWidth()).toBe(410);
  });

  it("supports keyboard resizing on the accessible separator", () => {
    renderShell();
    const divider = screen.getByRole("separator", { name: "Resize conversation sidebar" });
    fireEvent.keyDown(divider, { key: "ArrowRight" });
    expect(sidebarWidth()).toBe(288);
    expect(divider.getAttribute("aria-valuenow")).toBe("288");
    expect(localStorage.getItem(STORAGE_KEY)).toBe("288");
  });
});
