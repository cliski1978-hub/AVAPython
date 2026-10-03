// @vitest-environment jsdom
import { ApiClient, ApiError, createProject, deleteProject, deleteProjectFile, downloadProjectFile, getProject, getProjectExecutionDefaults, getRuntimes, listModelConfigurations, listProviderConnections, listProjectFiles, listProjects, listProjectConversations, setProjectArchived, updateProject, updateProjectExecutionDefaults, uploadProjectFile } from "@ava/api-client";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProjectsWorkspace, type ProjectsWorkspaceProps } from "./ProjectsWorkspace";

vi.mock("@ava/api-client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@ava/api-client")>();
  return {
    ...mod,
    listProjects: vi.fn(),
    getProject: vi.fn(),
    listProjectConversations: vi.fn(),
    listProjectFiles: vi.fn(),
    uploadProjectFile: vi.fn(),
    downloadProjectFile: vi.fn(),
    deleteProjectFile: vi.fn(),
    createProject: vi.fn(),
    setProjectArchived: vi.fn(),
    updateProject: vi.fn(),
    deleteProject: vi.fn(),
    getProjectExecutionDefaults: vi.fn(),
    getRuntimes: vi.fn(),
    listModelConfigurations: vi.fn(),
    listProviderConnections: vi.fn(),
    updateProjectExecutionDefaults: vi.fn(),
  };
});

const client = new ApiClient({ baseUrl: "http://localhost:99999" });
const project = (id: string, name: string, is_archived = false, instructions: string | null = null) => ({
  id,
  name,
  description: null,
  instructions,
  is_archived,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  contract_version: "v1" as const,
});


function renderPage(projectId: string | null = null, onBackToProjects = vi.fn(), extra: Partial<ProjectsWorkspaceProps> = {}) {
  return render(
    <ProjectsWorkspace
      client={client}
      active
      projectId={projectId}
      onOpenProject={vi.fn()}
      onBackToProjects={onBackToProjects}
      {...extra}
    />,
  );
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(listProjects).mockResolvedValue({ projects: [], contract_version: "v1" });
  vi.mocked(listProjectConversations).mockResolvedValue({ conversations: [], contract_version: "v1" });
  vi.mocked(listProjectFiles).mockResolvedValue({ project_id: "p-1", files: [], contract_version: "v1" });
  vi.mocked(uploadProjectFile).mockResolvedValue({
    id: "pf-uploaded", project_id: "p-1", file_name: "new.txt", content_type: "text/plain", size_bytes: 3,
    created_at: "2026-10-02T00:00:00Z", updated_at: "2026-10-02T00:00:00Z", contract_version: "v1",
  });
  vi.mocked(downloadProjectFile).mockResolvedValue(new Blob(["data"]));
  vi.mocked(deleteProjectFile).mockResolvedValue(undefined);
  vi.mocked(getProjectExecutionDefaults).mockResolvedValue({ project_id: "p-1", runtime_key: null, model_id: null, runtime_available: null, contract_version: "v1" });
  vi.mocked(getRuntimes).mockResolvedValue({ runtimes: [], default_runtime_id: "native", contract_version: "v1" });
  vi.mocked(listModelConfigurations).mockResolvedValue({ models: [], contract_version: "v1" });
  vi.mocked(listProviderConnections).mockResolvedValue({ provider_connections: [], contract_version: "v1" });
  vi.mocked(updateProjectExecutionDefaults).mockImplementation(async (_client, projectId, request) => ({
    project_id: projectId,
    runtime_key: request.runtime_key ?? null,
    model_id: request.model_id ?? null,
    runtime_available: true,
    contract_version: "v1",
  }));
  vi.mocked(updateProject).mockImplementation(async (_client, _projectId, request) => ({
    ...project("p-1", "One"),
    instructions: request.instructions ?? null,
    updated_at: "2026-01-02T00:00:00Z",
  }));
});

