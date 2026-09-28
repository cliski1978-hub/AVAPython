import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { SettingsModal, type SettingsModalState } from "./SettingsModal";

/**
 * Modal foundation tests.
 *
 * The harness below is exactly the ownership pattern the management phases
 * will use: local `useState` in the section that opened the dialog, no store,
 * no modal manager. Phase 5.11 ships the pattern with no domain consumer, so
 * proving it works means driving it the way 5.12-5.15 will.
 */

function Harness({
  initial,
  onSubmit,
}: {
  initial?: SettingsModalState;
  onSubmit?: (state: SettingsModalState) => void;
}) {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<SettingsModalState>(initial ?? "idle");
  const [error, setError] = useState<string | null>(null);

  return (
    <div>
      <button type="button" onClick={() => setOpen(true)}>
        Add Provider
      </button>
      <SettingsModal
        open={open}
        title="Add Provider"
        primaryAction="Create"
        onPrimaryAction={() => {
          setError("Provider connection already exists.");
          setState("busy");
          onSubmit?.(state);
        }}
        onClose={() => setOpen(false)}
        error={error}
        primaryBusy={state === "busy"}
      >
        <label htmlFor="display-name">Display name</label>
        <input id="display-name" aria-label="Display name" />
      </SettingsModal>
    </div>
  );
}

function openDialog() {
  fireEvent.click(screen.getByRole("button", { name: "Add Provider" }));
  return screen.getByRole("dialog", { name: "Add Provider" });
}

describe("SettingsModal", () => {
  it("opens from local section state", () => {
    render(<Harness />);
    expect(screen.queryByRole("dialog")).toBeNull();

    openDialog();
    expect(screen.getByRole("dialog", { name: "Add Provider" })).toBeTruthy();
  });

  it("closes via the cancel action", () => {
    render(<Harness />);
    openDialog();

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("closes via the standard close affordance", () => {
    render(<Harness />);
    openDialog();

    fireEvent.click(screen.getByRole("button", { name: "Close dialog" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("closes with the keyboard, without a mouse", () => {
    render(<Harness />);
    openDialog();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("exposes modal semantics and moves focus inside", () => {
    render(<Harness />);
    const dialog = openDialog();

    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(dialog.getAttribute("aria-labelledby")).toBeTruthy();
    expect(dialog.contains(document.activeElement)).toBe(true);
  });

  it("renders a body slot for future form fields", () => {
    render(<Harness />);
    openDialog();

    expect(screen.getByLabelText("Display name")).toBeTruthy();
  });

  it("renders the validation/error area as an alert", () => {
    render(<Harness />);
    openDialog();

    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    const alert = screen.getByTestId("settings-modal-error");
    expect(alert.getAttribute("role")).toBe("alert");
    expect(alert.textContent).toBe("Provider connection already exists.");
  });

  it("shows no error area until there is an error", () => {
    render(<Harness />);
    openDialog();

    expect(screen.queryByTestId("settings-modal-error")).toBeNull();
  });

  it("supports a busy primary action", () => {
    render(<Harness initial="busy" />);
    openDialog();

    const primary = screen.getByRole("button", { name: "Create" });
    expect(primary.getAttribute("aria-busy")).toBe("true");
    expect(primary.hasAttribute("disabled")).toBe(true);
  });

  it("supports a disabled primary action", () => {
    render(<Harness />);
    openDialog();

    // The harness has no disabled state, so assert the prop is honoured by
    // rendering the primitive directly.
    render(
      <SettingsModal
        open
        title="Edit Model"
        primaryAction="Save"
        primaryDisabled
        onClose={() => {}}
      >
        <input aria-label="Display name" />
      </SettingsModal>,
    );

    const saveButtons = screen.getAllByRole("button", { name: "Save" });
    expect(saveButtons[0].hasAttribute("disabled")).toBe(true);
  });

  it("moves focus into the dialog on open and restores focus on close", async () => {
    render(<Harness />);
    const trigger = screen.getByRole("button", { name: "Add Provider" });
    trigger.focus();

    fireEvent.click(trigger);

    // Focus enters the dialog on its first control in DOM order, which is the
    // close affordance in the header. One Tab then reaches the first field.
    const dialog = screen.getByRole("dialog", { name: "Add Provider" });
    await waitFor(() => {
      expect(dialog.contains(document.activeElement)).toBe(true);
    });
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: "Close dialog" }),
    );

    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => {
      expect(document.activeElement).toBe(trigger);
    });
  });

  it("uses only the one shared dialog primitive", () => {
    // Guard against a second modal system creeping into Settings: the wrapper
    // must compose @ava/ui-core's Modal, not a bespoke overlay.
    render(<Harness />);
    openDialog();

    // ui-core's Modal marks its backdrop with this testid.
    expect(screen.getByTestId("modal-overlay")).toBeTruthy();
  });

  it("reports the primary action to the caller", () => {
    const onSubmit = vi.fn();
    render(<Harness onSubmit={onSubmit} />);
    openDialog();

    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    expect(onSubmit).toHaveBeenCalledWith("idle");
  });
});
