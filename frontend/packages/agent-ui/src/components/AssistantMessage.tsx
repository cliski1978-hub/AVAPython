import { defaultTheme, LoadingIndicator, StatusIndicator } from "@ava/ui-core";
import type { CSSProperties } from "react";
import type { MessageStatus } from "../types";
import { MessageActions } from "./MessageActions";

export interface AssistantMessageProps {
  content: string;
  status: MessageStatus;
  /** User-readable failure detail to show when status is "failed". */
  error?: string;
  /** Retry a failed/cancelled response from its source prompt. */
  onRetry?: () => void;
  /** Regenerate a completed response from its source prompt. */
  onRegenerate?: () => void;
  /** Progress label shown while a run is active (starting/stopping/pending). */
  progressLabel?: string;
}

const t = defaultTheme;

/** Rounded assistant bubble. Wider than the user pill (up to 85%) so long
 * technical answers stay readable, with the same treatment across
 * complete / pending / failed / cancelled states. Never a full-bleed strip. */
const bubbleStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: t.spacing.sm,
  alignSelf: "flex-start",
  maxWidth: "85%",
  minWidth: 0,
  boxSizing: "border-box",
  background: t.colors.surface,
  border: `${t.border.width}px solid ${t.colors.borderStrong}`,
  borderRadius: t.radius.lg + 12,
  padding: "12px 14px",
  overflowWrap: "break-word",
};

function bodyStyle(): CSSProperties {
  return {
    whiteSpace: "pre-wrap",
    lineHeight: 1.6,
    fontSize: t.font.sizeMd,
    color: t.colors.foreground,
    overflowWrap: "break-word",
  };
}

/**
 * Shared assistant message. Renders a distinct representation per status
 * (complete / pending / failed / cancelled) with text labels so state is
 * understandable without color alone.
 */
export function AssistantMessage({
  content,
  status,
  error,
  onRetry,
  onRegenerate,
  progressLabel = "AVA is responding…",
}: AssistantMessageProps) {
  if (status === "pending") {
    return (
      <div
        data-message-role="assistant"
        data-message-state="pending"
        aria-live="polite"
        style={bubbleStyle}
      >
        <LoadingIndicator label={progressLabel} />
        {content.length > 0 && <div style={bodyStyle()}>{content}</div>}
      </div>
    );
  }

  if (status === "failed") {
    return (
      <div
        data-message-role="assistant"
        data-message-state="failed"
        style={bubbleStyle}
      >
        {content.length > 0 && <div style={bodyStyle()}>{content}</div>}
        <StatusIndicator state="error" label="Failed to generate response" />
        {error != null && error.length > 0 && (
          <div
            data-testid="assistant-message-error"
            style={{
              whiteSpace: "pre-wrap",
              lineHeight: 1.5,
              fontSize: t.font.sizeSm,
              color: t.colors.mutedText,
              overflowWrap: "break-word",
            }}
          >
            {error}
          </div>
        )}
        <MessageActions
          content={content}
          canCopy={content.length > 0}
          showRetry
          onRetry={onRetry}
        />
      </div>
    );
  }

  if (status === "cancelled") {
    return (
      <div
        data-message-role="assistant"
        data-message-state="cancelled"
        style={bubbleStyle}
      >
        {content.length > 0 && <div style={bodyStyle()}>{content}</div>}
        <StatusIndicator state="neutral" label="Response stopped" />
        <MessageActions
          content={content}
          canCopy={content.length > 0}
          showRetry
          onRetry={onRetry}
        />
      </div>
    );
  }

  return (
    <div
      data-message-role="assistant"
      data-message-state="complete"
      style={bubbleStyle}
    >
      <div style={bodyStyle()}>{content}</div>
      <MessageActions
        content={content}
        canCopy
        showRegenerate
        onRegenerate={onRegenerate}
      />
    </div>
  );
}