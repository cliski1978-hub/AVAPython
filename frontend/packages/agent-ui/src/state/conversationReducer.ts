import type {
  Conversation,
  ConversationMessage,
  ConversationRunState,
  MessageStatus,
} from "../types";
import { EMPTY_CONVERSATION_RUN } from "../types";

export interface ConversationState {
  conversations: Conversation[];
  activeConversationId: string | null;
}

export const DEFAULT_CONVERSATION_TITLE = "New Conversation";
export const TITLE_MAX_LENGTH = 40;
export const NEAR_BOTTOM_PX = 48;

export interface MessagePatch {
  content?: string;
  status?: MessageStatus;
  error?: string;
}

export type ConversationAction =
  | { type: "conversation:create" }
  | { type: "conversation:select"; id: string }
  | {
      type: "conversation:addUserMessage";
      conversationId: string | null;
      content: string;
      /** Id to use when this action creates a brand-new conversation. */
      createdConversationId?: string;
      /** Stable id for the user message (used for prompt association). */
      createdMessageId?: string;
    }
  | {
      type: "conversation:addAssistantMessage";
      conversationId: string;
      messageId: string;
      /** Optional link to the user message this assistant message answers. */
      sourceUserMessageId?: string;
    }
  | {
      type: "conversation:updateMessage";
      conversationId: string;
      messageId: string;
      patch: MessagePatch;
    }
  | {
      type: "conversation:setRunState";
      conversationId: string;
      update: Partial<ConversationRunState>;
    };

export function createEntityId(): string {
  if (typeof globalThis.crypto?.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  return `id-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

export function createTimestamp(): string {
  return new Date().toISOString();
}

export function deriveTitle(prompt: string): string {
  const singleLine = prompt.trim().replace(/\s+/g, " ");
  if (singleLine.length <= TITLE_MAX_LENGTH) return singleLine;
  return `${singleLine.slice(0, TITLE_MAX_LENGTH).trimEnd()}…`;
}

export function createConversationEntry(
  title: string,
  idOverride?: string,
): Conversation {
  return {
    id: idOverride ?? createEntityId(),
    title,
    createdAt: createTimestamp(),
    messages: [],
    run: { ...EMPTY_CONVERSATION_RUN },
  };
}

function createUserMessage(
  content: string,
  idOverride?: string,
): ConversationMessage {
  return {
    id: idOverride ?? createEntityId(),
    role: "user",
    status: "complete",
    content,
    createdAt: createTimestamp(),
  };
}

function appendUserMessage(
  state: ConversationState,
  target: Conversation | undefined,
  content: string,
  createdConversationId?: string,
  createdMessageId?: string,
): ConversationState {
  const message = createUserMessage(content, createdMessageId);

  if (target == null) {
    const created = {
      ...createConversationEntry(deriveTitle(content), createdConversationId),
      messages: [message],
    };
    return {
      conversations: [created, ...state.conversations],
      activeConversationId: created.id,
    };
  }

  const updated: Conversation =
    target.messages.length === 0
      ? {
          ...target,
          title: deriveTitle(content),
          messages: [...target.messages, message],
        }
      : { ...target, messages: [...target.messages, message] };

  return {
    conversations: state.conversations.map((conversation) =>
      conversation.id === target.id ? updated : conversation,
    ),
    activeConversationId: target.id,
  };
}

/** Immutably apply an updater to one conversation, leaving others untouched. */
export function updateConversation(
  state: ConversationState,
  conversationId: string,
  updater: (conversation: Conversation) => Conversation,
): ConversationState {
  let changed = false;
  const conversations = state.conversations.map((conversation) => {
    if (conversation.id !== conversationId) return conversation;
    const updated = updater(conversation);
    if (updated !== conversation) changed = true;
    return updated;
  });
  if (!changed) return state;
  return { ...state, conversations };
}

export function getActiveConversation(
  state: ConversationState,
): Conversation | null {
  if (state.activeConversationId == null) return null;
  return (
    state.conversations.find(
      (conversation) => conversation.id === state.activeConversationId,
    ) ?? null
  );
}

export function conversationReducer(
  state: ConversationState,
  action: ConversationAction,
): ConversationState {
  switch (action.type) {
    case "conversation:create": {
      const conversation = createConversationEntry(DEFAULT_CONVERSATION_TITLE);
      return {
        conversations: [conversation, ...state.conversations],
        activeConversationId: conversation.id,
      };
    }
    case "conversation:select": {
      const exists = state.conversations.some(
        (conversation) => conversation.id === action.id,
      );
      if (!exists) return state;
      return { ...state, activeConversationId: action.id };
    }
    case "conversation:addUserMessage": {
      if (action.content.trim().length === 0) return state;
      const target =
        action.conversationId != null
          ? state.conversations.find(
              (conversation) => conversation.id === action.conversationId,
            )
          : undefined;
      return appendUserMessage(
        state,
        target,
        action.content,
        action.createdConversationId,
        action.createdMessageId,
      );
    }
    case "conversation:addAssistantMessage": {
      return updateConversation(state, action.conversationId, (conversation) => {
        const exists = conversation.messages.some(
          (message) => message.id === action.messageId,
        );
        if (exists) return conversation;
        const message: ConversationMessage = {
          id: action.messageId,
          role: "assistant",
          status: "pending",
          content: "",
          sourceUserMessageId: action.sourceUserMessageId,
          createdAt: createTimestamp(),
        };
        return { ...conversation, messages: [...conversation.messages, message] };
      });
    }
    case "conversation:updateMessage": {
      return updateConversation(state, action.conversationId, (conversation) => {
        const messageExists = conversation.messages.some(
          (message) => message.id === action.messageId,
        );
        if (!messageExists) return conversation;
        return {
          ...conversation,
          messages: conversation.messages.map((message) =>
            message.id === action.messageId
              ? { ...message, ...action.patch }
              : message,
          ),
        };
      });
    }
    case "conversation:setRunState": {
      return updateConversation(state, action.conversationId, (conversation) => ({
        ...conversation,
        run: { ...EMPTY_CONVERSATION_RUN, ...conversation.run, ...action.update },
      }));
    }
  }
}