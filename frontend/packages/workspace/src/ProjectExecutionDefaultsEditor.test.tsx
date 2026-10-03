// @vitest-environment jsdom
import { ApiClient, getProjectExecutionDefaults, getRuntimes, listModelConfigurations, listProviderConnections, updateProjectExecutionDefaults } from "@ava/api-client";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProjectExecutionDefaultsEditor } from "./ProjectExecutionDefaultsEditor";

vi.mock("@ava/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@ava/api-client")>();
  return {
    ...actual,
    getProjectExecutionDefaults: vi.fn(),
    updateProjectExecutionDefaults: vi.fn(),
    getRuntimes: vi.fn(),
    listModelConfigurations: vi.fn(),
    listProviderConnections: vi.fn(),
  };
});

const client = new ApiClient({ baseUrl: "http://localhost:99999" });
const defaults = (runtime_key: string | null = null, model_id: string | null = null, runtime_available: boolean | null = null) => ({
  project_id: "project-a",
  runtime_key,
  model_id,
  runtime_available,
  contract_version: "v1" as const,
});
const runtimes = {
  contract_version: "v1" as const,
  default_runtime_id: "native",
  runtimes: ["native", "openhands"].map((runtime_id) => ({
    runtime_info: { runtime_id, display_name: runtime_id === "native" ? "AVA Native" : "OpenHands" },
    is_default: runtime_id === "native",
    contract_version: "v1" as const,
  })),
};
const models = {
  contract_version: "v1" as const,
  models: [
    { model_id: "model-a", display_name: "Model A", provider_connection_id: "connection-a", enabled: true, provider_model_name: "native-a", hosting_mode: "company_hosted" as const, capabilities: { chat: true, streaming: false, tool_calling: false, structured_output: false, vision: false, embeddings: false, reasoning: false, code_specialization: false, contract_version: "v1" as const }, contract_version: "v1" as const },
    { model_id: "model-b", display_name: "Model B", provider_connection_id: "connection-b", enabled: true, provider_model_name: "native-b", hosting_mode: "company_hosted" as const, capabilities: { chat: true, streaming: false, tool_calling: false, structured_output: false, vision: false, embeddings: false, reasoning: false, code_specialization: false, contract_version: "v1" as const }, contract_version: "v1" as const },
    { model_id: "model-disabled", display_name: "Disabled Model", provider_connection_id: "connection-a", enabled: false, provider_model_name: "native-disabled", hosting_mode: "company_hosted" as const, capabilities: { chat: true, streaming: false, tool_calling: false, structured_output: false, vision: false, embeddings: false, reasoning: false, code_specialization: false, contract_version: "v1" as const }, contract_version: "v1" as const },
  ],
};
const connections = {
  contract_version: "v1" as const,
  provider_connections: [
    { provider_connection_id: "connection-a", provider_id: "openai-compatible", display_name: "Primary connection", endpoint: null, enabled: true, credential_reference: null, contract_version: "v1" as const },
    { provider_connection_id: "connection-b", provider_id: "local", display_name: "Local connection", endpoint: null, enabled: true, credential_reference: null, contract_version: "v1" as const },
  ],
};

function renderEditor(projectId = "project-a") {
  return render(<ProjectExecutionDefaultsEditor client={client} projectId={projectId} />);
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(getProjectExecutionDefaults).mockResolvedValue(defaults());
  vi.mocked(getRuntimes).mockResolvedValue(runtimes);
  vi.mocked(listModelConfigurations).mockResolvedValue(models);
  vi.mocked(listProviderConnections).mockResolvedValue(connections);
  vi.mocked(updateProjectExecutionDefaults).mockImplementation(async (_client, projectId, request) => ({
    ...defaults(request.runtime_key ?? null, request.model_id ?? null),
    project_id: projectId,
    contract_version: "v1",
  }));
});

