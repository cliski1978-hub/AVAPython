import {
  Button,
  IconButton,
  Input,
  defaultTheme,
  useInteraction,
} from "@ava/ui-core";
import { useEffect, useRef, useState, type CSSProperties } from "react";
import type { Conversation } from "../types";

export interface ConversationListProps {
  conversations: Conversation[];
  activeConversationId: string | null;
  onNewChat: () => void;
  onSelect: (id: string) => void;
  /** Renames a conversation through the backend (authoritative). When omitted,
   * conversation items expose no action menu. */
  onRename?: (id: string, title: string) => Promise<void>;
  /** Shared conversation error (e.g. a failed rename), rendered as a strip. */
  error?: string | null;
}

const t = defaultTheme;

function conversationRowStyle(
  active: boolean,
  interaction: { hovered: boolean; focused: boolean },
): CSSProperties {
  return {
    position: "relative",
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
    ...(interaction.hovered ? { background: t.colors.ghostHover } : {}),
    ...(interaction.focused
      ? { boxShadow: `0 0 0 2px ${t.colors.focusRing}33` }
      : {}),
  };
}

const selectStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: t.spacing.sm,
  flex: 1,
  minWidth: 0,
  padding: 0,
  border: "none",
  background: "transparent",
  color: "inherit",
  fontSize: "inherit",
  fontWeight: "inherit",
  fontFamily: "inherit",
  textAlign: "left",
  cursor: "pointer",
  outline: "none",
};

const titleStyle: CSSProperties = {
  flex: 1,
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
};

const menuStyle: CSSProperties = {
  position: "absolute",
  top: "100%",
  right: 0,
  marginTop: t.spacing.xs,
  zIndex: 40,
  minWidth: 140,
  boxSizing: "border-box",
  padding: `${t.spacing.xs}px`,
  background: t.colors.surface,
  border: `${t.border.width}px solid ${t.colors.borderStrong}`,
  borderRadius: t.radius.md,
  boxShadow: "0 4px 12px rgba(17, 24, 39, 0.12)",
};

const menuItemStyle: CSSProperties = {
  display: "block",
  width: "100%",
  boxSizing: "border-box",
  padding: `${t.spacing.sm}px ${t.spacing.md}px`,
  border: "none",
  borderRadius: t.radius.sm,
  background: "transparent",
  color: t.colors.foreground,
  fontSize: t.font.sizeSm,
  fontFamily: t.font.family,
  textAlign: "left",
  cursor: "pointer",
};

/** Inline title editor: Enter confirms, Escape cancels, blank input cancels. */
function RenameEditor({
  initialTitle,
  onConfirm,
  onCancel,
}: {
  initialTitle: string;
  onConfirm: (title: string) => void;
  onCancel: () => void;
}) {
  const [value, setValue] = useState(initialTitle);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const input = containerRef.current?.querySelector("input");
    if (input != null) {
      input.focus();
      input.select();
    }
  }, []);

  const submit = () => {
    // A blank or whitespace-only title is never persisted (see backend guard).
    if (value.trim().length === 0) {
      onCancel();
      return;
    }
    onConfirm(value.trim());
  };

  return (
    <div
      ref={containerRef}
      data-conversation-renaming=""
      style={{ flex: 1, minWidth: 0 }}
      onKeyDown={(event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          submit();
        } else if (event.key === "Escape") {
          event.preventDefault();
          onCancel();
        }
      }}
    >
      <Input
        ariaLabel="Rename conversation"
        value={value}
        onChange={setValue}
      />
    </div>
  );
}

