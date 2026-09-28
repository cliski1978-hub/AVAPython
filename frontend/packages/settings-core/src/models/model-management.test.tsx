import { ApiClient, ApiError } from "@ava/api-client";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SettingsWorkspace } from "../settings/SettingsWorkspace";

/**
 * Phase 5.13 model-configuration management.
 *
 * The API client is mocked at the module boundary, so these tests assert which
 * typed Settings wrapper the UI calls and with what payload. The relationship
 * rules get the most attention: a model's provider connection must be chosen
 * from configured connections, never typed, and never silently changed.
 */

const listModelConfigurations = vi.fn();
const createModelConfiguration = vi.fn();
const updateModelConfiguration = vi.fn();
const listProviderConnections = vi.fn();
const listRuntimeConfigurations = vi.fn();
const getExecutionDefaults = vi.fn();

vi.mock("@ava/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@ava/api-client")>();
  return {
    ...actual,
    ApiClient: actual.ApiClient,
    ApiError: actual.ApiError,
    listModelConfigurations: (...args: unknown[]) => listModelConfigurations(...args),
    createModelConfiguration: (...args: unknown[]) => createModelConfiguration(...args),
    updateModelConfiguration: (...args: unknown[]) => updateModelConfiguration(...args),
    listProviderConnections: (...args: unknown[]) => listProviderConnections(...args),
    listRuntimeConfigurations: (...args: unknown[]) => listRuntimeConfigurations(...args),
    getExecutionDefaults: (...args: unknown[]) => getExecutionDefaults(...args),
  };
});

const client = new ApiClient({ baseUrl: "http://localhost:99999" });
const contractVersion = "v1" as const;

function capabilities(overrides: Record<string, boolean> = {}) {
  return {
    chat: false,
    streaming: false,
    tool_calling: false,
    structured_output: false,
    vision: false,
    embeddings: false,
    reasoning: false,
    code_specialization: false,
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
    hosting_mode: "external" as const,
    capabilities: capabilities({ chat: true, streaming: true }),
    enabled: true,
    contract_version: contractVersion,
    ...overrides,
  };
}

function connection(overrides: Record<string, unknown> = {}) {
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

async function renderModels() {
  render(<SettingsWorkspace client={client} />);
  await screen.findByTestId("settings-workspace");
  fireEvent.click(screen.getByRole("tab", { name: "Models" }));
  await waitFor(() =>
    expect(screen.getByRole("tab", { selected: true }).textContent).toBe("Models"),
  );
}

function dialog(): HTMLElement {
  return screen.getByRole("dialog");
}

function addButton(): HTMLElement {
  return screen.getByRole("button", { name: "Add Model" });
}

function editButton(displayName: string): HTMLElement {
  return screen.getByRole("button", { name: `Edit ${displayName}` });
}

function setField(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
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
  listModelConfigurations.mockResolvedValue({
    models: [],
    contract_version: contractVersion,
  });
  listProviderConnections.mockResolvedValue({
    provider_connections: [connection()],
    contract_version: contractVersion,
  });
  listRuntimeConfigurations.mockResolvedValue({
    runtimes: [],
    contract_version: contractVersion,
  });
  getExecutionDefaults.mockResolvedValue({
    configured: false,
    defaults: null,
    contract_version: contractVersion,
  });
  createModelConfiguration.mockImplementation(() => resolved(model()));
  updateModelConfiguration.mockImplementation(() => resolved(model()));
});

