import { useEffect, useRef } from "react";
import { defaultTheme } from "@ava/ui-core";
import type { ConversationMessage, UIRunPhase } from "../types";
import { NEAR_BOTTOM_PX } from "../state/conversationReducer";
import { AssistantMessage } from "./AssistantMessage";
import { UserMessage } from "./UserMessage";

export interface MessageListProps {
  messages: ConversationMessage[];
  runPhase?: UIRunPhase;
  onRetryMessage?: (messageId: string) => void;
  onRegenerateMessage?: (messageId: string) => void;
}

const t = defaultTheme;

function assistantProgressLabel(runPhase: UIRunPhase | undefined): string {
  if (runPhase === "starting") return "AVA is working…";
  if (runPhase === "stopping") return "Stopping…";
  return "AVA is responding…";
}

function SystemMessage({ content }: { content: string }) {
  return (
    <p
      data-message-role="system"
      style={{
        margin: 0,
        textAlign: "center",
        fontSize: t.font.sizeXs,
        color: t.colors.mutedText,
        fontStyle: "italic",
      }}
    >
      {content}
    </p>
  );
}

/**
 * Renders messages in order with stable ids as keys and its own scroll
 * region. Scrolls to the newest/updated message when its content, status, or
 * identity changes, but only if the reader is already near the bottom — a
 * reader who has scrolled upward is not yanked back down.
 */
export function MessageList({
  messages,
  runPhase,
  onRetryMessage,
  onRegenerateMessage,
}: MessageListProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const nearBottomRef = useRef(true);

  const lastMessage = messages.length > 0 ? messages[messages.length - 1] : null;
  const anchor =
    lastMessage != null
      ? `${lastMessage.id}:${lastMessage.content.length}:${lastMessage.status ?? ""}`
      : "empty";

  useEffect(() => {
    const el = scrollRef.current;
    if (el != null && nearBottomRef.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [anchor]);

  const handleScroll = () => {
    const el = scrollRef.current;
    if (el == null) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    nearBottomRef.current = distanceFromBottom < NEAR_BOTTOM_PX;
  };

  return (
    <div
      ref={scrollRef}
      data-message-scroll=""
      onScroll={handleScroll}
      style={{ flex: 1, overflowY: "auto", minHeight: 0 }}
    >
      <ol
        style={{
          listStyle: "none",
          margin: "0 auto",
          padding: `${t.spacing.lg}px`,
          boxSizing: "border-box",
          maxWidth: 720,
          display: "flex",
          flexDirection: "column",
          gap: t.spacing.lg,
        }}
      >
        {messages.map((message) => (
          <li
            key={message.id}
            style={{ margin: 0, display: "flex", flexDirection: "column", minWidth: 0 }}
          >
            {message.role === "user" ? (
              <UserMessage content={message.content} />
            ) : message.role === "assistant" ? (
              <AssistantMessage
                content={message.content}
                status={message.status ?? "complete"}
                error={message.error}
                progressLabel={assistantProgressLabel(runPhase)}
                onRetry={
                  onRetryMessage != null
                    ? () => onRetryMessage(message.id)
                    : undefined
                }
                onRegenerate={
                  onRegenerateMessage != null
                    ? () => onRegenerateMessage(message.id)
                    : undefined
                }
              />
            ) : (
              <SystemMessage content={message.content} />
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}