import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { ApiClient } from "@ava/api-client";

import { ExecutionDefaultsSection } from "../sections/ExecutionDefaultsSection";

/**
 * Integration coverage for the one record that Phase 5.8 made singular.
 *
 * The unit tests in `defaultChoices.test.ts` cover the option-shaping rules. What
 * can only be checked here is the behaviour that spans the section, the three
 * independent inventory loads, and the modal: what the operator is shown, what
 * blocks a save, and what leaves the screen as a request.
 */

const listProviderConnections = vi.fn();
const listModelConfigurations = vi.fn();
const listRuntimeConfigurations = vi.fn();
const getExecutionDefaults = vi.fn();
const setExecutionDefaults = vi.fn();

vi.mock("@ava/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@ava/api-client")>();
  return {
    ...actual,
    ApiClient: actual.ApiClient,
    listProviderConnections: (...args: unknown[]) => listProviderConnections(...args),
    listModelConfigurations: (...args: unknown[]) => listModelConfigurations(...args),
    listRuntimeConfigurations: (...args: unknown[]) => listRuntimeConfigurations(...args),
    getExecutionDefaults: (...args: unknown[]) => getExecutionDefaults(...args),
    setExecutionDefaults: (...args: unknown[]) => setExecutionDefaults(...args),
  };
});

const client = new ApiClient({ baseUrl: "http://localhost:99999" });
const contractVersion = "v1" as const;

function provider(overrides: Record<string, unknown> = {}) {
  return {
    provider_connection_id: "conn-a",
    provider_id: "acme",
    display_name: "Acme Primary",
    endpoint: "https://api.acme.test",
    enabled: true,
    credential_reference: "env:ACME_API_KEY",
    contract_version: contractVersion,
    ...overrides,
  };
}

function model(overrides: Record<string, unknown> = {}) {
  return {
    model_id: "model-a",
    provider_connection_id: "conn-a",
    provider_model_name: "large",
    display_name: "Acme Large",
    hosting_mode: "remote",
    capabilities: {},
    enabled: true,
    contract_version: contractVersion,
    ...overrides,
  };
}

function runtime(overrides: Record<string, unknown> = {}) {
  return {
    runtime_configuration_id: "rt-a",
    runtime_type: "subprocess",
    display_name: "Native",
    enabled: true,
    contract_version: contractVersion,
    ...overrides,
  };
}

const configured = {
  configured: true,
  defaults: {
    default_provider_connection_id: "conn-a",
    default_model_id: "model-a",
    default_runtime_configuration_id: "rt-a",
  },
  contract_version: contractVersion,
};

const unconfigured = {
  configured: false,
  defaults: null,
  contract_version: contractVersion,
};

function renderSection() {
  return render(<ExecutionDefaultsSection client={client} />);
}

/** The three selects, identified by their labels rather than by index. */
function field(label: string): HTMLSelectElement {
  return screen.getByLabelText(label) as HTMLSelectElement;
}

beforeEach(() => {
  vi.clearAllMocks();
  listProviderConnections.mockResolvedValue({
    provider_connections: [provider()],
    contract_version: contractVersion,
  });
  listModelConfigurations.mockResolvedValue({
    models: [model()],
    contract_version: contractVersion,
  });
  listRuntimeConfigurations.mockResolvedValue({
    runtimes: [runtime()],
    contract_version: contractVersion,
  });
  getExecutionDefaults.mockResolvedValue(unconfigured);
  setExecutionDefaults.mockResolvedValue({ contract_version: contractVersion });
});