describe("Models inventory actions", () => {
  it("offers Add Model, including when the inventory is empty", async () => {
    await renderModels();
    expect(addButton()).toBeTruthy();
  });

  it("offers Edit on every row, including a disabled model", async () => {
    listModelConfigurations.mockResolvedValue({
      models: [
        model(),
        model({
          model_id: "acme-small",
          display_name: "Acme Small",
          enabled: false,
        }),
      ],
      contract_version: contractVersion,
    });
    await renderModels();

    await screen.findByText("Acme Large");
    expect(editButton("Acme Large")).toBeTruthy();
    expect(screen.getByText("Acme Small")).toBeTruthy();
    expect(screen.getByText("Disabled")).toBeTruthy();
    expect(editButton("Acme Small")).toBeTruthy();
  });

  it("resolves the connection id to its configured display name", async () => {
    listModelConfigurations.mockResolvedValue({
      models: [model()],
      contract_version: contractVersion,
    });
    await renderModels();

    const row = (await screen.findByTestId("settings-inventory-entry")) as HTMLElement;
    const meta = within(row).getByTestId("settings-inventory-entry-meta").textContent ?? "";
    // The relationship reads as the operator named it, plus the provider-facing
    // name and hosting mode.
    expect(meta).toContain("Acme Primary");
    expect(meta).toContain("acme-large-2026");
    expect(within(row).getByTestId("settings-inventory-entry-id").textContent).toBe(
      "acme-large",
    );
  });

  it("falls back to the connection id when the connection list cannot load", async () => {
    listModelConfigurations.mockResolvedValue({
      models: [model()],
      contract_version: contractVersion,
    });
    listProviderConnections.mockRejectedValue(new Error("boom"));
    await renderModels();

    // Models stay readable and editable without the connection list.
    const row = (await screen.findByTestId("settings-inventory-entry")) as HTMLElement;
    const meta = within(row).getByTestId("settings-inventory-entry-meta").textContent ?? "";
    expect(meta).toContain("acme-primary");
  });

  it("summarises declared capabilities concisely", async () => {
    listModelConfigurations.mockResolvedValue({
      models: [model(), model({ model_id: "bare", capabilities: capabilities() })],
      contract_version: contractVersion,
    });
    await renderModels();

    const rows = await screen.findAllByTestId("settings-inventory-entry");
    const details = rows.map(
      (row) => within(row).getByTestId("settings-inventory-entry-details").textContent,
    );
    expect(details).toContain("chat · stream");
    // Nothing declared is a real state, and is stated rather than left blank.
    expect(details).toContain("No declared capabilities");
  });

  it("offers no delete or remove action", async () => {
    listModelConfigurations.mockResolvedValue({
      models: [model()],
      contract_version: contractVersion,
    });
    await renderModels();
    await screen.findByText("Acme Large");

    const destructive = screen
      .queryAllByRole("button")
      .map((button) => button.textContent ?? "")
      .filter((text) => /delete|remove/i.test(text));
    expect(destructive).toEqual([]);
  });
});

