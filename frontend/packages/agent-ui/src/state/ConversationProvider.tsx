import {
  createContext,
  useContext,
  useMemo,
  useReducer,
  useRef,
  type ReactNode,
} from "react";
import type { ApiClient } from "@ava/api-client";
import { createConversation, createMessage, listConversations, listMessages } from "@ava/api-client";
import { useEffect } from "react";

import type {
  Conversation,
  ConversationRunState,
} from "../types";
import {
  conversationReducer,
  getActiveConversation,
  type ConversationState,
  type MessagePatch,
} from "./conversationReducer";
import { createRenameConversationCommand } from "./renameConversation";
import { associateAssistantMessages } from "../lib/transcript";
import { presentAvaError } from "../lib/errorPresentation";

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
  createConversation: () => Promise<void>;
  selectConversation: (id: string) => Promise<void>;
  renameConversation: (id: string, title: string) => Promise<void>;
  /** Adds a user message, auto-creating a conversation when needed, and
   * returns the ids of the conversation and message that were added. */
  addUserMessage: (
    conversationId: string | null,
    content: string,
  ) => Promise<AddedUserMessage>;
  /** Adds a pending assistant message to a conversation (stable message id),
   * optionally linked to the user message that prompted it. */
  addAssistantMessage: (
    conversationId: string,
    messageId: string,
    sourceUserMessageId?: string | null,
    sourceRunId?: string | null,
  ) => void;
  /** Immutably patches an existing message. */
  updateMessage: (
    conversationId: string,
    messageId: string,
    patch: MessagePatch,
  ) => void;
  /** Removes a local-only optimistic message after its action was rejected. */
  removeMessage: (conversationId: string, messageId: string) => void;
  replaceMessage: (conversationId: string, placeholderId: string, message: import("../types").ConversationMessage) => void;
  associateAssistantMessage: (conversationId: string, placeholderId: string, messageId: string) => void;
  /** Merges run lifecycle state into a conversation. */
  setRunState: (
    conversationId: string,
    update: Partial<ConversationRunState>,
  ) => void;
  /** Reads the current run state of a conversation (freshest committed
   * state, never the value captured at call time). Used by the run
   * orchestrator to drop stale completions. */
  getRunState: (conversationId: string) => ConversationRunState | null;
}

const ConversationStateContext = createContext<ConversationManager | null>(null);

