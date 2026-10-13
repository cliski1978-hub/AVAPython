import { ApiClient } from "@ava/api-client";
import type { WorkspaceAccessResponse } from "@ava/contracts";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { SettingsWorkspace } from "../settings/SettingsWorkspace";
import { WorkspaceAccessSection } from "./WorkspaceAccessSection";

const { get, create, update } = vi.hoisted(() => ({ get: vi.fn(), create: vi.fn(), update: vi.fn() }));
vi.mock("@ava/api-client", async (original) => ({
  ...await original<typeof import("@ava/api-client")>(),
  getWorkspaceAccess: get, createWorkspaceAccess: create, updateWorkspaceAccess: update,
}));
const client = new ApiClient({ baseUrl: "http://test" });
function response(canManage = false): WorkspaceAccessResponse {
  return { contract_version: "v1", can_manage: canManage, roots_disclosed: canManage, configuration_status: "valid", workspaces: [{
    workspace_id: "safe-root", name: "Team files", kind: "local", root_path: canManage ? "/srv/ava/team" : null,
    allowed_capabilities: ["file_read"], status: "active", revision: 4,
    created_at: "2026-10-13T00:00:00Z", updated_at: "2026-10-13T00:00:00Z",
  }] };
}
beforeEach(() => { get.mockReset(); create.mockReset(); update.mockReset(); get.mockResolvedValue(response()); });

it("uses one shared Settings section and hides roots with mutations unavailable", async () => {
  render(<SettingsWorkspace client={client} initialSection="workspace-access" />);
  await screen.findByText(/Read-only: trusted Workspace administration is unavailable/);
  expect(screen.getByText("safe-root")).toBeTruthy();
  expect(screen.getByText("Hidden without trusted administrative access")).toBeTruthy();
  expect(screen.queryByText("/srv/ava/team")).toBeNull();
  expect(screen.queryByText("Create Workspace")).toBeNull();
  expect(create).not.toHaveBeenCalled(); expect(update).not.toHaveBeenCalled();
});

it("shows roots and offers explicit management controls only when trusted administration is available", async () => {
  get.mockResolvedValue(response(true));
  render(<WorkspaceAccessSection client={client} />);
  await screen.findByText("/srv/ava/team");
  expect(screen.getByRole("button", { name: "Create Workspace" }).hasAttribute("disabled")).toBe(true);
  expect(screen.getByText("Edit Workspace settings")).toBeTruthy();
});

it("requires an explicit security review before an authorized Workspace create", async () => {
  const empty = { ...response(true), workspaces: [] };
  get.mockResolvedValue(empty);
  create.mockResolvedValue(empty);
  render(<WorkspaceAccessSection client={client} />);
  fireEvent.click(await screen.findByText("Create Workspace", { selector: "summary" }));
  fireEvent.change(screen.getByRole("textbox", { name: "Stable Workspace ID" }), { target: { value: "team-files" } });
  fireEvent.change(screen.getByRole("textbox", { name: "Name" }), { target: { value: "Team files" } });
  fireEvent.change(screen.getByRole("textbox", { name: "Canonical absolute root path" }), { target: { value: "/srv/ava/team" } });
  const submit = screen.getByRole("button", { name: "Create Workspace" });
  expect(submit.hasAttribute("disabled")).toBe(true);
  fireEvent.click(screen.getByRole("checkbox", { name: /reviewed the selected host root/ }));
  fireEvent.click(submit);
  await screen.findByText("No execution Workspaces are configured.");
  expect(create).toHaveBeenCalledWith(client, {
    workspace_id: "team-files", name: "Team files", kind: "local", root_path: "/srv/ava/team", allowed_capabilities: [],
  });
});

it("discards a stale workspace response after the section switches clients", async () => {
  let resolve!: (value: WorkspaceAccessResponse) => void;
  get.mockImplementationOnce(() => new Promise<WorkspaceAccessResponse>((done) => { resolve = done; }));
  const view = render(<WorkspaceAccessSection client={client} />);
  const other = new ApiClient({ baseUrl: "http://other" });
  get.mockResolvedValueOnce({ ...response(), workspaces: [] });
  view.rerender(<WorkspaceAccessSection client={other} />);
  await screen.findByText("No execution Workspaces are configured.");
  await act(async () => { resolve(response(true)); });
  expect(screen.queryByText("/srv/ava/team")).toBeNull();
});
