import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { MessageActions } from "./MessageActions";

describe("MessageActions", () => {
  it("exposes a copy action for copyable content with a label", () => {
    const html = renderToStaticMarkup(
      <MessageActions content="text" canCopy />,
    );
    expect(html).toContain('aria-label="Copy message"');
    expect(html).toContain('title="Copy message to clipboard"');
  });

  it("hides the copy action when canCopy is false", () => {
    const html = renderToStaticMarkup(<MessageActions content="text" />);
    expect(html).not.toContain('aria-label="Copy message"');
  });

  it("renders the retry placeholder disabled when no handler exists", () => {
    const html = renderToStaticMarkup(
      <MessageActions content="text" showRetry />,
    );
    expect(html).toContain('aria-label="Retry response"');
    expect(html).toContain('disabled=""');
    expect(html).toContain('title="Retry not available"');
  });

  it("renders the regenerate action when showRegenerate is true", () => {
    const html = renderToStaticMarkup(
      <MessageActions content="text" showRegenerate onRegenerate={() => {}} />,
    );
    expect(html).toContain('aria-label="Regenerate response"');
    expect(html).not.toContain('disabled=""');
    expect(html).toContain('title="Regenerate response"');
  });

  it("says why regenerate is unavailable when no handler is wired", () => {
    const html = renderToStaticMarkup(
      <MessageActions content="text" showRegenerate />,
    );
    expect(html).toContain('disabled=""');
    expect(html).toContain('title="Regenerate not available"');
  });

  it("disables both attempt actions while a run owns the conversation", () => {
    const html = renderToStaticMarkup(
      <MessageActions
        content="text"
        showRetry
        showRegenerate
        onRetry={() => {}}
        onRegenerate={() => {}}
        retryDisabled
        regenerateDisabled
      />,
    );
    expect(html.match(/disabled=""/g)).toHaveLength(2);
    expect(html).toContain('title="Retry not available"');
    expect(html).toContain('title="Regenerate not available"');
  });
});