import { defaultTheme, IconButton } from "@ava/ui-core";
import { settingsSectionLabel, type SettingsSectionId } from "@ava/ui-core";
import { copyTextToClipboard } from "../lib/clipboard";

export interface MessageActionsProps {
  /** Content copied when the copy action is used. */
  content: string;
  canCopy?: boolean;
  onCopy?: () => void | Promise<void>;
  /** Retry a failed/cancelled assistant message. */
  showRetry?: boolean;
  onRetry?: () => void;
  /** Retry refused — typically because a run currently owns the conversation. */
  retryDisabled?: boolean;
  /** Regenerate a completed assistant message. */
  showRegenerate?: boolean;
  onRegenerate?: () => void;
  /** Regenerate refused — typically because a run currently owns the conversation. */
  regenerateDisabled?: boolean;
  settingsSection?: SettingsSectionId;
  onOpenSettings?: (section: SettingsSectionId) => void;
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
  regenerateDisabled = false,
  settingsSection,
  onOpenSettings,
}: MessageActionsProps) {
  const handleCopy = () => {
    void (onCopy != null ? onCopy() : copyTextToClipboard(content));
  };

  const retryUnavailable = retryDisabled || onRetry == null;
  const regenerateUnavailable = regenerateDisabled || onRegenerate == null;

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
      {settingsSection != null && onOpenSettings != null && (
        <IconButton
          size="sm"
          ariaLabel={`Open ${settingsSectionLabel[settingsSection]} Settings`}
          title={`Open ${settingsSectionLabel[settingsSection]} Settings`}
          onClick={() => onOpenSettings(settingsSection)}
        >
          ⚙
        </IconButton>
      )}
      {showRegenerate && (
        <IconButton
          size="sm"
          ariaLabel="Regenerate response"
          title={regenerateUnavailable ? "Regenerate not available" : "Regenerate response"}
          onClick={onRegenerate}
          disabled={regenerateUnavailable}
        >
          ↺
        </IconButton>
      )}
    </div>
  );
}
