import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../types";
import { MessageList } from "./MessageList";

const messages: ConversationMessage[] = [
  { id: "a", role: "user", content: "One" },
  { id: "b", role: "assistant", status: "complete", content: "Two" },
  { id: "c", role: "user", content: "Three" },
];

describe("MessageList", () => {
  it("preserves message order", () => {
    const html = renderToStaticMarkup(<MessageList messages={messages} />);
    const first = html.indexOf("One");
    const second = html.indexOf("Two");
    const third = html.indexOf("Three");
    expect(first).toBeGreaterThanOrEqual(0);
    expect(second).toBeGreaterThan(first);
    expect(third).toBeGreaterThan(second);
  });

  it("marks user and assistant roles in the DOM", () => {
    const html = renderToStaticMarkup(<MessageList messages={messages} />);
    expect(html).toContain('data-message-role="user"');
    expect(html).toContain('data-message-role="assistant"');
  });

  it("renders user message bubbles with role attribute", () => {
    const html = renderToStaticMarkup(<MessageList messages={messages} />);
    expect(html).toContain('data-message-bubble="user"');
  });

  it("renders a system message subtly", () => {
    const html = renderToStaticMarkup(
      <MessageList
        messages={[{ id: "s", role: "system", content: "System note" }]}
      />,
    );
    expect(html).toContain('data-message-role="system"');
    expect(html).toContain("System note");
  });

  it("keeps user bubbles naturally sized and rectangular for short and long prompts", () => {
    const long = "A".repeat(500);
    const markdown = "# Heading\n\n- first bullet\n- second bullet\n\nA second paragraph.";
    const html = renderToStaticMarkup(
      <MessageList
        messages={[
          { id: "short", role: "user", content: "Hello" },
          { id: "medium", role: "user", content: "A few sentences make a medium length prompt." },
          { id: "long", role: "user", content: `${long}\n\n${long}` },
          { id: "markdown", role: "user", content: markdown },
          { id: "a", role: "assistant", status: "complete", content: long },
        ]}
      />,
    );
    expect(html).toContain("overflow-wrap:break-word");
    expect(html).toContain("width:fit-content");
    expect(html).toContain("max-width:68%");
    expect(html).toContain("max-width:85%");
    expect(html).toContain("border-radius:8px");
    expect(html).not.toContain("border-radius:999px");
    expect(html).toContain("white-space:pre-wrap");
    expect(html).toContain("# Heading");
    expect(html).toContain("second paragraph.");
  });

  it("hides retry/regenerate actions when phase is active", () => {
    const html = renderToStaticMarkup(
      <MessageList
        messages={[{ id: "a", role: "assistant", status: "pending", content: "" }]}
        runPhase="running"
      />,
    );
    expect(html).toContain("AVA is responding…");
    expect(html).not.toContain('aria-label="Retry response"');
    expect(html).not.toContain('aria-label="Regenerate response"');
  });
});