describe("Project execution defaults", () => {
  it("loads stored nulls as application defaults and lists registry keys and enabled configured models", async () => {
    renderEditor();
    const runtime = await screen.findByLabelText("Preferred Runtime") as HTMLSelectElement;
    const model = screen.getByLabelText("Preferred Model") as HTMLSelectElement;
    expect(runtime.value).toBe("");
    expect(model.value).toBe("");
    expect(runtime.querySelector('option[value=""]')?.textContent).toBe("Use application default");
    expect(model.querySelector('option[value=""]')?.textContent).toBe("Use application default");
    expect(screen.getByRole("option", { name: "native — AVA Native" })).toBeTruthy();
    expect(screen.getByRole("option", { name: /Model B.*Local connection/ })).toBeTruthy();
    expect(screen.queryByRole("option", { name: /Disabled Model/ })).toBeNull();
    expect(getProjectExecutionDefaults).toHaveBeenCalledTimes(1);
    expect(getProjectExecutionDefaults).toHaveBeenCalledWith(client, "project-a");
    expect(screen.getByText(/Runtime and model are resolved independently/)).toBeTruthy();
    expect(screen.getByText(/Explicit run choice.*Project default.*Application default.*System fallback/)).toBeTruthy();
  });

  it("renders persisted runtime-only, model-only, and both-values states without resolving defaults", async () => {
    vi.mocked(getProjectExecutionDefaults).mockResolvedValueOnce(defaults("native", null));
    const first = renderEditor();
    expect((await screen.findByLabelText("Preferred Runtime") as HTMLSelectElement).value).toBe("native");
    expect((screen.getByLabelText("Preferred Model") as HTMLSelectElement).value).toBe("");
    first.unmount();

    vi.mocked(getProjectExecutionDefaults).mockResolvedValueOnce(defaults(null, "model-b"));
    const second = renderEditor();
    await waitFor(() => expect((screen.getByLabelText("Preferred Runtime") as HTMLSelectElement).value).toBe(""));
    expect((screen.getByLabelText("Preferred Model") as HTMLSelectElement).value).toBe("model-b");
    second.unmount();

    vi.mocked(getProjectExecutionDefaults).mockResolvedValueOnce(defaults("openhands", "model-a"));
    renderEditor();
    await waitFor(() => expect((screen.getByLabelText("Preferred Runtime") as HTMLSelectElement).value).toBe("openhands"));
    expect((screen.getByLabelText("Preferred Model") as HTMLSelectElement).value).toBe("model-a");
  });

  it("saves only the changed runtime, preserving the model by omission", async () => {
    vi.mocked(getProjectExecutionDefaults).mockResolvedValue(defaults(null, "model-a"));
    renderEditor();
    fireEvent.change(await screen.findByLabelText("Preferred Runtime"), { target: { value: "native" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(updateProjectExecutionDefaults).toHaveBeenCalledWith(client, "project-a", { runtime_key: "native" }));
    expect(updateProjectExecutionDefaults).not.toHaveBeenCalledWith(client, "project-a", expect.objectContaining({ model_id: null }));
  });

  it("saves only the changed model, preserving the runtime by omission", async () => {
    vi.mocked(getProjectExecutionDefaults).mockResolvedValue(defaults("native", null));
    renderEditor();
    fireEvent.change(await screen.findByLabelText("Preferred Model"), { target: { value: "model-b" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(updateProjectExecutionDefaults).toHaveBeenCalledWith(client, "project-a", { model_id: "model-b" }));
  });

  it("clears just the runtime with an explicit null", async () => {
    vi.mocked(getProjectExecutionDefaults).mockResolvedValue(defaults("native", "model-a"));
    renderEditor();
    fireEvent.change(await screen.findByLabelText("Preferred Runtime"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(updateProjectExecutionDefaults).toHaveBeenCalledWith(client, "project-a", { runtime_key: null }));
  });

  it("clears just the model with an explicit null", async () => {
    vi.mocked(getProjectExecutionDefaults).mockResolvedValue(defaults("native", "model-a"));
    renderEditor();
    fireEvent.change(await screen.findByLabelText("Preferred Model"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(updateProjectExecutionDefaults).toHaveBeenCalledWith(client, "project-a", { model_id: null }));
  });

  it("clears both values only when the user chooses application defaults", async () => {
    vi.mocked(getProjectExecutionDefaults).mockResolvedValue(defaults("native", "model-a"));
    renderEditor();
    fireEvent.click(await screen.findByRole("button", { name: "Use application defaults" }));
    expect((screen.getByLabelText("Preferred Runtime") as HTMLSelectElement).value).toBe("");
    expect((screen.getByLabelText("Preferred Model") as HTMLSelectElement).value).toBe("");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(updateProjectExecutionDefaults).toHaveBeenCalledWith(client, "project-a", { runtime_key: null, model_id: null }));
  });

  it("shows an unavailable stored model but does not offer it as a new choice", async () => {
    vi.mocked(getProjectExecutionDefaults).mockResolvedValue(defaults("native", "model-disabled"));
    renderEditor();
    const modelSelect = await screen.findByLabelText("Preferred Model") as HTMLSelectElement;
    expect(modelSelect.value).toBe("model-disabled");
    expect(screen.getByRole("option", { name: /Disabled Model.*disabled/ })).toBeTruthy();
    expect(screen.getByText(/Previously selected model unavailable/)).toBeTruthy();
    fireEvent.change(modelSelect, { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(updateProjectExecutionDefaults).toHaveBeenCalledWith(client, "project-a", { model_id: null }));
  });

  it("preserves an unavailable stored runtime and explains fallback", async () => {
    vi.mocked(getProjectExecutionDefaults).mockResolvedValue(defaults("gone-runtime", "model-a", false));
    renderEditor();
    const runtimeSelect = await screen.findByLabelText("Preferred Runtime") as HTMLSelectElement;
    expect(runtimeSelect.value).toBe("gone-runtime");
    expect(screen.getByRole("option", { name: "gone-runtime (unavailable)" })).toBeTruthy();
    expect(screen.getByText(/Configured runtime is no longer available/)).toBeTruthy();
  });

  it("keeps the draft after a save failure and allows retry", async () => {
    vi.mocked(updateProjectExecutionDefaults).mockRejectedValueOnce(new Error("private server details"));
    renderEditor();
    fireEvent.change(await screen.findByLabelText("Preferred Runtime"), { target: { value: "native" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Your draft is still here.");
    expect((screen.getByRole("button", { name: "Save" }) as HTMLButtonElement).disabled).toBe(false);
    expect((screen.getByLabelText("Preferred Runtime") as HTMLSelectElement).value).toBe("native");
  });

  it("prevents duplicate saves while a write is pending", async () => {
    let resolveSave: ((value: ReturnType<typeof defaults>) => void) | undefined;
    vi.mocked(updateProjectExecutionDefaults).mockImplementationOnce(() => new Promise((resolve) => { resolveSave = resolve; }));
    renderEditor();
    fireEvent.change(await screen.findByLabelText("Preferred Runtime"), { target: { value: "native" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect((await screen.findByRole("button", { name: "Saving…" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Saving…" }));
    expect(updateProjectExecutionDefaults).toHaveBeenCalledTimes(1);
    resolveSave?.(defaults("native", null));
    await waitFor(() => expect((screen.getByRole("button", { name: "Save" }) as HTMLButtonElement).disabled).toBe(true));
  });

  it("refreshes canonical values while clean and preserves a dirty draft", async () => {
    vi.mocked(getProjectExecutionDefaults)
      .mockResolvedValueOnce(defaults(null, null))
      .mockResolvedValueOnce(defaults("native", "model-a"))
      .mockResolvedValueOnce(defaults("openhands", "model-b"));
    renderEditor();
    await screen.findByLabelText("Preferred Runtime");
    fireEvent.click(screen.getByRole("button", { name: "Refresh stored values" }));
    await waitFor(() => {
      expect((screen.getByLabelText("Preferred Runtime") as HTMLSelectElement).value).toBe("native");
      expect((screen.getByLabelText("Preferred Model") as HTMLSelectElement).value).toBe("model-a");
    });
    fireEvent.change(screen.getByLabelText("Preferred Runtime"), { target: { value: "openhands" } });
    fireEvent.click(screen.getByRole("button", { name: "Refresh stored values" }));
    await waitFor(() => expect(getProjectExecutionDefaults).toHaveBeenCalledTimes(3));
    expect((screen.getByLabelText("Preferred Runtime") as HTMLSelectElement).value).toBe("openhands");
    expect((screen.getByLabelText("Preferred Model") as HTMLSelectElement).value).toBe("model-a");
  });
});
