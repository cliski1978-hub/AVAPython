import {
  ApiError,
  createProject,
  deleteProject,
  getProject,
  listProjectConversations,
  listProjects,
  setProjectArchived,
  updateProject,
  type ApiClient,
} from "@ava/api-client";
import {
  Button,
  Input,
  LoadingIndicator,
  Modal,
  Textarea,
  defaultTheme,
} from "@ava/ui-core";
import { CorePromptScopeAssignments } from "@ava/settings-core";
import { ProjectExecutionDefaultsEditor } from "./ProjectExecutionDefaultsEditor";
import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";
import type { Conversation } from "@ava/agent-ui";
import { ProjectFilesPanel } from "./project-files/ProjectFilesPanel";

export interface ProjectsWorkspaceProps {
  client: ApiClient;
  active: boolean;
  projectId: string | null;
  onOpenProject: (projectId: string) => void;
  onBackToProjects: () => void;
  conversations?: Conversation[];
  activeConversationId?: string | null;
  onOpenConversation?: (conversationId: string) => void;
  onCreateConversation?: (projectId: string) => Promise<void>;
  conversationsRevision?: number;
  onProjectCreated?: (project: Project) => void;
  onProjectDeleted?: (projectId: string) => void;
  onProjectArchived?: (project: Project) => void;
  onProjectUpdated?: (project: Project) => void;
}

const t = defaultTheme;
type Project = Awaited<ReturnType<typeof listProjects>>["projects"][number];
type ProjectSectionId = "overview" | "conversations" | "files" | "instructions" | "settings";

const PROJECT_SECTIONS: { id: ProjectSectionId; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "conversations", label: "Conversations" },
  { id: "files", label: "Files" },
  { id: "instructions", label: "Instructions" },
  { id: "settings", label: "Settings" },
];

const projectSectionPanelId = (id: ProjectSectionId) => `project-section-${id}`;

function isProjectNotFound(error: unknown): boolean {
  if (!(error instanceof ApiError) || error.status !== 404) return false;
  return typeof error.body === "object" && error.body !== null && "error_code" in error.body &&
    error.body.error_code === "project_not_found";
}

function safeError(error: unknown, fallback: string): string {
  if (error instanceof ApiError && error.status >= 500) return "AVA could not complete this request. Try again.";
  return fallback;
}

const sectionStyle = {
  display: "flex",
  flexDirection: "column" as const,
  gap: t.spacing.md,
};

const rowStyle = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: t.spacing.md,
  padding: t.spacing.md,
  border: `${t.border.width}px solid ${t.colors.border}`,
  borderRadius: t.radius.md,
  background: t.colors.surface,
};

