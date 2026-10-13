// @vitest-environment jsdom
import { ApiClient } from "@ava/api-client";
import type { CorePrompt, CorePromptAssignment, CorePromptAssignmentState, CorePromptScopeType } from "@ava/contracts";
import {
  createCorePrompt,
  deleteCorePrompt,
  getCapabilities,
  getRuntimes,
  listCorePromptAssignments,
  listCorePromptAssignmentsForScope,
  listCorePrompts,
  setCorePromptAssignment,
  setCorePromptEnabled,
  updateCorePrompt,
} from "@ava/api-client";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SettingsWorkspace } from "../settings/SettingsWorkspace";
import { CorePromptScopeAssignments } from "../prompts/CorePromptScopeAssignments";
import { SystemPromptsSection } from "./SystemPromptsSection";

vi.mock("@ava/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@ava/api-client")>();
  return {
    ...actual,
    listCorePrompts: vi.fn(),
    getCorePrompt: vi.fn(),
    createCorePrompt: vi.fn(),
    updateCorePrompt: vi.fn(),
    setCorePromptEnabled: vi.fn(),
    deleteCorePrompt: vi.fn(),
    listCorePromptAssignments: vi.fn(),
    listCorePromptAssignmentsForScope: vi.fn(),
    setCorePromptAssignment: vi.fn(),
    getRuntimes: vi.fn(),
    getCapabilities: vi.fn(),
  };
});

const client = new ApiClient({ baseUrl: "http://localhost:99999" });
const prompt = (id: string, overrides: Partial<CorePrompt> = {}): CorePrompt => ({
  id,
  name: `Prompt ${id}`,
  description: null,
  prompt_text: `Text ${id}`,
  category: "general",
  is_enabled: true,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  contract_version: "v1",
  ...overrides,
});
const assignment = (corePromptId: string, scopeType: CorePromptScopeType, scopeId: string | null, state: CorePromptAssignmentState): CorePromptAssignment => ({
  core_prompt_id: corePromptId,
  scope_type: scopeType,
  scope_id: scopeId,
  state,
  assignment_id: "assignment-1",
  created_at: null,
  updated_at: null,
  contract_version: "v1",
});

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listCorePrompts).mockResolvedValue({ core_prompts: [prompt("one"), prompt("two", { name: "Research note", category: "research", is_enabled: false })], contract_version: "v1" });
  vi.mocked(listCorePromptAssignments).mockResolvedValue({ assignments: [], contract_version: "v1" });
  vi.mocked(listCorePromptAssignmentsForScope).mockResolvedValue({ assignments: [], contract_version: "v1" });
  vi.mocked(createCorePrompt).mockResolvedValue(prompt("created"));
  vi.mocked(updateCorePrompt).mockResolvedValue(prompt("one"));
  vi.mocked(setCorePromptEnabled).mockImplementation(async (_client, _id, body) => prompt("one", { is_enabled: body.is_enabled }));
  vi.mocked(deleteCorePrompt).mockResolvedValue(undefined as never);
  vi.mocked(setCorePromptAssignment).mockResolvedValue(assignment("one", "global", null, "enable"));
  vi.mocked(getRuntimes).mockResolvedValue({ contract_version: "v1", default_runtime_id: "native", runtimes: [{ runtime_info: { runtime_id: "native" }, is_default: true, contract_version: "v1" }] });
  vi.mocked(getCapabilities).mockResolvedValue({ contract_version: "v1", application: "AVA", capabilities: { health: true, runs: true, streaming: true, tool_calling: true, structured_output: true, cancellation: true, document_operations: true, approvals: true, local_model: true, local_execution: true } });
});

