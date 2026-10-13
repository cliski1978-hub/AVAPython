// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Modal } from "./Modal";

// This is the first ui-core test that mounts into a document rather than
// rendering to static markup, so it unmounts and unlocks scroll itself
// instead of relying on a package-wide setup file.
afterEach(() => {
  cleanup();
  document.body.style.overflow = "";
});

describe("Modal", () => {
  it("uses semantic foreground and surface tokens for Dark mode", () => {
    const { getByRole } = render(
      <Modal open title="Theme check" onClose={() => {}}>
        <p>Dialog content</p>
      </Modal>,
    );
    const dialog = getByRole("dialog");
    expect(dialog.style.background).toBe("hsl(var(--background))");
    expect(dialog.style.color).toBe("hsl(var(--foreground))");
    expect(dialog.querySelector("h2")?.getAttribute("style")).toContain("foreground");
  });

  it("renders nothing when closed and its dialog when open", () => {
    const { rerender } = render(
      <Modal open={false} title="Add Provider" onClose={() => {}}>
        <input aria-label="Display name" />
      </Modal>,
    );
    expect(screen.queryByRole("dialog")).toBeNull();

    rerender(
      <Modal open title="Add Provider" onClose={() => {}}>
        <input aria-label="Display name" />
      </Modal>,
    );
    expect(screen.getByRole("dialog", { name: "Add Provider" })).toBeTruthy();
  });

  it("exposes dialog semantics to assistive technology", () => {
    render(
      <Modal open title="Edit Model" onClose={() => {}}>
        <input aria-label="Display name" />
      </Modal>,
    );
    const dialog = screen.getByRole("dialog", { name: "Edit Model" });
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(dialog.getAttribute("aria-labelledby")).toBeTruthy();
  });

  it("closes via Escape without a mouse", () => {
    const onClose = vi.fn();
    render(
      <Modal open title="Add Runtime" onClose={onClose}>
        <input aria-label="Display name" />
      </Modal>,
    );

    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("closes via the standard close affordance", () => {
    const onClose = vi.fn();
    render(
      <Modal open title="Add Runtime" onClose={onClose}>
        <input aria-label="Display name" />
      </Modal>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Close dialog" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("closes via the cancel action", () => {
    const onClose = vi.fn();
    const onSecondary = vi.fn();
    render(
      <Modal
        open
        title="Edit Defaults"
        onClose={onClose}
        onSecondaryAction={onSecondary}
        secondaryAction="Cancel"
        primaryAction="Save"
      >
        <input aria-label="Default model" />
      </Modal>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onSecondary).toHaveBeenCalledTimes(1);
  });

  it("closes on overlay click but not on dialog body click", () => {
    const onClose = vi.fn();
    render(
      <Modal open title="Add Provider" onClose={onClose}>
        <input aria-label="Display name" />
      </Modal>,
    );

    fireEvent.click(screen.getByRole("dialog"));
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId("modal-overlay"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("renders a busy primary action as disabled and busy", () => {
    render(
      <Modal
        open
        title="Add Provider"
        onClose={() => {}}
        primaryAction="Save"
        primaryBusy
      >
        <input aria-label="Display name" />
      </Modal>,
    );

    const primary = screen.getByRole("button", { name: "Save" });
    expect(primary.hasAttribute("disabled")).toBe(true);
    expect(primary.getAttribute("aria-busy")).toBe("true");
  });

  it("renders a disabled primary action", () => {
    render(
      <Modal
        open
        title="Add Provider"
        onClose={() => {}}
        primaryAction="Save"
        primaryDisabled
      >
        <input aria-label="Display name" />
      </Modal>,
    );

    expect(
      screen.getByRole("button", { name: "Save" }).hasAttribute("disabled"),
    ).toBe(true);
  });

  it("calls the primary action", () => {
    const onPrimaryAction = vi.fn();
    render(
      <Modal
        open
        title="Add Provider"
        onClose={() => {}}
        primaryAction="Save"
        onPrimaryAction={onPrimaryAction}
      >
        <input aria-label="Display name" />
      </Modal>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(onPrimaryAction).toHaveBeenCalledTimes(1);
  });

  it("renders the caller body content, including a validation error slot", () => {
    render(
      <Modal open title="Add Provider" onClose={() => {}}>
        <input aria-label="Display name" />
        <p role="alert">Display name is required.</p>
      </Modal>,
    );

    expect(screen.getByLabelText("Display name")).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toBe("Display name is required.");
  });

  it("moves focus into the dialog on open and restores it on close", () => {
    function Harness() {
      const [open, setOpen] = useState(false);
      return (
        <div>
          <button type="button" onClick={() => setOpen(true)}>
            Open trigger
          </button>
          <Modal open={open} title="Add Provider" onClose={() => setOpen(false)}>
            <input aria-label="Display name" />
          </Modal>
        </div>
      );
    }

    render(<Harness />);
    const trigger = screen.getByRole("button", { name: "Open trigger" });
    trigger.focus();
    expect(document.activeElement).toBe(trigger);

    fireEvent.click(trigger);

    // Focus entered the dialog rather than being left behind on the trigger.
    // It lands on the first control in DOM order, which is the close button in
    // the header; the body field is one Tab away.
    const dialog = screen.getByRole("dialog", { name: "Add Provider" });
    expect(dialog.contains(document.activeElement)).toBe(true);
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: "Close dialog" }),
    );

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();

    // Focus returned to the element that opened it.
    expect(document.activeElement).toBe(trigger);
  });

  it("traps Tab inside the dialog", () => {
    render(
      <Modal
        open
        title="Add Provider"
        onClose={() => {}}
        secondaryAction="Cancel"
        primaryAction="Save"
      >
        <input aria-label="Display name" />
      </Modal>,
    );

    const dialog = screen.getByRole("dialog");
    const focusable = Array.from(
      dialog.querySelectorAll<HTMLElement>(
        "button:not([disabled]), input:not([disabled])",
      ),
    );
    const last = focusable[focusable.length - 1];
    last.focus();
    expect(document.activeElement).toBe(last);

    // Tab from the last focusable element wraps back to the first.
    fireEvent.keyDown(document, { key: "Tab" });
    expect(document.activeElement).toBe(focusable[0]);
  });

  it("locks background scroll while open and restores it on close", () => {
    const { rerender } = render(
      <Modal open={false} title="Add Provider" onClose={() => {}}>
        <input aria-label="Display name" />
      </Modal>,
    );
    expect(document.body.style.overflow).toBe("");

    rerender(
      <Modal open title="Add Provider" onClose={() => {}}>
        <input aria-label="Display name" />
      </Modal>,
    );
    expect(document.body.style.overflow).toBe("hidden");

    rerender(
      <Modal open={false} title="Add Provider" onClose={() => {}}>
        <input aria-label="Display name" />
      </Modal>,
    );
    expect(document.body.style.overflow).toBe("");
  });
});
