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
      <MessageActions content="text" showRegenerate />,
    );
    expect(html).toContain('aria-label="Regenerate response"');
    expect(html).toContain('disabled=""');
    expect(html).toContain('title="Regenerate response"');
  });
});