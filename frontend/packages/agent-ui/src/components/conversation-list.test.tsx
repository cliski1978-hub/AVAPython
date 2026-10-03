import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ConversationList } from "./ConversationList";

const conversations = [
  { id: "a", title: "Explain robot zoning", messages: [] },
  { id: "b", title: "Plan the deployment", messages: [] },
];

describe("ConversationList", () => {
  it("provides a New Chat action", () => {
    const html = renderToStaticMarkup(
      <ConversationList
        conversations={[]}
        activeConversationId={null}
        onNewChat={() => undefined}
        onSelect={() => undefined}
      />,
    );
    expect(html).toContain("New Chat");
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
