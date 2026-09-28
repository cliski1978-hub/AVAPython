import { ApiClient, ApiError } from "@ava/api-client";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SettingsWorkspace } from "../settings/SettingsWorkspace";

/**
 * Phase 5.14 runtime-configuration management.
 *
 * The domain rule under test throughout: `runtime_type` is opaque and is *not*
 * validated against registered runtimes. Most of these tests exist to pin the
 * absence of constraints — an unregistered type must be creatable, an
 * unregistered stored type must render verbatim, and nothing may coerce a type
 * into a known value. That is the opposite discipline from 5.13's closed
 * `provider_connection_id` select, and the difference is the point.
 */

const listRuntimeConfigurations = vi.fn();
const createRuntimeConfiguration = vi.fn();
const updateRuntimeConfiguration = vi.fn();
const getRuntimesMock = vi.fn();
const listModelConfigurations = vi.fn();
const listProviderConnections = vi.fn();
const listRuntimeConfigurationsForDefaults = listRuntimeConfigurations;
const getExecutionDefaults = vi.fn();

vi.mock("@ava/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@ava/api-client")>();
  return {
    ...actual,
    ApiClient: actual.ApiClient,
    ApiError: actual.ApiError,
    getRuntimes: (...args: unknown[]) => getRuntimesMock(...args),
    listRuntimeConfigurations: (...args: unknown[]) =>
      listRuntimeConfigurationsForDefaults(...args),
    createRuntimeConfiguration: (...args: unknown[]) =>
      createRuntimeConfiguration(...args),
    updateRuntimeConfiguration: (...args: unknown[]) =>
      updateRuntimeConfiguration(...args),
    listModelConfigurations: (...args: unknown[]) => listModelConfigurations(...args),
    listProviderConnections: (...args: unknown[]) => listProviderConnections(...args),
    getExecutionDefaults: (...args: unknown[]) => getExecutionDefaults(...args),
  };
});

const client = new ApiClient({ baseUrl: "http://localhost:99999" });
const contractVersion = "v1" as const;

function runtime(overrides: Record<string, unknown> = {}) {
  return {
    runtime_configuration_id: "native-primary",
    runtime_type: "native",
    display_name: "AVA Native Runtime",
    enabled: true,
    contract_version: contractVersion,
    ...overrides,
  };
}

function discovery(...ids: string[]) {
  return {
    contract_version: contractVersion,
    default_runtime_id: ids[0] ?? "",
    runtimes: ids.map((runtime_id, index) => ({
      is_default: index === 0,
      runtime_info: {
        runtime_id,
        display_name:
          runtime_id === "native"
            ? "AVA Native Runtime"
            : runtime_id === "openhands"
              ? "OpenHands"
              : null,
      },
      contract_version: contractVersion,
    })),
  };
}

