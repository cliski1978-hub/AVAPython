import { Button, defaultTheme, useInteraction } from "@ava/ui-core";
import type { CSSProperties } from "react";
import type { Conversation } from "../types";

export interface ConversationListProps {
  conversations: Conversation[];
  activeConversationId: string | null;
  onNewChat: () => void;
  onSelect: (id: string) => void;
}

const t = defaultTheme;

function ConversationItem({
  conversation,
  active,
  onSelect,
}: {
  conversation: Conversation;
  active: boolean;
  onSelect: (id: string) => void;
}) {
  const interaction = useInteraction(true);

  const style: CSSProperties = {
    display: "flex",
    alignItems: "center",
    gap: t.spacing.sm,
    width: "100%",
    boxSizing: "border-box",
    padding: `${t.spacing.sm}px ${t.spacing.md}px`,
    borderRadius: t.radius.md,
    border: `${t.border.width}px solid ${
      active ? t.colors.primary : "transparent"
    }`,
    background: active ? t.colors.ghostHover : "transparent",
    color: active ? t.colors.primary : t.colors.foreground,
    fontSize: t.font.sizeSm,
    fontWeight: active ? t.font.weightSemibold : t.font.weightNormal,
    fontFamily: t.font.family,
    textAlign: "left",
    cursor: "pointer",
    outline: "none",
    transition:
      "background 120ms ease, border-color 120ms ease, color 120ms ease, box-shadow 120ms ease",
    ...(interaction.hovered
      ? { background: t.colors.ghostHover }
      : {}),
    ...(interaction.focused
      ? { boxShadow: `0 0 0 2px ${t.colors.focusRing}33` }
      : {}),
  };

  return (
    <button
      type="button"
      data-conversation-item={conversation.id}
      aria-current={active ? "true" : undefined}
      title={conversation.title}
      style={style}
      onClick={() => onSelect(conversation.id)}
      onMouseEnter={interaction.onMouseEnter}
      onMouseLeave={interaction.onMouseLeave}
      onFocus={interaction.onFocus}
      onBlur={interaction.onBlur}
    >
      {active && (
        <span
          aria-hidden
          style={{
            width: 6,
            height: 6,
            borderRadius: "50%",
            background: t.colors.primary,
            flexShrink: 0,
          }}
        />
      )}
      <span
        style={{
          flex: 1,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        {conversation.title}
      </span>
    </button>
  );
}

export function ConversationList({
  conversations,
  activeConversationId,
  onNewChat,
  onSelect,
}: ConversationListProps) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: t.spacing.sm,
      }}
      data-conversation-list=""
    >
      <span data-new-chat>
        <Button variant="primary" onClick={onNewChat}>
          New Chat
        </Button>
      </span>
      {conversations.length === 0 ? (
        <p
          style={{
            margin: 0,
            padding: t.spacing.md,
            color: t.colors.mutedText,
            fontSize: t.font.sizeSm,
            textAlign: "center",
            fontStyle: "italic",
          }}
        >
          No conversations yet
        </p>
      ) : (
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: t.spacing.xs,
          }}
        >
          {conversations.map((conversation) => (
            <ConversationItem
              key={conversation.id}
              conversation={conversation}
              active={conversation.id === activeConversationId}
              onSelect={onSelect}
            />
          ))}
        </div>
      )}
    </div>
  );
}