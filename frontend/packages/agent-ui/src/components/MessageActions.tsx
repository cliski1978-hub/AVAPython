import { defaultTheme, IconButton } from "@ava/ui-core";
import { copyTextToClipboard } from "../lib/clipboard";

export interface MessageActionsProps {
  /** Content copied when the copy action is used. */
  content: string;
  canCopy?: boolean;
  onCopy?: () => void | Promise<void>;
  /** Retry a failed/cancelled assistant message. */
  showRetry?: boolean;
  onRetry?: () => void;
  retryDisabled?: boolean;
  /** Regenerate a completed assistant message. */
  showRegenerate?: boolean;
  onRegenerate?: () => void;
}

const t = defaultTheme;

/**
 * Reusable message action row using shared ui-core primitives. No icon
 * library: glyphs are passed as button children.
 */
export function MessageActions({
  content,
  canCopy = false,
  onCopy,
  showRetry = false,
  onRetry,
  retryDisabled = false,
  showRegenerate = false,
  onRegenerate,
}: MessageActionsProps) {
  const handleCopy = () => {
    void (onCopy != null ? onCopy() : copyTextToClipboard(content));
  };

  const retryUnavailable = retryDisabled || onRetry == null;

  return (
    <div
      role="toolbar"
      aria-label="Message actions"
      style={{ display: "flex", gap: t.spacing.xs }}
    >
      {canCopy && (
        <IconButton
          size="sm"
          ariaLabel="Copy message"
          title="Copy message to clipboard"
          onClick={handleCopy}
        >
          ⧉
        </IconButton>
      )}
      {showRetry && (
        <IconButton
          size="sm"
          ariaLabel="Retry response"
          title={retryUnavailable ? "Retry not available" : "Retry response"}
          onClick={onRetry}
          disabled={retryUnavailable}
        >
          ↻
        </IconButton>
      )}
      {showRegenerate && (
        <IconButton
          size="sm"
          ariaLabel="Regenerate response"
          title="Regenerate response"
          onClick={onRegenerate}
          disabled={onRegenerate == null}
        >
          ↺
        </IconButton>
      )}
    </div>
  );
}