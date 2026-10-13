import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { EmptyState } from "./EmptyState";

describe("EmptyState", () => {
  it("renders the title and description", () => {
    const html = renderToStaticMarkup(
      <EmptyState
        title="No conversations"
        description="Start a new chat to get going."
      />,
    );
    expect(html).toContain(">No conversations</h3>");
    expect(html).toContain("Start a new chat to get going.");
    expect(html).toContain('class="text-foreground"');
    expect(html).toContain('class="text-muted-foreground"');
  });

  it("renders the optional action slot", () => {
    const html = renderToStaticMarkup(
      <EmptyState
        title="Empty"
        action={<button type="button">New chat</button>}
      />,
    );
    expect(html).toContain(">New chat</button>");
  });

  it("renders the optional visual slot", () => {
    const html = renderToStaticMarkup(
      <EmptyState title="Empty" visual={<span>logo</span>} />,
    );
    expect(html).toContain("logo");
  });
});