function resolved<T>(value: T) {
  return Promise.resolve(value);
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

beforeEach(() => {
  vi.clearAllMocks();
  listRuntimeConfigurations.mockResolvedValue({
    runtimes: [],
    contract_version: contractVersion,
  });
  listModelConfigurations.mockResolvedValue({
    models: [],
    contract_version: contractVersion,
  });
  listProviderConnections.mockResolvedValue({
    provider_connections: [],
    contract_version: contractVersion,
  });
  getExecutionDefaults.mockResolvedValue({
    configured: false,
    defaults: null,
    contract_version: contractVersion,
  });
  getRuntimesMock.mockResolvedValue(discovery("native", "openhands"));
  createRuntimeConfiguration.mockImplementation(() => resolved(runtime()));
  updateRuntimeConfiguration.mockImplementation(() => resolved(runtime()));
});

async function renderRuntimes() {
  render(<SettingsWorkspace client={client} />);
  await screen.findByTestId("settings-workspace");
  fireEvent.click(screen.getByRole("tab", { name: "Runtimes" }));
  await waitFor(() =>
    expect(screen.getByRole("tab", { selected: true }).textContent).toBe("Runtimes"),
  );
}

function dialog(): HTMLElement {
  return screen.getByRole("dialog");
}

function addButton(): HTMLElement {
  return screen.getByRole("button", { name: "Add Runtime" });
}

function editButton(displayName: string): HTMLElement {
  return screen.getByRole("button", { name: `Edit ${displayName}` });
}

function setField(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

async function openAdd() {
  await renderRuntimes();
  fireEvent.click(addButton());
  await waitFor(() => expect(dialog()).toBeTruthy());
}

describe("Runtimes inventory actions", () => {
  it("offers Add Runtime, including when the inventory is empty", async () => {
    await renderRuntimes();
    expect(addButton()).toBeTruthy();
  });

  it("offers Edit on every row, including a disabled runtime", async () => {
    listRuntimeConfigurations.mockResolvedValue({
      runtimes: [
        runtime(),
        runtime({
          runtime_configuration_id: "hands-standby",
          runtime_type: "openhands",
          display_name: "OpenHands Standby",
          enabled: false,
        }),
      ],
      contract_version: contractVersion,
    });
    await renderRuntimes();

    await screen.findByText("AVA Native Runtime");
    expect(editButton("AVA Native Runtime")).toBeTruthy();
    expect(screen.getByText("Disabled")).toBeTruthy();
    expect(editButton("OpenHands Standby")).toBeTruthy();
  });

  it("shows the stable id and the runtime type on separate lines", async () => {
    listRuntimeConfigurations.mockResolvedValue({
      runtimes: [runtime()],
      contract_version: contractVersion,
    });
    await renderRuntimes();

    const row = (await screen.findByTestId("settings-inventory-entry")) as HTMLElement;
    expect(within(row).getByTestId("settings-inventory-entry-id").textContent).toBe(
      "native-primary",
    );
    expect(within(row).getByTestId("settings-inventory-entry-meta").textContent).toBe(
      "native",
    );
  });

  it("offers no delete or remove action", async () => {
    listRuntimeConfigurations.mockResolvedValue({
      runtimes: [runtime()],
      contract_version: contractVersion,
    });
    await renderRuntimes();
    await screen.findByText("AVA Native Runtime");

    const destructive = screen
      .queryAllByRole("button")
      .map((button) => button.textContent ?? "")
      .filter((text) => /delete|remove/i.test(text));
    expect(destructive).toEqual([]);
  });

  it("adds no provider, model, or credential field to the domain", async () => {
    await openAdd();

    for (const label of [
      "Model ID",
      "Provider connection",
      "Provider type",
      "Endpoint",
      "Credential reference",
      "Hosting mode",
    ]) {
      expect(within(dialog()).queryByLabelText(label), label).toBeNull();
    }
    // Nor any per-adapter configuration bag: Phase 5.6 deliberately has none.
    for (const label of [
      "Executable",
      "Host",
      "Workspace path",
      "Runtime options",
      "Configuration",
    ]) {
      expect(within(dialog()).queryByLabelText(label), label).toBeNull();
    }
  });
});

describe("Add Runtime", () => {
  it("renders the domain's four fields", async () => {
    await openAdd();

    expect(within(dialog()).getByText("Add Runtime")).toBeTruthy();
    for (const label of [
      "Runtime configuration ID",
      "Runtime type",
      "Display name",
      "Enabled",
    ]) {
      expect(within(dialog()).getByLabelText(label), label).toBeTruthy();
    }
  });

  it("offers the currently registered runtime types from discovery", async () => {
    await openAdd();

    const select = within(dialog()).getByLabelText("Runtime type") as HTMLSelectElement;
    expect(select.tagName).toBe("SELECT");
    const options = within(select).getAllByRole("option") as HTMLOptionElement[];

    // The value is the registry key; the registered display name is secondary
    // text, so nothing is hard-coded in the form.
    const native = options.find((option) => option.value === "native");
    expect(native?.textContent).toBe("native — AVA Native Runtime");
    const openhands = options.find((option) => option.value === "openhands");
    expect(openhands?.textContent).toBe("openhands — OpenHands");
    // A registered type that is not installed is not invented by the form.
    expect(options.map((option) => option.value)).not.toContain("langgraph");
    expect(options.map((option) => option.value)).not.toContain("agentcore");
  });

  it("offers a custom-type escape hatch", async () => {
    await openAdd();

    const select = within(dialog()).getByLabelText("Runtime type");
    const labels = within(select)
      .getAllByRole("option")
      .map((option) => option.textContent ?? "")
      .join(" ");
    expect(labels).toMatch(/other runtime type/i);
  });

  it("sends the registry key when a known type is chosen", async () => {
    await openAdd();
    setField("Runtime configuration ID", "hands-primary");
    fireEvent.change(within(dialog()).getByLabelText("Runtime type"), {
      target: { value: "openhands" },
    });
    setField("Display name", "OpenHands");

    fireEvent.click(screen.getByRole("button", { name: "Create runtime" }));

    await waitFor(() =>
      expect(createRuntimeConfiguration).toHaveBeenCalledWith(client, {
        runtime_configuration_id: "hands-primary",
        runtime_type: "openhands",
        display_name: "OpenHands",
        enabled: true,
      }),
    );
  });

  it("sends an arbitrary type through the custom path", async () => {
    await openAdd();
    setField("Runtime configuration ID", "graphs-primary");
    fireEvent.change(within(dialog()).getByLabelText("Runtime type"), {
      target: { value: "__custom__" },
    });
    setField("Runtime type (custom)", "langgraph");
    setField("Display name", "LangGraph");

    fireEvent.click(screen.getByRole("button", { name: "Create runtime" }));

    await waitFor(() =>
      expect(createRuntimeConfiguration).toHaveBeenCalledWith(
        client,
        expect.objectContaining({ runtime_type: "langgraph" }),
      ),
    );
  });

  it("accepts a type that is not currently registered", async () => {
    // The backend stores any non-blank type and 5.7 round-trips unregistered
    // values, so the form must not refuse one.
    await openAdd();
    setField("Runtime configuration ID", "future-primary");
    fireEvent.change(within(dialog()).getByLabelText("Runtime type"), {
      target: { value: "__custom__" },
    });
    setField("Runtime type (custom)", "future-adapter");
    setField("Display name", "Future");

    fireEvent.click(screen.getByRole("button", { name: "Create runtime" }));

    await waitFor(() =>
      expect(createRuntimeConfiguration).toHaveBeenCalledWith(
        client,
        expect.objectContaining({ runtime_type: "future-adapter" }),
      ),
    );
  });

  it("falls back to a text field when discovery fails, and still allows creating", async () => {
    getRuntimesMock.mockRejectedValue(new Error("registry unavailable"));
    await openAdd();

    // No empty select is presented as if it were the only choice.
    const field = within(dialog()).getByLabelText("Runtime type");
    expect(field.tagName).toBe("INPUT");
    setField("Runtime configuration ID", "native-primary");
    setField("Runtime type", "native");
    setField("Display name", "AVA Native Runtime");

    fireEvent.click(screen.getByRole("button", { name: "Create runtime" }));

    await waitFor(() =>
      expect(createRuntimeConfiguration).toHaveBeenCalledWith(
        client,
        expect.objectContaining({ runtime_type: "native" }),
      ),
    );
  });

  it("falls back to a text field when discovery reports nothing", async () => {
    getRuntimesMock.mockResolvedValue(discovery());
    await openAdd();

    expect((within(dialog()).getByLabelText("Runtime type")).tagName).toBe("INPUT");
  });

  it("keeps a typed type when discovery answers after the operator started", async () => {
    const pending = deferred<unknown>();
    getRuntimesMock.mockImplementation(() => pending.promise);
    await renderRuntimes();
    fireEvent.click(addButton());
    await waitFor(() => expect(dialog()).toBeTruthy());

    // Discovery is still in flight, so the form is a text field. Type a type
    // that is not registered, then let discovery arrive.
    setField("Runtime configuration ID", "native-primary");
    setField("Runtime type", "langgraph");
    setField("Display name", "LangGraph");

    await act(async () => {
      pending.resolve(discovery("native", "openhands"));
      await pending.promise;
    });

    // A late answer must not rewrite what was typed into a select.
    expect((screen.getByLabelText("Runtime type (custom)") as HTMLInputElement).value).toBe(
      "langgraph",
    );
  });

  it("defaults enabled on", async () => {
    await openAdd();
    expect((within(dialog()).getByLabelText("Enabled") as HTMLInputElement).checked).toBe(
      true,
    );
  });

  it("refuses to submit without the required fields", async () => {
    await openAdd();

    fireEvent.click(screen.getByRole("button", { name: "Create runtime" }));

    expect(createRuntimeConfiguration).not.toHaveBeenCalled();
    expect(
      within(dialog()).getByText("A stable runtime configuration ID is required."),
    ).toBeTruthy();
    expect(within(dialog()).getByText("A runtime type is required.")).toBeTruthy();
    expect(within(dialog()).getByText("A display name is required.")).toBeTruthy();
    expect(dialog()).toBeTruthy();
  });

  it("closes on cancel without writing", async () => {
    await openAdd();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(createRuntimeConfiguration).not.toHaveBeenCalled();
  });

  it("trims identity and type consistently with the other records", async () => {
    await openAdd();
    setField("Runtime configuration ID", "  native-primary  ");
    fireEvent.change(within(dialog()).getByLabelText("Runtime type"), {
      target: { value: "native" },
    });
    setField("Display name", "  AVA Native Runtime  ");

    fireEvent.click(screen.getByRole("button", { name: "Create runtime" }));

    await waitFor(() =>
      expect(createRuntimeConfiguration).toHaveBeenCalledWith(client, {
        runtime_configuration_id: "native-primary",
        runtime_type: "native",
        display_name: "AVA Native Runtime",
        enabled: true,
      }),
    );
  });

  it("closes and refreshes the inventory on success", async () => {
    const created = runtime({
      runtime_configuration_id: "hands-primary",
      runtime_type: "openhands",
      display_name: "OpenHands",
    });
    listRuntimeConfigurations
      .mockResolvedValueOnce({ runtimes: [], contract_version: contractVersion })
      .mockResolvedValueOnce({ runtimes: [created], contract_version: contractVersion });
    createRuntimeConfiguration.mockImplementation(() => resolved(created));

    await openAdd();
    setField("Runtime configuration ID", "hands-primary");
    fireEvent.change(within(dialog()).getByLabelText("Runtime type"), {
      target: { value: "openhands" },
    });
    setField("Display name", "OpenHands");
    fireEvent.click(screen.getByRole("button", { name: "Create runtime" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(listRuntimeConfigurations).toHaveBeenCalledTimes(2);
    expect(await screen.findByText("OpenHands")).toBeTruthy();
  });

  it("keeps the form and a safe error when the save fails", async () => {
    createRuntimeConfiguration.mockRejectedValue(
      new ApiError("Request failed", 409, {
        error_code: "duplicate_runtime_configuration",
        message:
          "Runtime configuration already exists: native-primary",
        contract_version: contractVersion,
      }),
    );
    await openAdd();
    setField("Runtime configuration ID", "native-primary");
    fireEvent.change(within(dialog()).getByLabelText("Runtime type"), {
      target: { value: "native" },
    });
    setField("Display name", "AVA Native Runtime");
    fireEvent.click(screen.getByRole("button", { name: "Create runtime" }));

    const alert = await within(dialog()).findByRole("alert");
    expect(alert.textContent).toBe(
      "Runtime configuration already exists: native-primary",
    );
    expect(dialog()).toBeTruthy();
    expect((screen.getByLabelText("Display name") as HTMLInputElement).value).toBe(
      "AVA Native Runtime",
    );
    expect(alert.textContent).not.toContain("error_code");
  });

  it("reduces an unusable thrown value to a fixed sentence", async () => {
    createRuntimeConfiguration.mockRejectedValue(
      new Error("sqlalchemy.exc.IntegrityError at repo.py:91 (10.0.0.7:5432)"),
    );
    await openAdd();
    setField("Runtime configuration ID", "native-primary");
    fireEvent.change(within(dialog()).getByLabelText("Runtime type"), {
      target: { value: "native" },
    });
    setField("Display name", "AVA Native Runtime");
    fireEvent.click(screen.getByRole("button", { name: "Create runtime" }));

    const alert = await within(dialog()).findByRole("alert");
    expect(alert.textContent).toBe("AVA could not save this runtime. Try again.");
    expect(alert.textContent).not.toContain("sqlalchemy");
    expect(alert.textContent).not.toContain("5432");
  });

  it("refuses a duplicate submit and blocks dismissal while saving", async () => {
    const pending = deferred<unknown>();
    createRuntimeConfiguration.mockImplementation(() => pending.promise);
    await openAdd();
    setField("Runtime configuration ID", "native-primary");
    fireEvent.change(within(dialog()).getByLabelText("Runtime type"), {
      target: { value: "native" },
    });
    setField("Display name", "AVA Native Runtime");

    fireEvent.click(screen.getByRole("button", { name: "Create runtime" }));
    await waitFor(() =>
      expect(
        (screen.getByRole("button", { name: "Create runtime" }) as HTMLButtonElement)
          .disabled,
      ).toBe(true),
    );

    fireEvent.click(screen.getByRole("button", { name: "Create runtime" }));
    expect(createRuntimeConfiguration).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(dialog(), { key: "Escape" });
    expect(dialog()).toBeTruthy();

    await act(async () => {
      pending.resolve(runtime());
      await pending.promise;
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});

describe("Edit Runtime", () => {
  it("prepopulates the record and locks identity and type", async () => {
    listRuntimeConfigurations.mockResolvedValue({
      runtimes: [runtime()],
      contract_version: contractVersion,
    });
    await renderRuntimes();
    fireEvent.click(await screen.findByRole("button", { name: "Edit AVA Native Runtime" }));
    await waitFor(() => expect(dialog()).toBeTruthy());

    expect(within(dialog()).getByText("Edit Runtime")).toBeTruthy();
    const id = screen.getByLabelText("Runtime configuration ID") as HTMLInputElement;
    expect(id.value).toBe("native-primary");
    expect(id.readOnly).toBe(true);

    // The type is read-only text, never a select: there is no control that
    // could coerce an unregistered value.
    const type = screen.getByLabelText("Runtime type") as HTMLInputElement;
    expect(type.tagName).toBe("INPUT");
    expect(type.readOnly).toBe(true);
    expect(type.value).toBe("native");

    // Mutable fields stay editable and preloaded.
    expect((screen.getByLabelText("Display name") as HTMLInputElement).value).toBe(
      "AVA Native Runtime",
    );
    expect((screen.getByLabelText("Enabled") as HTMLInputElement).checked).toBe(true);
  });

  it("displays an unregistered stored type exactly, without coercing it", async () => {
    listRuntimeConfigurations.mockResolvedValue({
      runtimes: [runtime({ runtime_type: "langgraph" })],
      contract_version: contractVersion,
    });
    await renderRuntimes();
    fireEvent.click(await screen.findByRole("button", { name: "Edit AVA Native Runtime" }));
    await waitFor(() => expect(dialog()).toBeTruthy());

    const type = screen.getByLabelText("Runtime type") as HTMLInputElement;
    expect(type.value).toBe("langgraph");
    expect(type.value).not.toBe("native");
    // The form offers no select here, so there is nothing to fall back to.
    expect(within(dialog()).queryByRole("combobox")).toBeNull();
  });

  it("keeps a persisted runtime whose adapter is not registered editable", async () => {
    getRuntimesMock.mockResolvedValue(discovery("native"));
    listRuntimeConfigurations.mockResolvedValue({
      runtimes: [runtime({ runtime_type: "openhands" })],
      contract_version: contractVersion,
    });
    await renderRuntimes();
    fireEvent.click(await screen.findByRole("button", { name: "Edit AVA Native Runtime" }));
    await waitFor(() => expect(dialog()).toBeTruthy());

    expect((screen.getByLabelText("Runtime type") as HTMLInputElement).value).toBe(
      "openhands",
    );
    // Registration is not a save prerequisite.
    expect(
      (screen.getByRole("button", { name: "Save changes" }) as HTMLButtonElement)
        .disabled,
    ).toBe(false);
  });

  it("shows an unregistered persisted type in the inventory", async () => {
    getRuntimesMock.mockResolvedValue(discovery("native"));
    listRuntimeConfigurations.mockResolvedValue({
      runtimes: [runtime({ runtime_type: "openhands" })],
      contract_version: contractVersion,
    });
    await renderRuntimes();

    const row = (await screen.findByTestId("settings-inventory-entry")) as HTMLElement;
    expect(
      within(row).getByTestId("settings-inventory-entry-details").textContent,
    ).toBe("Not currently registered");
  });

  it("reports a registered type in the inventory", async () => {
    listRuntimeConfigurations.mockResolvedValue({
      runtimes: [runtime()],
      contract_version: contractVersion,
    });
    await renderRuntimes();

    const row = (await screen.findByTestId("settings-inventory-entry")) as HTMLElement;
    expect(
      within(row).getByTestId("settings-inventory-entry-details").textContent,
    ).toBe("Registered runtime");
  });

  it("omits the registry line while discovery is still in flight", async () => {
    const pending = deferred<unknown>();
    getRuntimesMock.mockImplementation(() => pending.promise);
    listRuntimeConfigurations.mockResolvedValue({
      runtimes: [runtime()],
      contract_version: contractVersion,
    });
    await renderRuntimes();

    const row = (await screen.findByTestId("settings-inventory-entry")) as HTMLElement;
    // Not yet known is not the same as "not registered".
    expect(
      within(row).queryByTestId("settings-inventory-entry-details"),
    ).toBeNull();

    await act(async () => {
      pending.resolve(discovery("native"));
      await pending.promise;
    });
    expect(
      within(
        (await screen.findByTestId("settings-inventory-entry")) as HTMLElement,
      ).getByTestId("settings-inventory-entry-details").textContent,
    ).toBe("Registered runtime");
  });

  it("issues no discovery-only state as an error when the registry is unreachable", async () => {
    getRuntimesMock.mockRejectedValue(new Error("registry unavailable"));
    listRuntimeConfigurations.mockResolvedValue({
      runtimes: [runtime()],
      contract_version: contractVersion,
    });
    await renderRuntimes();

    // The section still renders the record; the registry line is absent, and
    // specifically does NOT claim the runtime is unregistered.
    expect(await screen.findByText("AVA Native Runtime")).toBeTruthy();
    expect(screen.queryByTestId("settings-error")).toBeNull();
    const row = screen.getByTestId("settings-inventory-entry");
    expect(within(row).queryByTestId("settings-inventory-entry-details")).toBeNull();
    expect(screen.queryByText(/Not currently registered/)).toBeNull();
  });

  it("updates mutable fields, preserving the type and the identity", async () => {
    const updated = runtime({
      display_name: "AVA Native (EU)",
      enabled: false,
    });
    listRuntimeConfigurations
      .mockResolvedValueOnce({ runtimes: [runtime()], contract_version: contractVersion })
      .mockResolvedValueOnce({ runtimes: [updated], contract_version: contractVersion });
    updateRuntimeConfiguration.mockImplementation(() => resolved(updated));

    await renderRuntimes();
    fireEvent.click(await screen.findByRole("button", { name: "Edit AVA Native Runtime" }));
    await waitFor(() => expect(dialog()).toBeTruthy());

    setField("Display name", "AVA Native (EU)");
    fireEvent.click(within(dialog()).getByLabelText("Enabled"));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() =>
      expect(updateRuntimeConfiguration).toHaveBeenCalledWith(
        client,
        "native-primary",
        {
          // Echoed unchanged, never reselected.
          runtime_type: "native",
          display_name: "AVA Native (EU)",
          enabled: false,
        },
      ),
    );
    // Identity is the path parameter and is never a mutable body field.
    const payload = updateRuntimeConfiguration.mock.calls[0][2] as Record<string, unknown>;
    expect(payload.runtime_configuration_id).toBeUndefined();

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(listRuntimeConfigurations).toHaveBeenCalledTimes(2);
    expect(await screen.findByText("AVA Native (EU)")).toBeTruthy();
  });

  it("echoes an unregistered stored type unchanged on save", async () => {
    listRuntimeConfigurations.mockResolvedValue({
      runtimes: [runtime({ runtime_type: "langgraph" })],
      contract_version: contractVersion,
    });
    await renderRuntimes();
    fireEvent.click(await screen.findByRole("button", { name: "Edit AVA Native Runtime" }));
    await waitFor(() => expect(dialog()).toBeTruthy());

    setField("Display name", "LangGraph");
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() =>
      expect(updateRuntimeConfiguration).toHaveBeenCalledWith(
        client,
        "native-primary",
        expect.objectContaining({ runtime_type: "langgraph" }),
      ),
    );
  });

  it("cannot be made to retype a runtime", async () => {
    listRuntimeConfigurations.mockResolvedValue({
      runtimes: [runtime()],
      contract_version: contractVersion,
    });
    await renderRuntimes();
    fireEvent.click(await screen.findByRole("button", { name: "Edit AVA Native Runtime" }));
    await waitFor(() => expect(dialog()).toBeTruthy());

    // There is no editable type control at all, so native -> openhands is not
    // reachable under the same stable id.
    const type = screen.getByLabelText("Runtime type") as HTMLInputElement;
    fireEvent.change(type, { target: { value: "openhands" } });
    setField("Display name", "Renamed");
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(updateRuntimeConfiguration).toHaveBeenCalled());
    const payload = updateRuntimeConfiguration.mock.calls[0][2] as {
      runtime_type: string;
    };
    expect(payload.runtime_type).toBe("native");
  });

  it("keeps the dialog open with a safe message when the update is rejected", async () => {
    listRuntimeConfigurations.mockResolvedValue({
      runtimes: [runtime()],
      contract_version: contractVersion,
    });
    updateRuntimeConfiguration.mockRejectedValue(
      new ApiError("Request failed", 409, {
        error_code: "runtime_type_immutable",
        message: "Runtime configuration runtime_type cannot change",
        contract_version: contractVersion,
      }),
    );

    await renderRuntimes();
    fireEvent.click(await screen.findByRole("button", { name: "Edit AVA Native Runtime" }));
    await waitFor(() => expect(dialog()).toBeTruthy());
    setField("Display name", "Renamed");
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    const alert = await within(dialog()).findByRole("alert");
    expect(alert.textContent).toBe("Runtime configuration runtime_type cannot change");
    expect(dialog()).toBeTruthy();
    expect((screen.getByLabelText("Display name") as HTMLInputElement).value).toBe(
      "Renamed",
    );
  });
});

describe("Runtime discovery boundary", () => {
  it("reads configuration and discovery from separate endpoints", async () => {
    // Discovery reports two runtimes; nothing is configured.
    await renderRuntimes();
    await waitFor(() =>
      expect(screen.getByText("No runtimes configured.")).toBeTruthy(),
    );
    // The two datasets are not merged: a discovered runtime does not become a
    // configured row, which is what makes "installed but unconfigured" valid.
    expect(screen.getByTestId("settings-empty")).toBeTruthy();
    expect(screen.queryAllByTestId("settings-inventory-entry")).toHaveLength(0);
    expect(getRuntimesMock).toHaveBeenCalledWith(client);
  });

  it("does not turn a configured runtime into a discovered one", async () => {
    listRuntimeConfigurations.mockResolvedValue({
      runtimes: [runtime()],
      contract_version: contractVersion,
    });
    getRuntimesMock.mockResolvedValue(discovery("native"));
    await renderRuntimes();

    // Two runtimes are registered, one is configured, and the inventory shows
    // exactly the configured record.
    const rows = await screen.findAllByTestId("settings-inventory-entry");
    expect(rows).toHaveLength(1);
    expect(getRuntimesMock).toHaveBeenCalled();
  });
});