export function ConversationProvider({ children, client }: { children: ReactNode; client: ApiClient }) {
  const [state, dispatch] = useReducer(conversationReducer, {
    conversations: [],
    activeConversationId: null,
    loading: true,
    error: null,
  });
  // Mirror of the latest committed state so run-state reads (stale-completion
  // checks) are never served from a closure captured when a run started.
  const stateRef = useRef(state);
  stateRef.current = state;
  const selectedRef = useRef<string | null>(null);
  // Conversation identity alone cannot reject A → B → A races: the first A
  // request is stale once the second A selection begins. This counter is local
  // observer ownership, never durable application state.
  const loadGenerationRef = useRef(0);
  useEffect(() => {
    let live = true;
    dispatch({ type: "conversation:loadStart" });
    void listConversations(client).then(async ({ conversations }) => {
      const hydrated = await Promise.all(conversations.map(async (conversation) => {
        const messages = await listMessages(client, conversation.conversation_id);
        return { id: conversation.conversation_id, title: conversation.title, createdAt: conversation.created_at,
          messages: associateAssistantMessages(messages.messages.map((message) => ({ id: message.message_id, role: message.role, status: message.status, content: message.content, sourceUserMessageId: message.source_user_message_id ?? undefined, sourceRunId: message.source_run_id, errorCode: message.error_code ?? undefined, createdAt: message.created_at }))), run: undefined };
      }));
      if (live) dispatch({ type: "conversation:hydrate", conversations: hydrated });
    }).catch((error: unknown) => {
      if (live) dispatch({
        type: "conversation:loadFailure",
        error: presentAvaError(error, "Unable to load conversations."),
      });
    });
    return () => { live = false; };
  }, [client]);

  const manager = useMemo<ConversationManager>(
    () => ({
      state,
      conversations: state.conversations,
      activeConversation: getActiveConversation(state),
      createConversation: async () => {
        const created = await createConversation(client);
        dispatch({ type: "conversation:upsert", conversation: {
          id: created.conversation_id, title: created.title, createdAt: created.created_at,
          messages: [], run: undefined,
        } });
      },
      selectConversation: async (id) => {
        selectedRef.current = id;
        const generation = ++loadGenerationRef.current;
        dispatch({ type: "conversation:select", id });
        dispatch({ type: "conversation:messagesLoadStart", conversationId: id });
        try {
          const result = await listMessages(client, id);
          if (selectedRef.current !== id || loadGenerationRef.current !== generation) return;
          dispatch({ type: "conversation:messagesHydrate", conversationId: id, messages: associateAssistantMessages(result.messages.map((message) => ({ id: message.message_id, role: message.role, status: message.status, content: message.content, sourceUserMessageId: message.source_user_message_id ?? undefined, sourceRunId: message.source_run_id, errorCode: message.error_code ?? undefined, createdAt: message.created_at }))) });
        } catch (error) {
          if (selectedRef.current === id && loadGenerationRef.current === generation) dispatch({
            type: "conversation:messagesLoadFailure",
            conversationId: id,
            error: presentAvaError(error, "Unable to load this conversation."),
          });
        }
      },
      renameConversation: async (id, title) => {
        await createRenameConversationCommand({ client, onSuccess: (updated) => {
          // Reconcile the server's authoritative title without changing which
          // conversation is selected (renaming must never switch selection).
          dispatch({ type: "conversation:rename", conversationId: id, title: updated.title });
        }, onError: (error) => {
          dispatch({
            type: "conversation:messagesLoadFailure",
            conversationId: id,
            error: presentAvaError(error, "Unable to rename conversation."),
          });
        } })(id, title);
      },
      addUserMessage: async (conversationId, content) => {
        let resolvedConversationId = conversationId;
        if (resolvedConversationId == null) {
          const created = await createConversation(client, { title: content.trim().slice(0, 40) });
          resolvedConversationId = created.conversation_id;
          dispatch({ type: "conversation:upsert", conversation: { id: created.conversation_id, title: created.title, createdAt: created.created_at, messages: [], run: undefined } });
        }
        const persisted = await createMessage(client, resolvedConversationId, { content, role: "user" });
        const createdMessageId = persisted.message_id;
        if (resolvedConversationId != null) {
          dispatch({
            type: "conversation:addUserMessage",
            conversationId: resolvedConversationId,
            content,
            createdMessageId,
          });
          return { conversationId: resolvedConversationId, messageId: createdMessageId };
        }
        const createdConversationId = resolvedConversationId;
        dispatch({
          type: "conversation:addUserMessage",
          conversationId: null,
          content,
          createdConversationId,
          createdMessageId,
        });
        return { conversationId: createdConversationId, messageId: createdMessageId };
      },
      addAssistantMessage: (conversationId, messageId, sourceUserMessageId, sourceRunId) =>
        dispatch({
          type: "conversation:addAssistantMessage",
          conversationId,
          messageId,
          sourceUserMessageId: sourceUserMessageId ?? undefined,
          sourceRunId: sourceRunId ?? undefined,
        }),
      updateMessage: (conversationId, messageId, patch) =>
        dispatch({
          type: "conversation:updateMessage",
          conversationId,
          messageId,
          patch,
        }),
      removeMessage: (conversationId, messageId) =>
        dispatch({ type: "conversation:removeMessage", conversationId, messageId }),
      replaceMessage: (conversationId, placeholderId, message) => dispatch({ type: "conversation:replaceMessage", conversationId, placeholderId, message }),
      associateAssistantMessage: (conversationId, placeholderId, messageId) => dispatch({
        type: "conversation:associateAssistantMessage", conversationId, placeholderId, messageId,
      }),
      setRunState: (conversationId, update) =>
        dispatch({ type: "conversation:setRunState", conversationId, update }),
      getRunState: (conversationId) =>
        stateRef.current.conversations.find(
          (conversation) => conversation.id === conversationId,
        )?.run ?? null,
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
