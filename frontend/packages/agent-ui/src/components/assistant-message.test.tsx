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

  it("offers Settings only for a classified configuration failure", () => {
    const actionable = renderToStaticMarkup(
      <AssistantMessage status="failed" content="" errorCode="model_unavailable" onOpenSettings={() => undefined} />,
    );
    const generic = renderToStaticMarkup(
      <AssistantMessage status="failed" content="" errorCode="agent_failed" onOpenSettings={() => undefined} />,
    );
    // The action names its destination, so the user knows what to fix.
    expect(actionable).toContain('aria-label="Open Model Settings"');
    expect(generic).not.toContain('aria-label="Open Model Settings"');
    expect(generic).not.toContain("Settings");
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

  it("renders incomplete partial text in the existing streaming bubble", () => {
    const html = renderToStaticMarkup(
      <AssistantMessage status="streaming" content={"**bold\n`code\n[link\nこんにちは🙂"} />,
    );
    expect(html).toContain('data-message-state="streaming"');
    expect(html).toContain("**bold");
    expect(html).toContain("こんにちは🙂");
  });

  it("retains partial text after failure or cancellation", () => {
    for (const status of ["failed", "cancelled"] as const) {
      const html = renderToStaticMarkup(
        <AssistantMessage status={status} content="partial answer" />,
      );
      expect(html).toContain("partial answer");
    }
  });

  it("uses overflow-wrap to prevent horizontal overflow in the bubble", () => {
    const html = renderToStaticMarkup(
      <AssistantMessage status="complete" content="Hi" />,
    );
    expect(html).toContain("overflow-wrap:break-word");
  });
});

/**
 * What the user actually sees for each classified failure.
 *
 * The presentation map is unit-tested on its own; this asserts the component
 * honors it — the right title, a Retry action only where retrying can help, a
 * Settings action only where there is configuration to fix, and streamed
 * partial content that survives the failure.
 */
describe("classified failures render their own title and actions", () => {
  const render = (errorCode: string, content = "") =>
    renderToStaticMarkup(
      <AssistantMessage
        status="failed"
        content={content}
        errorCode={errorCode}
        error="The provider request was rejected."
        onRetry={() => undefined}
        onOpenSettings={() => undefined}
      />,
    );

  it.each([
    ["model_unavailable", "Model unavailable"],
    ["provider_connection_unavailable", "Provider unavailable"],
    ["provider_timeout", "Model request timed out"],
    ["provider_rate_limited", "Provider rate limit reached"],
    ["provider_authentication_failed", "Provider authentication failed"],
    ["provider_response_invalid", "Invalid provider response"],
    ["context_window_exceeded", "Conversation too large for this model"],
    ["runtime_unavailable", "Runtime unavailable"],
    ["credential_unavailable", "Provider credentials unavailable"],
    ["configuration_missing", "Execution configuration missing"],
    ["configuration_invalid", "Invalid execution configuration"],
    ["agent_failed", "Failed to generate response"],
  ])("titles %s specifically", (errorCode, title) => {
    expect(render(errorCode)).toContain(title);
  });

  it.each([
    ["model_unavailable", "Open Model Settings"],
    ["provider_connection_unavailable", "Open Provider Settings"],
    ["provider_authentication_failed", "Open Provider Settings"],
    ["credential_unavailable", "Open Provider Settings"],
    ["runtime_unavailable", "Open Runtime Settings"],
    ["configuration_missing", "Open Default Settings"],
  ])("sends %s to the right Settings section", (errorCode, label) => {
    expect(render(errorCode)).toContain(`aria-label="${label}"`);
  });

  it.each([["provider_rate_limited"], ["provider_response_invalid"], ["agent_failed"], ["execution_interrupted"]])(
    "offers no Settings detour for %s",
    (errorCode) => {
      expect(render(errorCode)).not.toContain("Settings");
    },
  );

  it.each([["provider_timeout"], ["provider_rate_limited"], ["model_unavailable"], ["provider_connection_unavailable"]])(
    "offers Retry for %s",
    (errorCode) => {
      expect(render(errorCode)).toContain('aria-label="Retry response"');
    },
  );

  it.each([["context_window_exceeded"], ["configuration_invalid"], ["provider_authentication_failed"]])(
    "hides Retry for %s, where an identical retry cannot help",
    (errorCode) => {
      expect(render(errorCode)).not.toContain('aria-label="Retry response"');
    },
  );

  it("keeps streamed partial content alongside the failure", () => {
    const html = render("provider_timeout", "Here is the first part of the answer");
    expect(html).toContain("Here is the first part of the answer");
    expect(html).toContain("Model request timed out");
    // And the underlying provider text stays visible only as the backend's safe wording.
    expect(html).toContain("The provider request was rejected.");
  });

  it("renders an unknown code with the generic title rather than an empty one", () => {
    const html = render("a_code_from_the_future");
    expect(html).toContain("Failed to generate response");
  });

  it("does not render a failed title for a cancelled message", () => {
    const html = renderToStaticMarkup(<AssistantMessage status="cancelled" content="partial" />);
    expect(html).toContain('data-message-state="cancelled"');
    expect(html).toContain("Response stopped");
    expect(html).not.toContain("Failed to generate response");
  });
});