describe("Projects page", () => {
  it("preserves backend order while grouping active and archived Projects", async () => {
    vi.mocked(listProjects).mockResolvedValue({
      projects: [project("p-a", "Alpha"), project("p-z", "Zulu"), project("p-old", "Archived", true)],
      contract_version: "v1",
    });
    const { container } = renderPage();
    const alpha = await screen.findByRole("button", { name: "Alpha" });
    const zulu = screen.getByRole("button", { name: "Zulu" });
    expect(alpha.compareDocumentPosition(zulu) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Active Projects" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Archived Projects" })).toBeTruthy();
    expect(container.querySelectorAll("article")).toHaveLength(3);
    expect(screen.getAllByRole("button", { name: "Archive" })).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Restore" })).toBeTruthy();
  });

  it("distinguishes an empty list from a list with only archived Projects", async () => {
    const { rerender } = renderPage();
    expect(await screen.findByText("No Projects yet. Create your first Project.")).toBeTruthy();
    vi.mocked(listProjects).mockResolvedValueOnce({ projects: [project("p-archived", "Old", true)], contract_version: "v1" });
    rerender(<ProjectsWorkspace client={client} active={false} projectId={null} onOpenProject={vi.fn()} onBackToProjects={vi.fn()} />);
    rerender(<ProjectsWorkspace client={client} active onOpenProject={vi.fn()} projectId={null} onBackToProjects={vi.fn()} />);
    expect(await screen.findByText("No active Projects.")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Archived Projects" })).toBeTruthy();
  });

  it("shows a retryable load error while keeping the page usable", async () => {
    vi.mocked(listProjects).mockRejectedValueOnce(new Error("private server detail"));
    renderPage();
    expect((await screen.findByRole("alert")).textContent).toContain("Projects could not be loaded");
    expect(screen.getByRole("button", { name: "New Project" })).toBeTruthy();
    vi.mocked(listProjects).mockResolvedValueOnce({ projects: [project("p-1", "One")], contract_version: "v1" });
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("button", { name: "One" })).toBeTruthy();
    expect(screen.queryByText("private server detail")).toBeNull();
  });

  it("opens a Project using the route callback", async () => {
    vi.mocked(listProjects).mockResolvedValue({ projects: [project("p-1", "One")], contract_version: "v1" });
    const onOpenProject = vi.fn();
    render(<ProjectsWorkspace client={client} active projectId={null} onOpenProject={onOpenProject} onBackToProjects={vi.fn()} />);
    const open = await screen.findByRole("button", { name: "Open" });
    fireEvent.click(open);
    expect(onOpenProject).toHaveBeenCalledWith("p-1");
  });

  it("validates names before create, and preserves fields when create fails", async () => {
    vi.mocked(createProject).mockRejectedValueOnce(new Error("private server detail"));
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "New Project" }));
    const dialog = screen.getByRole("dialog");
    const name = within(dialog).getByLabelText("Name");
    fireEvent.change(name, { target: { value: " \t " } });
    expect(within(dialog).getByRole("button", { name: "Create Project" }).hasAttribute("disabled")).toBe(true);
    fireEvent.submit(dialog.querySelector("form")!);
    expect((await within(dialog).findByText("Enter a Project name.")).textContent).toContain("Enter a Project name.");
    expect(createProject).not.toHaveBeenCalled();
    fireEvent.change(name, { target: { value: "  AVA Engineering  " } });
    fireEvent.change(within(dialog).getByLabelText("Description (optional)"), { target: { value: "Metadata" } });
    fireEvent.change(within(dialog).getByLabelText("Instructions (optional)"), { target: { value: "Inert" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Create Project" }));
    expect((await within(dialog).findByRole("alert")).textContent).toContain("Project could not be created");
    expect((name as HTMLInputElement).value).toBe("  AVA Engineering  ");
    expect(screen.queryByText("private server detail")).toBeNull();
    expect(createProject).toHaveBeenCalledWith(client, {
      name: "  AVA Engineering  ", description: "Metadata", instructions: "Inert",
    });
  });

  it("closes after create and reloads the backend-provided list", async () => {
    vi.mocked(createProject).mockResolvedValue(project("p-new", "New Project"));
    vi.mocked(listProjects)
      .mockResolvedValueOnce({ projects: [], contract_version: "v1" })
      .mockResolvedValueOnce({ projects: [project("p-existing", "Existing"), project("p-new", "New Project")], contract_version: "v1" });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "New Project" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "New Project" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Create Project" }));
    expect(await screen.findByRole("button", { name: "New Project" })).toBeTruthy();
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(listProjects).toHaveBeenCalledTimes(2);
  });

  it("moves Projects only after archive/restore succeeds and shows safe failures", async () => {
    vi.mocked(listProjects).mockResolvedValue({ projects: [project("p-1", "One")], contract_version: "v1" });
    vi.mocked(setProjectArchived).mockRejectedValueOnce(new Error("private server detail"));
    renderPage();
    fireEvent.click((await screen.findAllByRole("button", { name: "Archive" }))[0]);
    expect((await screen.findByRole("alert")).textContent).toContain("Project archive status could not be changed");
    expect(screen.getByRole("heading", { name: "Active Projects" })).toBeTruthy();
    expect(screen.queryByText("private server detail")).toBeNull();

    vi.mocked(setProjectArchived).mockResolvedValue(project("p-1", "One", true));
    vi.mocked(listProjects).mockResolvedValueOnce({ projects: [project("p-1", "One", true)], contract_version: "v1" });
    fireEvent.click(screen.getAllByRole("button", { name: "Archive" })[0]);
    expect(await screen.findByRole("button", { name: "Restore" })).toBeTruthy();
    expect(setProjectArchived).toHaveBeenLastCalledWith(client, "p-1", { is_archived: true });
  });

  it("blocks duplicate archive requests while a mutation is pending", async () => {
    let resolveArchive: ((value: ReturnType<typeof project>) => void) | undefined;
    vi.mocked(listProjects)
      .mockResolvedValueOnce({ projects: [project("p-1", "One")], contract_version: "v1" })
      .mockResolvedValueOnce({ projects: [project("p-1", "One", true)], contract_version: "v1" });
    vi.mocked(setProjectArchived).mockImplementationOnce(() => new Promise((resolve) => { resolveArchive = resolve; }));
    renderPage();
    const archive = await screen.findByRole("button", { name: "Archive" });
    fireEvent.click(archive);
    expect(archive.hasAttribute("disabled")).toBe(true);
    fireEvent.click(archive);
    expect(setProjectArchived).toHaveBeenCalledTimes(1);
    resolveArchive?.(project("p-1", "One", true));
    expect(await screen.findByRole("button", { name: "Restore" })).toBeTruthy();
  });

  it("requires confirmation, removes on delete success, reconciles 404, and keeps generic failures", async () => {
    vi.mocked(listProjects).mockResolvedValue({ projects: [project("p-1", "One")], contract_version: "v1" });
    vi.mocked(deleteProject).mockRejectedValueOnce(new Error("private server detail"));
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
    let dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText(/permanently removes the Project metadata/i)).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete Project" }));
    expect((await within(dialog).findByRole("alert")).textContent).toContain("Project could not be deleted");
    expect(screen.getByRole("button", { name: "One" })).toBeTruthy();
    expect(screen.queryByText("private server detail")).toBeNull();

    vi.mocked(deleteProject).mockRejectedValueOnce(new ApiError("not found", 404, { error_code: "project_not_found" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete Project" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "One" })).toBeNull());
    expect(deleteProject).toHaveBeenCalledTimes(2);
  });

  it("removes a Project from the list after a confirmed successful delete", async () => {
    vi.mocked(listProjects).mockResolvedValue({ projects: [project("p-1", "One")], contract_version: "v1" });
    vi.mocked(deleteProject).mockResolvedValue(undefined);
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete Project" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "One" })).toBeNull());
    expect(deleteProject).toHaveBeenCalledWith(client, "p-1");
  });


  it("loads a Project directly and shows a safe not-found state on refresh", async () => {
    vi.mocked(getProject).mockRejectedValue(new ApiError("not found", 404, { error_code: "project_not_found" }));
    const back = vi.fn();
    renderPage("bad-id", back);
    expect(await screen.findByRole("heading", { name: "Project not found" })).toBeTruthy();
    expect(getProject).toHaveBeenCalledWith(client, "bad-id");
    fireEvent.click(within(screen.getByRole("alert")).getByRole("button", { name: "Back to Projects" }));
    expect(back).toHaveBeenCalledTimes(1);
  });

  it("shows Project identity and persisted metadata in the Overview section", async () => {
    vi.mocked(getProject).mockResolvedValue({
      ...project("p-1", "AVA Engineering", true),
      description: "Shared engineering workspace",
      created_at: "2026-03-01T12:00:00Z",
      updated_at: "2026-03-04T15:30:00Z",
    });
    renderPage("p-1");

    expect(await screen.findByRole("heading", { name: "AVA Engineering" })).toBeTruthy();
    expect(screen.getByLabelText("Archived Project")).toBeTruthy();
    expect(screen.getAllByText("Shared engineering workspace")).toHaveLength(2);
    expect(screen.getByRole("tab", { name: "Overview" }).getAttribute("aria-selected")).toBe("true");
    const panel = screen.getByRole("tabpanel");
    expect(within(panel).getByText("Project name").nextElementSibling?.textContent).toBe("AVA Engineering");
    expect(within(panel).getByText("Description").nextElementSibling?.textContent).toBe("Shared engineering workspace");
    expect(within(panel).getByText("Status").nextElementSibling?.textContent).toBe("Archived");
    expect(within(panel).getByText("Created").nextElementSibling?.textContent).toBe("2026-03-01T12:00:00Z");
    expect(within(panel).getByText("Last updated").nextElementSibling?.textContent).toBe("2026-03-04T15:30:00Z");
  });

  it("activates the Project Files tab and exposes Project System Prompts under Settings", async () => {
    vi.mocked(getProject).mockResolvedValue(project("p-1", "One"));
    renderPage("p-1");
    await screen.findByRole("heading", { name: "One" });

    fireEvent.click(screen.getByRole("tab", { name: "Files" }));
    expect(await screen.findByRole("heading", { name: "Files", level: 2 })).toBeTruthy();
    expect(await screen.findByText("No files in this Project yet.")).toBeTruthy();
    expect(listProjectFiles).toHaveBeenCalledWith(client, "p-1");

    fireEvent.click(screen.getByRole("tab", { name: "Settings" }));
    expect(screen.getByRole("tab", { name: "Settings" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("heading", { name: "System Prompts", level: 2 })).toBeTruthy();
    expect(screen.getByLabelText("System Prompts for Project: One")).toBeTruthy();
    expect(screen.getByRole("tabpanel").getAttribute("aria-labelledby")).toBe("project-section-tab-settings");

  });

  it("keeps archived Project Files manageable and reconciles a deleted Project", async () => {
    vi.mocked(getProject).mockResolvedValue(project("p-archived", "Old", true));
    const archivedFile = {
      id: "pf-1", project_id: "p-archived", file_name: "stored.txt", content_type: "text/plain", size_bytes: 4,
      created_at: "2026-10-02T00:00:00Z", updated_at: "2026-10-02T00:00:00Z", contract_version: "v1" as const,
    };
    vi.mocked(listProjectFiles).mockResolvedValue({ project_id: "p-archived", files: [archivedFile], contract_version: "v1" });
    const onBackToProjects = vi.fn();
    const onProjectDeleted = vi.fn();
    renderPage("p-archived", onBackToProjects, { onProjectDeleted });
    await screen.findByRole("heading", { name: "Old" });
    fireEvent.click(screen.getByRole("tab", { name: "Files" }));
    const row = await screen.findByRole("row", { name: /stored\.txt/ });
    expect(within(row).getByRole("button", { name: "Download stored.txt" })).toBeTruthy();
    expect(within(row).getByRole("button", { name: "Delete stored.txt" })).toBeTruthy();

    vi.mocked(listProjectFiles).mockRejectedValueOnce(new ApiError("not found", 404, { error_code: "project_not_found" }));
    fireEvent.click(screen.getByRole("tab", { name: "Conversations" }));
    fireEvent.click(screen.getByRole("tab", { name: "Files" }));
    await waitFor(() => expect(onBackToProjects).toHaveBeenCalledTimes(1));
    expect(onProjectDeleted).toHaveBeenCalledWith("p-archived");
  });

  it("exposes independent execution defaults in Settings and keeps archived Projects editable", async () => {
    vi.mocked(getProject).mockResolvedValue(project("p-archived", "Old", true));
    vi.mocked(getProjectExecutionDefaults).mockResolvedValue({ project_id: "p-archived", runtime_key: null, model_id: null, runtime_available: null, contract_version: "v1" });
    vi.mocked(getRuntimes).mockResolvedValue({ runtimes: [{ runtime_info: { runtime_id: "native", display_name: "Native" }, is_default: true, contract_version: "v1" }], default_runtime_id: "native", contract_version: "v1" });
    renderPage("p-archived");
    await screen.findByRole("heading", { name: "Old" });
    fireEvent.click(screen.getByRole("tab", { name: "Settings" }));
    const runtime = await screen.findByLabelText("Preferred Runtime") as HTMLSelectElement;
    expect(runtime.value).toBe("");
    expect((screen.getByLabelText("Preferred Model") as HTMLSelectElement).value).toBe("");
    expect(screen.getByRole("heading", { name: "Execution Defaults", level: 2 })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "System Prompts", level: 2 })).toBeTruthy();
    fireEvent.change(runtime, { target: { value: "native" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(updateProjectExecutionDefaults).toHaveBeenCalledWith(client, "p-archived", { runtime_key: "native" }));
  });

  it("discards a Project A draft when navigating to Project B", async () => {
    vi.mocked(getProject)
      .mockResolvedValueOnce(project("p-a", "Project A"))
      .mockResolvedValueOnce(project("p-b", "Project B"));
    vi.mocked(getProjectExecutionDefaults)
      .mockResolvedValueOnce({ project_id: "p-a", runtime_key: null, model_id: null, runtime_available: null, contract_version: "v1" })
      .mockResolvedValueOnce({ project_id: "p-b", runtime_key: "openhands", model_id: "model-b", runtime_available: true, contract_version: "v1" });
    vi.mocked(getRuntimes).mockResolvedValue({ runtimes: [
      { runtime_info: { runtime_id: "native", display_name: "Native" }, is_default: false, contract_version: "v1" },
      { runtime_info: { runtime_id: "openhands", display_name: "OpenHands" }, is_default: false, contract_version: "v1" },
    ], default_runtime_id: "native", contract_version: "v1" });

    const page = renderPage("p-a");
    await screen.findByRole("heading", { name: "Project A" });
    fireEvent.click(screen.getByRole("tab", { name: "Settings" }));
    const runtime = await screen.findByLabelText("Preferred Runtime") as HTMLSelectElement;
    fireEvent.change(runtime, { target: { value: "native" } });

    page.rerender(<ProjectsWorkspace client={client} active projectId="p-b" onOpenProject={vi.fn()} onBackToProjects={vi.fn()} />);
    await screen.findByRole("heading", { name: "Project B" });
    fireEvent.click(screen.getByRole("tab", { name: "Settings" }));
    await waitFor(() => {
      expect((screen.getByLabelText("Preferred Runtime") as HTMLSelectElement).value).toBe("openhands");
      expect((screen.getByLabelText("Preferred Model") as HTMLSelectElement).value).toBe("model-b");
    });
    expect(updateProjectExecutionDefaults).not.toHaveBeenCalled();
  });

  it("shows null as an empty clean draft and preserves the initial string exactly", async () => {
    const multiline = "Line one\n\n- Item A\n  - 日本語 →";
    vi.mocked(getProject).mockResolvedValueOnce(project("p-null", "Null Project"));
    const { rerender } = renderPage("p-null");
    await screen.findByRole("heading", { name: "Null Project" });
    fireEvent.click(screen.getByRole("tab", { name: "Instructions" }));
    expect(document.getElementById("project-section-overview")?.getAttribute("style")).toContain("display: none");
    expect(document.getElementById("project-section-instructions")?.getAttribute("style")).toContain("display: flex");
    const editor = screen.getByRole("textbox", { name: "Project instructions" }) as HTMLTextAreaElement;
    expect(editor.value).toBe("");
    expect(screen.getByRole("button", { name: "Save" }).hasAttribute("disabled")).toBe(true);
    expect(updateProject).not.toHaveBeenCalled();

    vi.mocked(getProject).mockResolvedValueOnce(project("p-text", "Text Project", false, multiline));
    rerender(
      <ProjectsWorkspace client={client} active projectId="p-text" onOpenProject={vi.fn()} onBackToProjects={vi.fn()} />,
    );
    await screen.findByRole("heading", { name: "Text Project" });
    fireEvent.click(screen.getByRole("tab", { name: "Instructions" }));
    expect((screen.getByRole("textbox", { name: "Project instructions" }) as HTMLTextAreaElement).value).toBe(multiline);
  });

  it("saves multiline Unicode text exactly and reconciles canonical Project metadata", async () => {
    const original = "Old";
    const next = "Line one\n\n- Item A\n  - 日本語 →";
    const updated = { ...project("p-1", "One", false, next), updated_at: "2026-01-03T12:00:00Z" };
    vi.mocked(getProject).mockResolvedValue(project("p-1", "One", false, original));
    vi.mocked(listProjects).mockResolvedValue({ projects: [project("p-1", "One", false, original)], contract_version: "v1" });
    vi.mocked(updateProject).mockResolvedValue(updated);
    const onProjectUpdated = vi.fn();
    renderPage("p-1", vi.fn(), { onProjectUpdated });
    await screen.findByRole("heading", { name: "One" });
    fireEvent.click(screen.getByRole("tab", { name: "Instructions" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Project instructions" }), { target: { value: next } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(updateProject).toHaveBeenCalledWith(client, "p-1", { name: "One", instructions: next }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Save" }).hasAttribute("disabled")).toBe(true));
    expect((screen.getByRole("textbox", { name: "Project instructions" }) as HTMLTextAreaElement).value).toBe(next);
    expect(onProjectUpdated).toHaveBeenCalledWith(updated);
    fireEvent.click(screen.getByRole("tab", { name: "Overview" }));
    expect(screen.getByText("Last updated").nextElementSibling?.textContent).toBe(updated.updated_at);
  });

  it("saves an intentionally empty string as empty and keeps unchanged drafts request-free", async () => {
    const updated = { ...project("p-1", "One", false, ""), updated_at: "2026-01-03T00:00:00Z" };
    vi.mocked(getProject).mockResolvedValue(project("p-1", "One", false, "Old"));
    vi.mocked(updateProject).mockResolvedValue(updated);
    renderPage("p-1");
    await screen.findByRole("heading", { name: "One" });
    fireEvent.click(screen.getByRole("tab", { name: "Instructions" }));
    expect(screen.getByRole("button", { name: "Save" }).hasAttribute("disabled")).toBe(true);
    expect(updateProject).not.toHaveBeenCalled();

    fireEvent.change(screen.getByRole("textbox", { name: "Project instructions" }), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(updateProject).toHaveBeenCalledWith(client, "p-1", { name: "One", instructions: "" }));
  });

  it("clears explicitly to null and Cancel restores the persisted Project value", async () => {
    const cleared = { ...project("p-1", "One"), updated_at: "2026-01-04T00:00:00Z" };
    vi.mocked(getProject).mockResolvedValue(project("p-1", "One", false, "Saved"));
    vi.mocked(updateProject).mockResolvedValue(cleared);
    renderPage("p-1");
    await screen.findByRole("heading", { name: "One" });
    fireEvent.click(screen.getByRole("tab", { name: "Instructions" }));
    const editor = screen.getByRole("textbox", { name: "Project instructions" });
    fireEvent.change(editor, { target: { value: "Unsaved draft" } });
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect((editor as HTMLTextAreaElement).value).toBe("Saved");
    expect(updateProject).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Clear instructions" }));
    await waitFor(() => expect(updateProject).toHaveBeenCalledWith(client, "p-1", { name: "One", instructions: null }));
    await waitFor(() => expect((editor as HTMLTextAreaElement).value).toBe(""));
    expect(screen.getByRole("button", { name: "Save" }).hasAttribute("disabled")).toBe(true);
  });

  it("keeps a failed draft, reports a safe error, and re-enables retry", async () => {
    vi.mocked(getProject).mockResolvedValue(project("p-1", "One", false, "Persisted"));
    vi.mocked(updateProject).mockRejectedValueOnce(new Error("private server detail"));
    renderPage("p-1");
    await screen.findByRole("heading", { name: "One" });
    fireEvent.click(screen.getByRole("tab", { name: "Instructions" }));
    const editor = screen.getByRole("textbox", { name: "Project instructions" }) as HTMLTextAreaElement;
    fireEvent.change(editor, { target: { value: "Keep this draft" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect((await screen.findByRole("alert")).textContent).toContain("Your draft is still here");
    expect(editor.value).toBe("Keep this draft");
    expect(screen.queryByText("private server detail")).toBeNull();
    expect(screen.getByRole("button", { name: "Save" }).hasAttribute("disabled")).toBe(false);
  });

  it("prevents duplicate saves and discards an unsaved draft when switching Projects", async () => {
    let resolveUpdate: ((value: ReturnType<typeof project>) => void) | undefined;
    vi.mocked(getProject)
      .mockResolvedValueOnce(project("p-a", "Project A", false, "A"))
      .mockResolvedValueOnce(project("p-b", "Project B", false, "B"));
    vi.mocked(updateProject).mockImplementationOnce(() => new Promise((resolve) => { resolveUpdate = resolve; }));
    const { rerender } = renderPage("p-a");
    await screen.findByRole("heading", { name: "Project A" });
    fireEvent.click(screen.getByRole("tab", { name: "Instructions" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Project instructions" }), { target: { value: "A draft" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByRole("button", { name: "Saving…" }).hasAttribute("disabled")).toBe(true);
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Project instructions" }), { key: "Enter", ctrlKey: true });
    expect(updateProject).toHaveBeenCalledTimes(1);

    resolveUpdate?.({ ...project("p-a", "Project A", false, "A draft"), updated_at: "2026-01-02T00:00:00Z" });
    await waitFor(() => expect(screen.getByRole("button", { name: "Save" }).hasAttribute("disabled")).toBe(true));
    rerender(<ProjectsWorkspace client={client} active projectId="p-b" onOpenProject={vi.fn()} onBackToProjects={vi.fn()} />);
    await screen.findByRole("heading", { name: "Project B" });
    fireEvent.click(screen.getByRole("tab", { name: "Instructions" }));
    expect((screen.getByRole("textbox", { name: "Project instructions" }) as HTMLTextAreaElement).value).toBe("B");
  });

  it("allows editing instructions on archived Projects", async () => {
    vi.mocked(getProject).mockResolvedValue(project("p-archived", "Archived", true, "Old"));
    const updated = { ...project("p-archived", "Archived", true, "New"), updated_at: "2026-01-03T00:00:00Z" };
    vi.mocked(updateProject).mockResolvedValue(updated);
    renderPage("p-archived");
    await screen.findByRole("heading", { name: "Archived" });
    fireEvent.click(screen.getByRole("tab", { name: "Instructions" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Project instructions" }), { target: { value: "New" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(updateProject).toHaveBeenCalledWith(client, "p-archived", { name: "Archived", instructions: "New" }));
  });

  it("lists Project conversation references and opens or creates via canonical callbacks", async () => {
    const listed = {
      conversation_id: "conv-project",
      title: "Project thread",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
      is_pinned: false,
      is_archived: false,
      folder_id: "folder-1",
      project_id: "p-1",
      contract_version: "v1" as const,
    };
    vi.mocked(listProjectConversations).mockResolvedValue({ conversations: [listed], contract_version: "v1" });
    const onOpenConversation = vi.fn();
    const onCreateConversation = vi.fn().mockResolvedValue(undefined);
    vi.mocked(getProject).mockResolvedValue(project("p-1", "One"));
    renderPage("p-1", vi.fn(), {
      conversations: [{ id: "conv-project", title: "Project thread", createdAt: listed.created_at, folderId: "folder-1", projectId: "p-1", messages: [] }],
      onOpenConversation,
      onCreateConversation,
    });
    await screen.findByRole("heading", { name: "One" });
    fireEvent.click(screen.getByRole("tab", { name: "Conversations" }));
    expect(await screen.findByRole("button", { name: "Project thread" })).toBeTruthy();
    expect(listProjectConversations).toHaveBeenCalledWith(client, "p-1");
    fireEvent.click(screen.getByRole("button", { name: "Project thread" }));
    expect(onOpenConversation).toHaveBeenCalledWith("conv-project");
    fireEvent.click(screen.getByRole("button", { name: "New Chat" }));
    await waitFor(() => expect(onCreateConversation).toHaveBeenCalledWith("p-1"));
  });

  it("excludes archived conversations from the active Project conversation view", async () => {
    const active = {
      conversation_id: "active-project-chat", title: "Active Project chat", created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z", is_pinned: false, is_archived: false,
      folder_id: "folder-1", project_id: "p-1", contract_version: "v1" as const,
    };
    const archived = { ...active, conversation_id: "archived-project-chat", title: "Archived Project chat", is_archived: true };
    vi.mocked(listProjectConversations).mockResolvedValue({ conversations: [active, archived], contract_version: "v1" });
    vi.mocked(getProject).mockResolvedValue(project("p-1", "One"));
    renderPage("p-1", vi.fn(), {
      conversations: [
        { id: active.conversation_id, title: active.title, createdAt: active.created_at, folderId: active.folder_id, projectId: active.project_id, messages: [] },
        { id: archived.conversation_id, title: archived.title, createdAt: archived.created_at, isArchived: true, folderId: archived.folder_id, projectId: archived.project_id, messages: [] },
      ],
    });
    await screen.findByRole("heading", { name: "One" });
    fireEvent.click(screen.getByRole("tab", { name: "Conversations" }));
    expect(await screen.findByRole("button", { name: "Active Project chat" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Archived Project chat" })).toBeNull();
  });

  it("clears failed Project chat creation state so the user can retry once", async () => {
    const onCreateConversation = vi.fn()
      .mockRejectedValueOnce(new Error("temporary create failure"))
      .mockResolvedValueOnce(undefined);
    vi.mocked(getProject).mockResolvedValue(project("p-retry", "Retry Project"));
    vi.mocked(listProjectConversations).mockResolvedValue({ conversations: [], contract_version: "v1" });
    renderPage("p-retry", vi.fn(), { onCreateConversation });
    await screen.findByRole("heading", { name: "Retry Project" });
    fireEvent.click(screen.getByRole("tab", { name: "Conversations" }));

    const createButton = await screen.findByRole("button", { name: "New Chat" });
    fireEvent.click(createButton);
    expect((await screen.findByRole("alert")).textContent).toContain("A chat could not be created in this Project. Try again.");
    expect(createButton.hasAttribute("disabled")).toBe(false);

    fireEvent.click(createButton);
    await waitFor(() => expect(onCreateConversation).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("keeps the Project shell on Overview after a direct-route load", async () => {
    vi.mocked(getProject).mockResolvedValue(project("p-direct", "Direct Project"));
    renderPage("p-direct");
    expect(await screen.findByRole("heading", { name: "Direct Project" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Overview" }).getAttribute("aria-selected")).toBe("true");
    expect(getProject).toHaveBeenCalledWith(client, "p-direct");
  });

  it("returns to the list after deleting the Project open in its placeholder route", async () => {
    vi.mocked(getProject).mockResolvedValue(project("p-1", "One"));
    vi.mocked(deleteProject).mockResolvedValue(undefined);
    const back = vi.fn();
    renderPage("p-1", back);
    expect(await screen.findByRole("heading", { name: "One" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Delete Project" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText(/permanently removes the Project metadata/i)).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete Project" }));
    await waitFor(() => expect(back).toHaveBeenCalledTimes(1));
    expect(deleteProject).toHaveBeenCalledWith(client, "p-1");
  });
});
