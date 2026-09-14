import {
  createContext,
  useContext,
  useMemo,
  useReducer,
  type ReactNode,
} from "react";

import type {
  Conversation,
  ConversationRunState,
} from "../types";
import {
  conversationReducer,
  createEntityId,
  getActiveConversation,
  type ConversationState,
  type MessagePatch,
} from "./conversationReducer";

export interface AddedUserMessage {
  /** Id of the conversation the message was added to (possibly created). */
  conversationId: string;
  /** Stable id of the added user message. */
  messageId: string;
}

export interface ConversationManager {
  state: ConversationState;
  conversations: Conversation[];
  activeConversation: Conversation | null;
  createConversation: () => void;
  selectConversation: (id: string) => void;
  /** Adds a user message, auto-creating a conversation when needed, and
   * returns the ids of the conversation and message that were added. */
  addUserMessage: (
    conversationId: string | null,
    content: string,
  ) => AddedUserMessage;
  /** Adds a pending assistant message to a conversation (stable message id),
   * optionally linked to the user message that prompted it. */
  addAssistantMessage: (
    conversationId: string,
    messageId: string,
    sourceUserMessageId?: string | null,
  ) => void;
  /** Immutably patches an existing message. */
  updateMessage: (
    conversationId: string,
    messageId: string,
    patch: MessagePatch,
  ) => void;
  /** Merges run lifecycle state into a conversation. */
  setRunState: (
    conversationId: string,
    update: Partial<ConversationRunState>,
  ) => void;
}

const ConversationStateContext = createContext<ConversationManager | null>(null);

export function ConversationProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(conversationReducer, {
    conversations: [],
    activeConversationId: null,
  });

  const manager = useMemo<ConversationManager>(
    () => ({
      state,
      conversations: state.conversations,
      activeConversation: getActiveConversation(state),
      createConversation: () => dispatch({ type: "conversation:create" }),
      selectConversation: (id) => dispatch({ type: "conversation:select", id }),
      addUserMessage: (conversationId, content) => {
        const createdMessageId = createEntityId();
        if (conversationId != null) {
          dispatch({
            type: "conversation:addUserMessage",
            conversationId,
            content,
            createdMessageId,
          });
          return { conversationId, messageId: createdMessageId };
        }
        const createdConversationId = createEntityId();
        dispatch({
          type: "conversation:addUserMessage",
          conversationId: null,
          content,
          createdConversationId,
          createdMessageId,
        });
        return { conversationId: createdConversationId, messageId: createdMessageId };
      },
      addAssistantMessage: (conversationId, messageId, sourceUserMessageId) =>
        dispatch({
          type: "conversation:addAssistantMessage",
          conversationId,
          messageId,
          sourceUserMessageId: sourceUserMessageId ?? undefined,
        }),
      updateMessage: (conversationId, messageId, patch) =>
        dispatch({
          type: "conversation:updateMessage",
          conversationId,
          messageId,
          patch,
        }),
      setRunState: (conversationId, update) =>
        dispatch({ type: "conversation:setRunState", conversationId, update }),
    }),
    [state],
  );

  return (
    <ConversationStateContext.Provider value={manager}>
      {children}
    </ConversationStateContext.Provider>
  );
}

export function useConversationState(): ConversationManager {
  const context = useContext(ConversationStateContext);
  if (context == null) {
    throw new Error(
      "useConversationState must be used within a ConversationProvider",
    );
  }
  return context;
}