function ConversationItem({
  conversation,
  active,
  onSelect,
  onRename,
  renaming,
  menuOpen,
  onOpenMenu,
  onCloseMenu,
  onStartRename,
  onRenameDone,
}: {
  conversation: Conversation;
  active: boolean;
  onSelect: (id: string) => void;
  onRename?: (id: string, title: string) => Promise<void>;
  renaming: boolean;
  menuOpen: boolean;
  onOpenMenu: (id: string) => void;
  onCloseMenu: () => void;
  onStartRename: (id: string) => void;
  onRenameDone: (id: string, title: string) => void;
}) {
  const interaction = useInteraction(true);
  const showMenu = onRename != null;

  return (
    <div
      data-conversation-row={conversation.id}
      style={conversationRowStyle(active, interaction)}
      onMouseEnter={interaction.onMouseEnter}
      onMouseLeave={interaction.onMouseLeave}
      onFocus={interaction.onFocus}
      onBlur={interaction.onBlur}
    >
      {renaming && showMenu ? (
        <RenameEditor
          initialTitle={conversation.title}
          onConfirm={(title) => onRenameDone(conversation.id, title)}
          onCancel={onCloseMenu}
        />
      ) : (
        <>
          <button
            type="button"
            data-conversation-item={conversation.id}
            aria-current={active ? "true" : undefined}
            title={conversation.title}
            style={selectStyle}
            onClick={() => onSelect(conversation.id)}
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
            <span style={titleStyle}>{conversation.title}</span>
          </button>
          {showMenu && (
            <span
              aria-haspopup="menu"
              aria-expanded={menuOpen || undefined}
              style={{ display: "flex", flexShrink: 0 }}
            >
              <IconButton
                size="sm"
                ariaLabel={`Conversation actions for ${conversation.title}`}
                title="Conversation actions"
                onClick={() =>
                  menuOpen ? onCloseMenu() : onOpenMenu(conversation.id)
                }
              >
                {"\u2026"}
              </IconButton>
            </span>
          )}
          {menuOpen && (
            <div style={menuStyle} role="menu" data-conversation-menu="">
              <button
                type="button"
                role="menuitem"
                data-conversation-rename=""
                style={menuItemStyle}
                onClick={() => onStartRename(conversation.id)}
              >
                Rename
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

export function ConversationList({
  conversations,
  activeConversationId,
  onNewChat,
  onSelect,
  onRename,
  error,
}: ConversationListProps) {
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [menuOpenId, setMenuOpenId] = useState<string | null>(null);

  const startRename = (id: string) => {
    setMenuOpenId(null);
    setRenamingId(id);
  };

  const finishRename = async (id: string, title: string) => {
    setRenamingId(null);
    try {
      if (onRename != null) await onRename(id, title);
    } catch {
      // A failed rename never pretends success: the reducer keeps the prior
      // authoritative title and the shared `error` strip surfaces the failure.
    }
  };

  const listStyle: CSSProperties = {
    display: "flex",
    flexDirection: "column",
    gap: t.spacing.sm,
    width: "100%",
  };

  const errorStyle: CSSProperties = {
    boxSizing: "border-box",
    padding: `${t.spacing.sm}px ${t.spacing.md}px`,
    borderRadius: t.radius.md,
    background: t.colors.surface,
    border: `${t.border.width}px solid ${t.colors.danger}`,
    color: t.colors.dangerText,
    fontSize: t.font.sizeSm,
    fontFamily: t.font.family,
  };

  return (
    <div data-conversation-list="" style={listStyle}>
      <span data-new-chat>
        <Button variant="primary" onClick={onNewChat}>
          New Chat
        </Button>
      </span>
      {error != null && error.length > 0 && (
        <div role="alert" data-conversation-error="" style={errorStyle}>
          {error}
        </div>
      )}
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
        <>
          {menuOpenId != null && (
            <div
              aria-hidden
              style={{ position: "fixed", inset: 0, zIndex: 30 }}
              onClick={() => setMenuOpenId(null)}
            />
          )}
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
                onRename={onRename}
                renaming={renamingId === conversation.id}
                menuOpen={menuOpenId === conversation.id}
                onOpenMenu={(id) => {
                  setRenamingId(null);
                  setMenuOpenId(id);
                }}
                onCloseMenu={() => {
                  setRenamingId(null);
                  setMenuOpenId(null);
                }}
                onStartRename={startRename}
                onRenameDone={(id, title) => void finishRename(id, title)}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}