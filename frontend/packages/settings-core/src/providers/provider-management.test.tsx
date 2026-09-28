import { ApiClient, ApiError } from "@ava/api-client";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SettingsWorkspace } from "../settings/SettingsWorkspace";

/**
 * Phase 5.12 provider-connection management.
 *
 * The API client is mocked at the module boundary, so these tests assert which
 * typed Settings wrapper the UI calls and with what payload, without asserting
 * transport. Two things are deliberately checked beyond the happy path: that a
 * failed save cannot lose the operator's input or leak a raw thrown value, and
 * that no secret-shaped control exists anywhere in the form.
 */

const listProviderConnections = vi.fn();
const createProviderConnection = vi.fn();
const updateProviderConnection = vi.fn();
const getModelProviders = vi.fn();
const listModelConfigurations = vi.fn();
const listRuntimeConfigurations = vi.fn();
const getExecutionDefaults = vi.fn();

vi.mock("@ava/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@ava/api-client")>();
  return {
    ...actual,
    ApiClient: actual.ApiClient,
    ApiError: actual.ApiError,
    listProviderConnections: (...args: unknown[]) => listProviderConnections(...args),
    createProviderConnection: (...args: unknown[]) => createProviderConnection(...args),
    updateProviderConnection: (...args: unknown[]) => updateProviderConnection(...args),
    getModelProviders: (...args: unknown[]) => getModelProviders(...args),
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

function discovery(ids: string[] = ["acme", "openai"]) {
  return {
    default_provider_id: ids[0] ?? null,
    providers: ids.map((providerId) => ({
      provider_id: providerId,
      is_default: providerId === ids[0],
      model_info: {},
      health: {},
      contract_version: contractVersion,
    })),
    contract_version: contractVersion,
  };
}

async function renderSettings() {
  render(<SettingsWorkspace client={client} />);
  await screen.findByTestId("settings-workspace");
}

function dialog(): HTMLElement {
  return screen.getByRole("dialog");
}

function addButton(): HTMLElement {
  return screen.getByRole("button", { name: "Add Provider" });
}

function editButton(displayName: string): HTMLElement {
  return screen.getByRole("button", { name: `Edit ${displayName}` });
}

function setField(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

/** The wrapper's returned record is irrelevant to the UI; it refreshes instead. */
function resolved<T>(value: T) {
  return Promise.resolve(value);
}

/** A promise plus the handles to settle it from the test body. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

beforeEach(() => {
  vi.clearAllMocks();
  listProviderConnections.mockResolvedValue({
    provider_connections: [],
    contract_version: contractVersion,
  });
  listModelConfigurations.mockResolvedValue({ models: [], contract_version: contractVersion });
  listRuntimeConfigurations.mockResolvedValue({
    runtimes: [],
    contract_version: contractVersion,
  });
  getExecutionDefaults.mockResolvedValue({
    configured: false,
    defaults: null,
    contract_version: contractVersion,
  });
  getModelProviders.mockResolvedValue(discovery());
  createProviderConnection.mockImplementation(() => resolved(provider()));
  updateProviderConnection.mockImplementation(() => resolved(provider()));
});

describe("Providers inventory actions", () => {
  it("offers Add Provider, including when the inventory is empty", async () => {
    await renderSettings();
    expect(addButton()).toBeTruthy();
  });

  it("offers Edit on every row, including a disabled one", async () => {
    listProviderConnections.mockResolvedValue({
      provider_connections: [
        provider(),
        provider({
          provider_connection_id: "acme-standby",
          display_name: "Acme Standby",
          enabled: false,
        }),
      ],
      contract_version: contractVersion,
    });
    await renderSettings();

    await screen.findByText("Acme Primary");
    expect(editButton("Acme Primary")).toBeTruthy();
    // A disabled connection stays visible and stays editable.
    expect(screen.getByText("Acme Standby")).toBeTruthy();
    expect(screen.getByText("Disabled")).toBeTruthy();
    expect(editButton("Acme Standby")).toBeTruthy();
  });

  it("shows id, type, endpoint, and credential reference without a secret", async () => {
    listProviderConnections.mockResolvedValue({
      provider_connections: [provider()],
      contract_version: contractVersion,
    });
    await renderSettings();

    const row = (await screen.findByTestId("settings-inventory-entry")) as HTMLElement;
    expect(within(row).getByTestId("settings-inventory-entry-id").textContent).toBe(
      "acme-primary",
    );
    const meta = within(row).getByTestId("settings-inventory-entry-meta").textContent ?? "";
    expect(meta).toContain("acme");
    expect(meta).toContain("https://api.acme.test");
    expect(meta).toContain("env:ACME_API_KEY");
    // A reference names a location. No resolved value is ever rendered.
    expect(screen.queryByText(/sk-[a-z0-9]/i)).toBeNull();
  });

  it("offers no delete or remove action", async () => {
    listProviderConnections.mockResolvedValue({
      provider_connections: [provider()],
      contract_version: contractVersion,
    });
    await renderSettings();
    await screen.findByText("Acme Primary");

    for (const label of [/^Delete/, /^Remove/]) {
      expect(screen.queryByRole("button", { name: label })).toBeNull();
    }
    expect(deleteButtonNames()).toEqual([]);
  });
});

function deleteButtonNames(): string[] {
  return screen
    .queryAllByRole("button")
    .map((button) => button.textContent ?? "")
    .filter((text) => /delete|remove/i.test(text));
}

describe("Add Provider", () => {
  async function openAdd() {
    await renderSettings();
    fireEvent.click(addButton());
    await waitFor(() => expect(dialog()).toBeTruthy());
  }

  /**
   * Regression, found in Phase 5.14.
   *
   * The "Other provider type…" escape hatch was unreachable: choosing it
   * cleared the value, and the predicate that decides whether to show the
   * custom text field required a non-empty value. The field therefore never
   * appeared, and a provider type outside the discovered list could not be
   * entered at all — the exact case the escape hatch exists for. These two
   * tests were absent in 5.12; the second guards the late-discovery path.
   */
  it("reveals the custom type field when the escape hatch is chosen", async () => {
    await openAdd();
    await waitFor(() => expect(getModelProviders).toHaveBeenCalledWith(client));

    // Nothing shown while the operator has not asked for it.
    expect(
      within(dialog()).queryByLabelText("Provider type (custom)"),
    ).toBeNull();

    fireEvent.change(within(dialog()).getByLabelText("Provider type"), {
      target: { value: "__custom__" },
    });

    const custom = within(dialog()).getByLabelText(
      "Provider type (custom)",
    ) as HTMLInputElement;
    expect(custom.tagName).toBe("INPUT");
    // The select keeps showing the escape-hatch choice, not a blank placeholder.
    expect(
      (within(dialog()).getByLabelText("Provider type") as HTMLSelectElement).value,
    ).toBe("__custom__");
  });

  it("sends a custom provider type that discovery did not report", async () => {
    await openAdd();
    await waitFor(() => expect(getModelProviders).toHaveBeenCalledWith(client));
    setField("Connection ID", "acme-primary");
    fireEvent.change(within(dialog()).getByLabelText("Provider type"), {
      target: { value: "__custom__" },
    });
    setField("Provider type (custom)", "langgraph-provider");
    setField("Display name", "LangGraph");

    fireEvent.click(screen.getByRole("button", { name: "Create provider" }));

    await waitFor(() =>
      expect(createProviderConnection).toHaveBeenCalledWith(
        client,
        expect.objectContaining({ provider_id: "langgraph-provider" }),
      ),
    );
  });

  it("opens the settings modal with the domain's fields", async () => {
    await openAdd();

    expect(within(dialog()).getByText("Add Provider")).toBeTruthy();
    for (const label of [
      "Connection ID",
      "Provider type",
      "Display name",
      "Endpoint",
      "Enabled",
      "Credential reference",
    ]) {
      expect(within(dialog()).getByLabelText(label), label).toBeTruthy();
    }
  });

  it("offers provider types discovered from /model-providers, not from settings", async () => {
    await openAdd();

    // Discovery has answered by now; the select lists exactly those types.
    await waitFor(() => expect(getModelProviders).toHaveBeenCalledWith(client));
    const select = within(dialog()).getByLabelText(
      "Provider type",
    ) as HTMLSelectElement;
    expect(select.tagName).toBe("SELECT");
    const values = within(select)
      .getAllByRole("option")
      .map((option) => (option as HTMLOptionElement).value);
    expect(values).toContain("acme");
    expect(values).toContain("openai");
    // A configured connection must not become a provider type: the two datasets
    // are never merged.
    expect(values).not.toContain("acme-primary");
  });

  it("defaults enabled to true", async () => {
    await openAdd();

    const enabled = within(dialog()).getByLabelText("Enabled") as HTMLInputElement;
    expect(enabled.checked).toBe(true);
  });

  it("has no secret-shaped field", async () => {
    await openAdd();

    const labels = within(dialog())
      .queryAllByRole("textbox")
      .flatMap((box) => [
        box.getAttribute("aria-label") ?? "",
        document.querySelector(`label[for="${box.id}"]`)?.textContent ?? "",
      ])
      .join(" ")
      .toLowerCase();
    for (const forbidden of ["api key", "apikey", "password", "secret", "token"]) {
      expect(labels, forbidden).not.toContain(forbidden);
    }
    // The one credential concept is the reference.
    expect(within(dialog()).getByLabelText("Credential reference")).toBeTruthy();
  });

  it("refuses to submit without the required fields and explains why", async () => {
    await openAdd();

    fireEvent.click(screen.getByRole("button", { name: "Create provider" }));

    expect(createProviderConnection).not.toHaveBeenCalled();
    expect(within(dialog()).getByText("A stable connection ID is required.")).toBeTruthy();
    expect(within(dialog()).getByText("Choose or enter a provider type.")).toBeTruthy();
    expect(within(dialog()).getByText("A display name is required.")).toBeTruthy();
    expect(dialog()).toBeTruthy();
  });

  it("closes on cancel without writing", async () => {
    await openAdd();

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(createProviderConnection).not.toHaveBeenCalled();
  });

  it("closes on Escape without writing", async () => {
    await openAdd();

    fireEvent.keyDown(dialog(), { key: "Escape" });

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(createProviderConnection).not.toHaveBeenCalled();
  });

  it("sends the typed create payload, closes, and refreshes the inventory", async () => {
    const created = provider({
      provider_connection_id: "openai-prod",
      provider_id: "openai",
      display_name: "OpenAI Production",
      endpoint: null,
      credential_reference: null,
    });
    listProviderConnections
      .mockResolvedValueOnce({ provider_connections: [], contract_version: contractVersion })
      .mockResolvedValueOnce({ provider_connections: [created], contract_version: contractVersion });
    createProviderConnection.mockImplementation(() => resolved(created));

    await openAdd();
    await waitFor(() => expect(getModelProviders).toHaveBeenCalled());
    setField("Connection ID", "openai-prod");
    fireEvent.change(within(dialog()).getByLabelText("Provider type"), {
      target: { value: "openai" },
    });
    setField("Display name", "OpenAI Production");
    // Endpoint and credential reference stay empty and must be sent as null,
    // not as empty strings.
    fireEvent.click(screen.getByRole("button", { name: "Create provider" }));

    await waitFor(() =>
      expect(createProviderConnection).toHaveBeenCalledWith(client, {
        provider_connection_id: "openai-prod",
        provider_id: "openai",
        display_name: "OpenAI Production",
        endpoint: null,
        enabled: true,
        credential_reference: null,
      }),
    );

    // Closes, then re-reads the list rather than patching it optimistically.
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(listProviderConnections).toHaveBeenCalledTimes(2);
    expect(await screen.findByText("OpenAI Production")).toBeTruthy();
  });

  it("sends a provided endpoint and credential reference verbatim", async () => {
    await openAdd();
    await waitFor(() => expect(getModelProviders).toHaveBeenCalled());
    setField("Connection ID", "acme-prod");
    fireEvent.change(within(dialog()).getByLabelText("Provider type"), {
      target: { value: "acme" },
    });
    setField("Display name", "Acme Prod");
    setField("Endpoint", "acme-internal:9000");
    setField("Credential reference", "env:ACME_API_KEY");
    fireEvent.click(screen.getByRole("button", { name: "Create provider" }));

    await waitFor(() =>
      expect(createProviderConnection).toHaveBeenCalledWith(
        client,
        expect.objectContaining({
          // No browser URL validation: the backend treats endpoint as opaque.
          endpoint: "acme-internal:9000",
          credential_reference: "env:ACME_API_KEY",
        }),
      ),
    );
  });

  it("keeps the modal, the input, and a safe error when the save fails", async () => {
    createProviderConnection.mockRejectedValue(
      new ApiError("Request failed", 409, {
        error_code: "provider_connection_exists",
        message: "A provider connection with that ID already exists: openai-prod",
        contract_version: contractVersion,
      }),
    );
    await openAdd();
    await waitFor(() => expect(getModelProviders).toHaveBeenCalled());
    setField("Connection ID", "openai-prod");
    fireEvent.change(within(dialog()).getByLabelText("Provider type"), {
      target: { value: "openai" },
    });
    setField("Display name", "OpenAI Production");
    fireEvent.click(screen.getByRole("button", { name: "Create provider" }));

    // The backend's designed message is shown…
    const alert = await within(dialog()).findByRole("alert");
    expect(alert.textContent).toBe(
      "A provider connection with that ID already exists: openai-prod",
    );
    // …the dialog stays open with the input intact…
    expect(dialog()).toBeTruthy();
    expect((screen.getByLabelText("Display name") as HTMLInputElement).value).toBe(
      "OpenAI Production",
    );
    expect((screen.getByLabelText("Connection ID") as HTMLInputElement).value).toBe(
      "openai-prod",
    );
    // …and no raw thrown value leaks.
    expect(alert.textContent).not.toContain("Request failed");
    expect(alert.textContent).not.toContain("error_code");
  });

  it("replaces an unusable thrown value with a fixed sentence", async () => {
    createProviderConnection.mockRejectedValue(
      new Error("connect ECONNREFUSED 127.0.0.1:8000 at Object.<anonymous> (/app/main.py:42)"),
    );
    await openAdd();
    await waitFor(() => expect(getModelProviders).toHaveBeenCalled());
    setField("Connection ID", "acme-prod");
    fireEvent.change(within(dialog()).getByLabelText("Provider type"), {
      target: { value: "acme" },
    });
    setField("Display name", "Acme Prod");
    fireEvent.click(screen.getByRole("button", { name: "Create provider" }));

    const alert = await within(dialog()).findByRole("alert");
    expect(alert.textContent).toBe("AVA could not save this provider. Try again.");
    expect(alert.textContent).not.toContain("ECONNREFUSED");
    expect(alert.textContent).not.toContain("main.py");
  });

  it("saves when the form itself is submitted", async () => {
    await openAdd();
    await waitFor(() => expect(getModelProviders).toHaveBeenCalled());
    setField("Connection ID", "acme-prod");
    fireEvent.change(within(dialog()).getByLabelText("Provider type"), {
      target: { value: "acme" },
    });
    setField("Display name", "Acme Prod");

    // Exercises the form's own submit path, which is what the browser's
    // implicit submission (Enter in a field) triggers.
    fireEvent.submit(within(dialog()).getByRole("textbox", { name: "Display name" }).closest("form")!);

    await waitFor(() => expect(createProviderConnection).toHaveBeenCalledTimes(1));
  });

  it("disables the primary action and blocks a duplicate submit while saving", async () => {
    const pending = deferred<unknown>();
    createProviderConnection.mockImplementation(() => pending.promise);
    await openAdd();
    await waitFor(() => expect(getModelProviders).toHaveBeenCalled());
    setField("Connection ID", "acme-prod");
    fireEvent.change(within(dialog()).getByLabelText("Provider type"), {
      target: { value: "acme" },
    });
    setField("Display name", "Acme Prod");

    const primary = screen.getByRole("button", { name: "Create provider" });
    expect((primary as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(primary);
    await waitFor(() =>
      expect(
        (screen.getByRole("button", { name: "Create provider" }) as HTMLButtonElement)
          .disabled,
      ).toBe(true),
    );

    // A second click while the first is in flight must not issue a second write.
    fireEvent.click(screen.getByRole("button", { name: "Create provider" }));
    expect(createProviderConnection).toHaveBeenCalledTimes(1);
    // Escape must not discard a submit that is still running.
    fireEvent.keyDown(dialog(), { key: "Escape" });
    expect(dialog()).toBeTruthy();
    // The form's values survive the wait.
    expect((screen.getByLabelText("Display name") as HTMLInputElement).value).toBe(
      "Acme Prod",
    );

    await act(async () => {
      pending.resolve(provider());
      await pending.promise;
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});

describe("Edit Provider", () => {
  it("prepopulates the record and freezes both identity fields", async () => {
    listProviderConnections.mockResolvedValue({
      provider_connections: [provider()],
      contract_version: contractVersion,
    });
    await renderSettings();
    fireEvent.click(await screen.findByRole("button", { name: "Edit Acme Primary" }));
    await waitFor(() => expect(dialog()).toBeTruthy());

    expect(within(dialog()).getByText("Edit Provider")).toBeTruthy();
    const connectionId = screen.getByLabelText("Connection ID") as HTMLInputElement;
    const providerType = screen.getByLabelText("Provider type") as HTMLInputElement;

    expect(connectionId.value).toBe("acme-primary");
    expect(connectionId.readOnly).toBe(true);
    expect(providerType.value).toBe("acme");
    expect(providerType.readOnly).toBe(true);
    // On edit the type is a fixed value, not a list: there is nothing to pick.
    expect(providerType.tagName).toBe("INPUT");

    // Mutable fields are editable and preloaded.
    expect((screen.getByLabelText("Display name") as HTMLInputElement).value).toBe(
      "Acme Primary",
    );
    expect((screen.getByLabelText("Endpoint") as HTMLInputElement).value).toBe(
      "https://api.acme.test",
    );
    expect((screen.getByLabelText("Credential reference") as HTMLInputElement).value).toBe(
      "env:ACME_API_KEY",
    );
    expect((screen.getByLabelText("Enabled") as HTMLInputElement).checked).toBe(true);

    // Editing the form never calls discovery: there is no type to choose.
    expect(getModelProviders).not.toHaveBeenCalled();
  });

  it("updates by path, preserving identity, and refreshes the row", async () => {
    const updated = provider({
      display_name: "Acme Primary (eu)",
      enabled: false,
    });
    listProviderConnections
      .mockResolvedValueOnce({
        provider_connections: [provider()],
        contract_version: contractVersion,
      })
      .mockResolvedValueOnce({
        provider_connections: [updated],
        contract_version: contractVersion,
      });
    updateProviderConnection.mockImplementation(() => resolved(updated));

    await renderSettings();
    fireEvent.click(await screen.findByRole("button", { name: "Edit Acme Primary" }));
    await waitFor(() => expect(dialog()).toBeTruthy());

    setField("Display name", "Acme Primary (eu)");
    fireEvent.click(within(dialog()).getByLabelText("Enabled"));
    // Clearing an optional field sends null, not an empty string.
    setField("Endpoint", "");
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() =>
      expect(updateProviderConnection).toHaveBeenCalledWith(
        client,
        "acme-primary",
        expect.objectContaining({
          // The id is a path parameter; the type is echoed unchanged.
          provider_id: "acme",
          display_name: "Acme Primary (eu)",
          enabled: false,
          endpoint: null,
          credential_reference: "env:ACME_API_KEY",
        }),
      ),
    );
    // The payload cannot carry a connection id, so identity cannot be rewritten.
    const payload = updateProviderConnection.mock.calls[0][2] as Record<string, unknown>;
    expect(payload.provider_connection_id).toBeUndefined();

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(listProviderConnections).toHaveBeenCalledTimes(2);
    expect(await screen.findByText("Acme Primary (eu)")).toBeTruthy();
  });

  it("keeps the dialog open with a safe message when the update conflicts", async () => {
    listProviderConnections.mockResolvedValue({
      provider_connections: [provider()],
      contract_version: contractVersion,
    });
    updateProviderConnection.mockRejectedValue(
      new ApiError("Request failed", 409, {
        error_code: "provider_type_immutable",
        message: "provider_id is immutable for acme-primary",
        contract_version: contractVersion,
      }),
    );

    await renderSettings();
    fireEvent.click(await screen.findByRole("button", { name: "Edit Acme Primary" }));
    await waitFor(() => expect(dialog()).toBeTruthy());
    setField("Display name", "Renamed");
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    const alert = await within(dialog()).findByRole("alert");
    expect(alert.textContent).toBe("provider_id is immutable for acme-primary");
    expect(dialog()).toBeTruthy();
    expect((screen.getByLabelText("Display name") as HTMLInputElement).value).toBe(
      "Renamed",
    );
  });
});
