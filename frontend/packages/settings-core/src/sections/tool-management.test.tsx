import type { ToolFeaturesResponse } from "@ava/contracts";
import { AppearanceProvider, DEFAULT_APPEARANCE_PREFERENCES, writeAppearancePreferences, type ThemeMode } from "@ava/ui-core";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { ToolManagementPanel } from "./ToolManagementPanel";

function tools(): ToolFeaturesResponse["tools"] {
  return [
    { definition: {
      tool_id: "file.read", name: "Read reference", description: "Inspect a permitted source", tool_version: "1.2", contract_version: "v1",
      execution_category: "deterministic", risk: "low", approval_requirement: "policy", required_capabilities: ["file_read"],
      input_schema: { type: "object", properties: { resource: { type: "string" } }, required: ["resource"] },
      output_schema: { type: "object", properties: { content: { type: "string" } } },
    }, configured_enabled: true, effective_enabled: false, reason: "framework_disabled" },
    { definition: {
      tool_id: "file.delete", name: "Delete reference", description: "Metadata fixture only", tool_version: "2", contract_version: "v1",
      execution_category: "hybrid", risk: "critical", approval_requirement: "required", required_capabilities: ["file_delete", "file_write"],
      input_schema: { type: "object" }, output_schema: { type: "object" },
    }, configured_enabled: false, effective_enabled: false, reason: "tool_disabled" },
  ];
}
beforeEach(() => { writeAppearancePreferences(DEFAULT_APPEARANCE_PREFERENCES); });

it("shows identity, capabilities and approval metadata with separate saved/effective states and compact details", () => {
  render(<ToolManagementPanel tools={tools()} enabledIds={["file.read"]} controlsDisabled onToggle={vi.fn()} />);
  const read = within(screen.getByRole("article", { name: "Read reference" }));
  expect(read.getByText("file.read")).toBeTruthy();
  expect(read.getByText(/Declared capabilities: file_read/)).toBeTruthy();
  expect(read.getByText(/Saved: Enabled/)).toBeTruthy();
  expect(read.getByText(/Effective feature availability: Unavailable/)).toBeTruthy();
  expect(read.getByText(/Definition 1.2/)).toBeTruthy();
  expect(read.getByText("1 declared fields · 1 required fields")).toBeTruthy();
  expect(read.getByText("resource: string")).toBeTruthy();
  expect(read.getByText(/No authorization or runtime compatibility result/)).toBeTruthy();
  expect(screen.queryByText(/\{"type"/)).toBeNull();
  expect(read.getByRole("switch").hasAttribute("disabled")).toBe(true);
});

it("intersects name/ID, category, risk and saved-state filters without treating drafts as saved", () => {
  render(<ToolManagementPanel tools={tools()} enabledIds={["file.read", "file.delete"]} controlsDisabled={false} onToggle={vi.fn()} />);
  fireEvent.change(screen.getByRole("textbox", { name: "Search tools" }), { target: { value: " FILE.DELETE " } });
  expect(screen.queryByRole("article", { name: "Read reference" })).toBeNull();
  expect(screen.getByRole("article", { name: "Delete reference" })).toBeTruthy();
  fireEvent.change(screen.getByRole("combobox", { name: "Tool configured state" }), { target: { value: "disabled" } });
  expect(screen.getByText(/Unsaved: Enabled/)).toBeTruthy();
  fireEvent.change(screen.getByRole("combobox", { name: "Tool category" }), { target: { value: "hybrid" } });
  fireEvent.change(screen.getByRole("combobox", { name: "Tool risk" }), { target: { value: "critical" } });
  expect(screen.getByText(/1 of 2 registered tools/)).toBeTruthy();
  fireEvent.change(screen.getByRole("combobox", { name: "Tool risk" }), { target: { value: "low" } });
  expect(screen.getByText("No tools match these filters.")).toBeTruthy();
});

it("distinguishes an empty registry from no filter matches and emits only a known tool draft change", () => {
  const change = vi.fn();
  const view = render(<ToolManagementPanel tools={[]} enabledIds={[]} controlsDisabled onToggle={change} />);
  expect(screen.getByText("No normalized tools are registered yet.")).toBeTruthy();
  view.rerender(<ToolManagementPanel tools={tools()} enabledIds={[]} controlsDisabled={false} onToggle={change} />);
  fireEvent.click(screen.getByRole("switch", { name: "Enable Read reference" }));
  expect(change).toHaveBeenCalledWith("file.read", true);
  expect(screen.queryByRole("button", { name: /Execute|Run tool/ })).toBeNull();
});

const modes: ThemeMode[] = ["light", "dark", "system"];
it.each(modes)("uses shared semantic controls and responsive structure in %s mode", (mode) => {
  writeAppearancePreferences({ ...DEFAULT_APPEARANCE_PREFERENCES, themeMode: mode });
  const view = render(<AppearanceProvider><ToolManagementPanel tools={tools()} enabledIds={[]} controlsDisabled onToggle={vi.fn()} /></AppearanceProvider>);
  const article = screen.getByRole("article", { name: "Read reference" });
  expect(article.className).toContain("bg-card");
  expect(article.className).toContain("text-card-foreground");
  expect(view.container.querySelector(".grid")?.className).toContain("grid-cols-1");
  expect(view.container.querySelector(".grid")?.className).toContain("sm:grid-cols-2");
  expect(screen.getByRole("textbox", { name: "Search tools" }).className).toContain("bg-background");
  expect(article.style.background).toBe("");
});
