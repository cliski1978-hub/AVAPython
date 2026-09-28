// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Checkbox } from "./Checkbox";
import { Input } from "./Input";
import { Select } from "./Select";

afterEach(cleanup);

describe("Select", () => {
  const options = [
    { value: "acme", label: "acme" },
    { value: "openai", label: "openai" },
  ];

  it("renders a label, options, and the controlled value", () => {
    render(
      <Select label="Provider type" value="openai" onChange={() => {}} options={options} />,
    );

    const select = screen.getByLabelText("Provider type") as HTMLSelectElement;
    expect(select.value).toBe("openai");
    expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "acme",
      "openai",
    ]);
  });

  it("associates the label with the control", () => {
    render(<Select label="Provider type" value="" onChange={() => {}} options={options} />);

    // getByLabelText throws unless the association resolves to the control.
    expect(screen.getByLabelText("Provider type").tagName).toBe("SELECT");
  });

  it("reports the newly chosen value", () => {
    const chosen: string[] = [];
    render(
      <Select
        label="Provider type"
        value=""
        onChange={(value) => chosen.push(value)}
        options={options}
        placeholder="Choose…"
      />,
    );

    fireEvent.change(screen.getByLabelText("Provider type"), {
      target: { value: "acme" },
    });
    expect(chosen).toEqual(["acme"]);
  });

  it("is disabled when disabled", () => {
    render(
      <Select
        label="Provider type"
        value="acme"
        onChange={() => {}}
        options={options}
        disabled
      />,
    );

    expect((screen.getByLabelText("Provider type") as HTMLSelectElement).disabled).toBe(
      true,
    );
  });

  it("exposes help text and validation error through aria-describedby", () => {
    const { rerender } = render(
      <Select
        label="Provider type"
        value=""
        onChange={() => {}}
        options={options}
        helpText="Installed provider types."
      />,
    );
    const select = screen.getByLabelText("Provider type");
    const describedBy = select.getAttribute("aria-describedby");
    expect(describedBy).not.toBeNull();
    expect(document.getElementById(describedBy!)?.textContent).toBe(
      "Installed provider types.",
    );
    expect(select.getAttribute("aria-invalid")).toBeNull();

    rerender(
      <Select
        label="Provider type"
        value=""
        onChange={() => {}}
        options={options}
        error="Choose or enter a provider type."
      />,
    );
    expect(screen.getByLabelText("Provider type").getAttribute("aria-invalid")).toBe(
      "true",
    );
    expect(screen.getByText("Choose or enter a provider type.")).toBeTruthy();
  });

  it("renders a disabled placeholder option", () => {
    render(
      <Select
        label="Provider type"
        value=""
        onChange={() => {}}
        options={options}
        placeholder="Choose a provider type…"
      />,
    );
    const placeholder = within(
      screen.getByLabelText("Provider type"),
    ).getByRole("option", { name: "Choose a provider type…" }) as HTMLOptionElement;
    expect(placeholder.disabled).toBe(true);
  });
});

describe("Checkbox", () => {
  it("renders a label bound to a checkbox input", () => {
    render(<Checkbox label="Enabled" checked onChange={() => {}} />);

    const box = screen.getByLabelText("Enabled") as HTMLInputElement;
    expect(box.type).toBe("checkbox");
    expect(box.checked).toBe(true);
  });

  it("reports the toggled state", () => {
    const changes: boolean[] = [];
    render(<Checkbox label="Enabled" checked={false} onChange={(v) => changes.push(v)} />);

    fireEvent.click(screen.getByLabelText("Enabled"));
    expect(changes).toEqual([true]);
  });

  it("is disabled when disabled", () => {
    const changes: boolean[] = [];
    render(
      <Checkbox
        label="Enabled"
        checked={false}
        disabled
        onChange={(v) => changes.push(v)}
      />,
    );

    // The `disabled` attribute is the guarantee: the browser refuses pointer and
    // keyboard activation of a disabled control, so the handler cannot run.
    // (`fireEvent` dispatches directly and bypasses that, so it is not used
    // here to "prove" suppression.)
    expect((screen.getByLabelText("Enabled") as HTMLInputElement).disabled).toBe(true);
    expect(changes).toEqual([]);
  });

  it("exposes help text through aria-describedby", () => {
    render(
      <Checkbox
        label="Enabled"
        checked
        onChange={() => {}}
        helpText="Not an access setting."
      />,
    );
    const box = screen.getByLabelText("Enabled");
    const describedBy = box.getAttribute("aria-describedby");
    expect(describedBy).not.toBeNull();
    expect(document.getElementById(describedBy!)?.textContent).toBe(
      "Not an access setting.",
    );
  });
});

describe("Input", () => {
  it("keeps a readOnly value visible and out of reach of edits", () => {
    render(
      <Input
        label="Connection ID"
        value="acme-production"
        readOnly
        onChange={() => {}}
      />,
    );

    const input = screen.getByLabelText("Connection ID") as HTMLInputElement;
    expect(input.value).toBe("acme-production");
    // readOnly rather than disabled: the value is real and stays focusable and
    // selectable so it can be read and copied, while the browser refuses edits.
    // The attribute is the enforcement point, so it is what is asserted.
    expect(input.readOnly).toBe(true);
    expect(input.disabled).toBe(false);
    input.focus();
    expect(document.activeElement).toBe(input);
  });

  it("still reports edits when it is not readOnly", () => {
    const changes: string[] = [];
    render(
      <Input label="Display name" value="" onChange={(value) => changes.push(value)} />,
    );

    fireEvent.change(screen.getByLabelText("Display name"), {
      target: { value: "A" },
    });
    expect(changes).toEqual(["A"]);
  });

  it("marks an invalid field and shows the error", () => {
    render(
      <Input
        label="Display name"
        value=""
        onChange={() => {}}
        error="A display name is required."
      />,
    );

    const input = screen.getByLabelText("Display name");
    expect(input.getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByText("A display name is required.")).toBeTruthy();
  });
});
