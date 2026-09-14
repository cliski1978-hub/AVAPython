import {
  AgentRunProvider,
  ConversationList,
  ConversationProvider,
  ConversationView,
  PromptComposer,
  useAgentRun,
  useConversationState,
} from "@ava/agent-ui";
import type { ApiClient } from "@ava/api-client";
import { getHealth } from "@ava/api-client";
import { DocumentProvider, DocumentWorkspace } from "@ava/document-core";
import {
  AppShell,
  StatusIndicator,
  defaultTheme,
  type StatusState,
} from "@ava/ui-core";
import { useEffect, useState, type CSSProperties, type ReactNode } from "react";

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

  useEffect(() => {
    let cancelled = false;

    async function checkHealth() {
      try {
        const health = await getHealth(client);
        if (!cancelled && health.status === "healthy") {
          setStatus("healthy");
        } else if (!cancelled) {
          setStatus("unhealthy");
        }
      } catch {
        if (!cancelled) {
          setStatus("unavailable");
        }
      }
    }

    void checkHealth();
    return () => {
      cancelled = true;
    };
  }, [client]);

  const handleWorkspaceSelect = (next: WorkspaceId) => {
    setWorkspace(next);
    if (next === "document") {
      setDocumentOpened(true);
    }
  };

  const handleComposerSubmit = (prompt: string) => {
    void submitPrompt(prompt);
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
          }}
        >
          <PromptComposer
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
    <ConversationProvider>
      <DocumentProvider>
        <AgentRunProvider client={client}>
          <WorkspaceContent client={client} />
        </AgentRunProvider>
      </DocumentProvider>
    </ConversationProvider>
  );
}
