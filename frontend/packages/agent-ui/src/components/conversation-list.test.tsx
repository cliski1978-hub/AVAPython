import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ConversationList } from "./ConversationList";
import type { ConversationFolder, Project } from "@ava/contracts";

const conversations = [
  { id: "a", title: "Explain robot zoning", messages: [] },
  { id: "b", title: "Plan the deployment", messages: [] },
];

describe("ConversationList", () => {
  it("provides a minimal shared New Chat navigation action", () => {
    const html = renderToStaticMarkup(
      <ConversationList
        conversations={[]}
        activeConversationId={null}
        onNewChat={() => undefined}
        onSelect={() => undefined}
      />,
    );
    expect(html).toContain("New Chat");
    expect(html).toContain('data-new-chat="true"');
    expect(html).toContain("lucide-square-pen");
    expect(html).toContain("bg-transparent");
    expect(html).toContain("text-foreground");
    expect(html).toContain("hover:bg-muted");
    expect(html).toContain("h-8");
    expect(html).not.toContain("bg-primary");
  });

  it("uses the shared lucide-folder-plus Button for New Folder", () => {
    const html = renderToStaticMarkup(
      <ConversationList
        conversations={[]}
        activeConversationId={null}
        onNewChat={() => undefined}
        onSelect={() => undefined}
        onCreateFolder={async () => undefined}
      />,
    );
    expect(html).toContain('data-new-folder="true"');
    expect(html).toContain("lucide-folder-plus");
    expect(html).toContain("border-input");
    expect(html).toContain("text-foreground");
  });

  it("uses expanded Folder and Rocket icons with truncating labels in the sidebar", () => {
    const folder: ConversationFolder = {
      id: "folder-1", name: "An especially long folder name", created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z", contract_version: "v1",
    };
    const project: Project = {
      id: "project-1", name: "An especially long project name", description: null, instructions: null,
      is_archived: false, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
      contract_version: "v1",
    };
    const html = renderToStaticMarkup(
      <ConversationList
        conversations={[]}
        activeConversationId={null}
        onNewChat={() => undefined}
        onSelect={() => undefined}
        folders={[folder]}
        projects={[project]}
      />,
    );

    expect(html).toContain("lucide-folder-open");
    expect(html).toContain("lucide-rocket");
    expect(html).not.toContain("lucide-chevron-down");
    expect(html).not.toContain("lucide-chevron-right");
    expect(html).toContain("text-overflow:ellipsis");
    expect(html).toContain("min-width:0");
    expect(html).toContain("shrink-0");
  });

  it("uses semantic foreground styling for conversation titles in Dark mode", () => {
    const html = renderToStaticMarkup(
      <ConversationList
        conversations={conversations}
        activeConversationId={null}
        onNewChat={() => undefined}
        onSelect={() => undefined}
      />,
    );
    const row = html.match(/data-conversation-row="a"[^>]*style="([^"]*)"/);
    expect(row?.[1]).toContain("color:hsl(var(--foreground))");
    expect(row?.[1]).not.toMatch(/#111827|text-black|text-gray-/);
  });

  it("shows the active empty state and archived navigation when there are no conversations", () => {
    const html = renderToStaticMarkup(
      <ConversationList
        conversations={[]}
        activeConversationId={null}
        onNewChat={() => undefined}
        onSelect={() => undefined}
      />,
    );
    expect(html).toContain("No active conversations");
    expect(html).toContain('role="group" aria-label="Conversation views"');
    expect(html).toContain('aria-pressed="true"');
    expect(html).toContain(">Archived</button>");
  });

  it("does not describe a failed conversation load as a successfully empty collection", () => {
    const html = renderToStaticMarkup(
      <ConversationList
        conversations={[]}
        activeConversationId={null}
        onNewChat={() => undefined}
        onSelect={() => undefined}
        conversationsLoading={false}
        conversationLoadError="Unable to load conversations."
      />,
    );
    expect(html).toContain("Unable to load conversations.");
    expect(html).not.toContain("No active conversations");
  });

  it("labels the sidebar search and exposes an accessible clear action", () => {
    const html = renderToStaticMarkup(
      <ConversationList
        conversations={[]}
        activeConversationId={null}
        onNewChat={() => undefined}
        onSelect={() => undefined}
        searchQuery="arch"
        onSearchChange={() => undefined}
      />,
    );
    expect(html).toContain('aria-label="Search conversations"');
    expect(html).toContain('aria-label="Clear conversation search"');
    expect(html).toContain("bg-background");
    expect(html).toContain("text-foreground");
  });

  it("distinguishes a search miss from an account with no conversations", () => {
    const html = renderToStaticMarkup(
      <ConversationList
        conversations={[]}
        activeConversationId={null}
        onNewChat={() => undefined}
        onSelect={() => undefined}
        searchQuery="architecture"
        onSearchChange={() => undefined}
      />,
    );
    expect(html).toContain('No conversations found for “architecture”.');
    expect(html).not.toContain("No conversations yet");
  });

  it("renders conversation titles from real state", () => {
    const html = renderToStaticMarkup(
      <ConversationList
        conversations={conversations}
        activeConversationId={null}
        onNewChat={() => undefined}
        onSelect={() => undefined}
      />,
    );
    expect(html).toContain(">Explain robot zoning</span>");
    expect(html).toContain(">Plan the deployment</span>");
  });

  it("shows a compact accessible indicator for a conversation with an active backend run", () => {
    const html = renderToStaticMarkup(
      <ConversationList
        conversations={[
          {
            id: "a",
            title: "Generating response",
            messages: [],
            run: {
              runId: "run-a",
              backendStatus: "running",
              uiPhase: "running",
              runError: null,
              pendingMessageId: "message-a",
              runEpoch: "epoch-a",
            },
          },
        ]}
        activeConversationId="a"
        onNewChat={() => undefined}
        onSelect={() => undefined}
      />,
    );

    expect(html).toContain('aria-label="Response in progress"');
    expect(html).toContain('data-conversation-run-indicator="active"');
    expect(html).toContain("lucide-loader-circle");
    expect(html).toContain("animate-spin");
  });

  it("removes the row indicator when the backend reports a terminal run", () => {
    const terminalStatuses = ["completed", "failed", "cancelled"] as const;
    const html = renderToStaticMarkup(
      <ConversationList
        conversations={terminalStatuses.map((status) => ({
          id: status,
          title: `${status} response`,
          messages: [],
          run: {
            runId: `run-${status}`,
            backendStatus: status,
            uiPhase: status,
            runError: null,
            pendingMessageId: null,
            runEpoch: `epoch-${status}`,
          },
        }))}
        activeConversationId="a"
        onNewChat={() => undefined}
        onSelect={() => undefined}
      />,
    );

    expect(html.match(/data-conversation-run-indicator="idle"/g)).toHaveLength(3);
    expect(html).not.toContain('aria-label="Response in progress"');
    expect(html).not.toContain("animate-spin");
  });

  it("shows a background conversation's active run independently from selection", () => {
    const html = renderToStaticMarkup(
      <ConversationList
        conversations={[
          {
            id: "a",
            title: "Background response",
            messages: [],
            run: {
              runId: "run-a",
              backendStatus: "waiting_for_approval",
              uiPhase: "running",
              runError: null,
              pendingMessageId: "message-a",
              runEpoch: "epoch-a",
            },
          },
          { id: "b", title: "Selected conversation", messages: [] },
        ]}
        activeConversationId="b"
        onNewChat={() => undefined}
        onSelect={() => undefined}
      />,
    );

    const backgroundRowStart = html.indexOf('data-conversation-row="a"');
    const selectedRowStart = html.indexOf('data-conversation-row="b"');
    expect(html.slice(backgroundRowStart, selectedRowStart)).toContain('aria-label="Response in progress"');
    expect(html).toContain('data-conversation-item="b" aria-current="true"');
  });

  it("shows a recovered active run from conversation state", () => {
    const recovered = {
      id: "a",
      title: "Recovered response",
      messages: [],
      run: {
        runId: "run-a",
        backendStatus: "pending" as const,
        uiPhase: "running" as const,
        runError: null,
        pendingMessageId: "message-a",
        runEpoch: "recovered-epoch",
      },
    };
    const html = renderToStaticMarkup(
      <ConversationList
        conversations={[recovered]}
        activeConversationId={null}
        onNewChat={() => undefined}
        onSelect={() => undefined}
      />,
    );

    expect(html).toContain('data-conversation-run-indicator="active"');
    expect(html).toContain('aria-label="Response in progress"');
  });

  it("truncates long row titles while keeping the active-run and action slots fixed", () => {
    const longTitle = "Long conversation title ".repeat(20);
    const html = renderToStaticMarkup(
      <ConversationList
        conversations={[{
          id: "long",
          title: longTitle,
          messages: [],
          run: {
            runId: "run-long",
            backendStatus: "running",
            uiPhase: "running",
            runError: null,
            pendingMessageId: "message-long",
            runEpoch: "epoch-long",
          },
        }]}
        activeConversationId={null}
        onNewChat={() => undefined}
        onSelect={() => undefined}
        onRename={async () => undefined}
      />,
    );

    expect(html).toContain('data-conversation-title="" style="flex:1 1 0%;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"');
    expect(html).toContain('data-conversation-run-indicator="active"');
    expect(html).toContain('data-conversation-actions=""');
    expect(html).toContain("lucide-loader-circle");
    expect(html).toContain("flex shrink-0 pointer-events-none opacity-0");
    expect(html).not.toContain("overflow-x-auto");
  });

  it("keeps inactive row actions visually hidden until hover or focus", () => {
    const html = renderToStaticMarkup(
      <ConversationList
        conversations={conversations}
        activeConversationId={null}
        onNewChat={() => undefined}
        onSelect={() => undefined}
        onRename={async () => undefined}
      />,
    );

    expect(html).toContain("pointer-events-none opacity-0");
    expect(html).toContain("group-hover:pointer-events-auto");
    expect(html).toContain("group-hover:opacity-100");
    expect(html).toContain("group-focus-within:opacity-100");
  });

  it("marks the active conversation selection beyond color", () => {
    const html = renderToStaticMarkup(
      <ConversationList
        conversations={conversations}
        activeConversationId="b"
        onNewChat={() => undefined}
        onSelect={() => undefined}
      />,
    );
    expect(html).toContain('aria-current="true"');
    expect(html).not.toContain('aria-current="true" aria-current=""');
  });
});
