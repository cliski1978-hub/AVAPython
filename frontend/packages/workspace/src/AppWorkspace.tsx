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
  type ExecutionMode,
} from "@ava/agent-ui";
import { ApiError, deleteConversationAttachment, listConversationAttachments, uploadConversationAttachment, type ApiClient } from "@ava/api-client";
import { getHealth, getModelProviders, getModels, getRuntimes, getExecutionProfiles, getProjectExecutionDefaults, getWorkspaces, listProjects, listProjectConversations, subscribeConnectivity } from "@ava/api-client";
import { DocumentProvider, DocumentWorkspace } from "@ava/document-core";
import { ApprovalsWorkspace, type ApprovalDataSource } from "@ava/approvals-core";
import { CorePromptScopeAssignments, SettingsWorkspace, type AssignablePromptScope } from "@ava/settings-core";
import { ProjectsWorkspace } from "./ProjectsWorkspace";
import { RunInspector, type RunInspectorTab } from "./RunInspector";
import { useContextWindowPreview } from "./useContextWindowPreview";
import { attachmentContextSummary } from "@ava/agent-ui";
import type { SettingsSectionId } from "@ava/ui-core";
import {
  AppShell,
  DesignSystemPreview,
  Modal,
  StatusIndicator,
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
  /** Optional future authorized adapter. No production adapter is wired yet. */
  approvalDataSource?: ApprovalDataSource;
  /** Enables isolated developer-only UI previews in Vite hosts. */
  enableDesignSystemPreview?: boolean;
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

function workspaceFromPath(path: string): WorkspaceId {
  if (isProjectsPath(path)) return "projects";
  if (path === "/documents" || path.startsWith("/documents/")) return "document";
  if (path === "/settings" || path.startsWith("/settings/")) return "settings";
  if (path === "/approvals" || path.startsWith("/approvals/")) return "approvals";
  return "chat";
}

function pathForWorkspace(workspace: WorkspaceId): string {
  switch (workspace) {
    case "chat": return "/";
    case "projects": return "/projects";
    case "document": return "/documents";
    case "settings": return "/settings";
    case "approvals": return "/approvals";
  }
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

function WorkspaceContent({ client, approvalDataSource }: { client: ApiClient; approvalDataSource?: ApprovalDataSource }) {
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
    relocateConversation,
    createConversationInFolder,
    createConversationInProject,
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
  const [workspace, setWorkspace] = useState<WorkspaceId>(() => workspaceFromPath(browserPath()));
  const [inspectorOpen, setInspectorOpen] = useState(() => {
    try { return window.localStorage.getItem("ava.ui.run-inspector-open") === "true"; } catch { return false; }
  });
  const [inspectorWidth, setInspectorWidth] = useState(() => {
    try { const stored = Number(window.localStorage.getItem("ava.ui.run-inspector-width")); return Number.isFinite(stored) && stored >= 280 ? Math.min(stored, 700) : 380; } catch { return 380; }
  });
  const [inspectorTab, setInspectorTab] = useState<RunInspectorTab>("Prompts");
  const [promptDrafts, setPromptDrafts] = useState<Record<string, string>>({});
  const [executionMode, setExecutionMode] = useState<ExecutionMode>("chat");
  const preserveModeForCreatedConversation = useRef(false);
  const [conversationAttachments, setConversationAttachments] = useState<Awaited<ReturnType<typeof listConversationAttachments>>["attachments"]>([]);
  const [attachmentsOwnerId, setAttachmentsOwnerId] = useState<string | null>(null);
  const [attachmentsLoading, setAttachmentsLoading] = useState(false);
  const [attachmentsLoadError, setAttachmentsLoadError] = useState<string | null>(null);
  const activeConversationId = activeConversation?.id ?? null;
  useEffect(() => {
    if (preserveModeForCreatedConversation.current) {
      preserveModeForCreatedConversation.current = false;
      return;
    }
    setExecutionMode("chat");
  }, [activeConversationId]);
  const promptDraft = promptDrafts[activeConversationId ?? "__new__"] ?? "";
  const setPromptDraft = (value: string) => {
    const draftKey = activeConversationId ?? "__new__";
    setPromptDrafts((current) => ({ ...current, [draftKey]: value }));
  };
  const activeConversationIdRef = useRef(activeConversationId);
  activeConversationIdRef.current = activeConversationId;

  useEffect(() => {
    if (!activeConversationId) {
      setConversationAttachments([]);
      setAttachmentsOwnerId(null);
      setAttachmentsLoading(false);
      setAttachmentsLoadError(null);
      return;
    }
    let cancelled = false;
    setConversationAttachments([]);
    setAttachmentsOwnerId(activeConversationId);
    setAttachmentsLoading(true);
    setAttachmentsLoadError(null);
    void listConversationAttachments(client, activeConversationId).then((result) => {
      if (!cancelled) setConversationAttachments(result.attachments);
    }).catch(() => {
      if (!cancelled) setAttachmentsLoadError("Unable to load this conversation's attachments.");
    }).finally(() => {
      if (!cancelled) setAttachmentsLoading(false);
    });
    return () => { cancelled = true; };
  }, [client, activeConversationId]);

  const uploadActiveConversationAttachment = async (file: File, conversationId: string | null) => {
    if (!conversationId) return;
    const result = await uploadConversationAttachment(client, conversationId, file);
    if (activeConversationIdRef.current === conversationId) {
      setAttachmentsOwnerId(conversationId);
      setConversationAttachments((current) => current.some((item) => item.attachment_id === result.attachment_id)
        ? current
        : [...current, result]);
    }
  };

  const removeActiveConversationAttachment = async (attachmentId: string, conversationId: string | null) => {
    if (!conversationId) return;
    await deleteConversationAttachment(client, conversationId, attachmentId);
    if (activeConversationIdRef.current === conversationId) {
      setConversationAttachments((current) => current.filter((item) => item.attachment_id !== attachmentId));
    }
  };
  const [documentOpened, setDocumentOpened] = useState(() => workspaceFromPath(browserPath()) === "document");
  const [settingsOpened, setSettingsOpened] = useState(() => workspaceFromPath(browserPath()) === "settings");
  const [approvalsOpened, setApprovalsOpened] = useState(() => workspaceFromPath(browserPath()) === "approvals");
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
  const [projectDefaultModelId, setProjectDefaultModelId] = useState<string | null>(null);
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
      await relocateConversation(conversationId, projectId == null
        ? { destination_type: "ungrouped" }
        : { destination_type: "project", destination_id: projectId });
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

  const handleProjectDeleted = (projectId: string, deletedConversationIds: string[] = []) => {
    deletedProjectIds.current.add(projectId);
    setSidebarProjects((current) => current.filter((project) => project.id !== projectId));
    deleteProjectConversationCache(projectId);
    reconcileDeletedProject(projectId, deletedConversationIds);
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
      const nextWorkspace = workspaceFromPath(nextPath);
      setRoutePath(nextPath);
      setWorkspace(nextWorkspace);
      if (nextWorkspace === "document") setDocumentOpened(true);
      if (nextWorkspace === "settings") setSettingsOpened(true);
      if (nextWorkspace === "approvals") setApprovalsOpened(true);
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
    navigatePath(pathForWorkspace(next));
    if (next === "document") {
      setDocumentOpened(true);
    }
    if (next === "settings") {
      setSettingsOpened(true);
    }
    if (next === "approvals") setApprovalsOpened(true);
  };
  const openSettings = (section: SettingsSectionId) => {
    setSettingsSection(section);
    setSettingsOpened(true);
    setWorkspace("settings");
    navigatePath("/settings");
  };

  // An inherited Project model is shown in chat controls for clarity, but is
  // never converted into a RunExecutionOverride. The backend resolves the
  // current Project preference from the conversation on every run.
  useEffect(() => {
    const projectId = activeConversation?.projectId;
    if (projectId == null) {
      setProjectDefaultModelId(null);
      return;
    }
    let cancelled = false;
    setProjectDefaultModelId(null);
    void getProjectExecutionDefaults(client, projectId)
      .then((defaults) => {
        if (!cancelled) setProjectDefaultModelId(defaults.model_id);
      })
      .catch(() => {
        if (!cancelled) setProjectDefaultModelId(null);
      });
    return () => { cancelled = true; };
  }, [client, activeConversation?.projectId, routePath]);

  // The inherited Project model is context for display only. The run request
  // stays unset so the backend resolves the Project's current preference for
  // each new run instead of receiving a stale model as an explicit override.
  useEffect(() => {
    const projectId = activeConversation?.projectId;
    if (projectId == null) {
      setProjectDefaultModelId(null);
      return;
    }
    let cancelled = false;
    setProjectDefaultModelId(null);
    void getProjectExecutionDefaults(client, projectId)
      .then((defaults) => {
        if (!cancelled) setProjectDefaultModelId(defaults.model_id);
      })
      .catch(() => {
        if (!cancelled) setProjectDefaultModelId(null);
      });
    return () => { cancelled = true; };
  }, [client, activeConversation?.projectId, routePath]);

  // The session's current execution selection, resolved once and shared by a
  // first submission and by retry/regenerate. A new attempt resolves its own
  // configuration at creation time from this same selection, so an explicit
  // choice is neither dropped nor silently turned into a default — and the
  // prior run's resolved runtime and credentials are never copied.
  // "Application default" resolves to one concrete configured model, so the
  // option can name it instead of hiding what will actually run.
  const applicationDefaultModelDisplayName = defaultModelId == null
    ? undefined
    : (configuredModels.find(m => m.model_id === defaultModelId)?.display_name ?? defaultModelId);
  const projectDefaultModelDisplayName = projectDefaultModelId == null
    ? undefined
    : (configuredModels.find(m => m.model_id === projectDefaultModelId)?.display_name ?? projectDefaultModelId);
  const inheritsProjectModel = profileId === "application-default"
    && activeConversation?.projectId != null
    && projectDefaultModelDisplayName != null;
  const defaultModelDisplayName = inheritsProjectModel
    ? projectDefaultModelDisplayName
    : applicationDefaultModelDisplayName;
  const composerExecutionSummary = profileId === "application-default"
    ? (inheritsProjectModel ? `Project default · ${projectDefaultModelDisplayName}` : applicationDefaultModelDisplayName ?? "Application default")
    : profileId === "auto"
      ? "Auto"
      : profiles.find(profile => profile.id === profileId)?.name
        ?? configuredModels.find(model => model.model_id === providerId)?.display_name
        ?? "Custom execution";
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
  const currentExecutionKey = JSON.stringify(currentExecution ?? null);
  const selectedModelIdForStatus = profileId === "application-default"
    ? (activeConversation?.projectId != null && projectDefaultModelId != null ? projectDefaultModelId : defaultModelId)
    : providerId != null && configuredModels.some((model) => model.model_id === providerId)
      ? providerId
      : null;
  const selectedModelForStatus = selectedModelIdForStatus == null
    ? undefined
    : configuredModels.find((model) => model.model_id === selectedModelIdForStatus);
  const selectedRuntimeIdForStatus = runtimeId ?? runtimes.find((runtime) => runtime.is_default)?.runtime_info.runtime_id;
  const selectedRuntimeIsOpenHands = selectedRuntimeIdForStatus?.toLowerCase() === "openhands";
  const executionModeStatus = executionMode === "chat" ? null : (
    <span className="block space-y-0.5">
      <span className="block">
        Model tool calling: {selectedModelForStatus == null
          ? "not reported for this selection"
          : selectedModelForStatus.capabilities.tool_calling ? "reported supported" : "reported unsupported"}.
        {" "}Normalized tool execution is unavailable in this deployment; end-to-end readiness is not reported by the backend.
      </span>
      {selectedRuntimeIsOpenHands ? (
        <span className="block">
          OpenHands may expose legacy Workspace tools under separate security controls; they are not part of normalized approval-managed dispatch.
        </span>
      ) : null}
    </span>
  );

  const { preview: contextWindowPreview, loading: contextWindowPreviewLoading, error: contextWindowPreviewError } = useContextWindowPreview(client, {
    prompt: promptDraft,
    conversation_id: activeConversationId,
    execution: currentExecution,
  }, JSON.stringify([currentExecutionKey, attachmentsOwnerId, conversationAttachments.map(item => item.attachment_id), activeConversation?.projectId, activeConversation?.folderId, projectDefaultModelId, routePath, promptScopeDialog != null]));

  const contextWindowStatus = !promptDraft.trim()
    ? <span>Context window estimate appears while you draft a message.</span>
    : contextWindowPreviewLoading
      ? <span>Estimating context window…</span>
      : contextWindowPreviewError
        ? <span className="text-destructive">Context window estimate unavailable.</span>
        : contextWindowPreview
          ? <span className={contextWindowPreview.can_fit ? undefined : "text-destructive"}>
            {contextWindowPreview.estimated_input_tokens.toLocaleString()} estimated tokens
            {contextWindowPreview.input_budget_tokens != null ? ` / ${contextWindowPreview.input_budget_tokens.toLocaleString()} available` : " · input budget unbounded"}
            {contextWindowPreview.attachments?.length ? ` · Attachments: ${attachmentContextSummary(contextWindowPreview.attachments)} · ${contextWindowPreview.attachment_context_tokens?.toLocaleString() ?? "not captured"} context tokens (${contextWindowPreview.count_accuracy})` : ""}
            {contextWindowPreview.compaction_recommended ? " · Older turns may be compacted when you send" : ""}
          </span>
          : <span>Context window estimate unavailable.</span>;

  const currentWorkspaceId =
    selectedWorkspaceId != null &&
    workspaces.some(w => w.workspace_id === selectedWorkspaceId)
      ? selectedWorkspaceId
      : null;

  const handleComposerSubmit = (prompt: string, mode: ExecutionMode) => {
    const creatingConversation = activeConversationId == null;
    if (creatingConversation) preserveModeForCreatedConversation.current = true;
    return submitPrompt(prompt, currentExecution, currentWorkspaceId, mode).catch((error: unknown) => {
      if (creatingConversation) preserveModeForCreatedConversation.current = false;
      throw error;
    });
  };

  const toggleInspector = () => setInspectorOpen((open) => {
    const next = !open;
    try { window.localStorage.setItem("ava.ui.run-inspector-open", String(next)); } catch { /* optional UI preference */ }
    return next;
  });

  // A retry or regenerate creates a new run for the same source user message,
  // so it carries the same explicit selection a fresh submit would.
  const handleRetryMessage = (messageId: string) => {
    retryMessage(messageId, currentExecution, currentWorkspaceId, executionMode);
  };

  const handleRegenerateMessage = (messageId: string) => {
    regenerateMessage(messageId, currentExecution, currentWorkspaceId, executionMode);
  };

  return (
    <AppShell
      headerActions={
        <>
          <WorkspaceTabs active={workspace} onSelect={handleWorkspaceSelect} />
          {workspace === "chat" && <button type="button" aria-label="Toggle Run Inspector" aria-expanded={inspectorOpen} onClick={toggleInspector} className="rounded-md border border-border px-2.5 py-1.5 text-xs text-foreground hover:bg-muted focus-visible:outline focus-visible:outline-2">{inspectorOpen ? "Hide Inspector" : "Run Inspector"}</button>}
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
            <div className="flex min-h-0 min-w-0 flex-1 overflow-hidden">
              <div className="flex min-h-0 min-w-0 flex-1 overflow-hidden">
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
                  <div className="flex flex-1 items-center justify-center bg-background text-muted-foreground" style={{ fontSize: "calc(14px * var(--ava-font-scale, 1))" }}>No conversation selected.</div>
                )}
              </div>
              {inspectorOpen && <div
                role="separator" aria-orientation="vertical" aria-label="Resize Run Inspector" aria-valuemin={280} aria-valuemax={700} aria-valuenow={inspectorWidth} tabIndex={0}
                className="w-1 shrink-0 cursor-col-resize bg-border/60 hover:bg-primary focus-visible:bg-primary"
                onPointerDown={(event) => { event.currentTarget.setPointerCapture(event.pointerId); }}
                onPointerMove={(event) => { if (event.buttons !== 1) return; const next = Math.max(280, Math.min(700, window.innerWidth - event.clientX)); setInspectorWidth(next); try { window.localStorage.setItem("ava.ui.run-inspector-width", String(next)); } catch { /* optional UI preference */ } }}
                onKeyDown={(event) => { if (event.key === "ArrowLeft" || event.key === "ArrowRight") { event.preventDefault(); const direction = event.key === "ArrowLeft" ? 1 : -1; const next = Math.max(280, Math.min(700, inspectorWidth + direction * 16)); setInspectorWidth(next); try { window.localStorage.setItem("ava.ui.run-inspector-width", String(next)); } catch { /* optional UI preference */ } } }}
              />}
              {inspectorOpen && <div className="h-full min-h-0 shrink-0" style={{ width: `${inspectorWidth}px` }}><RunInspector client={client} conversationId={activeConversation?.id ?? null} activeRunId={activeConversation?.run?.runId} draftPrompt={promptDraft} contextWindowPreview={contextWindowPreview} contextWindowPreviewLoading={contextWindowPreviewLoading} contextWindowPreviewError={contextWindowPreviewError} onClose={toggleInspector} selectedTab={inspectorTab} onTabChange={setInspectorTab} /></div>}
            </div>
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
          {approvalsOpened && (
            <WorkspacePane visible={workspace === "approvals"} id="approvals-workspace">
              <ApprovalsWorkspace dataSource={approvalDataSource} />
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
          className="mx-auto box-border w-full max-w-[90rem] px-3 pb-4 sm:px-4 lg:px-6"
          style={{ display: workspace === "chat" ? undefined : "none" }}
        >
          <PromptComposer
            value={promptDraft}
            executionSummary={composerExecutionSummary}
            executionMode={executionMode}
            onExecutionModeChange={setExecutionMode}
            executionModeStatus={executionModeStatus}
            contextWindowStatus={contextWindowStatus}
            conversationId={activeConversationId}
            attachments={attachmentsOwnerId === activeConversationId ? conversationAttachments : []}
            attachmentContext={contextWindowPreview?.attachments}
            attachmentContextLoading={contextWindowPreviewLoading}
            attachmentsLoading={Boolean(activeConversationId) && (attachmentsOwnerId !== activeConversationId || attachmentsLoading)}
            attachmentsLoadError={attachmentsOwnerId === activeConversationId ? attachmentsLoadError : null}
            onUploadAttachment={activeConversationId ? (file, ownerId) => uploadActiveConversationAttachment(file, ownerId) : undefined}
            onRemoveAttachment={activeConversationId ? (attachmentId, ownerId) => removeActiveConversationAttachment(attachmentId, ownerId) : undefined}
            controls={<ExecutionControls layout="popover" profiles={profiles} selectedProfileId={profileId} onDefaultChange={() => { setProfileId("application-default"); setRuntimeId(undefined); setProviderId(undefined); }} onAutoChange={() => { setProfileId("auto"); setRuntimeId(undefined); setProviderId(undefined); }} onProfileChange={p => { setProfileId(p.id); setRuntimeId(p.runtime_id); setProviderId(p.model_provider_id); }} runtimes={runtimes} modelProviders={providers} configuredModels={configuredModels} defaultModelDisplayName={defaultModelDisplayName} defaultModelScopeLabel={inheritsProjectModel ? "Project default" : "Application default"} selectedRuntimeId={runtimeId} selectedModelProviderId={providerId} onRuntimeChange={id => { setProfileId(id || providerId ? "custom" : "application-default"); setRuntimeId(id || undefined); }} onModelProviderChange={id => { setProfileId(id || runtimeId ? "custom" : "application-default"); setProviderId(id || undefined); }} workspaces={workspaces} selectedWorkspaceId={selectedWorkspaceId} onWorkspaceChange={id => setSelectedWorkspaceId(id)} workspacesUnavailable={workspacesUnavailable} disabled={isRunning || isStarting || isStopping} />}
            placeholder="Ask AVA anything..."
            onChange={setPromptDraft}
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

export function AppWorkspace({ client, approvalDataSource, enableDesignSystemPreview = false }: AppWorkspaceProps) {
  if (enableDesignSystemPreview && browserPath() === "/dev/ui") {
    return <DesignSystemPreview />;
  }
  return (
    <ConversationProvider client={client}>
      <DocumentProvider client={client}>
        <AgentRunProvider client={client}>
        <WorkspaceContent client={client} approvalDataSource={approvalDataSource} />
        </AgentRunProvider>
      </DocumentProvider>
    </ConversationProvider>
  );
}
