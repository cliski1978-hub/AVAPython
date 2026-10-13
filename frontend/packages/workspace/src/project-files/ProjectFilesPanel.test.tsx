// @vitest-environment jsdom
import { ApiClient, ApiError, deleteProjectFile, downloadProjectFile, listProjectFiles, uploadProjectFile } from "@ava/api-client";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { formatProjectFileSize, ProjectFilesPanel } from "./ProjectFilesPanel";

vi.mock("@ava/api-client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@ava/api-client")>();
  return {
    ...mod,
    listProjectFiles: vi.fn(),
    uploadProjectFile: vi.fn(),
    downloadProjectFile: vi.fn(),
    deleteProjectFile: vi.fn(),
  };
});

const client = new ApiClient({ baseUrl: "http://localhost:99999" });
type ProjectFile = Awaited<ReturnType<typeof listProjectFiles>>["files"][number];

function file(id: string, fileName: string, sizeBytes = 10, contentType: string | null = "text/plain"): ProjectFile {
  return {
    id,
    project_id: "p-1",
    file_name: fileName,
    content_type: contentType,
    size_bytes: sizeBytes,
    created_at: "2026-10-02T12:00:00Z",
    updated_at: "2026-10-02T12:00:00Z",
    contract_version: "v1",
  };
}

function listResponse(files: ProjectFile[], projectId = "p-1") {
  return { project_id: projectId, files, contract_version: "v1" as const };
}

function renderPanel(projectId = "p-1", onProjectMissing = vi.fn()) {
  return render(
    <ProjectFilesPanel client={client} projectId={projectId} projectName={`Project ${projectId}`} onProjectMissing={onProjectMissing} />,
  );
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(listProjectFiles).mockResolvedValue(listResponse([]));
  vi.mocked(uploadProjectFile).mockResolvedValue(file("created", "created.txt"));
  vi.mocked(downloadProjectFile).mockResolvedValue(new Blob(["download"]));
  vi.mocked(deleteProjectFile).mockResolvedValue(undefined);
  Object.defineProperty(URL, "createObjectURL", { configurable: true, value: vi.fn(() => "blob:project-file") });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
});

