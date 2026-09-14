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

  it("shows a hint when there are no conversations", () => {
    const html = renderToStaticMarkup(
      <ConversationList
        conversations={[]}
        activeConversationId={null}
        onNewChat={() => undefined}
        onSelect={() => undefined}
      />,
    );
    expect(html).toContain("No conversations yet");
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