export function ProjectsWorkspace({
  client,
  active,
  projectId,
  onOpenProject,
  onBackToProjects,
  conversations = [],
  activeConversationId = null,
  onOpenConversation,
  onCreateConversation,
  conversationsRevision,
  onProjectCreated,
  onProjectDeleted,
  onProjectArchived,
  onProjectUpdated,
}: ProjectsWorkspaceProps) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [listLoading, setListLoading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [detail, setDetail] = useState<Project | null>(null);
  const [activeSection, setActiveSection] = useState<ProjectSectionId>("overview");
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<"not-found" | "failed" | null>(null);
  const [detailAttempt, setDetailAttempt] = useState(0);
  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [instructions, setInstructions] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);
  const [createPending, setCreatePending] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Project | null>(null);
  const [deletePending, setDeletePending] = useState(false);
  const [archivePendingId, setArchivePendingId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [nameError, setNameError] = useState<string | null>(null);
  const [projectConversationIds, setProjectConversationIds] = useState<string[]>([]);
  const [projectConversationsLoading, setProjectConversationsLoading] = useState(false);
  const [projectConversationsError, setProjectConversationsError] = useState<string | null>(null);
  const [projectConversationsAttempt, setProjectConversationsAttempt] = useState(0);
  const [projectChatPending, setProjectChatPending] = useState(false);
  const [projectChatError, setProjectChatError] = useState<string | null>(null);
  const deletedProjectIdsRef = useRef(new Set<string>());

  const reconcileMissingProject = useCallback(() => {
    if (projectId == null) return;
    onProjectDeleted?.(projectId);
    onBackToProjects();
  }, [onBackToProjects, onProjectDeleted, projectId]);

  async function reloadProjects(): Promise<void> {
    setListLoading(true);
    setListError(null);
    try {
      const response = await listProjects(client);
      setProjects(response.projects.filter((project) => !deletedProjectIdsRef.current.has(project.id)));
    } catch {
      setListError("Projects could not be loaded. Try again.");
    } finally {
      setListLoading(false);
    }
  }

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    setListLoading(true);
    setListError(null);
    void listProjects(client).then((response) => {
      if (!cancelled) {
        setProjects(response.projects.filter((project) => !deletedProjectIdsRef.current.has(project.id)));
      }
    }).catch(() => {
      if (!cancelled) setListError("Projects could not be loaded. Try again.");
    }).finally(() => {
      if (!cancelled) setListLoading(false);
    });
    return () => { cancelled = true; };
  }, [active, client]);

  useEffect(() => {
    setActiveSection("overview");
    if (!active || projectId == null) {
      setDetail(null);
      setDetailError(null);
      return;
    }
    let cancelled = false;
    setDetail(null);
    setDetailLoading(true);
    setDetailError(null);
    void getProject(client, projectId).then((project) => {
      if (!cancelled && !deletedProjectIdsRef.current.has(project.id)) setDetail(project);
    }).catch((error: unknown) => {
      if (cancelled) return;
      setDetailError(isProjectNotFound(error) ? "not-found" : "failed");
    }).finally(() => {
      if (!cancelled) setDetailLoading(false);
    });
    return () => { cancelled = true; };
  }, [active, client, detailAttempt, projectId]);

  useEffect(() => {
    if (!active || projectId == null || activeSection !== "conversations") return;
    let cancelled = false;
    setProjectConversationsLoading(true);
    setProjectConversationsError(null);
    void listProjectConversations(client, projectId).then((response) => {
      if (!cancelled) setProjectConversationIds(response.conversations.map((conversation) => conversation.conversation_id));
    }).catch(() => {
      if (!cancelled) setProjectConversationsError("Project conversations could not be loaded. Try again.");
    }).finally(() => {
      if (!cancelled) setProjectConversationsLoading(false);
    });
    return () => { cancelled = true; };
  }, [active, activeSection, client, conversationsRevision, projectConversationsAttempt, projectId]);

  async function submitCreate(): Promise<void> {
    if (createPending) return;
    if (!name.trim()) {
      setNameError("Enter a Project name.");
      return;
    }
    setNameError(null);
    setCreateError(null);
    setCreatePending(true);
    try {
      const created = await createProject(client, {
        name,
        description: description === "" ? null : description,
        instructions: instructions === "" ? null : instructions,
      });
      deletedProjectIdsRef.current.delete(created.id);
      onProjectCreated?.(created);
      setCreateOpen(false);
      setName("");
      setDescription("");
      setInstructions("");
      await reloadProjects();
    } catch (error) {
      setCreateError(safeError(error, "Project could not be created. Your entries are still here."));
    } finally {
      setCreatePending(false);
    }
  }

  async function createProjectChat(): Promise<void> {
    if (projectId == null || onCreateConversation == null || projectChatPending) return;
    setProjectChatPending(true);
    setProjectChatError(null);
    try {
      await onCreateConversation(projectId);
    } catch {
      setProjectChatError("A chat could not be created in this Project. Try again.");
    } finally {
      setProjectChatPending(false);
    }
  }

  async function changeArchived(project: Project, isArchived: boolean): Promise<void> {
    if (archivePendingId != null) return;
    setArchivePendingId(project.id);
    setActionError(null);
    try {
      const updated = await setProjectArchived(client, project.id, { is_archived: isArchived });
      onProjectArchived?.(updated);
      await reloadProjects();
    } catch (error) {
      setActionError(safeError(error, "Project archive status could not be changed."));
    } finally {
      setArchivePendingId(null);
    }
  }

  function reconcileProjectUpdate(updated: Project): void {
    setDetail((current) => current?.id === updated.id ? updated : current);
    setProjects((current) => current.map((project) => project.id === updated.id ? updated : project));
    onProjectUpdated?.(updated);
  }

  async function confirmDelete(): Promise<void> {
    const target = deleteTarget;
    if (target == null || deletePending) return;
    setDeletePending(true);
    setActionError(null);
    try {
      await deleteProject(client, target.id);
      deletedProjectIdsRef.current.add(target.id);
      setProjects((current) => current.filter((project) => project.id !== target.id));
      setDetail((current) => current?.id === target.id ? null : current);
      onProjectDeleted?.(target.id);
      setDeleteTarget(null);
      if (projectId === target.id) onBackToProjects();
    } catch (error) {
      if (isProjectNotFound(error)) {
        deletedProjectIdsRef.current.add(target.id);
        setProjects((current) => current.filter((project) => project.id !== target.id));
        setDetail((current) => current?.id === target.id ? null : current);
        onProjectDeleted?.(target.id);
        setDeleteTarget(null);
        if (projectId === target.id) onBackToProjects();
      } else {
        setActionError(safeError(error, "Project could not be deleted. It is still available."));
      }
    } finally {
      setDeletePending(false);
    }
  }

  const activeProjects = projects.filter((project) => !project.is_archived);
  const archivedProjects = projects.filter((project) => project.is_archived);

  if (projectId != null) {
    return (
      <div style={{ flex: 1, overflow: "auto", padding: t.spacing.xl }}>
        <Button variant="ghost" onClick={onBackToProjects} ariaLabel="Back to Projects">← Projects</Button>
        {detailLoading && <LoadingIndicator label="Loading Project…" />}
        {detailError === "not-found" && (
          <div role="alert" style={{ marginTop: t.spacing.xl }}>
            <h1>Project not found</h1>
            <p>This Project may have been deleted or the link may be incorrect.</p>
            <Button variant="primary" onClick={onBackToProjects}>Back to Projects</Button>
          </div>
        )}
        {detailError === "failed" && (
          <div role="alert" style={{ marginTop: t.spacing.xl }}>
            <h1>Project could not be loaded</h1>
            <p>Try again, or return to Projects.</p>
            <Button onClick={() => setDetailAttempt((attempt) => attempt + 1)}>Try again</Button>
          </div>
        )}
        {detail != null && !detailLoading && (
          <main style={{ ...sectionStyle, marginTop: t.spacing.lg, maxWidth: 900 }}>
            <header style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: t.spacing.md }}>
              <div style={sectionStyle}>
                <div style={{ display: "flex", alignItems: "center", gap: t.spacing.sm, flexWrap: "wrap" }}>
                  <h1 style={{ margin: 0 }}>{detail.name}</h1>
                  <span
                    aria-label={detail.is_archived ? "Archived Project" : "Active Project"}
                    style={{
                      borderRadius: t.radius.sm,
                      padding: `${t.spacing.xs}px ${t.spacing.sm}px`,
                      color: detail.is_archived ? t.colors.mutedText : t.colors.primary,
                      background: t.colors.surface,
                      fontSize: t.font.sizeSm,
                    }}
                  >
                    {detail.is_archived ? "Archived" : "Active"}
                  </span>
                </div>
                {detail.description != null && detail.description !== "" && (
                  <p style={{ margin: 0, color: t.colors.mutedText }}>{detail.description}</p>
                )}
              </div>
              <Button variant="danger" onClick={() => setDeleteTarget(detail)}>Delete Project</Button>
            </header>

            <ProjectSectionNav active={activeSection} onSelect={setActiveSection} />
        <ProjectSectionContent
              project={detail}
              client={client}
              active={activeSection}
              conversations={projectConversationIds
                .map((id) => conversations.find((conversation) => conversation.id === id))
                .filter((conversation): conversation is Conversation => conversation != null && !conversation.isArchived)}
              activeConversationId={activeConversationId}
              conversationsLoading={projectConversationsLoading}
              conversationsError={projectConversationsError}
              onRetryConversations={() => setProjectConversationsAttempt((attempt) => attempt + 1)}
              onCreateConversation={() => void createProjectChat()}
              creatingConversation={projectChatPending}
              createConversationError={projectChatError}
              onOpenConversation={onOpenConversation ?? (() => undefined)}
              onProjectUpdated={reconcileProjectUpdate}
              onProjectMissing={reconcileMissingProject}
            />
          </main>
        )}
        <DeleteProjectDialog
          target={deleteTarget}
          pending={deletePending}
          error={actionError}
          onClose={() => setDeleteTarget(null)}
          onDelete={() => void confirmDelete()}
        />
      </div>
    );
  }

  return (
    <div style={{ flex: 1, overflow: "auto", padding: t.spacing.xl }}>
      <header style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: t.spacing.md }}>
        <div>
          <h1 style={{ margin: 0 }}>Projects</h1>
          <p style={{ color: t.colors.mutedText }}>Durable workspace and context boundaries.</p>
        </div>
        <Button variant="primary" onClick={() => { setCreateError(null); setNameError(null); setCreateOpen(true); }}>
          New Project
        </Button>
      </header>
      {actionError != null && <p role="alert">{actionError}</p>}
      {listLoading && <LoadingIndicator label="Loading Projects…" />}
      {listError != null && (
        <div role="alert">
          <p>{listError}</p>
          <Button onClick={() => void reloadProjects()}>Retry</Button>
        </div>
      )}
      {!listLoading && listError == null && projects.length === 0 && (
        <p>No Projects yet. Create your first Project.</p>
      )}
      {!listLoading && listError == null && projects.length > 0 && (
        <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr)", gap: t.spacing.xl, maxWidth: 900, marginTop: t.spacing.xl }}>
          <section aria-labelledby="active-projects-heading" style={sectionStyle}>
            <h2 id="active-projects-heading" style={{ margin: 0 }}>Active Projects</h2>
            {activeProjects.length === 0 ? <p>No active Projects.</p> : activeProjects.map((project) => (
              <ProjectRow
                key={project.id}
                project={project}
                pending={archivePendingId === project.id}
                onOpen={() => onOpenProject(project.id)}
                onArchive={() => void changeArchived(project, true)}
                onRestore={() => void changeArchived(project, false)}
                onDelete={() => setDeleteTarget(project)}
              />
            ))}
          </section>
          {archivedProjects.length > 0 && (
            <section aria-labelledby="archived-projects-heading" style={sectionStyle}>
              <h2 id="archived-projects-heading" style={{ margin: 0 }}>Archived Projects</h2>
              {archivedProjects.map((project) => (
                <ProjectRow
                  key={project.id}
                  project={project}
                  pending={archivePendingId === project.id}
                  onOpen={() => onOpenProject(project.id)}
                  onArchive={() => void changeArchived(project, true)}
                  onRestore={() => void changeArchived(project, false)}
                  onDelete={() => setDeleteTarget(project)}
                />
              ))}
            </section>
          )}
        </div>
      )}

      <Modal
        open={createOpen}
        title="New Project"
        onClose={() => { if (!createPending) setCreateOpen(false); }}
        primaryAction="Create Project"
        onPrimaryAction={() => void submitCreate()}
        primaryBusy={createPending}
        primaryDisabled={createPending || !name.trim()}
        secondaryAction="Cancel"
        onSecondaryAction={() => { if (!createPending) setCreateOpen(false); }}
      >
        <form id="create-project-form" onSubmit={(event) => { event.preventDefault(); void submitCreate(); }} style={{ display: "grid", gap: t.spacing.md, padding: t.spacing.lg }}>
          <Input label="Name" value={name} onChange={(value) => { setName(value); setNameError(null); }} error={nameError ?? undefined} />
          <Textarea label="Description (optional)" value={description} onChange={setDescription} rows={3} />
          <Textarea label="Instructions (optional)" value={instructions} onChange={setInstructions} rows={3} />
          {createError != null && <p role="alert">{createError}</p>}
        </form>
      </Modal>
      <DeleteProjectDialog
        target={deleteTarget}
        pending={deletePending}
        error={actionError}
        onClose={() => setDeleteTarget(null)}
        onDelete={() => void confirmDelete()}
      />
    </div>
  );
}

