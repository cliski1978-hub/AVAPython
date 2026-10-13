import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ConversationView } from "./ConversationView";

describe("ConversationView", () => {
  it("uses semantic canvas and title colors instead of a fixed light surface", () => {
    const html = renderToStaticMarkup(<ConversationView title="New Conversation" />);
    expect(html).toContain("bg-background text-foreground");
    expect(html).toContain("border-border bg-background text-foreground");
    expect(html).not.toContain("linear-gradient(180deg, #f9fafb");
  });

  it("shows the AVA brand image in the new-conversation hero", () => {
    const html = renderToStaticMarkup(<ConversationView title="New Conversation" />);
    expect(html).toContain('data-ava-hero=""');
    expect(html).toContain('alt="AVA"');
    expect(html).toContain("How can I help?");
  });

  it("renders a localized conversation load failure with a retry action", () => {
    const html = renderToStaticMarkup(
      <ConversationView
        title="Conversation"
        error="Unable to load this conversation."
        onReload={() => undefined}
      />,
    );

    expect(html).toContain('data-conversation-error=""');
    expect(html).toContain('role="alert"');
    expect(html).toContain("Unable to load this conversation.");
    expect(html).toContain("Retry");
  });
});
