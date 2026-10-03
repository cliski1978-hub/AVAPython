import {
  AgentRunProvider,
  ConversationList,
  ConversationProvider,
  ConversationView,
  PromptComposer,
  ExecutionControls,
  useAgentRun,
  useConversationState,
  type RuntimeDiscoveryItem,
  type ModelInfo,
  type ModelProviderDiscoveryItem,
  type ExecutionProfile,
  type WorkspaceInfo,
} from "@ava/agent-ui";
import { ApiError, type ApiClient } from "@ava/api-client";
import { getHealth, getModelProviders, getModels, getRuntimes, getExecutionProfiles, getWorkspaces, listProjects, listProjectConversations, subscribeConnectivity } from "@ava/api-client";
import { DocumentProvider, DocumentWorkspace } from "@ava/document-core";
import { CorePromptScopeAssignments, SettingsWorkspace, type AssignablePromptScope } from "@ava/settings-core";
import { ProjectsWorkspace } from "./ProjectsWorkspace";
import type { SettingsSectionId } from "@ava/ui-core";
import {
  AppShell,
  Modal,
  StatusIndicator,
  defaultTheme,
  type StatusState,
} from "@ava/ui-core";
import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";

import { WorkspaceTabs, type WorkspaceId } from "./WorkspaceTabs";

/**
 * Shared AVA application workspace used by both Web and Desktop.
 *
 * Owns navigation between chat, document, settings, and Projects surfaces.
 * Their stateful providers and panes remain mounted when hidden so
 * conversation runs and in-session editor state survive destination changes.
 */

export interface AppWorkspaceProps {
  client: ApiClient;
}

type AppStatus = "checking" | "healthy" | "unhealthy" | "unavailable";
type ProjectSummary = Awaited<ReturnType<typeof listProjects>>["projects"][number];
type PromptScopeDialog = { scopeType: "conversation" | "folder"; scopeId: string; scopeLabel: string };

function browserPath(): string {
  return typeof window === "undefined" ? "/" : window.location.pathname;
}

function isProjectsPath(path: string): boolean {
  return path === "/projects" || path.startsWith("/projects/");
}

function projectIdFromPath(path: string): string | null {
  const match = path.match(/^\/projects\/([^/]+)\/?$/);
  if (match == null) return null;
  try {
    return decodeURIComponent(match[1]);
  } catch {
    return match[1];
  }
}

function isApiErrorCode(error: ApiError, errorCode: string): boolean {
  return typeof error.body === "object" && error.body !== null && "error_code" in error.body &&
    error.body.error_code === errorCode;
}

const t = defaultTheme;

function indicatorState(status: AppStatus): StatusState {
  switch (status) {
    case "healthy":
      return "success";
    case "unhealthy":
      return "error";
    case "unavailable":
      return "warning";
    case "checking":
      return "neutral";
  }
}

function statusText(status: AppStatus): string {
  switch (status) {
    case "checking":
      return "Checking\u2026";
    case "healthy":
      return "Connected";
    case "unhealthy":
      return "Unhealthy";
    case "unavailable":
      return "Unavailable";
  }
}

function WorkspacePane({
  visible,
  id,
  children,
}: {
  visible: boolean;
  id: string;
  children: ReactNode;
}) {
  const style: CSSProperties = {
    flex: 1,
    display: visible ? "flex" : "none",
    flexDirection: "column",
    overflow: "hidden",
    minWidth: 0,
  };
  return (
    <div id={id} role="tabpanel" style={style}>
      {children}
    </div>
  );
}