describe("System Prompts settings", () => {
  it("adds a Settings destination and renders definitions in backend order with definition state", async () => {
    render(<SettingsWorkspace client={client} />);
    fireEvent.click(screen.getByRole("tab", { name: "System Prompts" }));
    await screen.findAllByText("Prompt one");
    const profileRows = Array.from(document.querySelectorAll<HTMLElement>("[data-core-prompt]"));
    expect(profileRows.map((row) => row.dataset.corePrompt)).toEqual(["one", "two"]);
    expect(screen.getAllByText("Prompt enabled").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Prompt definition disabled").length).toBeGreaterThan(0);
    expect(listCorePrompts).toHaveBeenCalledWith(client);
  });

  it("uses active semantic theme tokens for CORE Prompt cards and metadata", async () => {
    const profiles = render(<SystemPromptsSection client={client} />);
    await screen.findAllByText("Prompt one");
    const profileCard = profiles.container.querySelector<HTMLElement>('[data-core-prompt="one"]');
    expect(profileCard?.classList.contains("bg-card")).toBe(true);
    expect(profileCard?.classList.contains("text-card-foreground")).toBe(true);
    expect(profileCard?.classList.contains("border-border")).toBe(true);
    expect(profileCard?.style.background).toBe("");
    expect(profileCard?.querySelector(".text-muted-foreground")).toBeTruthy();

    profiles.unmount();
    const assignments = render(
      <CorePromptScopeAssignments client={client} scopeType="global" scopeId={null} scopeLabel="Global" prompts={[prompt("one")]} />,
    );
    await screen.findByRole("combobox", { name: "Assignment for Prompt one at Global" });
    const assignmentCard = assignments.container.querySelector<HTMLElement>('[data-prompt-assignment="one"]');
    expect(assignmentCard?.classList.contains("bg-card")).toBe(true);
    expect(assignmentCard?.classList.contains("text-card-foreground")).toBe(true);
    expect(assignmentCard?.classList.contains("border-border")).toBe(true);
    expect(assignmentCard?.style.background).toBe("");
    expect(assignmentCard?.querySelector(".text-muted-foreground")).toBeTruthy();
  });

  it("creates an exact prompt definition without adding scope data", async () => {
    render(<SystemPromptsSection client={client} />);
    await screen.findAllByText("Prompt one");
    fireEvent.click(screen.getByRole("button", { name: "New System Prompt" }));
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Whitespace" } });
    fireEvent.change(screen.getByLabelText("Prompt text"), { target: { value: "  keep this\n\nexactly  " } });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(createCorePrompt).toHaveBeenCalledWith(client, {
      name: "Whitespace", description: null, category: "general", prompt_text: "  keep this\n\nexactly  ",
    }));
  });

  it("shows retryable loading failure and a distinct empty state", async () => {
    vi.mocked(listCorePrompts).mockRejectedValueOnce(new Error("private server detail"));
    render(<SystemPromptsSection client={client} />);
    expect(await screen.findByText("System Prompts could not be loaded. Try again.")).toBeTruthy();
    expect(screen.queryByText("private server detail")).toBeNull();
    vi.mocked(listCorePrompts).mockResolvedValueOnce({ core_prompts: [], contract_version: "v1" });
    fireEvent.click(screen.getByRole("button", { name: "Retry loading System Prompts" }));
    expect(await screen.findByText("No System Prompts yet.")).toBeTruthy();
  });

  it("edits exact prompt text and uses the enabled-definition API", async () => {
    render(<SystemPromptsSection client={client} />);
    await screen.findAllByText("Prompt one");
    fireEvent.click(screen.getAllByRole("button", { name: "Edit" })[0]);
    fireEvent.change(screen.getByLabelText("Prompt text"), { target: { value: "\n  edited\t\n" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(updateCorePrompt).toHaveBeenCalledWith(client, "one", {
      name: "Prompt one", description: null, category: "general", prompt_text: "\n  edited\t\n",
    }));
  });

  it("enables and disables a definition without changing assignment controls", async () => {
    render(<SystemPromptsSection client={client} />);
    await screen.findAllByText("Prompt one");
    fireEvent.click(screen.getAllByRole("button", { name: "Disable definition" })[0]);
    await waitFor(() => expect(setCorePromptEnabled).toHaveBeenCalledWith(client, "one", { is_enabled: false }));
    await waitFor(() => expect(screen.getAllByRole("button", { name: "Enable definition" }).length).toBeGreaterThan(0));
  });

  it("confirms deletion and distinguishes it from deleting its owning scope", async () => {
    render(<SystemPromptsSection client={client} />);
    await screen.findAllByText("Prompt one");
    fireEvent.click(screen.getAllByRole("button", { name: "Delete" })[0]);
    expect(screen.getByText(/permanently removes the reusable definition and its scoped assignments/i)).toBeTruthy();
    expect(screen.getByText(/does not delete any Project, Folder, or Conversation/i)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Delete permanently" }));
    await waitFor(() => expect(deleteCorePrompt).toHaveBeenCalledWith(client, "one"));
    await waitFor(() => expect(screen.queryAllByText("Prompt one")).toHaveLength(0));
  });

  it("keeps the prompt definition visible and the confirmation open when deletion fails", async () => {
    vi.mocked(deleteCorePrompt).mockRejectedValueOnce(new Error("private server detail"));
    render(<SystemPromptsSection client={client} />);
    await screen.findAllByText("Prompt one");
    fireEvent.click(screen.getAllByRole("button", { name: "Delete" })[0]);
    fireEvent.click(screen.getByRole("button", { name: "Delete permanently" }));
    expect(await screen.findByText("System Prompt could not be deleted. Try again.")).toBeTruthy();
    expect(screen.getAllByText("Prompt one").length).toBeGreaterThan(0);
    expect(screen.queryByText("private server detail")).toBeNull();
  });

  it("sets an explicit global assignment through the three-state selector", async () => {
    render(<SystemPromptsSection client={client} />);
    await screen.findAllByText("Prompt one");
    const selector = screen.getByRole("combobox", { name: "Assignment for Prompt one at Global" });
    fireEvent.change(selector, { target: { value: "disable" } });
    await waitFor(() => expect(setCorePromptAssignment).toHaveBeenCalledWith(client, "one", {
      scope_type: "global", scope_id: null, state: "disable",
    }));
    expect(within(selector.parentElement as HTMLElement).getByText("Explicitly suppress this CORE prompt at this scope.")).toBeTruthy();
  });

  it("writes a Project scope explicitly and leaves inherit as the no-row state", async () => {
    render(<CorePromptScopeAssignments client={client} scopeType="project" scopeId="project-7" scopeLabel="Project: Research" />);
    const selector = await screen.findByRole("combobox", { name: "Assignment for Prompt one at Project: Research" });
    expect(listCorePromptAssignmentsForScope).toHaveBeenCalledWith(client, "project", "project-7");
    expect(selector).toHaveProperty("value", "inherit");
    fireEvent.change(selector, { target: { value: "enable" } });
    await waitFor(() => expect(setCorePromptAssignment).toHaveBeenCalledWith(client, "one", {
      scope_type: "project", scope_id: "project-7", state: "enable",
    }));
  });

  it.each([
    ["global", null, "Global"],
    ["project", "project-7", "Project: Research"],
    ["folder", "folder-2", "Folder: Notes"],
    ["conversation", "chat-9", "Conversation: Draft"],
  ] as const)("maps explicit rows and missing rows to selector states at %s", async (scopeType, scopeId, scopeLabel) => {
    vi.mocked(listCorePrompts).mockResolvedValue({ core_prompts: [prompt("enabled"), prompt("disabled"), prompt("missing")], contract_version: "v1" });
    vi.mocked(listCorePromptAssignmentsForScope).mockResolvedValue({ assignments: [
      assignment("enabled", scopeType, scopeId, "enable"),
      assignment("disabled", scopeType, scopeId, "disable"),
    ], contract_version: "v1" });
    render(<CorePromptScopeAssignments client={client} scopeType={scopeType} scopeId={scopeId} scopeLabel={scopeLabel} />);
    expect(await screen.findByRole("combobox", { name: `Assignment for Prompt enabled at ${scopeLabel}` })).toHaveProperty("value", "enable");
    expect(screen.getByRole("combobox", { name: `Assignment for Prompt disabled at ${scopeLabel}` })).toHaveProperty("value", "disable");
    expect(screen.getByRole("combobox", { name: `Assignment for Prompt missing at ${scopeLabel}` })).toHaveProperty("value", "inherit");
  });

  it("supports every assignment state transition including removal to inherit", async () => {
    render(<CorePromptScopeAssignments client={client} scopeType="folder" scopeId="folder-2" scopeLabel="Folder: Notes" />);
    const selector = await screen.findByRole("combobox", { name: "Assignment for Prompt one at Folder: Notes" });
    for (const [from, to] of [["inherit", "enable"], ["enable", "disable"], ["disable", "inherit"], ["inherit", "disable"], ["disable", "enable"], ["enable", "inherit"]] as const) {
      expect(selector).toHaveProperty("value", from);
      fireEvent.change(selector, { target: { value: to } });
      await waitFor(() => expect(selector).toHaveProperty("value", to));
      expect(setCorePromptAssignment).toHaveBeenLastCalledWith(client, "one", {
        scope_type: "folder", scope_id: "folder-2", state: to,
      });
    }
    expect(setCorePromptAssignment).toHaveBeenCalledTimes(6);
  });

  it("keeps a disabled definition separate from an explicit ENABLE assignment", async () => {
    vi.mocked(listCorePrompts).mockResolvedValue({ core_prompts: [prompt("disabled-def", { name: "Retired", is_enabled: false })], contract_version: "v1" });
    vi.mocked(listCorePromptAssignmentsForScope).mockResolvedValue({ assignments: [assignment("disabled-def", "project", "project-7", "enable")], contract_version: "v1" });
    render(<CorePromptScopeAssignments client={client} scopeType="project" scopeId="project-7" scopeLabel="Project: Research" />);
    expect(await screen.findByLabelText("Definition disabled")).toBeTruthy();
    expect(screen.getByRole("combobox", { name: "Assignment for Retired at Project: Research" })).toHaveProperty("value", "enable");
  });

  it("does not resolve a Global ENABLE into a Project INHERIT", async () => {
    vi.mocked(listCorePromptAssignmentsForScope).mockResolvedValueOnce({ assignments: [assignment("one", "global", null, "enable")], contract_version: "v1" });
    const globalView = render(<CorePromptScopeAssignments client={client} scopeType="global" scopeId={null} scopeLabel="Global" />);
    expect(await screen.findByRole("combobox", { name: "Assignment for Prompt one at Global" })).toHaveProperty("value", "enable");
    globalView.unmount();
    vi.mocked(listCorePromptAssignmentsForScope).mockResolvedValueOnce({ assignments: [], contract_version: "v1" });
    render(<CorePromptScopeAssignments client={client} scopeType="project" scopeId="project-7" scopeLabel="Project: Research" />);
    expect(await screen.findByRole("combobox", { name: "Assignment for Prompt one at Project: Research" })).toHaveProperty("value", "inherit");
  });

  it("does not optimistically change explicit state when a write fails", async () => {
    vi.mocked(setCorePromptAssignment).mockRejectedValueOnce(new Error("offline"));
    render(<CorePromptScopeAssignments client={client} scopeType="conversation" scopeId="chat-1" scopeLabel="Conversation: Draft" />);
    const selector = await screen.findByRole("combobox", { name: "Assignment for Prompt one at Conversation: Draft" });
    fireEvent.change(selector, { target: { value: "enable" } });
    await screen.findByRole("alert");
    expect(selector).toHaveProperty("value", "inherit");
    expect(listCorePromptAssignmentsForScope).toHaveBeenCalledWith(client, "conversation", "chat-1");
    fireEvent.change(selector, { target: { value: "enable" } });
    await waitFor(() => expect(setCorePromptAssignment).toHaveBeenCalledTimes(2));
    expect(selector).toHaveProperty("value", "enable");
  });

  it("offers discovered runtime and canonical capability keys as target identifiers", async () => {
    render(<SystemPromptsSection client={client} />);
    await screen.findAllByText("Prompt one");
    fireEvent.change(screen.getByLabelText("Scope type"), { target: { value: "runtime" } });
    expect(await screen.findByRole("option", { name: "native" })).toBeTruthy();
    const runtimeSelector = screen.getByRole("combobox", { name: "Assignment for Prompt one at Runtime: native" });
    expect(runtimeSelector).toHaveProperty("value", "inherit");
    fireEvent.change(runtimeSelector, { target: { value: "enable" } });
    await waitFor(() => expect(setCorePromptAssignment).toHaveBeenCalledWith(client, "one", {
      scope_type: "runtime", scope_id: "native", state: "enable",
    }));
    fireEvent.change(screen.getByLabelText("Scope type"), { target: { value: "capability" } });
    expect(await screen.findByRole("option", { name: "tool_calling" })).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Target"), { target: { value: "tool_calling" } });
    const capabilitySelector = await screen.findByRole("combobox", { name: "Assignment for Prompt one at Capability: tool_calling" });
    fireEvent.change(capabilitySelector, { target: { value: "disable" } });
    await waitFor(() => expect(setCorePromptAssignment).toHaveBeenCalledWith(client, "one", {
      scope_type: "capability", scope_id: "tool_calling", state: "disable",
    }));
    expect(screen.queryByRole("option", { name: "Application" })).toBeNull();
    expect(screen.queryByRole("option", { name: "Model Compatibility" })).toBeNull();
  });
});
