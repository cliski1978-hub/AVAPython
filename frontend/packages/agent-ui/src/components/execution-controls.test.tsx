import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { WorkspaceInfo } from "@ava/contracts";

import { ExecutionControls } from "./ExecutionControls";

const noop = () => undefined;

function render(workspaces: WorkspaceInfo[], props: Record<string, unknown> = {}) {
  return renderToStaticMarkup(
    <ExecutionControls
      runtimes={[]}
      modelProviders={[]}
      onRuntimeChange={noop}
      onModelProviderChange={noop}
      workspaces={workspaces}
      {...props}
    />,
  );
}

const workspaces: WorkspaceInfo[] = [
  { workspace_id: "workspace-a", display_name: "Workspace A", kind: "local" },
  { workspace_id: "workspace-b", display_name: "Workspace B", kind: "ephemeral" },
];

describe("ExecutionControls workspace selector", () => {
  it("shows a None option by default when no workspace is selected", () => {
    const html = render([]);
    expect(html).toContain('aria-label="Select workspace"');
    expect(html).toContain('<option value="" selected="">None</option>');
    expect(html).not.toContain("Workspace options unavailable");
  });

  it("lists discovered workspaces as options using display_name and workspace_id", () => {
    const html = render(workspaces);
    expect(html).toContain('<option value="" selected="">None</option>');
    expect(html).toContain('<option value="workspace-a">Workspace A</option>');
    expect(html).toContain('<option value="workspace-b">Workspace B</option>');
  });

  it("reflects the selected workspace id as the select value", () => {
    const html = render(workspaces, { selectedWorkspaceId: "workspace-b" });
    expect(html).toContain('<option value="workspace-b" selected="">Workspace B</option>');
  });

  it("keeps None selected when no workspace is chosen even with options available", () => {
    const html = render(workspaces, { selectedWorkspaceId: null });
    expect(html).toContain('<option value="" selected="">None</option>');
  });

  it("shows only None without error when discovery returns an empty registry", () => {
    const html = render([]);
    expect(html).toContain('<option value="" selected="">None</option>');
    expect(html).not.toContain("Workspace options unavailable");
  });

  it("degrades to an unavailable state when workspace discovery fails", () => {
    const html = render([], { workspacesUnavailable: true });
    expect(html).toContain("Workspace options unavailable");
    expect(html).toContain('disabled=""');
  });

  it("does not render discovered workspaces while in the unavailable state", () => {
    const html = render(workspaces, { workspacesUnavailable: true });
    expect(html).toContain("Workspace options unavailable");
    expect(html).not.toContain(">Workspace A</option>");
    expect(html).not.toContain(">Workspace B</option>");
  });
});