describe("execution defaults display", () => {
  it("shows an unconfigured empty state with a configure action", async () => {
    renderSection();

    expect(
      await screen.findByText("Execution defaults are not configured."),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Configure Defaults" })).toBeTruthy();
  });

  it("never presents configured:false as an error", async () => {
    // 5.10 answers `200` with `configured: false` rather than `404`, so this is
    // ordinary first-run state. A retry affordance here would send the operator
    // looking for a failure that never happened.
    renderSection();

    await screen.findByText("Execution defaults are not configured.");
    expect(screen.queryByTestId("settings-error")).toBeNull();
  });

  it("shows stored references as display names with their ids", async () => {
    getExecutionDefaults.mockResolvedValue(configured);
    renderSection();

    const group = await screen.findByLabelText("Application execution defaults");
    expect(within(group).getByText("Acme Primary")).toBeTruthy();
    expect(within(group).getByText("Acme Large")).toBeTruthy();
    expect(within(group).getByText("Native")).toBeTruthy();
    expect(screen.getAllByTestId("settings-default-row")[0].className).toContain("dark:bg-black");
    expect(screen.getAllByTestId("settings-default-row")[0].className).toContain("dark:text-white");
    // The id stays visible underneath: the display name is a convenience, and
    // the stored reference is the thing that has to remain auditable.
    expect(within(group).getByText("conn-a")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Edit Defaults" })).toBeTruthy();
  });

  it("falls back to the raw id when an inventory is unavailable", async () => {
    // A failed inventory load must not blank the reference. Showing an id the
    // operator cannot yet resolve to a name is honest; showing nothing would
    // make stored configuration look unset and invite a destructive save.
    listRuntimeConfigurations.mockRejectedValue(new Error("boom"));
    getExecutionDefaults.mockResolvedValue(configured);
    renderSection();

    const group = await screen.findByLabelText("Application execution defaults");
    expect(within(group).getByText("rt-a")).toBeTruthy();
    // The section itself still renders: one failed inventory is not a failed
    // section, and the other two references are still readable.
    expect(within(group).getByText("Acme Primary")).toBeTruthy();
  });

  it("retries the defaults record itself when it fails", async () => {
    getExecutionDefaults.mockRejectedValueOnce(new Error("boom"));
    getExecutionDefaults.mockResolvedValue(unconfigured);
    renderSection();

    fireEvent.click(await screen.findByRole("button", { name: /retry/i }));
    expect(
      await screen.findByText("Execution defaults are not configured."),
    ).toBeTruthy();
  });
});

describe("defaults editor", () => {
  async function openEditor() {
    renderSection();
    fireEvent.click(await screen.findByRole("button", { name: "Configure Defaults" }));
    await screen.findByRole("dialog");
  }

  it("opens with three closed selects and no free-text escape", async () => {
    // Every field is a persisted reference the API validates, so a typed value
    // could only ever name something that does not exist. This is the opposite
    // of 5.14's custom runtime type, where the backend did not validate.
    await openEditor();

    for (const label of [
      "Default provider connection",
      "Default model",
      "Default runtime",
    ]) {
      const select = field(label);
      expect(select.tagName).toBe("SELECT");
    }
    // A placeholder is rendered for the empty selection, so the assertion that
    // matters is that no text input exists alongside the select — the closed
    // list is the only way in.
    expect(screen.queryByRole("textbox")).toBeNull();
    await waitFor(() =>
      expect(
        field("Default provider connection").querySelector('option[value="conn-a"]'),
      ).toBeTruthy(),
    );
  });

  it("offers only enabled records for a new selection", async () => {
    listProviderConnections.mockResolvedValue({
      provider_connections: [
        provider(),
        provider({ provider_connection_id: "conn-off", display_name: "Acme Retired", enabled: false }),
      ],
      contract_version: contractVersion,
    });
    await openEditor();

    const options = [...field("Default provider connection").options];
    expect(options.some((option) => option.value === "conn-off")).toBe(true);
    expect(options.find((option) => option.value === "conn-off")?.disabled).toBe(true);
  });

  it("filters models to the selected provider connection", async () => {
    listModelConfigurations.mockResolvedValue({
      models: [
        model(),
        model({ model_id: "model-b", provider_connection_id: "conn-b", display_name: "Other Large" }),
      ],
      contract_version: contractVersion,
    });
    await openEditor();

    fireEvent.change(field("Default provider connection"), {
      target: { value: "conn-a" },
    });

    const options = [...field("Default model").options];
    expect(options.some((option) => option.value === "model-b")).toBe(false);
  });

  it("clears a model that no longer belongs to the chosen provider", async () => {
    // 5.8 rejects that pairing, and 5.13 made the relationship immutable, so
    // there is no way to repair it in place. Clearing forces an explicit choice
    // rather than auto-picking the first model, which would choose something the
    // operator never asked for.
    listProviderConnections.mockResolvedValue({
      provider_connections: [provider(), provider({ provider_connection_id: "conn-b" })],
      contract_version: contractVersion,
    });
    listModelConfigurations.mockResolvedValue({
      models: [model()],
      contract_version: contractVersion,
    });
    getExecutionDefaults.mockResolvedValue(configured);
    renderSection();

    fireEvent.click(await screen.findByRole("button", { name: "Edit Defaults" }));
    await screen.findByRole("dialog");
    expect(field("Default model").value).toBe("model-a");

    fireEvent.change(field("Default provider connection"), {
      target: { value: "conn-b" },
    });

    expect(field("Default model").value).toBe("");
  });

  it("keeps a stored reference that is missing from the inventory, disabled", async () => {
    // Dropping it would render the field as unset, which reads as "no default"
    // instead of "a default points at something missing".
    listRuntimeConfigurations.mockResolvedValue({
      runtimes: [runtime()],
      contract_version: contractVersion,
    });
    getExecutionDefaults.mockResolvedValue({
      ...configured,
      defaults: { ...configured.defaults, default_runtime_configuration_id: "rt-gone" },
    });
    renderSection();

    fireEvent.click(await screen.findByRole("button", { name: "Edit Defaults" }));
    await screen.findByRole("dialog");

    const select = field("Default runtime");
    expect(select.value).toBe("rt-gone");
    const preserved = [...select.options].find(
      (option) => option.value === "rt-gone",
    );
    expect(preserved?.textContent).toContain("not present in current configuration");
    expect(preserved?.disabled).toBe(true);
  });

  it("says the inventory is empty rather than telling the operator to pick a provider", async () => {
    // With no models configured at all, "choose a provider connection to see
    // its models" is a dead end: no choice would reveal one. The two empty
    // states look identical in the DOM, so the reason has to come from the
    // source state rather than from the option count.
    listModelConfigurations.mockResolvedValue({
      models: [],
      contract_version: contractVersion,
    });
    await openEditor();

    expect(
      await screen.findByText("No model configurations are configured."),
    ).toBeTruthy();
    expect(
      screen.queryByText("Choose a provider connection to see its models."),
    ).toBeNull();
  });

  it("explains the filter once a provider is chosen but no model matches", async () => {
    listProviderConnections.mockResolvedValue({
      provider_connections: [provider()],
      contract_version: contractVersion,
    });
    listModelConfigurations.mockResolvedValue({
      models: [model({ model_id: "model-b", provider_connection_id: "conn-b" })],
      contract_version: contractVersion,
    });
    await openEditor();

    fireEvent.change(field("Default provider connection"), {
      target: { value: "conn-a" },
    });

    expect(
      await screen.findByText("Choose a provider connection to see its models."),
    ).toBeTruthy();
  });

  it("does not call a stored reference absent while the source is still loading", async () => {
    // The read-only side is the other half of the same rule: a reference that
    // cannot be resolved yet must render as itself, not as a claim.
    let release: (value: unknown) => void = () => {};
    listRuntimeConfigurations.mockImplementation(
      () => new Promise((resolve) => { release = resolve; }),
    );
    getExecutionDefaults.mockResolvedValue(configured);
    renderSection();

    const group = await screen.findByLabelText("Application execution defaults");
    expect(within(group).getByText("rt-a")).toBeTruthy();
    release({ runtimes: [], contract_version: contractVersion });
  });

  it("sends the three ids through setExecutionDefaults and reloads", async () => {
    await openEditor();

    fireEvent.change(field("Default provider connection"), { target: { value: "conn-a" } });
    fireEvent.change(field("Default model"), { target: { value: "model-a" } });
    fireEvent.change(field("Default runtime"), { target: { value: "rt-a" } });
    fireEvent.click(screen.getByRole("button", { name: "Save defaults" }));

    await waitFor(() => expect(setExecutionDefaults).toHaveBeenCalledTimes(1));
    expect(setExecutionDefaults.mock.calls[0][1]).toEqual({
      default_provider_connection_id: "conn-a",
      default_model_id: "model-a",
      default_runtime_configuration_id: "rt-a",
    });
    // The write target is the singular record, so only that record is re-read.
    // Re-fetching the three inventories would flicker the display for nothing.
    await waitFor(() =>
      expect(getExecutionDefaults.mock.calls.length).toBeGreaterThan(1),
    );
    expect(listProviderConnections).toHaveBeenCalledTimes(1);
  });

  it("shows one field message per field and does not call the API", async () => {
    await openEditor();
    fireEvent.click(screen.getByRole("button", { name: "Save defaults" }));

    expect(
      await screen.findByText("Select a provider connection."),
    ).toBeTruthy();
    expect(screen.getByText("Select a model for this provider connection.")).toBeTruthy();
    expect(screen.getByText("Select a runtime configuration.")).toBeTruthy();
    expect(setExecutionDefaults).not.toHaveBeenCalled();
  });

  it("blocks saving and offers a retry when an inventory is unavailable", async () => {
    // "AVA could not ask" and "you have nothing configured" must not both render
    // as an empty list. A save here would be a guess, and the operator's only
    // route back is a retry on the field that failed.
    listRuntimeConfigurations.mockRejectedValue(new Error("boom"));
    await openEditor();

    expect(
      await screen.findByText("Runtime configurations could not be loaded."),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Retry loading runtime configurations" }),
    ).toBeTruthy();
    expect(
      (screen.getByRole("button", { name: "Save defaults" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  });

  it("retries only the failed source", async () => {
    listRuntimeConfigurations.mockRejectedValueOnce(new Error("boom"));
    listRuntimeConfigurations.mockResolvedValue({
      runtimes: [runtime()],
      contract_version: contractVersion,
    });
    await openEditor();

    fireEvent.click(
      await screen.findByRole("button", {
        name: "Retry loading runtime configurations",
      }),
    );

    await waitFor(() => expect(listRuntimeConfigurations).toHaveBeenCalledTimes(2));
    expect(listProviderConnections).toHaveBeenCalledTimes(1);
    expect(listModelConfigurations).toHaveBeenCalledTimes(1);
  });

  it("disables the primary action and blocks dismissal while saving", async () => {
    let release: (value: unknown) => void = () => {};
    setExecutionDefaults.mockImplementation(
      () => new Promise((resolve) => { release = resolve; }),
    );
    await openEditor();

    fireEvent.change(field("Default provider connection"), { target: { value: "conn-a" } });
    fireEvent.change(field("Default model"), { target: { value: "model-a" } });
    fireEvent.change(field("Default runtime"), { target: { value: "rt-a" } });
    fireEvent.click(screen.getByRole("button", { name: "Save defaults" }));

    await waitFor(() =>
      expect(
        (screen.getByRole("button", { name: "Save defaults" }) as HTMLButtonElement)
          .disabled,
      ).toBe(true),
    );
    // A second click must not produce a second request.
    fireEvent.click(screen.getByRole("button", { name: "Save defaults" }));
    expect(setExecutionDefaults).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("dialog")).toBeTruthy();

    release({ contract_version: contractVersion });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("shows a safe message for a thrown non-Error failure", async () => {
    setExecutionDefaults.mockRejectedValue("plain string failure");
    await openEditor();

    fireEvent.change(field("Default provider connection"), { target: { value: "conn-a" } });
    fireEvent.change(field("Default model"), { target: { value: "model-a" } });
    fireEvent.change(field("Default runtime"), { target: { value: "rt-a" } });
    fireEvent.click(screen.getByRole("button", { name: "Save defaults" }));

    expect(
      await screen.findByText("AVA could not save these defaults. Try again."),
    ).toBeTruthy();
  });
});