function ProjectSectionNav({
  active,
  onSelect,
}: {
  active: ProjectSectionId;
  onSelect: (section: ProjectSectionId) => void;
}) {
  return (
    <div
      role="tablist"
      aria-label="Project workspace sections"
      style={{ display: "flex", alignItems: "center", gap: t.spacing.xs, flexWrap: "wrap" }}
    >
      {PROJECT_SECTIONS.map((section) => {
        const selected = active === section.id;
        return (
          <button
            key={section.id}
            type="button"
            role="tab"
            aria-selected={selected}
            aria-controls={projectSectionPanelId(section.id)}
            id={`project-section-tab-${section.id}`}
            onClick={() => onSelect(section.id)}
            style={{
              border: `${t.border.width}px solid transparent`,
              borderRadius: t.radius.md,
              padding: `${t.spacing.sm}px ${t.spacing.md}px`,
              background: selected ? t.colors.surface : "transparent",
              color: selected ? t.colors.primary : t.colors.mutedText,
              font: `inherit`,
              fontWeight: selected ? t.font.weightSemibold : t.font.weightNormal,
              cursor: "pointer",
            }}
          >
            {section.label}
          </button>
        );
      })}
    </div>
  );
}

function ProjectSectionContent({
  project,
  client,
  active,
  conversations,
  activeConversationId,
  conversationsLoading,
  conversationsError,
  onRetryConversations,
  onCreateConversation,
  creatingConversation,
  createConversationError,
  onOpenConversation,
  onProjectUpdated,
  onProjectMissing,
}: {
  project: Project;
  client: ApiClient;
  active: ProjectSectionId;
  conversations: Conversation[];
  activeConversationId: string | null;
  conversationsLoading: boolean;
  conversationsError: string | null;
  onRetryConversations: () => void;
  onCreateConversation: () => void;
  creatingConversation: boolean;
  createConversationError: string | null;
  onOpenConversation: (conversationId: string) => void;
  onProjectUpdated: (project: Project) => void;
  onProjectMissing: () => void;
}) {
  const panelStyle = {
    ...sectionStyle,
    minHeight: 180,
    padding: t.spacing.lg,
    border: `${t.border.width}px solid ${t.colors.border}`,
    borderRadius: t.radius.md,
    background: t.colors.surface,
  };

  return (
    <>
      {PROJECT_SECTIONS.map((section) => {
        const content = section.id === "overview" ? (
          <>
            <h2 style={{ margin: 0 }}>Overview</h2>
            <dl style={{ display: "grid", gridTemplateColumns: "max-content minmax(0, 1fr)", gap: `${t.spacing.sm}px ${t.spacing.lg}px`, margin: 0 }}>
              <dt>Project name</dt><dd style={{ margin: 0 }}>{project.name}</dd>
              <dt>Description</dt><dd style={{ margin: 0 }}>{project.description || "No description provided."}</dd>
              <dt>Status</dt><dd style={{ margin: 0 }}>{project.is_archived ? "Archived" : "Active"}</dd>
              <dt>Created</dt><dd style={{ margin: 0 }}><time dateTime={project.created_at}>{project.created_at}</time></dd>
              <dt>Last updated</dt><dd style={{ margin: 0 }}><time dateTime={project.updated_at}>{project.updated_at}</time></dd>
            </dl>
          </>
        ) : section.id === "conversations" ? (
          <>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: t.spacing.md }}>
              <h2 style={{ margin: 0 }}>Conversations</h2>
              <Button variant="primary" disabled={creatingConversation} onClick={onCreateConversation}>
                {creatingConversation ? "Creating…" : "New Chat"}
              </Button>
            </div>
            {createConversationError != null && <p role="alert">{createConversationError}</p>}
            {conversationsLoading && <LoadingIndicator label="Loading Project conversations…" />}
            {conversationsError != null && (
              <div role="alert">
                <p>{conversationsError}</p>
                <Button onClick={onRetryConversations}>Retry</Button>
              </div>
            )}
            {!conversationsLoading && conversationsError == null && conversations.length === 0 && (
              <p style={{ margin: 0, color: t.colors.mutedText }}>No conversations in this Project yet.</p>
            )}
            {!conversationsLoading && conversationsError == null && conversations.map((conversation) => (
              <button
                key={conversation.id}
                type="button"
                aria-current={conversation.id === activeConversationId ? "true" : undefined}
                data-project-conversation={conversation.id}
                onClick={() => onOpenConversation(conversation.id)}
                style={{
                  textAlign: "left",
                  padding: t.spacing.md,
                  border: `${t.border.width}px solid ${conversation.id === activeConversationId ? t.colors.primary : t.colors.border}`,
                  borderRadius: t.radius.md,
                  background: t.colors.surface,
                  color: t.colors.foreground,
                  font: "inherit",
                  cursor: "pointer",
                }}
              >
                {conversation.title}
              </button>
            ))}
          </>
        ) : section.id === "instructions" ? (
          <ProjectInstructionsEditor
            key={project.id}
            client={client}
            project={project}
            onProjectUpdated={onProjectUpdated}
          />
        ) : section.id === "settings" ? (
          active === "settings" ? (
            <>
              <ProjectExecutionDefaultsEditor key={project.id} client={client} projectId={project.id} />
              <CorePromptScopeAssignments client={client} scopeType="project" scopeId={project.id} scopeLabel={`Project: ${project.name}`} />
            </>
          ) : null
        ) : section.id === "files" ? (
          active === "files" ? (
            <ProjectFilesPanel
              key={project.id}
              client={client}
              projectId={project.id}
              projectName={project.name}
              onProjectMissing={onProjectMissing}
            />
          ) : null
        ) : (
          <>
            <h2 style={{ margin: 0 }}>{section.label}</h2>
          </>
        );
        return (
          <section
            key={section.id}
            role="tabpanel"
            id={projectSectionPanelId(section.id)}
            aria-labelledby={`project-section-tab-${section.id}`}
            tabIndex={0}
            hidden={active !== section.id}
            style={{ ...panelStyle, display: active === section.id ? "flex" : "none" }}
          >
            {content}
          </section>
        );
      })}
    </>
  );
}