describe("Add Model", () => {
  async function openAdd() {
    await renderModels();
    fireEvent.click(addButton());
    await waitFor(() => expect(dialog()).toBeTruthy());
  }

  it("opens the settings modal with the domain's fields", async () => {
    await openAdd();

    expect(within(dialog()).getByText("Add Model")).toBeTruthy();
    for (const label of [
      "Model ID",
      "Provider connection",
      "Provider model name",
      "Display name",
      "Hosting mode",
      "Enabled",
    ]) {
      expect(within(dialog()).getByLabelText(label), label).toBeTruthy();
    }
    // Declared capabilities render as a group of checkboxes, one per flag.
    const group = within(dialog()).getByRole("group", { name: "Declared capabilities" });
    for (const flag of [
      "Chat",
      "Streaming",
      "Tool calling",
      "Structured output",
      "Vision",
      "Embeddings",
      "Reasoning",
      "Code specialization",
    ]) {
      expect(within(group).getByLabelText(flag), flag).toBeTruthy();
    }
  });

  it("populates the connection select from configured Settings providers", async () => {
    listProviderConnections.mockResolvedValue({
      provider_connections: [
        connection(),
        connection({
          provider_connection_id: "acme-standby",
          display_name: "Acme Standby",
          provider_id: "acme",
          enabled: false,
        }),
      ],
      contract_version: contractVersion,
    });
    await openAdd();

    const select = within(dialog()).getByLabelText(
      "Provider connection",
    ) as HTMLSelectElement;
    expect(select.tagName).toBe("SELECT");

    const options = within(select).getAllByRole("option") as HTMLOptionElement[];
    // The value is the connection id; the label is the configured display name.
    const enabled = options.find((option) => option.value === "acme-primary");
    expect(enabled?.textContent).toBe("Acme Primary");
    // A disabled connection stays visible in the configured inventory, and is
    // not offered for a new model.
    const disabled = options.find((option) => option.value === "acme-standby");
    expect(disabled?.textContent).toBe("Acme Standby (disabled)");
    expect(disabled?.disabled).toBe(true);
    // The provider *type* is never the selection value.
    expect(options.map((option) => option.value)).not.toContain("acme");
  });

  it("offers no free-text escape hatch for the relationship", async () => {
    await openAdd();

    const select = within(dialog()).getByLabelText("Provider connection");
    expect(select.tagName).toBe("SELECT");
    const labels = within(select)
      .getAllByRole("option")
      .map((option) => option.textContent ?? "")
      .join(" ");
    expect(labels).not.toMatch(/other/i);
    expect(labels).not.toMatch(/custom/i);
    // No provider creation is embedded in the model form.
    expect(within(dialog()).queryByRole("button", { name: /add provider/i })).toBeNull();
  });

  it("blocks creation and explains when no provider connection is configured", async () => {
    listProviderConnections.mockResolvedValue({
      provider_connections: [],
      contract_version: contractVersion,
    });
    await openAdd();

    expect(
      within(dialog()).getByText(/Add one under Settings → Providers first\./),
    ).toBeTruthy();
    expect(
      (screen.getByRole("button", { name: "Create model" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);

    // An operator can still reach the provider section rather than being stuck.
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(createModelConfiguration).not.toHaveBeenCalled();
  });

  it("defaults capabilities off and enabled on", async () => {
    await openAdd();

    const group = within(dialog()).getByRole("group", { name: "Declared capabilities" });
    for (const flag of ["Chat", "Vision", "Reasoning"]) {
      expect((within(group).getByLabelText(flag) as HTMLInputElement).checked).toBe(false);
    }
    expect((within(dialog()).getByLabelText("Enabled") as HTMLInputElement).checked).toBe(
      true,
    );
  });

  it("offers only the canonical hosting modes", async () => {
    await openAdd();

    const select = within(dialog()).getByLabelText("Hosting mode") as HTMLSelectElement;
    const values = within(select)
      .getAllByRole("option")
      .map((option) => (option as HTMLOptionElement).value);
    expect(values).toEqual(["local", "company_hosted", "external"]);
    // Friendly labels, canonical values.
    expect(within(select).getByRole("option", { name: "Company Hosted" })).toBeTruthy();
  });

  it("refuses to submit without the required fields", async () => {
    await openAdd();

    fireEvent.click(screen.getByRole("button", { name: "Create model" }));

    expect(createModelConfiguration).not.toHaveBeenCalled();
    expect(within(dialog()).getByText("A stable model ID is required.")).toBeTruthy();
    expect(within(dialog()).getByText("Choose a provider connection.")).toBeTruthy();
    expect(within(dialog()).getByText("A provider model name is required.")).toBeTruthy();
    expect(within(dialog()).getByText("A display name is required.")).toBeTruthy();
    expect(dialog()).toBeTruthy();
  });

  it("enforces the domain's distinctness rules", async () => {
    await openAdd();
    setField("Model ID", "acme-primary");
    setField("Provider model name", "acme-primary");
    fireEvent.change(within(dialog()).getByLabelText("Provider connection"), {
      target: { value: "acme-primary" },
    });

    fireEvent.click(screen.getByRole("button", { name: "Create model" }));

    expect(createModelConfiguration).not.toHaveBeenCalled();
    // One field carries one message, so the connection conflict is reported.
    expect(
      within(dialog()).getByText(
        "The model ID must be distinct from the provider connection ID.",
      ),
    ).toBeTruthy();
    expect(
      within(dialog()).getByText(
        "The provider model name must be distinct from the provider connection ID.",
      ),
    ).toBeTruthy();
  });

  it("reports a model id that collides with the provider model name", async () => {
    await openAdd();
    setField("Model ID", "acme-large-2026");
    fireEvent.change(within(dialog()).getByLabelText("Provider connection"), {
      target: { value: "acme-primary" },
    });
    setField("Provider model name", "acme-large-2026");

    fireEvent.click(screen.getByRole("button", { name: "Create model" }));

    expect(createModelConfiguration).not.toHaveBeenCalled();
    expect(
      within(dialog()).getByText(
        "The model ID must be distinct from the provider model name.",
      ),
    ).toBeTruthy();
  });

  it("never silently rewrites a hosting mode the build does not offer", async () => {
    // Defensive: the contract cannot produce this today, but a closed select
    // would otherwise coerce it to the first option and rewrite stored data.
    listModelConfigurations.mockResolvedValue({
      models: [model({ hosting_mode: "on_premise" })],
      contract_version: contractVersion,
    });
    await renderModels();
    fireEvent.click(await screen.findByRole("button", { name: "Edit Acme Large" }));
    await waitFor(() => expect(dialog()).toBeTruthy());

    const select = screen.getByLabelText("Hosting mode") as HTMLSelectElement;
    expect(select.value).toBe("on_premise");
    expect(
      within(select).getByRole("option", { name: /not offered by this build/ }),
    ).toBeTruthy();
  });

  it("closes on cancel without writing", async () => {
    await openAdd();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(createModelConfiguration).not.toHaveBeenCalled();
  });

  it("sends the typed payload, closes, and refreshes the inventory", async () => {
    const created = model({
      model_id: "qwen-coder",
      provider_model_name: "Qwen2.5-Coder-7B-Instruct",
      display_name: "Qwen Coder",
      hosting_mode: "external",
      capabilities: capabilities({ chat: true, tool_calling: true }),
    });
    listModelConfigurations
      .mockResolvedValueOnce({ models: [], contract_version: contractVersion })
      .mockResolvedValueOnce({ models: [created], contract_version: contractVersion });
    createModelConfiguration.mockImplementation(() => resolved(created));

    await openAdd();
    setField("Model ID", "qwen-coder");
    fireEvent.change(within(dialog()).getByLabelText("Provider connection"), {
      target: { value: "acme-primary" },
    });
    // Stored exactly as entered: no provider-specific formatting is imposed.
    setField("Provider model name", "Qwen2.5-Coder-7B-Instruct");
    setField("Display name", "Qwen Coder");
    fireEvent.change(within(dialog()).getByLabelText("Hosting mode"), {
      target: { value: "external" },
    });
    const group = within(dialog()).getByRole("group", { name: "Declared capabilities" });
    fireEvent.click(within(group).getByLabelText("Chat"));
    fireEvent.click(within(group).getByLabelText("Tool calling"));

    fireEvent.click(screen.getByRole("button", { name: "Create model" }));

    await waitFor(() =>
      expect(createModelConfiguration).toHaveBeenCalledWith(client, {
        model_id: "qwen-coder",
        provider_connection_id: "acme-primary",
        provider_model_name: "Qwen2.5-Coder-7B-Instruct",
        display_name: "Qwen Coder",
        hosting_mode: "external",
        capabilities: capabilities({ chat: true, tool_calling: true }),
        enabled: true,
      }),
    );

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(listModelConfigurations).toHaveBeenCalledTimes(2);
    expect(await screen.findByText("Qwen Coder")).toBeTruthy();
  });

  it("round-trips capabilities without inventing or dropping flags", async () => {
    await openAdd();
    setField("Model ID", "acme-large");
    fireEvent.change(within(dialog()).getByLabelText("Provider connection"), {
      target: { value: "acme-primary" },
    });
    setField("Provider model name", "acme-large-2026");
    setField("Display name", "Acme Large");
    const group = within(dialog()).getByRole("group", { name: "Declared capabilities" });
    for (const flag of ["Chat", "Streaming", "Tool calling", "Structured output"]) {
      fireEvent.click(within(group).getByLabelText(flag));
    }

    fireEvent.click(screen.getByRole("button", { name: "Create model" }));

    await waitFor(() => expect(createModelConfiguration).toHaveBeenCalled());
    const payload = createModelConfiguration.mock.calls[0][1] as {
      capabilities: Record<string, unknown>;
    };
    // Every declared flag is present and boolean, and the version is carried.
    expect(Object.keys(payload.capabilities).sort()).toEqual(
      [
        "chat",
        "code_specialization",
        "contract_version",
        "embeddings",
        "reasoning",
        "streaming",
        "structured_output",
        "tool_calling",
        "vision",
      ].sort(),
    );
    expect(payload.capabilities.chat).toBe(true);
    expect(payload.capabilities.vision).toBe(false);
    expect(payload.capabilities.contract_version).toBe("v1");
  });

  it("keeps the modal, the input, and a safe error when the save fails", async () => {
    createModelConfiguration.mockRejectedValue(
      new ApiError("Request failed", 400, {
        error_code: "duplicate_model",
        message: "Model configuration already exists: acme-large",
        contract_version: contractVersion,
      }),
    );
    await openAdd();
    setField("Model ID", "acme-large");
    fireEvent.change(within(dialog()).getByLabelText("Provider connection"), {
      target: { value: "acme-primary" },
    });
    setField("Provider model name", "acme-large-2026");
    setField("Display name", "Acme Large");
    fireEvent.click(screen.getByRole("button", { name: "Create model" }));

    const alert = await within(dialog()).findByRole("alert");
    expect(alert.textContent).toBe("Model configuration already exists: acme-large");
    expect(dialog()).toBeTruthy();
    expect((screen.getByLabelText("Display name") as HTMLInputElement).value).toBe(
      "Acme Large",
    );
    expect(alert.textContent).not.toContain("error_code");
  });

  it("reduces an unusable thrown value to a fixed sentence", async () => {
    createModelConfiguration.mockRejectedValue(
      new Error("psycopg2.errors.UniqueViolation at repo.py:88 (10.0.0.4:5432)"),
    );
    await openAdd();
    setField("Model ID", "acme-large");
    fireEvent.change(within(dialog()).getByLabelText("Provider connection"), {
      target: { value: "acme-primary" },
    });
    setField("Provider model name", "acme-large-2026");
    setField("Display name", "Acme Large");
    fireEvent.click(screen.getByRole("button", { name: "Create model" }));

    const alert = await within(dialog()).findByRole("alert");
    expect(alert.textContent).toBe("AVA could not save this model. Try again.");
    expect(alert.textContent).not.toContain("psycopg2");
    expect(alert.textContent).not.toContain("5432");
  });

  it("disables the primary action and blocks a duplicate submit while saving", async () => {
    const pending = deferred<unknown>();
    createModelConfiguration.mockImplementation(() => pending.promise);
    await openAdd();
    setField("Model ID", "acme-large");
    fireEvent.change(within(dialog()).getByLabelText("Provider connection"), {
      target: { value: "acme-primary" },
    });
    setField("Provider model name", "acme-large-2026");
    setField("Display name", "Acme Large");

    fireEvent.click(screen.getByRole("button", { name: "Create model" }));
    await waitFor(() =>
      expect(
        (screen.getByRole("button", { name: "Create model" }) as HTMLButtonElement)
          .disabled,
      ).toBe(true),
    );

    fireEvent.click(screen.getByRole("button", { name: "Create model" }));
    expect(createModelConfiguration).toHaveBeenCalledTimes(1);
    // Escape must not discard a submit that is still running.
    fireEvent.keyDown(dialog(), { key: "Escape" });
    expect(dialog()).toBeTruthy();
    expect((screen.getByLabelText("Display name") as HTMLInputElement).value).toBe(
      "Acme Large",
    );

    await act(async () => {
      pending.resolve(model());
      await pending.promise;
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});

describe("Edit Model", () => {
  it("prepopulates the record and locks identity and relationship", async () => {
    listModelConfigurations.mockResolvedValue({
      models: [model()],
      contract_version: contractVersion,
    });
    await renderModels();
    fireEvent.click(await screen.findByRole("button", { name: "Edit Acme Large" }));
    await waitFor(() => expect(dialog()).toBeTruthy());

    expect(within(dialog()).getByText("Edit Model")).toBeTruthy();
    const modelId = screen.getByLabelText("Model ID") as HTMLInputElement;
    expect(modelId.value).toBe("acme-large");
    expect(modelId.readOnly).toBe(true);

    // The association shows the configured display name and is not a picker.
    const linked = screen.getByLabelText("Provider connection") as HTMLInputElement;
    expect(linked.tagName).toBe("INPUT");
    expect(linked.readOnly).toBe(true);
    expect(linked.value).toBe("Acme Primary");

    // Mutable fields are editable and preloaded.
    expect((screen.getByLabelText("Provider model name") as HTMLInputElement).value).toBe(
      "acme-large-2026",
    );
    expect((screen.getByLabelText("Display name") as HTMLInputElement).value).toBe(
      "Acme Large",
    );
    expect((screen.getByLabelText("Hosting mode") as HTMLSelectElement).value).toBe(
      "external",
    );
    expect((screen.getByLabelText("Enabled") as HTMLInputElement).checked).toBe(true);

    const group = within(dialog()).getByRole("group", { name: "Declared capabilities" });
    expect((within(group).getByLabelText("Chat") as HTMLInputElement).checked).toBe(true);
    expect((within(group).getByLabelText("Streaming") as HTMLInputElement).checked).toBe(
      true,
    );
    expect((within(group).getByLabelText("Vision") as HTMLInputElement).checked).toBe(
      false,
    );
  });

  it("still shows the relationship when its connection is now disabled", async () => {
    listModelConfigurations.mockResolvedValue({
      models: [model()],
      contract_version: contractVersion,
    });
    listProviderConnections.mockResolvedValue({
      provider_connections: [
        connection({
          enabled: false,
        }),
      ],
      contract_version: contractVersion,
    });
    await renderModels();
    fireEvent.click(await screen.findByRole("button", { name: "Edit Acme Large" }));
    await waitFor(() => expect(dialog()).toBeTruthy());

    // A model whose connection was disabled later is still editable, and still
    // shows the relationship it was configured with.
    const linked = screen.getByLabelText("Provider connection") as HTMLInputElement;
    expect(linked.value).toBe("Acme Primary");
    expect(linked.readOnly).toBe(true);
    // And the save action is available: nothing forces the operator to change it.
    expect(
      (screen.getByRole("button", { name: "Save changes" }) as HTMLButtonElement)
        .disabled,
    ).toBe(false);
  });

  it("falls back to the connection id when the connection is not listed", async () => {
    listModelConfigurations.mockResolvedValue({
      models: [model()],
      contract_version: contractVersion,
    });
    listProviderConnections.mockResolvedValue({
      provider_connections: [],
      contract_version: contractVersion,
    });
    await renderModels();
    fireEvent.click(await screen.findByRole("button", { name: "Edit Acme Large" }));
    await waitFor(() => expect(dialog()).toBeTruthy());

    // An empty connection list is a create-time blocker, never an edit-time one.
    expect((screen.getByLabelText("Provider connection") as HTMLInputElement).value).toBe(
      "acme-primary",
    );
    expect(
      (screen.getByRole("button", { name: "Save changes" }) as HTMLButtonElement)
        .disabled,
    ).toBe(false);
  });

  it("updates mutable fields by path, preserving identity and relationship", async () => {
    const updated = model({
      display_name: "Acme Large (EU)",
      hosting_mode: "company_hosted",
      enabled: false,
      capabilities: capabilities({ chat: true, vision: true }),
    });
    listModelConfigurations
      .mockResolvedValueOnce({ models: [model()], contract_version: contractVersion })
      .mockResolvedValueOnce({ models: [updated], contract_version: contractVersion });
    updateModelConfiguration.mockImplementation(() => resolved(updated));

    await renderModels();
    fireEvent.click(await screen.findByRole("button", { name: "Edit Acme Large" }));
    await waitFor(() => expect(dialog()).toBeTruthy());

    setField("Display name", "Acme Large (EU)");
    fireEvent.change(within(dialog()).getByLabelText("Hosting mode"), {
      target: { value: "company_hosted" },
    });
    fireEvent.click(within(dialog()).getByLabelText("Enabled"));
    const group = within(dialog()).getByRole("group", { name: "Declared capabilities" });
    fireEvent.click(within(group).getByLabelText("Vision"));
    fireEvent.click(within(group).getByLabelText("Streaming"));

    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() =>
      expect(updateModelConfiguration).toHaveBeenCalledWith(
        client,
        "acme-large",
        expect.objectContaining({
          // Echoed unchanged, never reassigned.
          provider_connection_id: "acme-primary",
          display_name: "Acme Large (EU)",
          hosting_mode: "company_hosted",
          enabled: false,
          capabilities: capabilities({ chat: true, vision: true }),
        }),
      ),
    );
    // The model id is a path parameter and cannot appear in the body.
    const payload = updateModelConfiguration.mock.calls[0][2] as Record<string, unknown>;
    expect(payload.model_id).toBeUndefined();

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(listModelConfigurations).toHaveBeenCalledTimes(2);
    expect(await screen.findByText("Acme Large (EU)")).toBeTruthy();
  });

  it("keeps the dialog open with a safe message when the update is rejected", async () => {
    listModelConfigurations.mockResolvedValue({
      models: [model()],
      contract_version: contractVersion,
    });
    updateModelConfiguration.mockRejectedValue(
      new ApiError("Request failed", 400, {
        error_code: "unknown_provider_connection",
        message: "Unknown provider connection: acme-primary",
        contract_version: contractVersion,
      }),
    );

    await renderModels();
    fireEvent.click(await screen.findByRole("button", { name: "Edit Acme Large" }));
    await waitFor(() => expect(dialog()).toBeTruthy());
    setField("Display name", "Renamed");
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    const alert = await within(dialog()).findByRole("alert");
    expect(alert.textContent).toBe("Unknown provider connection: acme-primary");
    expect(dialog()).toBeTruthy();
    expect((screen.getByLabelText("Display name") as HTMLInputElement).value).toBe(
      "Renamed",
    );
  });
});

describe("Model capability helpers", () => {
  it("keeps a declared version when converting", async () => {
    const { capabilitiesFrom, capabilityToggles, emptyCapabilities } = await import(
      "../models/modelCapabilities"
    );
    expect(emptyCapabilities().contract_version).toBe("v1");
    const toggles = capabilityToggles(capabilities({ chat: true, vision: true }));
    expect(toggles.chat).toBe(true);
    expect(toggles.vision).toBe(true);
    expect(toggles.embeddings).toBe(false);
    const rebuilt = capabilitiesFrom(toggles, "v1");
    expect(rebuilt.chat).toBe(true);
    expect(rebuilt.vision).toBe(true);
    expect(rebuilt.structured_output).toBe(false);
  });
});
