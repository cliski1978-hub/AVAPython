import { ApiClient, ApiError } from "@ava/api-client";
import type { ToolFeaturesResponse } from "@ava/contracts";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { ToolFeaturesSection } from "./ToolFeaturesSection";
import { SettingsWorkspace } from "../settings/SettingsWorkspace";

const { get, update } = vi.hoisted(() => ({ get: vi.fn(), update: vi.fn() }));
vi.mock("@ava/api-client", async (original) => ({
  ...await original<typeof import("@ava/api-client")>(), getToolFeatures: get, updateToolFeatures: update,
}));
const client = new ApiClient({ baseUrl: "http://test" });
function response(enabled = false, manage = true, version = 0): ToolFeaturesResponse {
  return {
    contract_version: "v1", framework_effective_enabled: enabled, can_manage: manage, configuration_status: version ? "valid" : "missing",
    configuration: { contract_version: "v1", framework_enabled: enabled, enabled_tool_ids: [], configuration_version: version },
    tools: [{
      definition: { tool_id: "test.delete", name: "Delete fixture", description: "Metadata only", tool_version: "1", contract_version: "v1",
        input_schema: { type: "object" }, output_schema: { type: "object" }, required_capabilities: ["file_delete"],
        risk: "high", approval_requirement: "required", execution_category: "deterministic" },
      configured_enabled: false, effective_enabled: false, reason: enabled ? "tool_disabled" : "framework_disabled",
    }],
  };
}
beforeEach(() => { get.mockReset(); update.mockReset(); get.mockResolvedValue(response()); });

it("loads through the shared Settings Features & Tools destination and fails closed for administration", async () => {
  get.mockResolvedValue(response(false, false));
  render(<SettingsWorkspace client={client} initialSection="features-tools" />);
  expect(screen.getByText("Loading Features & Tools…")).toBeTruthy();
  await screen.findByText(/Read-only: authenticated feature administration/);
  expect(screen.getByRole("switch", { name: "Tool framework" }).hasAttribute("disabled")).toBe(true);
  expect(screen.getByRole("switch", { name: "Enable Delete fixture" }).hasAttribute("disabled")).toBe(true);
  expect(update).not.toHaveBeenCalled();
});

it("confirms framework enablement and saves expected version without granting execution permission", async () => {
  update.mockResolvedValue(response(true, true, 1));
  render(<ToolFeaturesSection client={client} />);
  fireEvent.click(await screen.findByRole("switch", { name: "Tool framework" }));
  expect(screen.getByRole("dialog")).toBeTruthy();
  expect(update).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Confirm enable" }));
  fireEvent.click(screen.getByRole("button", { name: "Save feature settings" }));
  await screen.findByText("Feature settings saved.");
  expect(update).toHaveBeenCalledWith(client, { framework_enabled: true, enabled_tool_ids: [], expected_version: 0 });
  expect(screen.getByText(/does not grant Workspace access/)).toBeTruthy();
  expect(screen.getByText(/but no tools are enabled/)).toBeTruthy();
});

it("requires confirmation for elevated-risk tools and preserves draft on a conflict", async () => {
  get.mockResolvedValue(response(true, true, 4));
  update.mockRejectedValue(new ApiError("Conflict", 409, { error_code: "feature_configuration_conflict", message: "Reload before saving." }));
  render(<ToolFeaturesSection client={client} />);
  fireEvent.click(await screen.findByRole("switch", { name: "Enable Delete fixture" }));
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.getByRole("switch", { name: "Enable Delete fixture" }).getAttribute("aria-checked")).toBe("false");
  fireEvent.click(screen.getByRole("switch", { name: "Enable Delete fixture" }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm enable" }));
  fireEvent.click(screen.getByRole("button", { name: "Save feature settings" }));
  await screen.findByRole("alert");
  expect(screen.queryByText("Feature settings saved.")).toBeNull();
  expect(screen.getByRole("switch", { name: "Enable Delete fixture" }).getAttribute("aria-checked")).toBe("true");
  expect(update).toHaveBeenCalledWith(client, { framework_enabled: true, enabled_tool_ids: ["test.delete"], expected_version: 4 });
});

it("handles load failure and retry without inventing configuration", async () => {
  get.mockRejectedValueOnce(new Error("untrusted stack")).mockResolvedValueOnce(response());
  render(<ToolFeaturesSection client={client} />);
  await screen.findByRole("alert");
  expect(screen.queryByRole("switch")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: /Retry/ }));
  await screen.findByRole("switch", { name: "Tool framework" });
  expect(screen.queryByText("untrusted stack")).toBeNull();
});

it("drops a stale load after changing clients", async () => {
  let resolve!: (value: ToolFeaturesResponse) => void;
  get.mockImplementationOnce(() => new Promise<ToolFeaturesResponse>((done) => { resolve = done; }));
  const view = render(<ToolFeaturesSection client={client} />);
  const other = new ApiClient({ baseUrl: "http://other" });
  view.rerender(<ToolFeaturesSection client={other} />);
  await screen.findByRole("switch", { name: "Tool framework" });
  await act(async () => { resolve(response(true, true, 12)); });
  expect(screen.getByRole("switch", { name: "Tool framework" }).getAttribute("aria-checked")).toBe("false");
});

it("prevents duplicate saves and ignores a save response after section unmount", async () => {
  let resolve!: (value: ToolFeaturesResponse) => void;
  update.mockImplementation(() => new Promise<ToolFeaturesResponse>((done) => { resolve = done; }));
  const view = render(<ToolFeaturesSection client={client} />);
  fireEvent.click(await screen.findByRole("switch", { name: "Tool framework" }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm enable" }));
  const save = screen.getByRole("button", { name: "Save feature settings" });
  fireEvent.click(save); fireEvent.click(save);
  await waitFor(() => expect(update).toHaveBeenCalledTimes(1));
  expect(screen.getByRole("button", { name: "Saving…" }).hasAttribute("disabled")).toBe(true);
  view.unmount();
  await act(async () => { resolve(response(true, true, 1)); });
});

it("keeps hidden configured tools in the complete versioned save payload", async () => {
  const state = response(true, true, 4);
  state.configuration.enabled_tool_ids = ["test.read"];
  state.tools.push({
    definition: { ...state.tools[0].definition, tool_id: "test.read", name: "Read fixture", risk: "low", required_capabilities: ["file_read"] },
    configured_enabled: true, effective_enabled: true, reason: "feature_enabled",
  });
  get.mockResolvedValue(state);
  update.mockResolvedValue(response(true, true, 5));
  render(<ToolFeaturesSection client={client} />);
  fireEvent.change(await screen.findByRole("textbox", { name: "Search tools" }), { target: { value: "delete" } });
  expect(screen.queryByRole("article", { name: "Read fixture" })).toBeNull();
  fireEvent.click(screen.getByRole("switch", { name: "Enable Delete fixture" }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm enable" }));
  fireEvent.click(screen.getByRole("button", { name: "Save feature settings" }));
  await screen.findByText("Feature settings saved.");
  expect(update).toHaveBeenCalledWith(client, {
    framework_enabled: true, enabled_tool_ids: ["test.read", "test.delete"], expected_version: 4,
  });
});
