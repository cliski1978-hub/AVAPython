import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { useSettingsForm, type SettingsFormErrors } from "./useSettingsForm";

/**
 * The shared submit lifecycle. The provider and model editors exercise it
 * through their own flows; these tests pin the behaviour those two do not
 * isolate — the ordering of validate and send, error clearing on edit, and the
 * busy guard.
 */

interface Values {
  name: string;
  count: number;
}

function Harness({
  validate,
  perform,
}: {
  validate: (values: Values) => SettingsFormErrors<Values>;
  perform: (values: Values) => Promise<void>;
}) {
  const [saved, setSaved] = useState(0);
  const [closed, setClosed] = useState(0);
  const form = useSettingsForm<Values>({
    initial: { name: "", count: 0 },
    validate,
    perform,
    onSaved: () => setSaved((count) => count + 1),
    onClose: () => setClosed((count) => count + 1),
    fallbackMessage: "Could not save.",
  });

  return (
    <div>
      <input
        aria-label="name"
        value={form.values.name}
        onChange={(event) => form.set("name", event.target.value)}
      />
      {form.errors.name != null && <span role="alert">{form.errors.name}</span>}
      <span data-testid="submit-error">{form.submitError ?? ""}</span>
      <span data-testid="busy">{String(form.busy)}</span>
      <button
        type="button"
        disabled={form.busy}
        onClick={() => void form.save()}
      >
        Save
      </button>
      <button type="button" onClick={form.requestClose}>
        Cancel
      </button>
      <span data-testid="saved">{String(saved)}</span>
      <span data-testid="closed">{String(closed)}</span>
    </div>
  );
}

describe("useSettingsForm", () => {
  it("validates before sending anything", async () => {
    const perform = vi.fn().mockResolvedValue(undefined);
    render(
      <Harness
        validate={() => ({ name: "Required." })}
        perform={perform}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(perform).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toBe("Required.");
  });

  it("clears a field's error when that field is edited", async () => {
    render(
      <Harness
        validate={() => ({ name: "Required." })}
        perform={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByRole("alert")).toBeTruthy();

    fireEvent.change(screen.getByLabelText("name"), { target: { value: "a" } });
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("refuses a second save while one is in flight, then reports success once", async () => {
    let release!: () => void;
    const perform = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          release = resolve;
        }),
    );
    render(
      <Harness
        validate={() => ({})}
        perform={perform}
      />,
    );

    const save = screen.getByRole("button", { name: "Save" });
    fireEvent.click(save);
    expect(screen.getByTestId("busy").textContent).toBe("true");
    expect((save as HTMLButtonElement).disabled).toBe(true);

    // A second click while the first is in flight issues no second write.
    fireEvent.click(save);
    expect(perform).toHaveBeenCalledTimes(1);

    // Dismissal is refused mid-flight so a pending write is not discarded.
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByTestId("closed").textContent).toBe("0");

    await act(async () => {
      release();
    });

    await waitFor(() => expect(screen.getByTestId("busy").textContent).toBe("false"));
    expect(screen.getByTestId("saved").textContent).toBe("1");
  });

  it("maps a thrown value to the fallback sentence and stays open", async () => {
    const onClosed = { current: 0 };
    function Throwing() {
      const form = useSettingsForm<Values>({
        initial: { name: "", count: 0 },
        validate: () => ({}),
        perform: () => Promise.reject(new Error("secret detail at db.py:12")),
        onSaved: vi.fn(),
        onClose: () => {
          onClosed.current += 1;
        },
        fallbackMessage: "Could not save.",
      });
      return (
        <div>
          <span data-testid="submit-error">{form.submitError ?? ""}</span>
          <button type="button" onClick={() => void form.save()}>
            Save
          </button>
        </div>
      );
    }
    render(<Throwing />);

    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await act(async () => {
      await Promise.resolve();
    });

    expect(screen.getByTestId("submit-error").textContent).toBe("Could not save.");
    expect(onClosed.current).toBe(0);
  });
});
