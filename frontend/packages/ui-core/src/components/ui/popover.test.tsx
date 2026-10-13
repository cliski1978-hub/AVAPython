// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Popover, PopoverContent, PopoverTrigger } from "./popover";
import { Button } from "./button";

describe("shared Popover", () => {
  it("provides an accessible non-modal surface with Escape and outside dismissal", () => {
    render(
      <>
        <Popover>
          <PopoverTrigger asChild>
            <Button aria-label="Open settings">Settings</Button>
          </PopoverTrigger>
          <PopoverContent aria-label="Execution settings">Controls</PopoverContent>
        </Popover>
        <button type="button">Outside</button>
      </>,
    );

    const trigger = screen.getByRole("button", { name: "Open settings" });
    expect(trigger.getAttribute("aria-haspopup")).toBe("dialog");
    fireEvent.click(trigger);
    expect(screen.getByRole("dialog", { name: "Execution settings" })).toBeTruthy();
    expect(trigger.getAttribute("aria-expanded")).toBe("true");

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Execution settings" })).toBeNull();
    expect(document.activeElement).toBe(trigger);

    fireEvent.click(trigger);
    fireEvent.pointerDown(screen.getByRole("button", { name: "Outside" }));
    expect(screen.queryByRole("dialog", { name: "Execution settings" })).toBeNull();
  });
});
