import { defaultTheme } from "@ava/ui-core";
import type { Conversation, ConversationMessage } from "../types";
import { ConversationEmptyState } from "./ConversationEmptyState";
import { ConversationHeader } from "./ConversationHeader";
import { MessageList } from "./MessageList";

export interface ConversationViewProps {
  conversation?: Conversation | null;
  /** Explicit message override (useful for previews without a conversation). */
  messages?: ConversationMessage[];
  title?: string;
  onRetryMessage?: (messageId: string) => void;
  onRegenerateMessage?: (messageId: string) => void;
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
  onRetryMessage,
  onRegenerateMessage,
}: ConversationViewProps) {
  const list = messages ?? conversation?.messages ?? [];
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
        />
      )}
    </div>
  );
}