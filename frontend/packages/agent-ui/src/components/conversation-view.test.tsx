import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ConversationView } from "./ConversationView";

describe("ConversationView", () => {
  it("renders the empty/welcome state when there are no messages", () => {
    const html = renderToStaticMarkup(
      <ConversationView
        conversation={{ id: "c", title: "New Conversation", messages: [] }}
      />,
    );
    expect(html).toContain(">AVA</h3>");
    expect(html).toContain("How can I help?");
    const first = html.indexOf("Explain a technical concept");
    const second = html.indexOf("Summarize a document");
    const third = html.indexOf("Help me solve an engineering problem");
    expect(first).toBeGreaterThan(-1);
    expect(second).toBeGreaterThan(first);
    expect(third).toBeGreaterThan(second);
  });

  it("renders a populated conversation with its header title", () => {
    const html = renderToStaticMarkup(
      <ConversationView
        conversation={{
          id: "c",
          title: "My Conversation",
          messages: [
            { id: "a", role: "user", content: "Hello" },
            { id: "b", role: "assistant", status: "complete", content: "Hi" },
          ],
        }}
      />,
    );
    expect(html).toContain(">My Conversation</h2>");
    expect(html).toContain("Hello");
    expect(html).toContain("Hi");
    expect(html).not.toContain("How can I help?");
  });

  it("renders only the active regenerated assistant response for a turn", () => {
    const html = renderToStaticMarkup(
      <ConversationView
        conversation={{
          id: "c",
          title: "Regenerated Chat",
          messages: [
            { id: "u1", role: "user", content: "Hello" },
            { id: "a1", role: "assistant", status: "complete", content: "AVA First" },
            { id: "a2", role: "assistant", status: "complete", content: "AVA Second" },
          ],
        }}
      />,
    );
    expect(html).toContain("AVA Second");
    expect(html).not.toContain("AVA First");
    expect(html).toContain("Hello");
  });

  it("renders the active response per turn, keeping both turns when two exist", () => {
    const html = renderToStaticMarkup(
      <ConversationView
        conversation={{
          id: "c",
          title: "Two Turns",
          messages: [
            { id: "u1", role: "user", content: "Hello" },
            { id: "a1", role: "assistant", status: "complete", content: "First A" },
            { id: "a2", role: "assistant", status: "complete", content: "First B" },
            { id: "u2", role: "user", content: "Again" },
            { id: "b1", role: "assistant", status: "complete", content: "Second A" },
          ],
        }}
      />,
    );
    expect(html).toContain("First B");
    expect(html).not.toContain("First A");
    expect(html).toContain("Second A");
    expect(html).toContain("Again");
  });
});