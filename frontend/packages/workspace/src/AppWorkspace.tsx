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
import type { ApiClient } from "@ava/api-client";
import { getHealth, getModelProviders, getModels, getRuntimes, getExecutionProfiles, getWorkspaces, subscribeConnectivity } from "@ava/api-client";
import { DocumentProvider, DocumentWorkspace } from "@ava/document-core";
import { SettingsWorkspace } from "@ava/settings-core";
import type { SettingsSectionId } from "@ava/ui-core";
import {
  AppShell,
  StatusIndicator,
  defaultTheme,
  type StatusState,
} from "@ava/ui-core";
import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";

import { WorkspaceTabs, type WorkspaceId } from "./WorkspaceTabs";

/**
 * Shared AVA application workspace used by both Web and Desktop.
 *
 * Owns the workspace selection between the AI Conversation and the Document
 * workspace. Both panes stay mounted so in-session state (conversation
 * messages, editor content) survives switching. Persistence is intentionally
 * not implemented.
 */

export interface AppWorkspaceProps {
  client: ApiClient;
}

type AppStatus = "checking" | "healthy" | "unhealthy" | "unavailable";

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
    conversations,
    activeConversation,
    createConversation,
    selectConversation,
    renameConversation,
    state,
  } = useConversationState();
  const {
    submitPrompt,
    stopRun,
    retryMessage,
    regenerateMessage,
    isStarting,
    isRunning,
    isStopping,
  } = useAgentRun();

  const [workspace, setWorkspace] = useState<WorkspaceId>("chat");
  const [documentOpened, setDocumentOpened] = useState(false);
  const [settingsOpened, setSettingsOpened] = useState(false);
  const [settingsSection, setSettingsSection] = useState<SettingsSectionId>("providers");
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
          conversations={conversations}
          activeConversationId={activeConversation?.id ?? null}
          onNewChat={createConversation}
          onSelect={selectConversation}
          onRename={renameConversation}
          error={state.error ?? null}
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
