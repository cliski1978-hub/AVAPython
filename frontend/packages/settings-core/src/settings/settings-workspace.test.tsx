import { ApiClient } from "@ava/api-client";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SettingsWorkspace } from "./SettingsWorkspace";

/**
 * Section navigation and section-body behaviour for the Settings foundation.
 *
 * The API client is mocked at the module boundary, so these tests assert the
 * UI's use of the typed 5.10 surface (which function is called, what is
 * rendered from its result) without asserting transport.
 */

const listProviderConnections = vi.fn();
const listModelConfigurations = vi.fn();
const listRuntimeConfigurations = vi.fn();
const getExecutionDefaults = vi.fn();

vi.mock("@ava/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@ava/api-client")>();
  return {
    ...actual,
    ApiClient: actual.ApiClient,
    listProviderConnections: (...args: unknown[]) => listProviderConnections(...args),
    listModelConfigurations: (...args: unknown[]) => listModelConfigurations(...args),
    listRuntimeConfigurations: (...args: unknown[]) => listRuntimeConfigurations(...args),
    getExecutionDefaults: (...args: unknown[]) => getExecutionDefaults(...args),
  };
});

const client = new ApiClient({ baseUrl: "http://localhost:99999" });

const contractVersion = "v1" as const;

function provider(overrides: Record<string, unknown> = {}) {
  return {
    provider_connection_id: "acme-primary",
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
    model_id: "acme-large",
    provider_connection_id: "acme-primary",
    provider_model_name: "acme-large-2026",
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
    runtime_configuration_id: "native",
    runtime_type: "native",
    display_name: "Native",
    enabled: true,
    contract_version: contractVersion,
    ...overrides,
  };
}

const unconfiguredDefaults = {
  configured: false,
  defaults: null,
  contract_version: contractVersion,
};

const configuredDefaults = {
  configured: true,
  defaults: {
    default_provider_connection_id: "acme-primary",
    default_model_id: "acme-large",
    default_runtime_configuration_id: "native",
    contract_version: contractVersion,
  },
  contract_version: contractVersion,
};

function sectionTab(name: string): HTMLElement {
  return screen.getByRole("tab", { name });
}

