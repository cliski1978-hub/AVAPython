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
  type ModelProviderDiscoveryItem,
  type ExecutionProfile,
  type WorkspaceInfo,
} from "@ava/agent-ui";
import type { ApiClient } from "@ava/api-client";
import { getHealth, getModelProviders, getRuntimes, getExecutionProfiles, getWorkspaces, subscribeConnectivity } from "@ava/api-client";
import { DocumentProvider, DocumentWorkspace } from "@ava/document-core";
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
  const [status, setStatus] = useState<AppStatus>("checking");
  const connectivityVersion = useRef(0);
  const [runtimes, setRuntimes] = useState<RuntimeDiscoveryItem[]>([]);
  const [providers, setProviders] = useState<ModelProviderDiscoveryItem[]>([]);
  const [runtimeId, setRuntimeId] = useState<string>();
  const [providerId, setProviderId] = useState<string>();
  const [profileId, setProfileId] = useState("custom");
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
      if (r.runtimes.some(x => x.runtime_info.runtime_id === r.default_runtime_id)) setRuntimeId(r.default_runtime_id);
      if (p.providers.some(x => x.provider_id === p.default_provider_id)) setProviderId(p.default_provider_id);
      if (profilesResponse.profiles.some(x => x.id === profilesResponse.default_profile_id)) setProfileId(profilesResponse.default_profile_id);
    }).catch(() => undefined);

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
  };

  const handleComposerSubmit = (prompt: string) => {
    const execution = profileId === "auto" ? { mode: "auto" as const } : (runtimeId || providerId ? { ...(runtimeId ? { runtime_id: runtimeId } : {}), ...(providerId ? { model_provider_id: providerId } : {}) } : undefined);
    const workspaceId =
      selectedWorkspaceId != null &&
      workspaces.some(w => w.workspace_id === selectedWorkspaceId)
        ? selectedWorkspaceId
        : null;
    void submitPrompt(prompt, execution, workspaceId);
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
                onRetryMessage={retryMessage}
                onRegenerateMessage={regenerateMessage}
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
            controls={<ExecutionControls profiles={profiles} selectedProfileId={profileId} onAutoChange={() => setProfileId("auto")} onProfileChange={p => { setProfileId(p.id); setRuntimeId(p.runtime_id); setProviderId(p.model_provider_id); }} runtimes={runtimes} modelProviders={providers} selectedRuntimeId={runtimeId} selectedModelProviderId={providerId} onRuntimeChange={id => { setProfileId("custom"); setRuntimeId(id); }} onModelProviderChange={id => { setProfileId("custom"); setProviderId(id); }} workspaces={workspaces} selectedWorkspaceId={selectedWorkspaceId} onWorkspaceChange={id => setSelectedWorkspaceId(id)} workspacesUnavailable={workspacesUnavailable} disabled={isRunning || isStarting || isStopping} />}
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