describe("ProjectFilesPanel", () => {
  it("formats zero-byte and binary-unit sizes consistently", () => {
    expect(formatProjectFileSize(0)).toBe("0 B");
    expect(formatProjectFileSize(1_229)).toBe("1.2 KB");
    expect(formatProjectFileSize(14 * 1024 * 1024)).toBe("14 MB");
  });

  it("shows a local loading state, then backend-ordered files and the public metadata only", async () => {
    let resolve: ((value: ReturnType<typeof listResponse>) => void) | undefined;
    vi.mocked(listProjectFiles).mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
    renderPanel();
    expect(screen.getByRole("status", { name: "Loading Project files…" })).toBeTruthy();
    resolve?.(listResponse([
      file("b", "spec.pdf", 0, null),
      file("a", "requirements.pdf", 1_229, "application/pdf"),
      file("unicode", "設計仕様書.pdf"),
    ]));

    const table = await screen.findByRole("table", { name: "Files in Project p-1" });
    const rows = within(table).getAllByRole("row");
    expect(rows.slice(1).map((row) => row.getAttribute("data-project-file-id"))).toEqual(["b", "a", "unicode"]);
    expect(within(rows[1]).getByText("Unknown")).toBeTruthy();
    expect(within(rows[1]).getByText("0 B")).toBeTruthy();
    expect(within(rows[2]).getByText("1.2 KB")).toBeTruthy();
    expect(within(rows[3]).getByText("設計仕様書.pdf")).toBeTruthy();
    expect(table.textContent).not.toContain("content_ref");
    expect(table.textContent).not.toContain("storage_root");
  });

  it("renders the empty state and keeps Upload available", async () => {
    renderPanel();
    expect(await screen.findByText("No files in this Project yet.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Upload File" })).toBeTruthy();
  });

  it("retries a failed list request and renders the second response", async () => {
    vi.mocked(listProjectFiles)
      .mockRejectedValueOnce(new Error("private server detail"))
      .mockResolvedValueOnce(listResponse([file("retry", "retry.md")]));
    renderPanel();
    expect(await screen.findByText("Project files could not be loaded.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("retry.md")).toBeTruthy();
    expect(listProjectFiles).toHaveBeenCalledTimes(2);
    expect(screen.queryByText("private server detail")).toBeNull();
  });

  it("uploads the selected File object and reconciles backend order", async () => {
    vi.mocked(listProjectFiles)
      .mockResolvedValueOnce(listResponse([file("old", "requirements.pdf")]))
      .mockResolvedValueOnce(listResponse([file("new", "spec.pdf"), file("old", "requirements.pdf")]));
    vi.mocked(uploadProjectFile).mockResolvedValueOnce(file("new", "spec.pdf"));
    renderPanel();
    await screen.findByText("requirements.pdf");
    const selected = new File(["new content"], "spec.pdf", { type: "" });
    fireEvent.change(screen.getByLabelText("Choose a Project file to upload"), { target: { files: [selected] } });
    fireEvent.click(screen.getByRole("button", { name: "Upload File" }));

    await waitFor(() => expect(within(screen.getByRole("table", { name: "Files in Project p-1" })).getByText("spec.pdf")).toBeTruthy());
    expect(uploadProjectFile).toHaveBeenCalledWith(client, "p-1", selected, { fileName: "spec.pdf", contentType: null });
    const rows = screen.getByRole("table", { name: "Files in Project p-1" }).querySelectorAll("tbody tr");
    expect(Array.from(rows).map((row) => row.getAttribute("data-project-file-id"))).toEqual(["new", "old"]);
    expect((screen.getByLabelText("Choose a Project file to upload") as HTMLInputElement).value).toBe("");
  });

  it("shows the backend duplicate-name conflict without changing the file list", async () => {
    vi.mocked(listProjectFiles).mockResolvedValue(listResponse([file("existing", "SKILL.md")]));
    vi.mocked(uploadProjectFile).mockRejectedValueOnce(new ApiError("Request failed: 409", 409, {
      error_code: "project_file_name_conflict",
    }));
    renderPanel();
    await screen.findByText("SKILL.md");
    fireEvent.change(screen.getByLabelText("Choose a Project file to upload"), {
      target: { files: [new File(["replacement"], "skill.md", { type: "text/markdown" })] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Upload File" }));

    expect((await screen.findByRole("alert")).textContent).toContain(
      'A file named "skill.md" already exists in this Project.',
    );
    expect(screen.getAllByText("SKILL.md")).toHaveLength(1);
    expect(screen.getByText("Selected: skill.md")).toBeTruthy();
    expect(listProjectFiles).toHaveBeenCalledTimes(1);
  });

  it("shows upload pending state and prevents a duplicate submission", async () => {
    let resolveUpload: ((value: ProjectFile) => void) | undefined;
    vi.mocked(uploadProjectFile).mockImplementationOnce(() => new Promise((resolve) => { resolveUpload = resolve; }));
    vi.mocked(listProjectFiles)
      .mockResolvedValueOnce(listResponse([]))
      .mockResolvedValueOnce(listResponse([file("pending", "pending.txt")]));
    renderPanel();
    await screen.findByText("No files in this Project yet.");
    fireEvent.change(screen.getByLabelText("Choose a Project file to upload"), {
      target: { files: [new File(["x"], "pending.txt", { type: "text/plain" })] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Upload File" }));
    expect(screen.getByRole("button", { name: /Uploading…/ }).hasAttribute("disabled")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: /Uploading…/ }));
    expect(uploadProjectFile).toHaveBeenCalledTimes(1);
    resolveUpload?.(file("pending", "pending.txt"));
    expect(await screen.findByText("pending.txt")).toBeTruthy();
  });

  it("keeps the selected file after upload failure and allows retry without a phantom row", async () => {
    vi.mocked(uploadProjectFile)
      .mockRejectedValueOnce(new Error("private server detail"))
      .mockResolvedValueOnce(file("ok", "retry.txt"));
    vi.mocked(listProjectFiles)
      .mockResolvedValueOnce(listResponse([]))
      .mockResolvedValueOnce(listResponse([file("ok", "retry.txt")]));
    renderPanel();
    await screen.findByText("No files in this Project yet.");
    const selected = new File(["retry"], "retry.txt", { type: "text/plain" });
    fireEvent.change(screen.getByLabelText("Choose a Project file to upload"), { target: { files: [selected] } });
    fireEvent.click(screen.getByRole("button", { name: "Upload File" }));

    expect((await screen.findByRole("alert")).textContent).toContain("Unable to upload this file.");
    expect(screen.getByText("Selected: retry.txt")).toBeTruthy();
    expect(screen.queryByRole("row", { name: /retry\.txt/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Upload File" }));
    expect(await screen.findByText("retry.txt")).toBeTruthy();
    expect(uploadProjectFile).toHaveBeenCalledTimes(2);
  });

  it("downloads by exact Project/file IDs and releases its temporary object URL", async () => {
    vi.mocked(listProjectFiles).mockResolvedValue(listResponse([file("download-id", "résumé.txt")]));
    const { container } = renderPanel();
    const row = await screen.findByRole("row", { name: /résumé\.txt/ });
    let downloadedName = "";
    vi.mocked(HTMLAnchorElement.prototype.click).mockImplementation(function (this: HTMLAnchorElement) {
      downloadedName = this.download;
    });
    fireEvent.click(within(row).getByRole("button", { name: "Download résumé.txt" }));
    await waitFor(() => expect(downloadProjectFile).toHaveBeenCalledWith(client, "p-1", "download-id"));
    await waitFor(() => expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:project-file"));
    expect(HTMLAnchorElement.prototype.click).toHaveBeenCalled();
    expect(downloadedName).toBe("résumé.txt");
    expect(container.querySelector('a[download="résumé.txt"]')).toBeNull();
  });

  it("shows download failure on the row and leaves the file available for retry", async () => {
    vi.mocked(listProjectFiles).mockResolvedValue(listResponse([file("download-id", "one.txt")]));
    vi.mocked(downloadProjectFile).mockRejectedValueOnce(new Error("private detail"));
    renderPanel();
    const row = await screen.findByRole("row", { name: /one\.txt/ });
    fireEvent.click(within(row).getByRole("button", { name: "Download one.txt" }));
    expect((await within(row).findByRole("alert")).textContent).toContain("Unable to download this file.");
    expect(within(row).getByRole("button", { name: "Download one.txt" })).toBeTruthy();
    expect(screen.getByText("one.txt")).toBeTruthy();
  });

  it("requires confirmation and deletes the selected file by ID", async () => {
    vi.mocked(listProjectFiles).mockResolvedValue(listResponse([file("a", "first.pdf"), file("b", "second.pdf")]));
    renderPanel();
    const table = await screen.findByRole("table", { name: "Files in Project p-1" });
    const rows = table.querySelectorAll("tbody tr");
    const rowA = rows[0] as HTMLElement;
    fireEvent.click(within(rowA).getByRole("button", { name: "Delete first.pdf" }));
    expect(screen.getByRole("heading", { name: "Delete “first.pdf”?" })).toBeTruthy();
    expect(deleteProjectFile).not.toHaveBeenCalled();
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete file" }));
    await waitFor(() => expect(deleteProjectFile).toHaveBeenCalledWith(client, "p-1", "a"));
    await waitFor(() => expect(screen.getByRole("table", { name: "Files in Project p-1" }).querySelectorAll("tbody tr")).toHaveLength(1));
    expect(screen.getByRole("row", { name: /second\.pdf/ }).getAttribute("data-project-file-id")).toBe("b");
    expect(rowA.getAttribute("data-project-file-id")).toBe("a");
  });

  it("keeps the row after delete failure and allows a confirmed retry", async () => {
    vi.mocked(listProjectFiles).mockResolvedValue(listResponse([file("delete-id", "keep.txt")]));
    vi.mocked(deleteProjectFile).mockRejectedValueOnce(new Error("private detail"));
    renderPanel();
    const row = await screen.findByRole("row", { name: /keep\.txt/ });
    fireEvent.click(within(row).getByRole("button", { name: "Delete keep.txt" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete file" }));
    expect((await within(screen.getByRole("dialog")).findByRole("alert")).textContent).toContain("Unable to delete this file.");
    expect(screen.getByRole("row", { name: /keep\.txt/ })).toBeTruthy();
    vi.mocked(deleteProjectFile).mockResolvedValueOnce(undefined);
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete file" }));
    await waitFor(() => expect(screen.queryByRole("row", { name: /keep\.txt/ })).toBeNull());
  });

  it("does not let a late Project A response replace Project B", async () => {
    let resolveA: ((value: ReturnType<typeof listResponse>) => void) | undefined;
    vi.mocked(listProjectFiles)
      .mockImplementationOnce(() => new Promise((resolve) => { resolveA = resolve; }))
      .mockResolvedValueOnce(listResponse([file("b-file", "project-b.txt", 1, "text/plain")], "p-b"));
    const page = renderPanel("p-a");
    page.rerender(<ProjectFilesPanel client={client} projectId="p-b" projectName="Project p-b" />);
    expect(screen.queryByText("project-a.txt")).toBeNull();
    expect(await screen.findByText("project-b.txt")).toBeTruthy();
    resolveA?.(listResponse([file("a-file", "project-a.txt")], "p-a"));
    await waitFor(() => expect(screen.queryByText("project-a.txt")).toBeNull());
    expect(screen.getByText("project-b.txt")).toBeTruthy();
  });
});
