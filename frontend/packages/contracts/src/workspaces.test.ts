import { describe, expect, it } from "vitest";

import { CONTRACT_VERSION } from "./version";
import type {
  RunRequest,
  WorkspaceDiscoveryResponse,
  WorkspaceInfo,
  WorkspaceKind,
} from "./index";

describe("workspace contracts", () => {
  it("types workspace discovery the same as the backend /workspaces response", () => {
    const response: WorkspaceDiscoveryResponse = {
      contract_version: "v1",
      workspaces: [
        { workspace_id: "temporary-test", display_name: "Temporary Test", kind: "local" },
        { workspace_id: "project-test", display_name: "Project Test", kind: "ephemeral" },
      ],
    };
    expect(response.contract_version).toBe(CONTRACT_VERSION);
    expect(response.workspaces[0].kind).toBe<WorkspaceKind>("local");
    expect(response.workspaces[1].kind).toBe<WorkspaceKind>("ephemeral");
  });

  it("exposes only public-safe workspace fields", () => {
    const workspace: WorkspaceInfo = {
      workspace_id: "workspace-a",
      display_name: "Workspace A",
      kind: "local",
    };
    expect(Object.keys(workspace).sort()).toEqual([
      "display_name",
      "kind",
      "workspace_id",
    ]);
  });

  it("allows an empty workspace discovery response", () => {
    const response: WorkspaceDiscoveryResponse = {
      contract_version: "v1",
      workspaces: [],
    };
    expect(response.workspaces).toEqual([]);
  });

  it("supports workspace_id on a run request, omittable when no workspace is selected", () => {
    const withoutWorkspace: RunRequest = { prompt: "Explain the project" };
    expect("workspace_id" in withoutWorkspace).toBe(false);

    const withWorkspace: RunRequest = {
      prompt: "Explain the project",
      workspace_id: "approved-workspace",
    };
    expect(withWorkspace.workspace_id).toBe("approved-workspace");
  });
});