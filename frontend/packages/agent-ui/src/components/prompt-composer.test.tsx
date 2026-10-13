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
    expect(html).toContain('class="box-border');
  });

  it("shows Send when idle and not running", () => {
    const html = renderToStaticMarkup(
      <PromptComposer onSubmit={noop} onStop={noop} />,
    );
    expect(html).toContain('aria-label="Send"');
    expect(html).toContain("bg-primary");
    expect(html).toContain("text-primary-foreground");
    expect(html).not.toContain('aria-label="Stop"');
  });

  it("themes the composer shell and message entry with AVA semantic tokens", () => {
    const html = renderToStaticMarkup(<PromptComposer onSubmit={noop} onStop={noop} />);
    expect(html).toContain("bg-card");
    expect(html).toContain("text-card-foreground");
    expect(html).toContain("text-foreground");
    expect(html).toContain("placeholder:text-muted-foreground");
  });

  it("shows Stop instead of Send while running", () => {
    const html = renderToStaticMarkup(
      <PromptComposer onSubmit={noop} onStop={noop} isRunning />,
    );
    expect(html).toContain('aria-label="Stop"');
    expect(html).toContain("<svg");
    expect(html).not.toContain('aria-label="Send"');
  });

  it("shows a disabled Stop with Starting status while the run id is being created", () => {
    const html = renderToStaticMarkup(
      <PromptComposer onSubmit={noop} onStop={noop} isStarting />,
    );
    expect(html).toContain('aria-label="Stop"');
    expect(html).toContain('disabled=""');
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
    expect(html).toContain('data-composer-status=""');
    expect(html).toContain("Stopping…");
    expect(html).not.toContain('aria-label="Send"');
    expect(html).not.toContain('aria-label="Attach file"');
  });

  it("disables Send when the prompt has no meaningful content", () => {
    const html = renderToStaticMarkup(
      <PromptComposer onSubmit={noop} onStop={noop} />,
    );
    expect(countDisabled(html)).toBe(1);
  });

  it("enables Send when controlled content is meaningful", () => {
    const html = renderToStaticMarkup(
      <PromptComposer value="hello" onSubmit={noop} onStop={noop} />,
    );
    expect(html).toContain('aria-label="Send"');
    expect(countDisabled(html)).toBe(0);
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
    expect(countDisabled(html)).toBe(2);
  });

  it("disables Stop as well when disabled while running", () => {
    const html = renderToStaticMarkup(
      <PromptComposer onSubmit={noop} onStop={noop} isRunning disabled />,
    );
    expect(html).toContain('aria-label="Stop"');
    expect(countDisabled(html)).toBe(2);
  });

  it("shows the attachment affordance only when a conversation upload action exists", () => {
    const html = renderToStaticMarkup(
      <PromptComposer onSubmit={noop} onStop={noop} />,
    );
    expect(html).not.toContain('aria-label="Attach files"');
    const withAttachments = renderToStaticMarkup(
      <PromptComposer onSubmit={noop} onStop={noop} onUploadAttachment={async () => undefined} />,
    );
    expect(withAttachments).toContain('aria-label="Attach files"');
  });

  it("renders conversation attachment names, sizes, and the current context limitation", () => {
    const html = renderToStaticMarkup(
      <PromptComposer
        onSubmit={noop}
        onStop={noop}
        onUploadAttachment={async () => undefined}
        onRemoveAttachment={async () => undefined}
        attachments={[{
          attachment_id: "attachment-1",
          file_name: "notes.md",
          media_type: "text/markdown",
          size_bytes: 14 * 1024,
          owner_type: "conversation",
          owner_id: "conversation-1",
          status: "available",
          created_at: "2026-10-06T00:00:00Z",
          contract_version: "v1",
        }]}
      />,
    );
    expect(html).toContain("notes.md");
    expect(html).toContain("14 KB");
    expect(html).toContain("Supported text files are included when they fit the model context.");
    expect(html).toContain('aria-label="Remove notes.md"');
  });

  it("keeps execution selectors out of the resting composer", () => {
    const controls = <div>
      <select aria-label="Select profile" />
      <select aria-label="Select runtime" />
      <select aria-label="Select model" />
      <select aria-label="Select workspace" />
    </div>;
    const html = renderToStaticMarkup(
      <PromptComposer controls={controls} executionSummary="Qwen 3" onSubmit={noop} onStop={noop} />,
    );
    expect(html).toContain("Qwen 3");
    expect(html).toContain('aria-haspopup="dialog"');
    expect(html).toContain("dark:bg-black");
    expect(html).toContain("dark:text-white");
    expect(html).not.toContain("<select");
    expect(html).not.toContain('data-execution-settings-popover');
  });

  it("uses a wide, unified surface with a lower action row", () => {
    const html = renderToStaticMarkup(<PromptComposer onSubmit={noop} onStop={noop} />);
    expect(html).toContain("w-full rounded-3xl");
    expect(html).toContain("focus-within:ring-2");
    expect(html).toContain("min-h-12 items-center justify-between");
    expect(html).toContain('aria-label="Send"');
  });
});

it("uses authoritative preview outcomes for compact stored attachment statuses", () => {
  const statuses = ["included", "unsupported", "extraction_failed", "excluded_context_limit"] as const;
  const html = renderToStaticMarkup(<PromptComposer onSubmit={noop} onStop={noop} onUploadAttachment={async () => undefined}
    attachments={statuses.map((status, i) => ({ attachment_id: `file-${i}`, file_name: `${status}.md`, media_type: "text/markdown", size_bytes: 100, owner_type: "conversation", owner_id: "c", status: "available", created_at: "2026-10-09T00:00:00Z", contract_version: "v1" }))}
    attachmentContext={statuses.map((status, i) => ({ attachment_id: `file-${i}`, file_name: `${status}.md`, media_type: "text/markdown", status, included: status === "included", token_count: 93, count_accuracy: "estimated", text: null, error_code: null, error_message: "INTERNAL STORAGE DETAILS" }))} />);
  expect(html).toContain("Ready for context");
  expect(html).toContain("Stored · text unsupported");
  expect(html).toContain("Stored · extraction failed");
  expect(html).toContain("Stored · context limit");
  expect(html).not.toContain("INTERNAL STORAGE DETAILS");
});

it("does not claim stored files are ready until backend context is checked", () => {
  const html = renderToStaticMarkup(<PromptComposer onSubmit={noop} onStop={noop} onUploadAttachment={async () => undefined}
    attachments={[{ attachment_id: "a", file_name: "SKILL.md", media_type: "text/markdown", size_bytes: 4, owner_type: "conversation", owner_id: "c", status: "available", created_at: "2026-10-09T00:00:00Z", contract_version: "v1" }]} />);
  expect(html).toContain("Stored · context not checked");
  expect(html).not.toContain("Ready for context");
});
