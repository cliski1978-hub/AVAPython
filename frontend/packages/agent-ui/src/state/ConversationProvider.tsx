import {
  createContext,
  useContext,
  useCallback,
  useMemo,
  useReducer,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type { ApiClient } from "@ava/api-client";
import { ApiError, createConversation, createProjectConversation, createConversationFolder, createMessage, deleteConversation, deleteConversationFolder as deleteFolderRequest, listConversationFolders, listConversations, listMessages, setConversationArchived as setConversationArchivedRequest, setConversationFolder as setConversationFolderRequest, setConversationPinned as setConversationPinnedRequest, setConversationProject as setConversationProjectRequest, updateConversationFolder } from "@ava/api-client";
import { useEffect } from "react";

import type {
  Conversation,
  ConversationRunState,
} from "../types";
import type { ConversationFolder } from "@ava/contracts";
import {
  conversationReducer,
  getActiveConversation,
  type ConversationState,
  type MessagePatch,
} from "./conversationReducer";
import { createRenameConversationCommand } from "./renameConversation";
import { associateAssistantMessages } from "../lib/transcript";
import { presentAvaError } from "../lib/errorPresentation";
import { selectActiveConversations, selectArchivedConversations } from "./conversationSelectors";

export interface AddedUserMessage {
  /** Id of the conversation the message was added to (possibly created). */
  conversationId: string;
  /** Stable id of the added user message. */
  messageId: string;
}

export interface ConversationManager {
  state: ConversationState;
  conversations: Conversation[];
  activeConversations: Conversation[];
  archivedConversations: Conversation[];
  /** List snapshots shown in the sidebar; search never changes transcript state. */
  conversationList: Conversation[];
  searchQuery: string;
  searchLoading: boolean;
  searchError: string | null;
  reloadConversations: () => Promise<void>;
  folders: ConversationFolder[];
  foldersLoading: boolean;
  folderError: string | null;
  reloadFolders: () => Promise<void>;
  createFolder: (name: string) => Promise<void>;
  renameFolder: (id: string, name: string) => Promise<void>;
  deleteFolder: (id: string) => Promise<void>;
  moveConversation: (conversationId: string, folderId: string | null) => Promise<void>;
  createConversationInFolder: (folderId: string) => Promise<string>;
  createConversationInProject: (projectId: string) => Promise<string>;
  setConversationProject: (conversationId: string, projectId: string | null) => Promise<void>;
  setConversationPinned: (conversationId: string, isPinned: boolean) => Promise<void>;
  setConversationArchived: (conversationId: string, isArchived: boolean) => Promise<void>;
  reconcileDeletedProject: (projectId: string) => void;
  setSearchQuery: (query: string) => void;
  activeConversation: Conversation | null;
  createConversation: () => Promise<void>;
  selectConversation: (id: string) => Promise<void>;
  renameConversation: (id: string, title: string) => Promise<void>;
  /** Permanently deletes a conversation; reconciles a server-confirmed 404. */
  deleteConversation: (id: string) => Promise<void>;
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
  const [searchQuery, setSearchQueryState] = useState("");
  const [searchResults, setSearchResults] = useState<Conversation[] | null>(null);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [searchRevision, setSearchRevision] = useState(0);
  const [folders, setFolders] = useState<ConversationFolder[]>([]);
  const [foldersLoading, setFoldersLoading] = useState(true);
  const [folderError, setFolderError] = useState<string | null>(null);
  // Mirror of the latest committed state so run-state reads (stale-completion
  // checks) are never served from a closure captured when a run started.
  const stateRef = useRef(state);
  stateRef.current = state;
  const foldersRef = useRef(folders);
  foldersRef.current = folders;
  // Deletion is canonical immediately. A list response that started before a
  // successful DELETE must not put that identity back into local UI state.
  const deletedConversationIdsRef = useRef(new Set<string>());
  const deletedFolderIdsRef = useRef(new Set<string>());
  const selectedRef = useRef<string | null>(null);
  // Conversation identity alone cannot reject A → B → A races: the first A
  // request is stale once the second A selection begins. This counter is local
  // observer ownership, never durable application state.
  const loadGenerationRef = useRef(0);
  const conversationCollectionGenerationRef = useRef(0);
  const folderCollectionGenerationRef = useRef(0);
  const searchGenerationRef = useRef(0);
  const orderGenerationRef = useRef(0);
  const folderMovesRef = useRef(new Map<string, { targetFolderId: string | null; promise: Promise<void> }>());
  const archiveMovesRef = useRef(new Map<string, { targetArchived: boolean; promise: Promise<void> }>());

  const fetchCanonicalConversationOrder = async (): Promise<{
    generation: number;
    conversationIds: string[] | null;
  }> => {
    const generation = ++orderGenerationRef.current;
    try {
      const { conversations } = await listConversations(client);
      return {
        generation,
        conversationIds: orderGenerationRef.current === generation
          ? conversations.map((conversation) => conversation.conversation_id)
          : null,
      };
    } catch {
      return { generation, conversationIds: null };
    }
  };

  const refreshCanonicalConversationOrder = async (): Promise<void> => {
    const result = await fetchCanonicalConversationOrder();
    if (result.conversationIds != null && orderGenerationRef.current === result.generation) {
      dispatch({ type: "conversation:reorder", conversationIds: result.conversationIds });
    }
  };

  const reconcileMissingConversation = (id: string) => {
    // Success or a 404 means the durable conversation no longer exists. Pick
    // the item at its old position (or the prior last item) and discard any
    // message hydration still outstanding for the selected stale id.
    const latest = stateRef.current;
    const index = latest.conversations.findIndex((item) => item.id === id);
    const remaining = latest.conversations.filter((item) => item.id !== id);
    const deletingActive = latest.activeConversationId === id;
    const nextActiveConversationId = deletingActive
      ? remaining[Math.min(Math.max(index, 0), remaining.length - 1)]?.id ?? null
      : latest.activeConversationId;

    if (selectedRef.current === id || deletingActive) {
      selectedRef.current = nextActiveConversationId;
      loadGenerationRef.current += 1;
    }
    dispatch({
      type: "conversation:delete",
      conversationId: id,
      activeConversationId: nextActiveConversationId,
    });
  };

  const reloadConversations = useCallback(async () => {
    const generation = ++conversationCollectionGenerationRef.current;
    dispatch({ type: "conversation:loadStart" });
    try {
      const { conversations } = await listConversations(client);
      const hydrated = await Promise.all(conversations.map(async (conversation) => {
        const messages = await listMessages(client, conversation.conversation_id);
        return { id: conversation.conversation_id, title: conversation.title, createdAt: conversation.created_at,
          isPinned: conversation.is_pinned, isArchived: conversation.is_archived, folderId: conversation.folder_id,
          projectId: conversation.project_id,
          messages: associateAssistantMessages(messages.messages.map((message) => ({ id: message.message_id, role: message.role, status: message.status, content: message.content, sourceUserMessageId: message.source_user_message_id ?? undefined, sourceRunId: message.source_run_id, errorCode: message.error_code ?? undefined, createdAt: message.created_at }))), run: undefined };
      }));
      if (conversationCollectionGenerationRef.current === generation) dispatch({
        type: "conversation:hydrate",
        conversations: hydrated.filter((item) => !deletedConversationIdsRef.current.has(item.id)),
      });
    } catch (error: unknown) {
      if (conversationCollectionGenerationRef.current === generation) dispatch({
        type: "conversation:loadFailure",
        error: presentAvaError(error, "Unable to load conversations."),
      });
    }
  }, [client]);

  useEffect(() => {
    void reloadConversations();
    return () => { conversationCollectionGenerationRef.current += 1; };
  }, [reloadConversations]);

  const reloadFolders = useCallback(async () => {
    const generation = ++folderCollectionGenerationRef.current;
    setFoldersLoading(true);
    setFolderError(null);
    try {
      const { folders: loaded } = await listConversationFolders(client);
      if (folderCollectionGenerationRef.current === generation) {
        setFolders(loaded.filter((folder) => !deletedFolderIdsRef.current.has(folder.id)));
      }
    } catch {
      if (folderCollectionGenerationRef.current === generation) {
        setFolders([]);
        setFolderError("Unable to load folders. Conversations are shown without folders.");
      }
    } finally {
      if (folderCollectionGenerationRef.current === generation) setFoldersLoading(false);
    }
  }, [client]);

  useEffect(() => {
    void reloadFolders();
    return () => { folderCollectionGenerationRef.current += 1; };
  }, [reloadFolders]);

  const refreshFolders = async () => {
    const result = await listConversationFolders(client);
    const current = result.folders.filter((folder) => !deletedFolderIdsRef.current.has(folder.id));
    setFolders(current);
    setFolderError(null);
    return current;
  };

  const refreshFolderAssignments = async () => {
    const result = await listConversations(client);
    const current = new Map(result.conversations.map((item) => [item.conversation_id, item.folder_id]));
    for (const conversation of stateRef.current.conversations) {
      if (current.has(conversation.id)) {
        dispatch({ type: "conversation:setFolder", conversationId: conversation.id, folderId: current.get(conversation.id) ?? null });
      }
    }
    setSearchResults((previous) => previous?.map((conversation) => current.has(conversation.id)
      ? { ...conversation, folderId: current.get(conversation.id) ?? null }
      : conversation) ?? null);
  };

  useEffect(() => {
    const search = searchQuery.trim();
    if (!search) return;

    const generation = ++searchGenerationRef.current;
    let live = true;
    const timeout = setTimeout(() => {
      setSearchLoading(true);
      setSearchError(null);
      void listConversations(client, { search }).then(({ conversations }) => {
        if (!live || searchGenerationRef.current !== generation) return;
        setSearchResults(conversations.map((item) => {
          const existing = stateRef.current.conversations.find(
            (conversation) => conversation.id === item.conversation_id,
          );
          return {
            ...(existing ?? { messages: [], run: undefined }),
            id: item.conversation_id,
            title: item.title,
            createdAt: item.created_at,
            isPinned: item.is_pinned,
            isArchived: item.is_archived,
            folderId: item.folder_id,
            projectId: item.project_id,
          };
        }));
      }).catch(() => {
        if (!live || searchGenerationRef.current !== generation) return;
        setSearchError("Unable to search conversations.");
      }).finally(() => {
        if (live && searchGenerationRef.current === generation) setSearchLoading(false);
      });
    }, 250);

    return () => {
      live = false;
      clearTimeout(timeout);
    };
  }, [client, searchQuery, searchRevision]);

  const manager = useMemo<ConversationManager>(
    () => ({
      state,
      conversations: state.conversations,
      activeConversations: selectActiveConversations(state.conversations),
      archivedConversations: selectArchivedConversations(state.conversations),
      conversationList: searchResults ?? state.conversations,
      searchQuery,
      searchLoading,
      searchError,
      reloadConversations,
      folders,
      foldersLoading,
      folderError,
      reloadFolders,
      createFolder: async (name) => {
        setFolderError(null);
        const created = await createConversationFolder(client, { name: name.trim() });
        deletedFolderIdsRef.current.delete(created.id);
        try {
          await refreshFolders();
        } catch {
          // Keep the successful creation visible even if the follow-up list fails.
          setFolders((current) => [...current, created]);
          setFolderError("Folder created, but the folder list could not be refreshed.");
        }
      },
      renameFolder: async (id, name) => {
        setFolderError(null);
        await updateConversationFolder(client, id, { name: name.trim() });
        try {
          await refreshFolders();
        } catch {
          setFolders((current) => current.map((folder) => folder.id === id ? { ...folder, name: name.trim() } : folder));
          setFolderError("Folder renamed, but the folder list could not be refreshed.");
        }
      },
      deleteFolder: async (id) => {
        setFolderError(null);
        try {
          await deleteFolderRequest(client, id);
        } catch (error) {
          if (!(error instanceof ApiError && error.status === 404)) throw error;
          deletedFolderIdsRef.current.add(id);
          // A stale folder is removed locally and current assignment metadata is
          // reconciled without reloading transcript or selection state.
          await Promise.allSettled([refreshFolders(), refreshFolderAssignments()]);
          setFolders((current) => current.filter((folder) => folder.id !== id));
          setFolderError("That folder was already removed. Sidebar assignments were refreshed.");
          return;
        }
        deletedFolderIdsRef.current.add(id);
        setFolders((current) => current.filter((folder) => folder.id !== id));
        for (const conversation of stateRef.current.conversations) {
          if (conversation.folderId === id) {
            dispatch({ type: "conversation:setFolder", conversationId: conversation.id, folderId: null });
          }
        }
        setSearchResults((current) => current?.map((conversation) => conversation.folderId === id
          ? { ...conversation, folderId: null }
          : conversation) ?? null);
      },
      moveConversation: async (conversationId, folderId) => {
        setFolderError(null);
        const currentConversation = stateRef.current.conversations.find((item) => item.id === conversationId);
        const pending = folderMovesRef.current.get(conversationId);
        if (pending != null) {
          if (pending.targetFolderId === folderId) return pending.promise;
          pending.targetFolderId = folderId;
          return pending.promise;
        }
        if (currentConversation?.folderId === folderId) return;

        const move = { targetFolderId: folderId, promise: Promise.resolve() };
        const operation = (async () => {
          let requestedFolderId = folderId;
          while (true) {
            const destinationWasKnown = requestedFolderId == null ||
              foldersRef.current.some((folder) => folder.id === requestedFolderId);
            let updated: Awaited<ReturnType<typeof setConversationFolderRequest>>;
            try {
              updated = await setConversationFolderRequest(client, conversationId, { folder_id: requestedFolderId });
            } catch (error) {
              if (move.targetFolderId !== requestedFolderId) {
                requestedFolderId = move.targetFolderId;
                continue;
              }
              if (error instanceof ApiError && error.body != null && typeof error.body === "object" &&
                  "error_code" in error.body && error.body.error_code === "conversation_folder_not_found") {
                await Promise.allSettled([refreshFolders(), refreshFolderAssignments()]);
                setFolderError("That folder no longer exists. Conversation assignments were refreshed.");
                return;
              }
              throw error;
            }
            if (move.targetFolderId !== requestedFolderId) {
              requestedFolderId = move.targetFolderId;
              continue;
            }
            if (updated.folder_id != null && destinationWasKnown &&
                !foldersRef.current.some((folder) => folder.id === updated.folder_id)) {
              // A Folder deleted locally while this request was pending must
              // be reconciled from canonical assignments, not reintroduced.
              await refreshFolderAssignments();
              return;
            }
            // The response is canonical. Updating only the folder field keeps
            // Project membership, selection, transcript, and active run intact.
            dispatch({ type: "conversation:setFolder", conversationId, folderId: updated.folder_id });
            setSearchResults((current) => current?.map((item) => item.id === conversationId
              ? { ...item, folderId: updated.folder_id }
              : item) ?? null);
            if (searchQuery.trim()) {
              searchGenerationRef.current += 1;
              setSearchRevision((value) => value + 1);
            }
            return;
          }
        })();
        move.promise = operation;
        folderMovesRef.current.set(conversationId, move);
        try {
          await operation;
        } finally {
          if (folderMovesRef.current.get(conversationId) === move) {
            folderMovesRef.current.delete(conversationId);
          }
        }
      },
      createConversationInFolder: async (folderId) => {
        const created = await createConversation(client, { folder_id: folderId });
        deletedConversationIdsRef.current.delete(created.conversation_id);
        const order = await fetchCanonicalConversationOrder();
        dispatch({ type: "conversation:upsert", conversation: {
          id: created.conversation_id,
          title: created.title,
          createdAt: created.created_at,
          isPinned: created.is_pinned,
          isArchived: created.is_archived,
          folderId: created.folder_id,
          projectId: created.project_id,
          messages: [],
          run: undefined,
        } });
        if (order.conversationIds != null && order.generation === orderGenerationRef.current) {
          dispatch({ type: "conversation:reorder", conversationIds: order.conversationIds });
        }
        if (searchQuery.trim()) {
          searchGenerationRef.current += 1;
          setSearchRevision((value) => value + 1);
        }
        return created.conversation_id;
      },
      createConversationInProject: async (projectId) => {
        const created = await createProjectConversation(client, projectId);
        deletedConversationIdsRef.current.delete(created.conversation_id);
        const order = await fetchCanonicalConversationOrder();
        dispatch({ type: "conversation:upsert", conversation: {
          id: created.conversation_id,
          title: created.title,
          createdAt: created.created_at,
          isPinned: created.is_pinned,
          isArchived: created.is_archived,
          folderId: created.folder_id,
          projectId: created.project_id,
          messages: [],
          run: undefined,
        } });
        if (order.conversationIds != null && order.generation === orderGenerationRef.current) {
          dispatch({ type: "conversation:reorder", conversationIds: order.conversationIds });
        }
        if (searchQuery.trim()) {
          searchGenerationRef.current += 1;
          setSearchRevision((value) => value + 1);
        }
        return created.conversation_id;
      },
      reconcileDeletedProject: (projectId) => {
        for (const conversation of stateRef.current.conversations) {
          if (conversation.projectId === projectId) {
            dispatch({ type: "conversation:setProject", conversationId: conversation.id, projectId: null });
          }
        }
        setSearchResults((current) => current?.map((item) => item.projectId === projectId
          ? { ...item, projectId: null }
          : item) ?? null);
      },
      setConversationProject: async (conversationId, projectId) => {
        try {
          const updated = await setConversationProjectRequest(client, conversationId, { project_id: projectId });
          dispatch({ type: "conversation:setProject", conversationId, projectId: updated.project_id });
          setSearchResults((current) => current?.map((item) => item.id === conversationId
            ? { ...item, projectId: updated.project_id }
            : item) ?? null);
        } catch (error) {
          if (error instanceof ApiError && error.status === 404 && error.body != null &&
              typeof error.body === "object" && "error_code" in error.body &&
              error.body.error_code === "conversation_not_found") {
            reconcileMissingConversation(conversationId);
          }
          throw error;
        }
      },
      setConversationPinned: async (conversationId, isPinned) => {
        const updated = await setConversationPinnedRequest(client, conversationId, { is_pinned: isPinned });
        dispatch({ type: "conversation:setPinned", conversationId, isPinned: updated.is_pinned });
        if (searchQuery.trim()) {
          searchGenerationRef.current += 1;
          setSearchRevision((value) => value + 1);
        }
        void refreshCanonicalConversationOrder();
      },
      setConversationArchived: async (conversationId, isArchived) => {
        const pending = archiveMovesRef.current.get(conversationId);
        if (pending != null) {
          pending.targetArchived = isArchived;
          return pending.promise;
        }
        const move = { targetArchived: isArchived, promise: Promise.resolve() };
        const operation = (async () => {
          let requestedArchived = isArchived;
          while (true) {
            const updated = await setConversationArchivedRequest(client, conversationId, { is_archived: requestedArchived });
            if (move.targetArchived !== requestedArchived) {
              requestedArchived = move.targetArchived;
              continue;
            }
            dispatch({ type: "conversation:setArchived", conversationId, isArchived: updated.is_archived });
            if (searchQuery.trim()) {
              searchGenerationRef.current += 1;
              setSearchRevision((value) => value + 1);
            }
            return;
          }
        })();
        move.promise = operation;
        archiveMovesRef.current.set(conversationId, move);
        try {
          await operation;
        } finally {
          if (archiveMovesRef.current.get(conversationId) === move) {
            archiveMovesRef.current.delete(conversationId);
          }
        }
      },
      setSearchQuery: (query) => {
        searchGenerationRef.current += 1;
        setSearchQueryState(query);
        setSearchError(null);
        if (!query.trim()) {
          setSearchResults(null);
          setSearchLoading(false);
          setSearchError(null);
        }
      },
      activeConversation: getActiveConversation(state),
      createConversation: async () => {
        const created = await createConversation(client);
        deletedConversationIdsRef.current.delete(created.conversation_id);
        const order = await fetchCanonicalConversationOrder();
        dispatch({ type: "conversation:upsert", conversation: {
          id: created.conversation_id, title: created.title, createdAt: created.created_at,
          isPinned: created.is_pinned, isArchived: created.is_archived, folderId: created.folder_id,
          projectId: created.project_id,
          messages: [], run: undefined,
        } });
        if (order.conversationIds != null && order.generation === orderGenerationRef.current) {
          dispatch({ type: "conversation:reorder", conversationIds: order.conversationIds });
        }
        if (searchQuery.trim()) {
          searchGenerationRef.current += 1;
          setSearchRevision((value) => value + 1);
        }
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
          void refreshCanonicalConversationOrder();
          if (searchQuery.trim()) {
            searchGenerationRef.current += 1;
            setSearchRevision((value) => value + 1);
          }
        }, onError: (error) => {
          if (error instanceof ApiError && error.status === 404) {
            reconcileMissingConversation(id);
            return;
          }
          dispatch({
            type: "conversation:messagesLoadFailure",
            conversationId: id,
            error: presentAvaError(error, "Unable to rename conversation."),
          });
        } })(id, title);
      },
      deleteConversation: async (id) => {
        try {
          await deleteConversation(client, id);
        } catch (error) {
          const isAlreadyGone = error instanceof ApiError && error.status === 404;
          if (!isAlreadyGone) throw error;
        }

        // A successful delete and a 404 share the same local reconciliation.
        deletedConversationIdsRef.current.add(id);
        searchGenerationRef.current += 1;
        setSearchLoading(false);
        reconcileMissingConversation(id);
        setSearchResults((current) => current?.filter((item) => item.id !== id) ?? null);
      },
      addUserMessage: async (conversationId, content) => {
        let resolvedConversationId = conversationId;
        if (resolvedConversationId == null) {
          const created = await createConversation(client, { title: content.trim().slice(0, 40) });
          resolvedConversationId = created.conversation_id;
          deletedConversationIdsRef.current.delete(created.conversation_id);
          const order = await fetchCanonicalConversationOrder();
          dispatch({ type: "conversation:upsert", conversation: { id: created.conversation_id, title: created.title, createdAt: created.created_at, messages: [], run: undefined } });
          if (order.conversationIds != null && order.generation === orderGenerationRef.current) {
            dispatch({ type: "conversation:reorder", conversationIds: order.conversationIds });
          }
          if (searchQuery.trim()) {
            searchGenerationRef.current += 1;
            setSearchRevision((value) => value + 1);
          }
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
    [state, searchQuery, searchResults, searchLoading, searchError, reloadConversations, folders, foldersLoading, folderError, reloadFolders],
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
