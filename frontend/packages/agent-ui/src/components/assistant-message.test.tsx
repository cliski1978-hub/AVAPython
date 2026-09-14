import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AssistantMessage } from "./AssistantMessage";

describe("AssistantMessage", () => {
  it("renders complete content with the completed state in a bubble", () => {
    const html = renderToStaticMarkup(
      <AssistantMessage status="complete" content="Here is the answer." />,
    );
    expect(html).toContain('data-message-state="complete"');
    expect(html).toContain("Here is the answer.");
    expect(html).toContain("aria-label=\"Regenerate response\"");
    expect(html).toContain("aria-label=\"Copy message\"");
    expect(html).toContain("max-width:85%");
    expect(html).toContain("border-radius:20px");
  });

  it("renders a subtle pending/working state", () => {
    const html = renderToStaticMarkup(
      <AssistantMessage status="pending" content="" />,
    );
    expect(html).toContain('data-message-state="pending"');
    expect(html).toContain("AVA is responding…");
    expect(html).toContain('role="status"');
  });

  it("renders a custom progress label in the pending state", () => {
    const html = renderToStaticMarkup(
      <AssistantMessage status="pending" content="" progressLabel="AVA is working…" />,
    );
    expect(html).toContain("AVA is working…");
    expect(html).not.toContain("AVA is responding…");
  });

  it("renders a clear failed state with a retry slot", () => {
    const html = renderToStaticMarkup(
      <AssistantMessage status="failed" content="oops" />,
    );
    expect(html).toContain('data-message-state="failed"');
    expect(html).toContain("Failed to generate response");
    expect(html).toContain('aria-label="Retry response"');
  });

  it("renders the user-readable error in the failed state", () => {
    const html = renderToStaticMarkup(
      <AssistantMessage
        status="failed"
        content=""
        error="AVA is unavailable. Please try again."
      />,
    );
    expect(html).toContain("Failed to generate response");
    expect(html).toContain("AVA is unavailable. Please try again.");
  });

  it("keeps the error text out of non-failed states", () => {
    const html = renderToStaticMarkup(
      <AssistantMessage status="pending" content="" error="should not show" />,
    );
    expect(html).not.toContain("should not show");
    expect(html).not.toContain("Failed to generate response");
  });

  it("renders a cancelled/stopped state", () => {
    const html = renderToStaticMarkup(
      <AssistantMessage status="cancelled" content="" />,
    );
    expect(html).toContain('data-message-state="cancelled"');
    expect(html).toContain("Response stopped");
    expect(html).toContain('aria-label="Retry response"');
  });

  it("does not show actions during the pending state", () => {
    const html = renderToStaticMarkup(
      <AssistantMessage status="pending" content="partial" />,
    );
    expect(html).not.toContain("aria-label=\"Copy message\"");
    expect(html).not.toContain('aria-label="Retry response"');
  });

  it("uses overflow-wrap to prevent horizontal overflow in the bubble", () => {
    const html = renderToStaticMarkup(
      <AssistantMessage status="complete" content="Hi" />,
    );
    expect(html).toContain("overflow-wrap:break-word");
  });
});
