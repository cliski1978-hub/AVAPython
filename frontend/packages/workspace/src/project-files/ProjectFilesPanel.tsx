import {
  ApiError,
  deleteProjectFile,
  downloadProjectFile,
  listProjectFiles,
  uploadProjectFile,
  type ApiClient,
} from "@ava/api-client";
import { Button, LoadingIndicator, Modal, defaultTheme } from "@ava/ui-core";
import { useEffect, useRef, useState, type ChangeEvent } from "react";

const t = defaultTheme;
type ProjectFile = Awaited<ReturnType<typeof listProjectFiles>>["files"][number];

const sectionStyle = {
  display: "flex",
  flexDirection: "column" as const,
  gap: t.spacing.md,
};

const fileRowStyle = {
  borderBottom: `${t.border.width}px solid ${t.colors.border}`,
};

function isProjectNotFound(error: unknown): boolean {
  if (!(error instanceof ApiError) || error.status !== 404) return false;
  return typeof error.body === "object" && error.body !== null &&
    "error_code" in error.body && error.body.error_code === "project_not_found";
}

export function formatProjectFileSize(sizeBytes: number): string {
  if (sizeBytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const unitIndex = Math.min(Math.floor(Math.log(sizeBytes) / Math.log(1024)), units.length - 1);
  const value = sizeBytes / (1024 ** unitIndex);
  const formatted = new Intl.NumberFormat("en-US", {
    maximumFractionDigits: value < 10 && unitIndex > 0 ? 1 : 0,
  }).format(value);
  return `${formatted} ${units[unitIndex]}`;
}

function formatCreatedAt(createdAt: string): string {
  const date = new Date(createdAt);
  if (Number.isNaN(date.getTime())) return createdAt;
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(date);
}

function triggerBlobDownload(blob: Blob, fileName: string): void {
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = fileName;
  anchor.style.display = "none";
  document.body.append(anchor);
  try {
    anchor.click();
  } finally {
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
  }
}

export function ProjectFilesPanel({
  client,
  projectId,
  projectName,
  onProjectMissing,
}: {
  client: ApiClient;
  projectId: string;
  projectName: string;
  onProjectMissing?: () => void;
}) {
  const [files, setFiles] = useState<ProjectFile[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploadPending, setUploadPending] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [refreshNotice, setRefreshNotice] = useState(false);
  const [downloadingIds, setDownloadingIds] = useState<Set<string>>(() => new Set());
  const [rowErrors, setRowErrors] = useState<Record<string, string>>({});
  const [deleteTarget, setDeleteTarget] = useState<ProjectFile | null>(null);
  const [deletePending, setDeletePending] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const uploadPendingRef = useRef(false);
  const deletingRef = useRef(false);
  const downloadingRef = useRef<Set<string>>(new Set());
  const currentProjectIdRef = useRef(projectId);
  currentProjectIdRef.current = projectId;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError(false);
    setRefreshNotice(false);
    void listProjectFiles(client, projectId)
      .then((response) => {
        if (!cancelled) setFiles(response.files);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        if (isProjectNotFound(error)) {
          onProjectMissing?.();
          return;
        }
        setLoadError(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [client, loadAttempt, onProjectMissing, projectId]);

  function selectFile(event: ChangeEvent<HTMLInputElement>): void {
    setSelectedFile(event.currentTarget.files?.[0] ?? null);
    setUploadError(null);
    setRefreshNotice(false);
    // Let the user choose the same file again after a failed attempt.
    event.currentTarget.value = "";
  }

  async function uploadSelectedFile(): Promise<void> {
    const file = selectedFile;
    if (file == null || uploadPendingRef.current) return;
    uploadPendingRef.current = true;
    setUploadPending(true);
    setUploadError(null);
    setRefreshNotice(false);
    try {
      const created = await uploadProjectFile(client, projectId, file, {
        fileName: file.name,
        contentType: file.type || null,
      });
      if (currentProjectIdRef.current !== projectId) return;
      setSelectedFile(null);
      if (fileInputRef.current != null) fileInputRef.current.value = "";
      try {
        // The list endpoint owns canonical ordering, including duplicate names.
        const response = await listProjectFiles(client, projectId);
        if (currentProjectIdRef.current !== projectId) return;
        setFiles(response.files);
      } catch (error) {
        if (currentProjectIdRef.current !== projectId) return;
        if (isProjectNotFound(error)) {
          onProjectMissing?.();
          return;
        }
        setFiles((current) => current.some((item) => item.id === created.id)
          ? current
          : [...current, created]);
        setRefreshNotice(true);
      }
    } catch (error) {
      if (currentProjectIdRef.current !== projectId) return;
      if (isProjectNotFound(error)) onProjectMissing?.();
      else setUploadError("Unable to upload this file.");
    } finally {
      uploadPendingRef.current = false;
      setUploadPending(false);
    }
  }

  async function downloadFile(file: ProjectFile): Promise<void> {
    if (downloadingRef.current.has(file.id)) return;
    downloadingRef.current.add(file.id);
    setDownloadingIds(new Set(downloadingRef.current));
    setRowErrors((current) => ({ ...current, [file.id]: "" }));
    try {
      const blob = await downloadProjectFile(client, projectId, file.id);
      if (currentProjectIdRef.current !== projectId) return;
      triggerBlobDownload(blob, file.file_name);
    } catch (error) {
      if (currentProjectIdRef.current !== projectId) return;
      if (isProjectNotFound(error)) onProjectMissing?.();
      else setRowErrors((current) => ({ ...current, [file.id]: "Unable to download this file." }));
    } finally {
      downloadingRef.current.delete(file.id);
      setDownloadingIds(new Set(downloadingRef.current));
    }
  }

  async function confirmDelete(): Promise<void> {
    const target = deleteTarget;
    if (target == null || deletingRef.current) return;
    deletingRef.current = true;
    setDeletePending(true);
    setDeleteError(null);
    try {
      await deleteProjectFile(client, projectId, target.id);
      if (currentProjectIdRef.current !== projectId) return;
      setFiles((current) => current.filter((file) => file.id !== target.id));
      setRowErrors((current) => {
        const next = { ...current };
        delete next[target.id];
        return next;
      });
      setDeleteTarget(null);
    } catch (error) {
      if (currentProjectIdRef.current !== projectId) return;
      if (isProjectNotFound(error)) onProjectMissing?.();
      else setDeleteError("Unable to delete this file.");
    } finally {
      deletingRef.current = false;
      setDeletePending(false);
    }
  }

  return (
    <div style={sectionStyle} aria-busy={loading || uploadPending}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: t.spacing.md, flexWrap: "wrap" }}>
        <div>
          <h2 style={{ margin: 0 }}>Files</h2>
          <p style={{ margin: `${t.spacing.xs}px 0 0`, color: t.colors.mutedText }}>
            Keep files together in this Project.
          </p>
        </div>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: t.spacing.sm, flexWrap: "wrap" }}>
        <label htmlFor={`project-file-input-${encodeURIComponent(projectId)}`}>Choose file</label>
        <input
          ref={fileInputRef}
          id={`project-file-input-${encodeURIComponent(projectId)}`}
          type="file"
          aria-label="Choose a Project file to upload"
          disabled={uploadPending}
          onChange={selectFile}
        />
        <Button
          variant="primary"
          disabled={selectedFile == null || uploadPending}
          loading={uploadPending}
          onClick={() => void uploadSelectedFile()}
        >
          {uploadPending ? "Uploading…" : "Upload File"}
        </Button>
      </div>
      {selectedFile != null && <p style={{ margin: 0 }} aria-live="polite">Selected: {selectedFile.name}</p>}
      {uploadError != null && <p role="alert">{uploadError}</p>}
      {refreshNotice && (
        <div role="status">
          <span>The file was uploaded, but the list could not be refreshed.</span>{" "}
          <Button size="sm" onClick={() => setLoadAttempt((attempt) => attempt + 1)}>Retry</Button>
        </div>
      )}

      {loading && <LoadingIndicator label="Loading Project files…" />}
      {loadError && (
        <div role="alert">
          <p>Project files could not be loaded.</p>
          <Button onClick={() => setLoadAttempt((attempt) => attempt + 1)}>Retry</Button>
        </div>
      )}
      {!loading && !loadError && files.length === 0 && (
        <div>
          <p style={{ margin: 0, fontWeight: t.font.weightSemibold }}>No files in this Project yet.</p>
          <p style={{ margin: `${t.spacing.xs}px 0 0`, color: t.colors.mutedText }}>
            Upload files here to keep Project resources together.
          </p>
        </div>
      )}
      {!loading && !loadError && files.length > 0 && (
        <div style={{ overflowX: "auto" }}>
          <table aria-label={`Files in ${projectName}`} style={{ width: "100%", borderCollapse: "collapse", textAlign: "left" }}>
            <thead>
              <tr>
                {["Name", "Type", "Size", "Added", "Actions"].map((label) => (
                  <th key={label} scope="col" style={{ padding: t.spacing.sm, color: t.colors.mutedText }}>{label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {files.map((file) => (
                <tr key={file.id} data-project-file-id={file.id} style={fileRowStyle}>
                  <th scope="row" style={{ padding: t.spacing.sm, fontWeight: t.font.weightNormal }}>{file.file_name}</th>
                  <td style={{ padding: t.spacing.sm }}>{file.content_type || "Unknown"}</td>
                  <td style={{ padding: t.spacing.sm }}>{formatProjectFileSize(file.size_bytes)}</td>
                  <td style={{ padding: t.spacing.sm }}><time dateTime={file.created_at}>{formatCreatedAt(file.created_at)}</time></td>
                  <td style={{ padding: t.spacing.sm }}>
                    <div style={{ display: "flex", alignItems: "center", gap: t.spacing.xs, flexWrap: "wrap" }}>
                      <Button
                        size="sm"
                        ariaLabel={`Download ${file.file_name}`}
                        disabled={downloadingIds.has(file.id)}
                        loading={downloadingIds.has(file.id)}
                        onClick={() => void downloadFile(file)}
                      >
                        {downloadingIds.has(file.id) ? "Downloading…" : "Download"}
                      </Button>
                      <Button
                        size="sm"
                        variant="danger"
                        ariaLabel={`Delete ${file.file_name}`}
                        disabled={deletePending && deleteTarget?.id === file.id}
                        onClick={() => { setDeleteError(null); setDeleteTarget(file); }}
                      >
                        Delete
                      </Button>
                    </div>
                    {rowErrors[file.id] && <p role="alert" style={{ margin: `${t.spacing.xs}px 0 0` }}>{rowErrors[file.id]}</p>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Modal
        open={deleteTarget != null}
        title={deleteTarget == null ? "Delete Project file?" : `Delete “${deleteTarget.file_name}”?`}
        onClose={() => { if (!deletePending) setDeleteTarget(null); }}
        primaryAction="Delete file"
        onPrimaryAction={() => void confirmDelete()}
        primaryBusy={deletePending}
        primaryDisabled={deletePending}
        secondaryAction="Cancel"
        onSecondaryAction={() => { if (!deletePending) setDeleteTarget(null); }}
        closeOnOverlayClick={!deletePending}
        closeOnEscape={!deletePending}
      >
        <div style={{ padding: t.spacing.lg }}>
          <p>This permanently removes the Project file and its stored content.</p>
          {deleteError != null && <p role="alert">{deleteError}</p>}
        </div>
      </Modal>
    </div>
  );
}
