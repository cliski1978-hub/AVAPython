import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ConversationView } from "./ConversationView";

describe("ConversationView", () => {
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