function ProjectInstructionsEditor({
  client,
  project,
  onProjectUpdated,
}: {
  client: ApiClient;
  project: Project;
  onProjectUpdated: (project: Project) => void;
}) {
  const [persistedInstructions, setPersistedInstructions] = useState(project.instructions);
  const [draft, setDraft] = useState(project.instructions ?? "");
  const [edited, setEdited] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const savingRef = useRef(false);
  const isDirty = draft !== (persistedInstructions ?? "") || (persistedInstructions === null && edited);

  useEffect(() => {
    if (project.instructions === persistedInstructions) return;
    const wasDirty = isDirty;
    setPersistedInstructions(project.instructions);
    if (!wasDirty) {
      setDraft(project.instructions ?? "");
      setEdited(false);
      setSaveError(null);
    }
  }, [isDirty, persistedInstructions, project.instructions]);

  function cancelEditing(): void {
    setPersistedInstructions(project.instructions);
    setDraft(project.instructions ?? "");
    setEdited(false);
    setSaveError(null);
  }

  async function persistInstructions(value: string | null): Promise<void> {
    if (savingRef.current) return;
    if (value !== null && !isDirty) return;
    if (value === null && persistedInstructions === null && !isDirty) {
      setDraft("");
      setEdited(false);
      setSaveError(null);
      return;
    }
    savingRef.current = true;
    setSaving(true);
    setSaveError(null);
    try {
      const updated = await updateProject(client, project.id, {
        name: project.name,
        instructions: value,
      });
      setPersistedInstructions(updated.instructions);
      setDraft(updated.instructions ?? "");
      setEdited(false);
      onProjectUpdated(updated);
    } catch (error) {
      setSaveError(safeError(error, "Project instructions could not be saved. Your draft is still here."));
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>): void {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      void persistInstructions(draft);
    } else if (event.key === "Escape" && isDirty && !saving) {
      event.preventDefault();
      cancelEditing();
    }
  }

  return (
    <div style={{ ...sectionStyle, maxWidth: 760 }}>
      <h2 style={{ margin: 0 }}>Instructions</h2>
      <p style={{ margin: 0, color: t.colors.mutedText }}>
        These Project-specific instructions are saved for future use. They will affect conversations only after execution integration is added.
      </p>
      <Textarea
        label="Project instructions"
        value={draft}
        rows={12}
        disabled={saving}
        onChange={(value) => { setDraft(value); setEdited(true); setSaveError(null); }}
        onKeyDown={handleKeyDown}
      />
      <div style={{ display: "flex", flexWrap: "wrap", gap: t.spacing.sm }}>
        <Button variant="primary" disabled={!isDirty || saving} onClick={() => void persistInstructions(draft)}>
          {saving ? "Saving…" : "Save"}
        </Button>
        <Button disabled={!isDirty || saving} onClick={cancelEditing}>Cancel</Button>
        <Button disabled={saving || (persistedInstructions === null && !isDirty)} onClick={() => void persistInstructions(null)}>
          Clear instructions
        </Button>
      </div>
      {saving && <p role="status" aria-live="polite">Saving Project instructions…</p>}
      {saveError != null && <p role="alert">{saveError}</p>}
    </div>
  );
}