function WorkspaceContent({ client }: { client: ApiClient }) {
  const {
    conversationList,
    activeConversations,
    archivedConversations,
    activeConversation,
    createConversation,
    selectConversation,
    renameConversation,
    deleteConversation,
    searchQuery,
    searchLoading,
    searchError,
    setSearchQuery,
    reloadConversations,
    folders,
    foldersLoading,
    folderError,
    reloadFolders,
    createFolder,
    renameFolder,
    deleteFolder,
    moveConversation,
    createConversationInFolder,
    createConversationInProject,
    setConversationProject,
    setConversationPinned,
    setConversationArchived,
    reconcileDeletedProject,
    state,
  } = useConversationState();
  const {
    submitPrompt,
    stopRun,
    retryMessage,
    regenerateMessage,
    forgetConversation,
    isStarting,
    isRunning,
    isStopping,
  } = useAgentRun();

  const [routePath, setRoutePath] = useState(browserPath);
  const [workspace, setWorkspace] = useState<WorkspaceId>(() => isProjectsPath(browserPath()) ? "projects" : "chat");
  const [documentOpened, setDocumentOpened] = useState(false);
  const [settingsOpened, setSettingsOpened] = useState(false);
  const [settingsSection, setSettingsSection] = useState<SettingsSectionId>("providers");
  const [promptScopeDialog, setPromptScopeDialog] = useState<PromptScopeDialog | null>(null);
  const [status, setStatus] = useState<AppStatus>("checking");
  const connectivityVersion = useRef(0);
  const [runtimes, setRuntimes] = useState<RuntimeDiscoveryItem[]>([]);
  const [providers, setProviders] = useState<ModelProviderDiscoveryItem[]>([]);
  // Configured models are the catalog the composer offers. `/models` reports
  // persisted ModelConfiguration records alongside bootstrap profiles, so a
  // model added in Settings is selectable without a restart.
  const [configuredModels, setConfiguredModels] = useState<ModelInfo[]>([]);
  const [defaultModelId, setDefaultModelId] = useState<string | null>(null);
  const [runtimeId, setRuntimeId] = useState<string>();
  const [providerId, setProviderId] = useState<string>();
  const [profileId, setProfileId] = useState("application-default");
  const [profiles, setProfiles] = useState<ExecutionProfile[]>([]);
  const [workspaces, setWorkspaces] = useState<WorkspaceInfo[]>([]);
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<string | null>(null);
  const [workspacesUnavailable, setWorkspacesUnavailable] = useState(false);
  const [sidebarProjects, setSidebarProjects] = useState<ProjectSummary[]>([]);
  const deletedProjectIds = useRef(new Set<string>());
  const [sidebarProjectsLoading, setSidebarProjectsLoading] = useState(true);
  const [sidebarProjectsError, setSidebarProjectsError] = useState<string | null>(null);
  const [projectConversationIds, setProjectConversationIds] = useState<Record<string, string[]>>({});
  const [projectConversationLoading, setProjectConversationLoading] = useState<Record<string, boolean>>({});
  const [projectConversationErrors, setProjectConversationErrors] = useState<Record<string, string | null>>({});
  const [projectConversationRevision, setProjectConversationRevision] = useState(0);
  const projectConversationLoads = useRef(new Set<string>());
  const projectConversationReloads = useRef(new Set<string>());

  const refreshSidebarProjects = async () => {
    setSidebarProjectsLoading(true);
    setSidebarProjectsError(null);
    try {
      const response = await listProjects(client);
      setSidebarProjects(response.projects.filter((project) => !deletedProjectIds.current.has(project.id)));
    } catch {
      setSidebarProjectsError("Projects are temporarily unavailable.");
    } finally {
      setSidebarProjectsLoading(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    setSidebarProjectsLoading(true);
    void listProjects(client).then((response) => {
      if (!cancelled) {
        setSidebarProjects(response.projects.filter((project) => !deletedProjectIds.current.has(project.id)));
        setSidebarProjectsError(null);
      }
    }).catch(() => {
      if (!cancelled) setSidebarProjectsError("Projects are temporarily unavailable.");
    }).finally(() => {
      if (!cancelled) setSidebarProjectsLoading(false);
    });
    return () => { cancelled = true; };
  }, [client]);

  const loadProjectConversations = async (projectId: string, force = false) => {
    if (projectConversationLoads.current.has(projectId)) {
      if (force) projectConversationReloads.current.add(projectId);
      return;
    }
    if (!force && Object.prototype.hasOwnProperty.call(projectConversationIds, projectId)) return;
    projectConversationLoads.current.add(projectId);
    setProjectConversationLoading((current) => ({ ...current, [projectId]: true }));
    setProjectConversationErrors((current) => ({ ...current, [projectId]: null }));
    try {
      const response = await listProjectConversations(client, projectId);
      setProjectConversationIds((current) => ({
        ...current,
        [projectId]: response.conversations.map((conversation) => conversation.conversation_id),
      }));
    } catch (error) {
      if (error instanceof ApiError && error.status === 404 && isApiErrorCode(error, "project_not_found")) {
        setSidebarProjects((current) => current.filter((project) => project.id !== projectId));
        deleteProjectConversationCache(projectId);
        void refreshSidebarProjects();
      }
      setProjectConversationErrors((current) => ({
        ...current,
        [projectId]: "This Project's conversations could not be loaded.",
      }));
    } finally {
      projectConversationLoads.current.delete(projectId);
      setProjectConversationLoading((current) => ({ ...current, [projectId]: false }));
      if (projectConversationReloads.current.delete(projectId)) {
        void Promise.resolve().then(() => loadProjectConversations(projectId, true));
      }
    }
  };

  const deleteProjectConversationCache = (projectId: string) => {
    setProjectConversationIds((current) => {
      const next = { ...current };
      delete next[projectId];
      return next;
    });
  };

  const handleNewProjectConversation = async (projectId: string) => {
    const conversationId = await createConversationInProject(projectId);
    setWorkspace("chat");
    navigatePath("/");
    await selectConversation(conversationId);
    await loadProjectConversations(projectId, true);
    setProjectConversationRevision((revision) => revision + 1);
  };

  const handleNewFolderConversation = async (folderId: string) => {
    const conversationId = await createConversationInFolder(folderId);
    setWorkspace("chat");
    navigatePath("/");
    await selectConversation(conversationId);
  };

  const handleProjectConversationMove = async (conversationId: string, projectId: string | null) => {
    const current = state.conversations.find((conversation) => conversation.id === conversationId);
    try {
      await setConversationProject(conversationId, projectId);
    } catch (error) {
      if (error instanceof ApiError && error.status === 404 && isApiErrorCode(error, "project_not_found")) {
        await refreshSidebarProjects();
      }
      if (error instanceof ApiError && error.status === 404 && isApiErrorCode(error, "conversation_not_found")) {
        setProjectConversationRevision((revision) => revision + 1);
      }
      throw error;
    }
    const affected = new Set([current?.projectId ?? null, projectId].filter((id): id is string => id != null));
    await Promise.all([...affected].map((id) => loadProjectConversations(id, true)));
    setProjectConversationRevision((revision) => revision + 1);
  };

  const updateConversationProjectMetadata = async (
    conversationId: string,
    update: (id: string, value: boolean) => Promise<void>,
    value: boolean,
  ) => {
    const projectId = state.conversations.find((conversation) => conversation.id === conversationId)?.projectId;
    await update(conversationId, value);
    if (projectId != null) await loadProjectConversations(projectId, true);
    setProjectConversationRevision((revision) => revision + 1);
  };

  const handleProjectDeleted = (projectId: string) => {
    deletedProjectIds.current.add(projectId);
    setSidebarProjects((current) => current.filter((project) => project.id !== projectId));
    deleteProjectConversationCache(projectId);
    reconcileDeletedProject(projectId);
    setProjectConversationRevision((revision) => revision + 1);
  };

  const handleProjectArchived = (project: ProjectSummary) => {
    if (deletedProjectIds.current.has(project.id)) return;
    setSidebarProjects((current) => current.map((item) => item.id === project.id ? project : item));
  };

  const handleProjectUpdated = (project: ProjectSummary) => {
    if (deletedProjectIds.current.has(project.id)) return;
    setSidebarProjects((current) => current.map((item) => item.id === project.id ? project : item));
  };

  useEffect(() => {
    const onPopState = () => {
      const nextPath = browserPath();
      setRoutePath(nextPath);
      setWorkspace(isProjectsPath(nextPath) ? "projects" : "chat");
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const navigatePath = (path: string) => {
    if (typeof window !== "undefined" && window.location.pathname !== path) {
      window.history.pushState(null, "", path);
    }
    setRoutePath(path);
  };

  useEffect(() => subscribeConnectivity((next) => {
    connectivityVersion.current += 1;
    setStatus(next === "reachable" ? "healthy" : "unavailable");
  }), []);

  useEffect(() => {
    let cancelled = false;
    const healthVersion = connectivityVersion.current;

    async function checkHealth() {
      try {
        const health = await getHealth(client);
        if (!cancelled && connectivityVersion.current === healthVersion && health.status === "healthy") {
          setStatus("healthy");
        } else if (!cancelled && connectivityVersion.current === healthVersion) {
          setStatus("unhealthy");
        }
      } catch {
        if (!cancelled && connectivityVersion.current === healthVersion) {
          setStatus("unavailable");
        }
      }
    }

    void checkHealth();
    return () => {
      cancelled = true;
    };
  }, [client]);

  useEffect(() => {
    let cancelled = false;
    Promise.all([getRuntimes(client), getModelProviders(client), getExecutionProfiles(client)]).then(([r, p, profilesResponse]) => {
      if (cancelled) return;
      setRuntimes(r.runtimes); setProviders(p.providers);
      setProfiles(profilesResponse.profiles);
      // Discovery offers explicit choices; it never expresses user intent.
    }).catch(() => undefined);

    // The model catalog is isolated for the same reason as workspaces: a
    // `/models` failure must not blind runtime/provider/profile selection. An
    // empty catalog degrades the Model control to the legacy provider list
    // rather than removing the choice.
    getModels(client)
      .then(catalog => {
        if (cancelled) return;
        setConfiguredModels(catalog.models);
        setDefaultModelId(catalog.default_model_id ?? null);
        // A selection the catalog no longer contains is dropped rather than sent
        // as a stale identity.
        setProviderId(previous => previous != null && catalog.models.some(m => m.model_id === previous) ? previous : undefined);
      })
      .catch(() => undefined);

    // Workspace discovery is isolated: a /workspaces failure must not block
    // runtime/provider/profile selection or the prompt composer.
    getWorkspaces(client)
      .then(response => {
        if (cancelled) return;
        setWorkspaces(response.workspaces);
        setWorkspacesUnavailable(false);
        setSelectedWorkspaceId(prev =>
          prev != null && !response.workspaces.some(w => w.workspace_id === prev)
            ? null
            : prev,
        );
      })
      .catch(() => {
        if (!cancelled) {
          setWorkspacesUnavailable(true);
        }
      });

    return () => { cancelled = true; };
  }, [client]);

  const handleWorkspaceSelect = (next: WorkspaceId) => {
    setWorkspace(next);
    if (next === "projects") {
      navigatePath("/projects");
    } else if (isProjectsPath(routePath)) {
      navigatePath("/");
    }
    if (next === "document") {
      setDocumentOpened(true);
    }
    if (next === "settings") {
      setSettingsOpened(true);
    }
  };
  const openSettings = (section: SettingsSectionId) => {
    setSettingsSection(section);
    setSettingsOpened(true);
    setWorkspace("settings");
  };

  // The session's current execution selection, resolved once and shared by a
  // first submission and by retry/regenerate. A new attempt resolves its own
  // configuration at creation time from this same selection, so an explicit
  // choice is neither dropped nor silently turned into a default — and the
  // prior run's resolved runtime and credentials are never copied.
  // "Application default" resolves to one concrete configured model, so the
  // option can name it instead of hiding what will actually run.
  const defaultModelDisplayName = defaultModelId == null
    ? undefined
    : (configuredModels.find(m => m.model_id === defaultModelId)?.display_name ?? defaultModelId);
  // A configured model is addressed by its stable AVA `model_id`; the backend
  // resolves it to the exact ModelConfiguration and its provider connection. An
  // execution profile pins a provider instead, so that value belongs on the
  // legacy `model_provider_id` axis. The two id spaces are never mixed, which is
  // why the catalog decides the field rather than the caller.
  const providerIdIsModel = providerId != null && configuredModels.some(m => m.model_id === providerId);
  const modelAxis = providerId == null
    ? {}
    : providerIdIsModel ? { model_id: providerId } : { model_provider_id: providerId };
  const currentExecution = profileId === "application-default" ? undefined : profileId === "auto" ? { mode: "auto" as const } : (runtimeId || providerId ? { ...(runtimeId ? { runtime_id: runtimeId } : {}), ...modelAxis } : undefined);

  const currentWorkspaceId =
    selectedWorkspaceId != null &&
    workspaces.some(w => w.workspace_id === selectedWorkspaceId)
      ? selectedWorkspaceId
      : null;

  const handleComposerSubmit = (prompt: string) => {
    void submitPrompt(prompt, currentExecution, currentWorkspaceId);
  };

  // A retry or regenerate creates a new run for the same source user message,
  // so it carries the same explicit selection a fresh submit would.
  const handleRetryMessage = (messageId: string) => {
    retryMessage(messageId, currentExecution, currentWorkspaceId);
  };

  const handleRegenerateMessage = (messageId: string) => {
    regenerateMessage(messageId, currentExecution, currentWorkspaceId);
  };

  return (
    <AppShell
      headerActions={
        <>
          <WorkspaceTabs active={workspace} onSelect={handleWorkspaceSelect} />
          <StatusIndicator
            state={indicatorState(status)}
            label={statusText(status)}
          />
        </>
      }
      showSidebar={workspace === "chat"}
      sidebarChildren={
        <ConversationList
          conversations={conversationList}
          activeConversations={activeConversations}
          archivedConversations={archivedConversations}
          activeConversationId={activeConversation?.id ?? null}
          onNewChat={createConversation}
          onSelect={selectConversation}
          onRename={async (id, title) => {
            const projectId = state.conversations.find((conversation) => conversation.id === id)?.projectId;
            try {
              await renameConversation(id, title);
              if (projectId != null) await loadProjectConversations(projectId, true);
              setProjectConversationRevision((revision) => revision + 1);
            } catch (error) {
              if (error instanceof ApiError && error.status === 404) {
                forgetConversation(id);
              }
              throw error;
            }
          }}
          onDelete={async (id) => {
            await deleteConversation(id);
            forgetConversation(id);
            setProjectConversationRevision((revision) => revision + 1);
          }}
          searchQuery={searchQuery}
          onSearchChange={setSearchQuery}
          searchLoading={searchLoading}
          searchError={searchError}
          conversationsLoading={state.loading === true}
          conversationLoadError={state.loadError ?? null}
          onRetryConversations={() => void reloadConversations()}
          folders={folders}
          foldersLoading={foldersLoading}
          folderError={folderError}
          onRetryFolders={() => void reloadFolders()}
          onCreateFolder={createFolder}
          onRenameFolder={renameFolder}
          onDeleteFolder={deleteFolder}
          onMoveConversation={moveConversation}
          onNewChatInFolder={handleNewFolderConversation}
          projects={sidebarProjects}
          projectsLoading={sidebarProjectsLoading}
          projectsError={sidebarProjectsError}
          onRetryProjects={() => void refreshSidebarProjects()}
          projectConversationIds={projectConversationIds}
          projectConversationLoading={projectConversationLoading}
          projectConversationErrors={projectConversationErrors}
          onExpandProject={(projectId) => {
            void loadProjectConversations(projectId);
          }}
          onNewChatInProject={handleNewProjectConversation}
          onRetryProjectConversations={(projectId) => void loadProjectConversations(projectId, true)}
          onSetConversationProject={handleProjectConversationMove}
          onSetConversationPinned={(id, pinned) => updateConversationProjectMetadata(id, setConversationPinned, pinned)}
          onSetConversationArchived={(id, archived) => updateConversationProjectMetadata(id, setConversationArchived, archived)}
          onOpenConversationSystemPrompts={(id, title) => setPromptScopeDialog({ scopeType: "conversation", scopeId: id, scopeLabel: `Conversation: ${title}` })}
          onOpenFolderSystemPrompts={(id, name) => setPromptScopeDialog({ scopeType: "folder", scopeId: id, scopeLabel: `Folder: ${name}` })}
          error={state.loadError == null ? state.error ?? null : null}
        />
      }
      mainContent={
        <>
          <WorkspacePane visible={workspace === "chat"} id="chat-workspace">
            {activeConversation != null ? (
              <ConversationView
                conversation={activeConversation}
                error={state.error}
                onReload={() => { void selectConversation(activeConversation.id); }}
                onRetryMessage={handleRetryMessage}
                onRegenerateMessage={handleRegenerateMessage}
                onOpenSettings={openSettings}
              />
            ) : (
              <div
                style={{
                  flex: 1,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: t.colors.mutedText,
                  fontSize: 14,
                }}
              >
                No conversation selected.
              </div>
            )}
          </WorkspacePane>
          {documentOpened && (
            <WorkspacePane
              visible={workspace === "document"}
              id="document-workspace"
            >
              <DocumentWorkspace />
            </WorkspacePane>
          )}
          {settingsOpened && (
            <WorkspacePane visible={workspace === "settings"} id="settings-workspace">
              <SettingsWorkspace client={client} initialSection={settingsSection} key={settingsSection} />
            </WorkspacePane>
          )}
          <WorkspacePane visible={workspace === "projects"} id="projects-workspace">
            <ProjectsWorkspace
              client={client}
              active={workspace === "projects"}
              projectId={projectIdFromPath(routePath)}
              onOpenProject={(id) => navigatePath(`/projects/${encodeURIComponent(id)}`)}
              onBackToProjects={() => navigatePath("/projects")}
              conversations={state.conversations}
              activeConversationId={activeConversation?.id ?? null}
              onOpenConversation={(id) => {
                setWorkspace("chat");
                navigatePath("/");
                void selectConversation(id);
              }}
              onCreateConversation={handleNewProjectConversation}
              conversationsRevision={projectConversationRevision}
              onProjectCreated={(project) => {
                deletedProjectIds.current.delete(project.id);
                void refreshSidebarProjects();
              }}
              onProjectDeleted={handleProjectDeleted}
              onProjectArchived={handleProjectArchived}
              onProjectUpdated={handleProjectUpdated}
            />
          </WorkspacePane>
          <Modal
            open={promptScopeDialog != null}
            title={promptScopeDialog == null ? "System Prompts" : `System Prompts — ${promptScopeDialog.scopeLabel}`}
            onClose={() => setPromptScopeDialog(null)}
            primaryAction="Done"
            onPrimaryAction={() => setPromptScopeDialog(null)}
            width={720}
          >
            {promptScopeDialog != null && <CorePromptScopeAssignments client={client} scopeType={promptScopeDialog.scopeType as AssignablePromptScope} scopeId={promptScopeDialog.scopeId} scopeLabel={promptScopeDialog.scopeLabel} />}
          </Modal>
        </>
      }
      prompt={
        <div
          style={{
            width: "100%",
            maxWidth: 640,
            margin: "0 auto",
            display: workspace === "chat" ? undefined : "none",
            paddingBottom: 16,
          }}
        >
          <PromptComposer
            controls={<ExecutionControls profiles={profiles} selectedProfileId={profileId} onDefaultChange={() => { setProfileId("application-default"); setRuntimeId(undefined); setProviderId(undefined); }} onAutoChange={() => { setProfileId("auto"); setRuntimeId(undefined); setProviderId(undefined); }} onProfileChange={p => { setProfileId(p.id); setRuntimeId(p.runtime_id); setProviderId(p.model_provider_id); }} runtimes={runtimes} modelProviders={providers} configuredModels={configuredModels} defaultModelDisplayName={defaultModelDisplayName} selectedRuntimeId={runtimeId} selectedModelProviderId={providerId} onRuntimeChange={id => { setProfileId(id || providerId ? "custom" : "application-default"); setRuntimeId(id || undefined); }} onModelProviderChange={id => { setProfileId(id || runtimeId ? "custom" : "application-default"); setProviderId(id || undefined); }} workspaces={workspaces} selectedWorkspaceId={selectedWorkspaceId} onWorkspaceChange={id => setSelectedWorkspaceId(id)} workspacesUnavailable={workspacesUnavailable} disabled={isRunning || isStarting || isStopping} />}
            placeholder="Ask AVA anything..."
            onSubmit={handleComposerSubmit}
            onStop={stopRun}
            isRunning={isRunning}
            isStarting={isStarting}
            isStopping={isStopping}
          />
        </div>
      }
    />
  );
}

export function AppWorkspace({ client }: AppWorkspaceProps) {
  return (
    <ConversationProvider client={client}>
      <DocumentProvider client={client}>
        <AgentRunProvider client={client}>
          <WorkspaceContent client={client} />
        </AgentRunProvider>
      </DocumentProvider>
    </ConversationProvider>
  );
}