async function renderSettings() {
  render(<SettingsWorkspace client={client} />);
  await waitFor(() => {
    expect(screen.getByTestId("settings-workspace")).toBeTruthy();
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  listProviderConnections.mockResolvedValue({
    provider_connections: [],
    contract_version: contractVersion,
  });
  listModelConfigurations.mockResolvedValue({
    models: [],
    contract_version: contractVersion,
  });
  listRuntimeConfigurations.mockResolvedValue({
    runtimes: [],
    contract_version: contractVersion,
  });
  getExecutionDefaults.mockResolvedValue(unconfiguredDefaults);
});

describe("Settings section navigation", () => {
  it("shows the settings sections and starts on Providers", async () => {
    await renderSettings();

    for (const label of ["Providers", "Models", "Runtimes", "Defaults", "System Prompts"]) {
      expect(sectionTab(label)).toBeTruthy();
    }
    expect(sectionTab("Providers").getAttribute("aria-selected")).toBe("true");
    expect(sectionTab("Models").getAttribute("aria-selected")).toBe("false");
  });

  it("keeps the Settings shell and navigation present while a section loads", async () => {
    let release: (value: unknown) => void = () => {};
    listProviderConnections.mockImplementation(
      () => new Promise((resolve) => { release = resolve; }),
    );

    render(<SettingsWorkspace client={client} />);

    // The shell exists before any data resolves.
    expect(screen.getByTestId("settings-workspace")).toBeTruthy();
    expect(sectionTab("Models")).toBeTruthy();
    expect(screen.getByTestId("settings-loading")).toBeTruthy();

    release({ provider_connections: [], contract_version: contractVersion });
    await waitFor(() => expect(screen.getByTestId("settings-empty")).toBeTruthy());
  });

  it("keeps navigation usable when a section fails", async () => {
    listProviderConnections.mockRejectedValue(new Error("network down"));
    render(<SettingsWorkspace client={client} />);

    await waitFor(() => expect(screen.getByTestId("settings-error")).toBeTruthy());
    expect(sectionTab("Models")).toBeTruthy();

    fireEvent.click(sectionTab("Models"));
    expect(sectionTab("Models").getAttribute("aria-selected")).toBe("true");
  });

  it("selects each section and renders its panel", async () => {
    await renderSettings();

    fireEvent.click(sectionTab("Models"));
    expect(sectionTab("Models").getAttribute("aria-selected")).toBe("true");
    await waitFor(() => expect(listModelConfigurations).toHaveBeenCalled());

    fireEvent.click(sectionTab("Runtimes"));
    expect(sectionTab("Runtimes").getAttribute("aria-selected")).toBe("true");
    await waitFor(() => expect(listRuntimeConfigurations).toHaveBeenCalled());

    fireEvent.click(sectionTab("Defaults"));
    expect(sectionTab("Defaults").getAttribute("aria-selected")).toBe("true");
    await waitFor(() => expect(getExecutionDefaults).toHaveBeenCalled());
  });

  it("associates each control with its panel", async () => {
    await renderSettings();
    const controlled = sectionTab("Runtimes").getAttribute("aria-controls");
    expect(controlled).toBe("settings-section-runtimes");

    fireEvent.click(sectionTab("Runtimes"));
    await waitFor(() => {
      expect(
        screen.getByRole("tabpanel").getAttribute("id"),
      ).toBe("settings-section-runtimes");
    });
  });
});

describe("Settings provider section", () => {
  it("loads provider connections from the settings endpoint", async () => {
    listProviderConnections.mockResolvedValue({
      provider_connections: [provider()],
      contract_version: contractVersion,
    });
    await renderSettings();

    await waitFor(() => expect(screen.getByText("Acme Primary")).toBeTruthy());
    expect(listProviderConnections).toHaveBeenCalledWith(client);
  });

  it("shows the credential reference as configuration metadata", async () => {
    listProviderConnections.mockResolvedValue({
      provider_connections: [provider()],
      contract_version: contractVersion,
    });
    await renderSettings();

    const inventory = await screen.findByLabelText("Configured provider connections");
    const row = within(inventory).getByTestId("settings-inventory-entry");
    // Association and metadata are shown; the reference is a location, not a value.
    expect(row.textContent).toContain("acme");
    expect(row.textContent).toContain("https://api.acme.test");
  });

  it("keeps disabled provider connections visible and labelled", async () => {
    listProviderConnections.mockResolvedValue({
      provider_connections: [
        provider({
          provider_connection_id: "acme-retired",
          display_name: "Retired Acme",
          enabled: false,
        }),
        provider(),
      ],
      contract_version: contractVersion,
    });
    await renderSettings();

    await screen.findByText("Retired Acme");
    const inventory = screen.getByLabelText("Configured provider connections");
    expect(within(inventory).getByText("Disabled")).toBeTruthy();
    expect(within(inventory).getByText("Enabled")).toBeTruthy();
  });

  it("shows an empty state, not an error, when nothing is configured", async () => {
    await renderSettings();

    await waitFor(() =>
      expect(screen.getByText("No provider connections configured.")).toBeTruthy(),
    );
    expect(screen.queryByTestId("settings-error")).toBeNull();
  });
});

describe("Settings model section", () => {
  it("loads configured models", async () => {
    listModelConfigurations.mockResolvedValue({
      models: [model()],
      contract_version: contractVersion,
    });
    await renderSettings();
    fireEvent.click(sectionTab("Models"));

    await screen.findByText("Acme Large");
    const inventory = screen.getByLabelText("Configured models");
    expect(within(inventory).getByText(/remote/)).toBeTruthy();
  });

  it("keeps a disabled model visible", async () => {
    listModelConfigurations.mockResolvedValue({
      models: [model({ enabled: false })],
      contract_version: contractVersion,
    });
    await renderSettings();
    fireEvent.click(sectionTab("Models"));

    await screen.findByText("Acme Large");
    expect(screen.getByText("Disabled")).toBeTruthy();
  });

  it("shows an empty state when no models are configured", async () => {
    await renderSettings();
    fireEvent.click(sectionTab("Models"));

    await waitFor(() => expect(screen.getByText("No models configured.")).toBeTruthy());
  });
});

describe("Settings runtime section", () => {
  it("loads configured runtimes", async () => {
    listRuntimeConfigurations.mockResolvedValue({
      runtimes: [runtime()],
      contract_version: contractVersion,
    });
    await renderSettings();
    fireEvent.click(sectionTab("Runtimes"));

    await screen.findByText("Native");
    const inventory = screen.getByLabelText("Configured runtimes");
    const row = within(inventory).getAllByTestId("settings-inventory-entry")[0];
    // The row shows the stable configured id and, separately, the runtime type.
    expect(within(row).getByTestId("settings-inventory-entry-id").textContent).toBe(
      "native",
    );
    expect(within(row).getByTestId("settings-inventory-entry-meta").textContent).toBe(
      "native",
    );
  });

  it("keeps a disabled runtime visible", async () => {
    listRuntimeConfigurations.mockResolvedValue({
      runtimes: [runtime({ enabled: false })],
      contract_version: contractVersion,
    });
    await renderSettings();
    fireEvent.click(sectionTab("Runtimes"));

    await screen.findByText("Native");
    expect(screen.getByText("Disabled")).toBeTruthy();
  });

  it("shows an empty state when no runtimes are configured", async () => {
    await renderSettings();
    fireEvent.click(sectionTab("Runtimes"));

    await waitFor(() => expect(screen.getByText("No runtimes configured.")).toBeTruthy());
  });
});

describe("Settings defaults section", () => {
  it("renders configured defaults", async () => {
    getExecutionDefaults.mockResolvedValue(configuredDefaults);
    await renderSettings();
    fireEvent.click(sectionTab("Defaults"));

    const group = await screen.findByLabelText("Application execution defaults");
    expect(within(group).getByText("acme-primary")).toBeTruthy();
    expect(within(group).getByText("acme-large")).toBeTruthy();
    expect(within(group).getByText(/native/)).toBeTruthy();
  });

  it("treats configured:false as normal unconfigured state, not an error", async () => {
    getExecutionDefaults.mockResolvedValue(unconfiguredDefaults);
    await renderSettings();
    fireEvent.click(sectionTab("Defaults"));

    await waitFor(() =>
      expect(
        screen.getByText("Execution defaults are not configured."),
      ).toBeTruthy(),
    );
    expect(screen.queryByTestId("settings-error")).toBeNull();
    expect(screen.getByTestId("settings-empty")).toBeTruthy();
  });
});

describe("Settings error and retry", () => {
  it("shows a retryable error with no backend detail for a section", async () => {
    listProviderConnections.mockRejectedValue(new Error("ECONNREFUSED 10.0.0.5:8000"));
    await renderSettings();

    const alert = await screen.findByTestId("settings-error");
    expect(alert.getAttribute("role")).toBe("alert");
    // No stack trace, host, port, or thrown message leaks into the UI.
    expect(alert.textContent).not.toContain("ECONNREFUSED");
    expect(alert.textContent).not.toContain("10.0.0.5");
    expect(alert.textContent).not.toContain("at ");
  });

  it("retries the failed section on demand", async () => {
    listProviderConnections.mockRejectedValueOnce(new Error("boom"));
    await renderSettings();

    const alert = await screen.findByTestId("settings-error");
    const retry = within(alert).getByRole("button", { name: "Retry loading providers" });

    listProviderConnections.mockResolvedValue({
      provider_connections: [provider()],
      contract_version: contractVersion,
    });
    fireEvent.click(retry);

    await screen.findByText("Acme Primary");
    expect(screen.queryByTestId("settings-error")).toBeNull();
  });

  it("keeps one failure scoped to its own section", async () => {
    listProviderConnections.mockRejectedValue(new Error("boom"));
    listModelConfigurations.mockResolvedValue({
      models: [model()],
      contract_version: contractVersion,
    });
    await renderSettings();

    await screen.findByTestId("settings-error");
    fireEvent.click(sectionTab("Models"));

    // Models load normally while providers are still failing.
    await screen.findByText("Acme Large");
    expect(screen.queryByTestId("settings-error")).toBeNull();
  });
});

describe("Settings 5.15 boundary", () => {
  /**
   * 5.11 forbade management controls everywhere in Settings. 5.12 opened
   * provider management, 5.13 model management, 5.14 runtime management, and
   * 5.15 defaults editing — so no section is read-only any more.
   *
   * What replaces the old read-only assertion is narrower and more specific to
   * what defaults actually are. 5.8 made the repository singular: one record,
   * `get` and `set`, no list, no create, no delete. So the section must offer an
   * edit action and must offer no *Add* action (there is no second record to
   * add), and no section anywhere may offer Delete or Remove, because retirement
   * in this domain is done by disabling.
   *
   * The wording follows from the same fact: `Edit Defaults`, never
   * `Add Default`. The assertion checks both halves, since a bare "no Add" would
   * also pass a section that had simply lost its edit action.
   */
  it("offers an edit action and never an add action in the defaults section", async () => {
    listModelConfigurations.mockResolvedValue({
      models: [model()],
      contract_version: contractVersion,
    });
    listRuntimeConfigurations.mockResolvedValue({
      runtimes: [runtime()],
      contract_version: contractVersion,
    });
    getExecutionDefaults.mockResolvedValue(configuredDefaults);
    await renderSettings();

    fireEvent.click(sectionTab("Defaults"));
    expect(await screen.findByText("Edit Defaults")).toBeTruthy();

    for (const label of ["Add", "Add Default", "Create"]) {
      expect(
        screen.queryByRole("button", { name: new RegExp(label, "i") }),
        `Defaults: ${label}`,
      ).toBeNull();
    }
  });

  it("offers no delete or remove action anywhere, including defaults", async () => {
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
    getExecutionDefaults.mockResolvedValue(configuredDefaults);
    await renderSettings();

    fireEvent.click(sectionTab("Defaults"));
    await screen.findByText("Edit Defaults");
    for (const label of ["Delete", "Remove"]) {
      expect(
        screen.queryByRole("button", { name: new RegExp(label, "i") }),
        `Defaults: ${label}`,
      ).toBeNull();
    }
  });

  it("keeps delete and remove out of every managed section", async () => {
    listModelConfigurations.mockResolvedValue({
      models: [model()],
      contract_version: contractVersion,
    });
    listProviderConnections.mockResolvedValue({
      provider_connections: [provider()],
      contract_version: contractVersion,
    });
    listRuntimeConfigurations.mockResolvedValue({
      runtimes: [runtime()],
      contract_version: contractVersion,
    });
    getExecutionDefaults.mockResolvedValue(configuredDefaults);
    await renderSettings();

    for (const [section, present] of [
      ["Providers", "Acme Primary"],
      ["Models", "Acme Large"],
      ["Runtimes", "Native"],
    ] as const) {
      fireEvent.click(sectionTab(section));
      expect(await screen.findByText(present)).toBeTruthy();
      for (const label of ["Delete", "Remove"]) {
        expect(
          screen.queryByRole("button", { name: label }),
          `${section}: ${label}`,
        ).toBeNull();
        expect(
          screen.queryByRole("button", { name: new RegExp(label, "i") }),
          `${section}: ${label}`,
        ).toBeNull();
      }
    }
  });

  it("offers an enabled toggle only inside a modal, never on a row", async () => {
    listRuntimeConfigurations.mockResolvedValue({
      runtimes: [runtime()],
      contract_version: contractVersion,
    });
    await renderSettings();
    fireEvent.click(sectionTab("Runtimes"));
    await screen.findByText("Native");

    // A row may state state ("Disabled"), never offer to change it.
    expect(
      screen.queryAllByRole("checkbox").filter(
        (box) => !box.closest("[role='dialog']"),
      ),
    ).toHaveLength(0);

    // The change happens through the explicit edit dialog instead.
    fireEvent.click(screen.getByRole("button", { name: /Edit/ }));
    await waitFor(() => expect(screen.getByRole("dialog")).toBeTruthy());
    expect(
      within(screen.getByRole("dialog")).getByLabelText("Enabled"),
    ).toBeTruthy();
  });
});
