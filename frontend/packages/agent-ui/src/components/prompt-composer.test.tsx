import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { PromptComposer } from "./PromptComposer";

function countDisabled(html: string): number {
  return html.split('disabled=""').length - 1;
}

const noop = () => undefined;

describe("PromptComposer", () => {
  it("renders a message textarea with an accessible label and placeholder", () => {
    const html = renderToStaticMarkup(
      <PromptComposer
        onSubmit={noop}
        onStop={noop}
        placeholder="Ask AVA anything..."
      />,
    );
    expect(html).toContain("<textarea");
    expect(html).toContain('aria-label="Message"');
    expect(html).toContain('placeholder="Ask AVA anything..."');
  });

  it("shows Send when idle and not running", () => {
    const html = renderToStaticMarkup(
      <PromptComposer onSubmit={noop} onStop={noop} />,
    );
    expect(html).toContain('aria-label="Send"');
    expect(html).toContain(">↑</span>");
    expect(html).not.toContain('aria-label="Stop"');
  });

  it("shows Stop instead of Send while running", () => {
    const html = renderToStaticMarkup(
      <PromptComposer onSubmit={noop} onStop={noop} isRunning />,
    );
    expect(html).toContain('aria-label="Stop"');
    expect(html).toContain(">Stop</span>");
    expect(html).not.toContain('aria-label="Send"');
  });

  it("shows a disabled Stop with Starting status while the run id is being created", () => {
    const html = renderToStaticMarkup(
      <PromptComposer onSubmit={noop} onStop={noop} isStarting />,
    );
    expect(html).toContain('aria-label="Stop"');
    expect(html).toContain('disabled=""');
    expect(html).toContain(">Stop</span>");
    expect(html).toContain('data-composer-status=""');
    expect(html).toContain("Starting…");
    expect(html).not.toContain('aria-label="Send"');
    expect(html).not.toContain('aria-label="Attach file"');
  });

  it("shows a disabled Stop with Stopping status while a cancel is in flight", () => {
    const html = renderToStaticMarkup(
      <PromptComposer onSubmit={noop} onStop={noop} isStopping />,
    );
    expect(html).toContain('aria-label="Stop"');
    expect(html).toContain('disabled=""');
    expect(html).toContain(">Stop</span>");
    expect(html).toContain('data-composer-status=""');
    expect(html).toContain("Stopping…");
    expect(html).not.toContain('aria-label="Send"');
    expect(html).not.toContain('aria-label="Attach file"');
  });

  it("disables Send when the prompt has no meaningful content", () => {
    const html = renderToStaticMarkup(
      <PromptComposer onSubmit={noop} onStop={noop} />,
    );
    expect(countDisabled(html)).toBe(2);
  });

  it("enables Send when controlled content is meaningful", () => {
    const html = renderToStaticMarkup(
      <PromptComposer value="hello" onSubmit={noop} onStop={noop} />,
    );
    expect(html).toContain(">↑</span>");
    expect(countDisabled(html)).toBe(1);
  });

  it("reflects a controlled value in the textarea", () => {
    const html = renderToStaticMarkup(
      <PromptComposer value="typed text" onSubmit={noop} onStop={noop} />,
    );
    expect(html).toContain(">typed text</textarea>");
  });

  it("exposes real disabled semantics for the whole composer", () => {
    const html = renderToStaticMarkup(
      <PromptComposer onSubmit={noop} onStop={noop} disabled />,
    );
    expect(countDisabled(html)).toBe(3);
  });

  it("disables Stop as well when disabled while running", () => {
    const html = renderToStaticMarkup(
      <PromptComposer onSubmit={noop} onStop={noop} isRunning disabled />,
    );
    expect(html).toContain('aria-label="Stop"');
    expect(countDisabled(html)).toBe(3);
  });

  it("provides an accessible, non-functional attachment affordance", () => {
    const html = renderToStaticMarkup(
      <PromptComposer onSubmit={noop} onStop={noop} />,
    );
    expect(html).toContain('aria-label="Attach file"');
    expect(html).toContain('title="Attachments are not available yet"');
  });
});