function ProjectRow({
  project,
  pending,
  onOpen,
  onArchive,
  onRestore,
  onDelete,
}: {
  project: Project;
  pending: boolean;
  onOpen: () => void;
  onArchive: () => void;
  onRestore: () => void;
  onDelete: () => void;
}) {
  return (
    <article style={rowStyle}>
      <div style={{ minWidth: 0 }}>
        <button type="button" onClick={onOpen} style={{ border: 0, padding: 0, background: "transparent", color: t.colors.primary, font: "inherit", fontWeight: t.font.weightSemibold, cursor: "pointer" }}>
          {project.name}
        </button>
        {project.description != null && project.description !== "" && <p style={{ margin: `${t.spacing.xs}px 0 0`, color: t.colors.mutedText }}>{project.description}</p>}
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: t.spacing.sm }}>
        <Button size="sm" onClick={onOpen}>Open</Button>
        <Button size="sm" disabled={pending} onClick={project.is_archived ? onRestore : onArchive}>
          {project.is_archived ? "Restore" : "Archive"}
        </Button>
        <Button size="sm" variant="danger" onClick={onDelete}>Delete</Button>
      </div>
    </article>
  );
}

function DeleteProjectDialog({
  target,
  pending,
  error,
  onClose,
  onDelete,
}: {
  target: Project | null;
  pending: boolean;
  error: string | null;
  onClose: () => void;
  onDelete: () => void;
}) {
  return (
    <Modal
      open={target != null}
      title={target == null ? "Delete Project" : `Delete Project “${target.name}”?`}
      onClose={() => { if (!pending) onClose(); }}
      primaryAction="Delete Project"
      onPrimaryAction={onDelete}
      primaryBusy={pending}
      primaryDisabled={pending}
      secondaryAction="Cancel"
      onSecondaryAction={onClose}
      closeOnOverlayClick={!pending}
      closeOnEscape={!pending}
    >
      <div style={{ padding: t.spacing.lg }}>
        <p>This permanently removes the Project metadata. This cannot be undone.</p>
        {error != null && <p role="alert">{error}</p>}
      </div>
    </Modal>
  );
}
