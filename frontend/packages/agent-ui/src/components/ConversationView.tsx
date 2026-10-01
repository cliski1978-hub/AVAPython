import { Button, defaultTheme } from "@ava/ui-core";
import type { SettingsSectionId } from "@ava/ui-core";
import type { Conversation, ConversationMessage } from "../types";
import { selectTranscriptMessages } from "../lib/transcript";
import { ConversationEmptyState } from "./ConversationEmptyState";
import { ConversationHeader } from "./ConversationHeader";
import { MessageList } from "./MessageList";

export interface ConversationViewProps {
  conversation?: Conversation | null;
  /** Explicit message override (useful for previews without a conversation). */
  messages?: ConversationMessage[];
  title?: string;
  /** Localized loading/action feedback for this conversation. */
  error?: string | null;
  /** Re-runs the current conversation load after a recoverable failure. */
  onReload?: () => void;
  onRetryMessage?: (messageId: string) => void;
  onRegenerateMessage?: (messageId: string) => void;
  onOpenSettings?: (section: SettingsSectionId) => void;
}

const t = defaultTheme;

/**
 * Main reusable conversation display. Fills the available space, scrolls its
 * own message region, and swaps between an empty/welcome state and the
 * message list. Composer/prompt logic is intentionally absent.
 */
export function ConversationView({
  conversation,
  messages,
  title,
  error,
  onReload,
  onRetryMessage,
  onRegenerateMessage,
  onOpenSettings,
}: ConversationViewProps) {
  const raw = messages ?? conversation?.messages ?? [];
  // Normal transcript: superseded regenerated assistant responses are hidden;
  // only the active/latest response per user turn is rendered.
  const list = selectTranscriptMessages(raw);
  const heading =
    title ?? conversation?.title ?? "New Conversation";
  const runPhase = conversation?.run?.uiPhase;

  return (
    <div
      style={{
        flex: 1,
        display: "flex",
        flexDirection: "column",
        height: "100%",
        overflow: "hidden",
        minWidth: 0,
      }}
    >
      <ConversationHeader title={heading} />
      {error != null && error.length > 0 && (
        <div
          role="alert"
          data-conversation-error=""
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: t.spacing.sm,
            margin: `${t.spacing.sm}px ${t.spacing.md}px 0`,
            padding: `${t.spacing.sm}px ${t.spacing.md}px`,
            border: `${t.border.width}px solid ${t.colors.danger}`,
            borderRadius: t.radius.md,
            color: t.colors.dangerText,
            fontSize: t.font.sizeSm,
          }}
        >
          <span>{error}</span>
          {onReload != null && <Button variant="secondary" onClick={onReload}>Retry</Button>}
        </div>
      )}
      {list.length === 0 ? (
        <div
          style={{
            flex: 1,
            overflow: "auto",
            display: "flex",
            background: `linear-gradient(180deg, ${t.colors.surface} 0%, ${t.colors.background} 55%)`,
          }}
        >
          <div style={{ margin: "auto" }}>
            <ConversationEmptyState />
          </div>
        </div>
      ) : (
        <MessageList
          messages={list}
          runPhase={runPhase}
          onRetryMessage={onRetryMessage}
          onRegenerateMessage={onRegenerateMessage}
          onOpenSettings={onOpenSettings}
        />
      )}
    </div>
  );
}
