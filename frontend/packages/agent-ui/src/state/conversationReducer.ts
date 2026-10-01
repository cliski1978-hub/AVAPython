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
  loading?: boolean;
  error?: string | null;
}

export const DEFAULT_CONVERSATION_TITLE = "New Conversation";
export const TITLE_MAX_LENGTH = 40;
export const NEAR_BOTTOM_PX = 48;

export interface MessagePatch {
  content?: string;
  status?: MessageStatus;
  error?: string;
  errorCode?: string;
  /**
   * The run that produced this response. Recorded when a run is accepted so the
   * response's durable lineage is available without re-reading the
   * conversation — retry and regenerate branch from it.
   */
  sourceRunId?: string | null;
}

export type ConversationAction =
  | { type: "conversation:upsert"; conversation: Conversation }
  | { type: "conversation:rename"; conversationId: string; title: string }
  | { type: "conversation:messagesLoadStart"; conversationId: string }
  | { type: "conversation:messagesHydrate"; conversationId: string; messages: Conversation["messages"] }
  | { type: "conversation:messagesLoadFailure"; conversationId: string; error: string }
  | { type: "conversation:replaceMessage"; conversationId: string; placeholderId: string; message: ConversationMessage }
  | { type: "conversation:associateAssistantMessage"; conversationId: string; placeholderId: string; messageId: string }
  | { type: "conversation:hydrate"; conversations: Conversation[] }
  | { type: "conversation:loadStart" }
  | { type: "conversation:loadFailure"; error: string }
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
      /** Optional link to the run that produced this assistant message. */
      sourceRunId?: string | null;
    }
  | {
      type: "conversation:updateMessage";
      conversationId: string;
      messageId: string;
      patch: MessagePatch;
    }
  | { type: "conversation:removeMessage"; conversationId: string; messageId: string }
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

/**
 * Merge a server (authoritative) message snapshot into the local conversation
 * without dropping messages whose persistence is still in flight.
 *
 * Server-known messages take the server snapshot in authoritative (append)
 * order; identical ids that already exist locally are replaced by the server
 * copy. Local-only messages — those the server does not know yet (typically
 * the in-flight assistant placeholder for a run that has not finished
 * persisting) — are kept, after the server messages, in their local order.
 * Re-merging the same snapshot is a no-op (no duplicates on re-select), and
 * the final list is deduplicated by stable message id.
 *
 * The authoritative server order matters for regenerate semantics: when a
 * failed/superseded assistant response (A1) is re-read together with the
 * regenerated response (A2), the server lists A1 before A2, so a caller that
 * derives the turn's active response sees the newest row last.
 */
export function mergeConversationMessages(
  current: ConversationMessage[],
  incoming: ConversationMessage[],
): ConversationMessage[] {
  if (current.length === 0) return incoming;
  if (incoming.length === 0) return current;
  const incomingIds = new Set(incoming.map((message) => message.id));
  const merged = [
    ...incoming,
    ...current.filter((message) => !incomingIds.has(message.id)),
  ];
  const seen = new Set<string>();
  const unique: ConversationMessage[] = [];
  for (const message of merged) {
    if (seen.has(message.id)) continue;
    seen.add(message.id);
    unique.push(message);
  }
  return unique;
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
    case "conversation:upsert": {
      const exists = state.conversations.some((item) => item.id === action.conversation.id);
      return { ...state, conversations: exists ? state.conversations.map((item) => item.id === action.conversation.id ? action.conversation : item) : [action.conversation, ...state.conversations], activeConversationId: action.conversation.id };
    }
    case "conversation:rename": {
      // Rename only the title. Unlike upsert, this never touches selection or
      // messages, so renaming a non-active conversation from the sidebar menu
      // cannot switch the active conversation.
      return updateConversation(state, action.conversationId, (conversation) =>
        conversation.title === action.title
          ? conversation
          : { ...conversation, title: action.title },
      );
    }
    case "conversation:messagesLoadStart": return { ...state, error: null };
    case "conversation:messagesLoadFailure": return { ...state, error: action.error };
    case "conversation:messagesHydrate": return updateConversation(state, action.conversationId, (conversation) => ({ ...conversation, messages: mergeConversationMessages(conversation.messages, action.messages) }));
    case "conversation:replaceMessage": return updateConversation(state, action.conversationId, (conversation) => ({ ...conversation, messages: conversation.messages.map((message) => message.id === action.placeholderId ? action.message : message) }));
    case "conversation:associateAssistantMessage": return updateConversation(state, action.conversationId, (conversation) => {
      if (conversation.messages.some((message) => message.id === action.messageId)) {
        return { ...conversation, messages: conversation.messages.filter((message) => message.id !== action.placeholderId) };
      }
      return {
        ...conversation,
        messages: conversation.messages.map((message) =>
          message.id === action.placeholderId ? { ...message, id: action.messageId } : message,
        ),
      };
    });
    case "conversation:loadStart": return { ...state, loading: true, error: null };
    case "conversation:loadFailure": return { ...state, loading: false, error: action.error };
    case "conversation:hydrate": return {
      ...state, loading: false, error: null, conversations: action.conversations,
      activeConversationId: state.activeConversationId ?? action.conversations[0]?.id ?? null,
    };
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
          sourceRunId: action.sourceRunId,
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
    case "conversation:removeMessage": {
      return updateConversation(state, action.conversationId, (conversation) => ({
        ...conversation,
        messages: conversation.messages.filter((message) => message.id !== action.messageId),
      }));
    }
    case "conversation:setRunState": {
      return updateConversation(state, action.conversationId, (conversation) => ({
        ...conversation,
        run: { ...EMPTY_CONVERSATION_RUN, ...conversation.run, ...action.update },
      }));
    }
  }
}
