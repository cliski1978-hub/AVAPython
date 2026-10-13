import {
  defaultTheme,
  Modal,
  shadcn,
  PlusIcon,
  SquarePenIcon,
  SearchIcon,
  XIcon,
  FolderIcon,
  FolderOpenIcon,
  FolderPlusIcon,
  RocketIcon,
  EllipsisIcon,
  LoaderCircleIcon,
  useInteraction,
} from "@ava/ui-core";
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  type DragEndEvent,
  type KeyboardCoordinateGetter,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import type { Conversation } from "../types";
import type { ConversationFolder } from "@ava/contracts";
import type { Project } from "@ava/contracts";
import { isActiveRunStatus } from "../lib/runActions";

export interface ConversationListProps {
  conversations: Conversation[];
  activeConversationId: string | null;
  onNewChat: () => void;
  onSelect: (id: string) => void;
  /** Renames a conversation through the backend (authoritative). When omitted,
   * conversation items expose no action menu. */
  onRename?: (id: string, title: string) => Promise<void>;
  /** Permanently deletes a conversation after explicit confirmation. */
  onDelete?: (id: string) => Promise<void>;
  /** Shared conversation error (e.g. a failed rename), rendered as a strip. */
  error?: string | null;
  searchQuery?: string;
  onSearchChange?: (query: string) => void;
  searchLoading?: boolean;
  searchError?: string | null;
  conversationsLoading?: boolean;
  conversationLoadError?: string | null;
  onRetryConversations?: () => void;
  folders?: ConversationFolder[];
  foldersLoading?: boolean;
  folderError?: string | null;
  onRetryFolders?: () => void;
  onCreateFolder?: (name: string) => Promise<void>;
  onRenameFolder?: (id: string, name: string) => Promise<void>;
  onDeleteFolder?: (id: string) => Promise<void>;
  onMoveConversation?: (conversationId: string, folderId: string | null) => Promise<void>;
  onNewChatInFolder?: (folderId: string) => Promise<void>;
  projects?: Project[];
  projectsLoading?: boolean;
  projectsError?: string | null;
  onRetryProjects?: () => void;
  projectConversationIds?: Record<string, string[]>;
  projectConversationLoading?: Record<string, boolean>;
  projectConversationErrors?: Record<string, string | null>;
  onExpandProject?: (projectId: string) => void;
  onNewChatInProject?: (projectId: string) => Promise<void>;
  onRetryProjectConversations?: (projectId: string) => void;
  onSetConversationProject?: (conversationId: string, projectId: string | null) => Promise<void>;
  onSetConversationPinned?: (conversationId: string, isPinned: boolean) => Promise<void>;
  onSetConversationArchived?: (conversationId: string, isArchived: boolean) => Promise<void>;
  onOpenConversationSystemPrompts?: (conversationId: string, title: string) => void;
  onOpenFolderSystemPrompts?: (folderId: string, name: string) => void;
  activeConversations?: Conversation[];
  archivedConversations?: Conversation[];
}

const t = defaultTheme;
const semantic = (token: string) => `hsl(var(--${token}))`;

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
    minWidth: 0,
    minHeight: 44,
    boxSizing: "border-box",
    padding: `0 ${t.spacing.md}px`,
    borderRadius: t.radius.md,
    border: `${t.border.width}px solid ${
      active ? semantic("primary") : "transparent"
    }`,
    background: active ? semantic("secondary") : "transparent",
    color: semantic("foreground"),
    fontSize: t.font.sizeSm,
    fontWeight: active ? t.font.weightSemibold : t.font.weightNormal,
    fontFamily: t.font.family,
    textAlign: "left",
    cursor: "pointer",
    outline: "none",
    transition:
      "background 120ms ease, border-color 120ms ease, color 120ms ease, box-shadow 120ms ease",
    ...(interaction.hovered ? { background: semantic("secondary") } : {}),
    ...(interaction.focused
      ? { boxShadow: "0 0 0 2px hsl(var(--ring) / 0.25)" }
      : {}),
  };
}

const selectStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  alignSelf: "stretch",
  gap: t.spacing.sm,
  flex: 1,
  minWidth: 0,
  padding: `${t.spacing.sm}px 0`,
  border: "none",
  background: "transparent",
  color: "inherit",
  fontSize: "inherit",
  fontWeight: "inherit",
  fontFamily: "inherit",
  textAlign: "left",
  cursor: "pointer",
  outline: "none",
  overflow: "hidden",
};

const titleStyle: CSSProperties = {
  flex: "1 1 0%",
  minWidth: 0,
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
  background: semantic("popover"),
  border: `${t.border.width}px solid ${semantic("border")}`,
  borderRadius: t.radius.md,
  boxShadow: "0 4px 12px hsl(var(--foreground) / 0.08)",
};

const menuItemStyle: CSSProperties = {
  display: "block",
  width: "100%",
  boxSizing: "border-box",
  padding: `${t.spacing.sm}px ${t.spacing.md}px`,
  border: "none",
  borderRadius: t.radius.sm,
  background: "transparent",
  color: semantic("popover-foreground"),
  fontSize: t.font.sizeSm,
  fontFamily: t.font.family,
  textAlign: "left",
  cursor: "pointer",
};

const folderDropKeyboardCoordinates: KeyboardCoordinateGetter = (
  event,
  { currentCoordinates, context },
) => {
  if (event.code !== "ArrowDown" && event.code !== "ArrowUp") return;
  const activeRect = context.collisionRect;
  if (activeRect == null) return;

  const direction = event.code === "ArrowDown" ? 1 : -1;
  const targets = context.droppableContainers.getEnabled()
    .filter((container) => container.data.current?.type === "conversation-folder")
    .map((container) => ({ container, rect: context.droppableRects.get(container.id) }))
    .filter((entry): entry is { container: (typeof entry.container); rect: NonNullable<typeof entry.rect> } => entry.rect != null)
    .filter(({ rect }) => direction > 0 ? rect.top > activeRect.top : rect.top < activeRect.top)
    .sort((left, right) => direction * (left.rect.top - right.rect.top));
  const target = targets[0];
  if (target == null) return;

  event.preventDefault();
  return {
    x: currentCoordinates.x + target.rect.left - activeRect.left,
    y: currentCoordinates.y + target.rect.top - activeRect.top,
  };
};

/** Inline title editor: Enter confirms, Escape cancels, blank input cancels. */
function RenameEditor({
  initialTitle,
  disabled,
  onConfirm,
  onCancel,
}: {
  initialTitle: string;
  disabled: boolean;
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
    if (disabled) return;
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
        if (disabled) return;
        if (event.key === "Enter") {
          event.preventDefault();
          submit();
        } else if (event.key === "Escape") {
          event.preventDefault();
          onCancel();
        }
      }}
    >
      <shadcn.Input
        aria-label="Rename conversation"
        value={value}
        onChange={(event) => setValue(event.currentTarget.value)}
        disabled={disabled}
      />
    </div>
  );
}

function ConversationFolderDropTarget({
  folderId,
  disabled,
  children,
  style,
}: {
  folderId: string | null;
  disabled: boolean;
  children: ReactNode;
  style: CSSProperties;
}) {
  const targetId = folderId == null ? "ungrouped" : folderId;
  const { isOver, setNodeRef } = useDroppable({
    id: `folder-target:${targetId}`,
    disabled,
    data: { type: "conversation-folder", folderId },
  });

  return (
    <section
      ref={setNodeRef}
      data-conversation-folder={folderId ?? undefined}
      data-ungrouped-conversations={folderId == null ? "" : undefined}
      data-folder-drop-target={targetId}
      data-drop-target-active={isOver ? "" : undefined}
      style={{
        ...style,
        ...(isOver ? { outline: `2px solid ${semantic("primary")}`, outlineOffset: 2, borderRadius: t.radius.md } : {}),
      }}
    >
      {children}
    </section>
  );
}

function ConversationItem({
  conversation,
  rowKey,
  active,
  onSelect,
  onRename,
  onDeleteRequested,
  renaming,
  renameSaving,
  menuOpen,
  onOpenMenu,
  onCloseMenu,
  onStartRename,
  onRenameDone,
  onRequestMove,
  canMoveToFolder = true,
  onSetPinned,
  onSetArchived,
  onOpenSystemPrompts,
  showArchivedStatus = false,
  dragDisabled = true,
}: {
  conversation: Conversation;
  rowKey: string;
  active: boolean;
  onSelect: (id: string) => void;
  onRename?: (id: string, title: string) => Promise<void>;
  onDeleteRequested?: (id: string) => void;
  renaming: boolean;
  renameSaving: boolean;
  menuOpen: boolean;
  onOpenMenu: (id: string) => void;
  onCloseMenu: () => void;
  onStartRename: (rowKey: string) => void;
  onRenameDone: (id: string, title: string) => void;
  onRequestMove?: (conversationId: string, allowFolder: boolean) => void;
  canMoveToFolder?: boolean;
  onSetPinned?: (conversationId: string, isPinned: boolean) => Promise<void>;
  onSetArchived?: (conversationId: string, isArchived: boolean) => Promise<void>;
  onOpenSystemPrompts?: (conversationId: string, title: string) => void;
  showArchivedStatus?: boolean;
  dragDisabled?: boolean;
}) {
  const {
    attributes,
    listeners,
    setNodeRef,
    isDragging,
  } = useDraggable({
    // In the Project section the same conversation may also appear in its
    // Folder section. Only the canonical Folder/ungrouped row is draggable;
    // keep disabled duplicate registrations distinct inside dnd-kit.
    id: dragDisabled ? `${conversation.id}:${rowKey}` : conversation.id,
    disabled: dragDisabled,
    data: { type: "conversation", conversationId: conversation.id },
  });
  const interaction = useInteraction(true);
  const [metadataPending, setMetadataPending] = useState(false);
  const [metadataError, setMetadataError] = useState<string | null>(null);
  const showMenu = onRename != null || onDeleteRequested != null || onRequestMove != null || onSetPinned != null || onSetArchived != null || onOpenSystemPrompts != null;

  const updateMetadata = async (callback: typeof onSetPinned, next: boolean, safeError: string) => {
    if (callback == null || metadataPending) return;
    setMetadataPending(true);
    setMetadataError(null);
    try {
      await callback(conversation.id, next);
      onCloseMenu();
    } catch {
      setMetadataError(safeError);
    } finally {
      setMetadataPending(false);
    }
  };

  return (
    <div
      ref={setNodeRef}
      className="group min-w-0"
      data-conversation-row={conversation.id}
      data-dragging-conversation={isDragging ? "" : undefined}
      style={{ ...conversationRowStyle(active, interaction), ...(isDragging ? { opacity: 0.45 } : {}) }}
      onMouseEnter={interaction.onMouseEnter}
      onMouseLeave={interaction.onMouseLeave}
      onFocus={interaction.onFocus}
      onBlur={interaction.onBlur}
    >
      {renaming && showMenu ? (
        <RenameEditor
          initialTitle={conversation.title}
          disabled={renameSaving}
          onConfirm={(title) => onRenameDone(conversation.id, title)}
          onCancel={onCloseMenu}
        />
      ) : (
        <>
          <button
            {...attributes}
            {...listeners}
            type="button"
            data-conversation-item={conversation.id}
            data-draggable-conversation={dragDisabled ? undefined : conversation.id}
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
                  background: semantic("primary"),
                  flexShrink: 0,
                }}
              />
            )}
            <span data-conversation-title="" style={titleStyle}>{conversation.title}</span>
            {showArchivedStatus && conversation.isArchived && (
              <span data-archived-indicator="" style={{ color: semantic("muted-foreground"), fontSize: t.font.sizeXs, flexShrink: 0 }}>
                Archived
              </span>
            )}
          </button>
          <span
            role={isActiveRunStatus(conversation.run?.backendStatus) ? "img" : undefined}
            aria-label={isActiveRunStatus(conversation.run?.backendStatus) ? "Response in progress" : undefined}
            title={isActiveRunStatus(conversation.run?.backendStatus) ? "Response in progress" : undefined}
            data-conversation-run-indicator={isActiveRunStatus(conversation.run?.backendStatus) ? "active" : "idle"}
            style={{ width: 16, height: 16, flex: "0 0 16px", display: "grid", placeItems: "center" }}
          >
            {isActiveRunStatus(conversation.run?.backendStatus) && (
              <LoaderCircleIcon aria-hidden className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
            )}
          </span>
          {showMenu && (
            <span
              className={active || menuOpen
                ? "flex shrink-0 opacity-100 transition-opacity"
                : "flex shrink-0 pointer-events-none opacity-0 transition-opacity group-hover:pointer-events-auto group-hover:opacity-100 group-focus-within:pointer-events-auto group-focus-within:opacity-100"}
              data-conversation-actions=""
              style={{ display: "flex", flexShrink: 0 }}
            >
              <shadcn.IconButton
                size="compact"
                icon={EllipsisIcon}
                appearance="row-action"
                label={`Conversation actions for ${conversation.title}`}
                tooltip="Conversation actions"
                aria-haspopup="menu"
                aria-expanded={menuOpen}
                className="shrink-0"
                onClick={() =>
                  menuOpen ? onCloseMenu() : onOpenMenu(rowKey)
                }
              />
            </span>
          )}
          {menuOpen && (
            <div style={menuStyle} role="menu" data-conversation-menu="">
              {onRename != null && (
                <button
                  type="button"
                  role="menuitem"
                  data-conversation-rename=""
                  disabled={renameSaving}
                  style={{
                    ...menuItemStyle,
                    ...(renameSaving ? { opacity: 0.55, cursor: "not-allowed" } : {}),
                  }}
                  onClick={() => onStartRename(rowKey)}
                >
                  Rename
                </button>
              )}
              {onSetPinned != null && (
                <button type="button" role="menuitem" disabled={metadataPending} style={menuItemStyle}
                  onClick={() => void updateMetadata(onSetPinned, !conversation.isPinned, "Unable to update this conversation's pin. Please try again.")}>
                  {conversation.isPinned ? "Unpin" : "Pin"}
                </button>
              )}
              {onSetArchived != null && (
                <button type="button" role="menuitem" disabled={metadataPending} style={menuItemStyle}
                  onClick={() => void updateMetadata(onSetArchived, !conversation.isArchived, "Unable to update this conversation's archive status. Please try again.")}>
                  {conversation.isArchived ? "Restore" : "Archive"}
                </button>
              )}
              {onOpenSystemPrompts != null && <button type="button" role="menuitem" style={menuItemStyle} onClick={() => { onCloseMenu(); onOpenSystemPrompts(conversation.id, conversation.title); }}>System Prompts</button>}
              {onDeleteRequested != null && (
                <button
                  type="button"
                  role="menuitem"
                  data-conversation-delete=""
                  style={{ ...menuItemStyle, color: semantic("destructive") }}
                  onClick={() => {
                    onCloseMenu();
                    onDeleteRequested(conversation.id);
                  }}
                >
                  Delete
                </button>
              )}
              {onRequestMove != null && <button type="button" role="menuitem" data-conversation-move=""
                style={menuItemStyle} onClick={() => { onCloseMenu(); onRequestMove(conversation.id, canMoveToFolder); }}>Move</button>}
            </div>
          )}
          {metadataError != null && <div role="alert" style={{ fontSize: t.font.sizeXs, color: semantic("destructive") }}>{metadataError}</div>}
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
  onDelete,
  error,
  searchQuery = "",
  onSearchChange,
  searchLoading = false,
  searchError = null,
  conversationsLoading = false,
  conversationLoadError = null,
  onRetryConversations,
  folders = [],
  foldersLoading = false,
  folderError = null,
  onRetryFolders,
  onCreateFolder,
  onRenameFolder,
  onDeleteFolder,
  onMoveConversation,
  onNewChatInFolder,
  projects = [],
  projectsLoading = false,
  projectsError = null,
  onRetryProjects,
  projectConversationIds = {},
  projectConversationLoading = {},
  projectConversationErrors = {},
  onExpandProject,
  onNewChatInProject,
  onRetryProjectConversations,
  onSetConversationProject,
  onSetConversationPinned,
  onSetConversationArchived,
  onOpenConversationSystemPrompts,
  onOpenFolderSystemPrompts,
  activeConversations: activeConversationsProp,
  archivedConversations: archivedConversationsProp,
}: ConversationListProps) {
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameSaving, setRenameSaving] = useState(false);
  const renameInFlightRef = useRef(false);
  const [menuOpenId, setMenuOpenId] = useState<string | null>(null);
  const [deleteTargetId, setDeleteTargetId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [collapsedFolders, setCollapsedFolders] = useState<Record<string, boolean>>({});
  const [folderMenuOpenId, setFolderMenuOpenId] = useState<string | null>(null);
  const [folderEditor, setFolderEditor] = useState<{ id: string | null; name: string } | null>(null);
  const [folderEditorName, setFolderEditorName] = useState("");
  const [folderEditorError, setFolderEditorError] = useState<string | null>(null);
  const [folderSaving, setFolderSaving] = useState(false);
  const [deleteFolderTarget, setDeleteFolderTarget] = useState<ConversationFolder | null>(null);
  const [deleteFolderError, setDeleteFolderError] = useState<string | null>(null);
  const [deletingFolder, setDeletingFolder] = useState(false);
  const [expandedProjects, setExpandedProjects] = useState<Record<string, boolean>>({});
  const [archivedView, setArchivedView] = useState(false);
  const [archiveStatusMessage, setArchiveStatusMessage] = useState<string | null>(null);
  const activeViewButtonRef = useRef<HTMLButtonElement>(null);
  const archivedViewButtonRef = useRef<HTMLButtonElement>(null);
  const [creatingProjectChatId, setCreatingProjectChatId] = useState<string | null>(null);
  const [creatingFolderChatId, setCreatingFolderChatId] = useState<string | null>(null);
  const [projectActionError, setProjectActionError] = useState<string | null>(null);
  const [moveError, setMoveError] = useState<string | null>(null);
  const [moveTarget, setMoveTarget] = useState<{ conversationId: string; allowFolder: boolean } | null>(null);
  const [moveType, setMoveType] = useState<"project" | "folder">("project");
  const [moveDestination, setMoveDestination] = useState("");
  const [moveSaving, setMoveSaving] = useState(false);
  const [moveDialogError, setMoveDialogError] = useState<string | null>(null);
  const [folderChatError, setFolderChatError] = useState<string | null>(null);
  const deleteTarget = conversations.find((item) => item.id === deleteTargetId) ?? null;
  const searchActive = searchQuery.trim().length > 0;
  const conversationCollectionSettled = conversationsLoading !== true && conversationLoadError == null;
  const activeConversationItems = activeConversationsProp ?? conversations.filter((conversation) => !conversation.isArchived);
  const archivedConversationItems = archivedConversationsProp ?? conversations.filter((conversation) => conversation.isArchived);
  const dragEnabled = onMoveConversation != null && !foldersLoading && !searchActive && !archivedView;
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: folderDropKeyboardCoordinates }),
  );
  const showFolderSections = folders.length > 0 || (onCreateFolder != null && folderError == null);
  const activeProjects = projects.filter((project) => !project.is_archived);
  const folderGroups = folders.map((folder) => ({
    folder,
    conversations: activeConversationItems.filter((conversation) => conversation.folderId === folder.id),
  })).filter(({ conversations: items }) => !searchActive || items.length > 0);
  const ungrouped = activeConversationItems.filter((conversation) =>
    (conversation.folderId == null || !folders.some((folder) => folder.id === conversation.folderId)) &&
    (conversation.projectId == null || projectsError != null || projectConversationErrors[conversation.projectId] != null ||
      !activeProjects.some((project) => project.id === conversation.projectId)),
  );

  const requestDelete = (id: string) => {
    setDeleteError(null);
    setDeleteTargetId(id);
  };

  const confirmDelete = async () => {
    if (deleteTarget == null || onDelete == null || deleting) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await onDelete(deleteTarget.id);
      setDeleteTargetId(null);
    } catch (error) {
      const isActiveRunConflict =
        typeof error === "object" && error != null &&
        "status" in error && error.status === 409 &&
        "body" in error && typeof error.body === "object" && error.body != null &&
        "error_code" in error.body && error.body.error_code === "conversation_run_active";
      setDeleteError(isActiveRunConflict
        ? "Conversation is still generating. Stop the active response before deleting this conversation."
        : "Unable to delete this conversation. Please try again.");
    } finally {
      setDeleting(false);
    }
  };

  const startRename = (id: string) => {
    if (renameInFlightRef.current) return;
    setMenuOpenId(null);
    setRenamingId(id);
  };

  const finishRename = async (id: string, title: string) => {
    if (renameInFlightRef.current || onRename == null) return;
    renameInFlightRef.current = true;
    setRenameSaving(true);
    try {
      await onRename(id, title);
    } catch {
      // A failed rename never pretends success: the reducer keeps the prior
      // authoritative title and the shared `error` strip surfaces the failure.
    } finally {
      renameInFlightRef.current = false;
      setRenameSaving(false);
      setRenamingId(null);
    }
  };

  const openFolderEditor = (folder: ConversationFolder | null) => {
    setFolderMenuOpenId(null);
    setFolderEditor(folder == null ? { id: null, name: "" } : { id: folder.id, name: folder.name });
    setFolderEditorName(folder?.name ?? "");
    setFolderEditorError(null);
  };

  const saveFolder = async () => {
    if (folderSaving || folderEditor == null) return;
    const name = folderEditorName.trim();
    if (!name) { setFolderEditorError("Enter a folder name."); return; }
    const save = folderEditor.id == null ? onCreateFolder : onRenameFolder;
    if (save == null) return;
    setFolderSaving(true);
    setFolderEditorError(null);
    try {
      await (folderEditor.id == null ? onCreateFolder?.(name) : onRenameFolder?.(folderEditor.id, name));
      setFolderEditor(null);
    } catch {
      setFolderEditorError(folderEditor.id == null ? "Unable to create folder. Please try again." : "Unable to rename folder. Please try again.");
    } finally {
      setFolderSaving(false);
    }
  };

  const confirmDeleteFolder = async () => {
    if (deleteFolderTarget == null || onDeleteFolder == null || deletingFolder) return;
    setDeletingFolder(true);
    setDeleteFolderError(null);
    try {
      await onDeleteFolder(deleteFolderTarget.id);
      setDeleteFolderTarget(null);
    } catch {
      setDeleteFolderError("Unable to delete folder. Its conversations are unchanged. Please try again.");
    } finally {
      setDeletingFolder(false);
    }
  };

  const requestMove = (conversationId: string, folderId: string | null) => {
    if (onMoveConversation == null) return;
    setMoveError(null);
    void onMoveConversation(conversationId, folderId).catch(() => {
      setMoveError("Unable to move this conversation. Please try again.");
    });
  };

  const handleDragEnd = ({ active, over }: DragEndEvent) => {
    if (!dragEnabled || over == null || onMoveConversation == null) return;
    const activeData = active.data.current;
    const targetData = over.data.current;
    if (activeData?.type !== "conversation" || targetData?.type !== "conversation-folder") return;
    const conversationId = activeData.conversationId;
    const folderId = targetData.folderId as string | null;
    const conversation = conversations.find((item) => item.id === conversationId);
    if (conversation == null || conversation.folderId === folderId) return;
    if (folderId != null && !folders.some((folder) => folder.id === folderId)) return;
    requestMove(conversation.id, folderId);
  };

  const createFolderChat = async (folderId: string) => {
    if (onNewChatInFolder == null || creatingFolderChatId != null) return;
    setCreatingFolderChatId(folderId);
    setFolderChatError(null);
    try {
      await onNewChatInFolder(folderId);
      setFolderMenuOpenId(null);
    } catch {
      setFolderChatError("Unable to create a chat in this folder. Please try again.");
    } finally {
      setCreatingFolderChatId(null);
    }
  };

  const openMoveDialog = (conversationId: string, allowFolder: boolean) => {
    setMoveTarget({ conversationId, allowFolder });
    setMoveType(onSetConversationProject != null ? "project" : "folder");
    setMoveDestination("");
    setMoveDialogError(null);
  };

  const submitMove = async () => {
    if (moveTarget == null || moveDestination === "" || moveSaving) return;
    setMoveSaving(true);
    setMoveDialogError(null);
    try {
      if (moveType === "project") {
        if (onSetConversationProject == null) return;
        await onSetConversationProject(moveTarget.conversationId, moveDestination === "__none__" ? null : moveDestination);
      } else {
        if (onMoveConversation == null) return;
        await onMoveConversation(moveTarget.conversationId, moveDestination === "__ungrouped__" ? null : moveDestination);
      }
      setMoveTarget(null);
    } catch {
      setMoveDialogError(moveType === "project"
        ? "Unable to move this conversation to the Project. Please try again."
        : "Unable to move this conversation to the Folder. Please try again.");
    } finally {
      setMoveSaving(false);
    }
  };

  const toggleProject = (projectId: string) => {
    const expanding = expandedProjects[projectId] !== true;
    setExpandedProjects((current) => ({ ...current, [projectId]: expanding }));
    if (expanding) onExpandProject?.(projectId);
  };

  const createProjectChat = async (projectId: string) => {
    if (onNewChatInProject == null || creatingProjectChatId != null) return;
    setCreatingProjectChatId(projectId);
    setProjectActionError(null);
    try {
      await onNewChatInProject(projectId);
    } catch {
      setProjectActionError("Unable to create a chat in this Project. Please try again.");
    } finally {
      setCreatingProjectChatId(null);
    }
  };

  const listStyle: CSSProperties = {
    display: "flex",
    flexDirection: "column",
    gap: t.spacing.sm,
    width: "100%",
    minWidth: 0,
  };

  const errorStyle: CSSProperties = {
    boxSizing: "border-box",
    padding: `${t.spacing.sm}px ${t.spacing.md}px`,
    borderRadius: t.radius.md,
    background: semantic("card"),
    border: `${t.border.width}px solid ${semantic("destructive")}`,
    color: semantic("destructive"),
    fontSize: t.font.sizeSm,
    fontFamily: t.font.family,
  };

  const changeArchiveStatus = async (conversationId: string, isArchived: boolean) => {
    if (onSetConversationArchived == null) return;
    await onSetConversationArchived(conversationId, isArchived);
    setArchiveStatusMessage(isArchived ? "Conversation archived." : "Conversation restored.");
    const focusTarget = () => {
      const item = Array.from(document.querySelectorAll<HTMLElement>("[data-conversation-item]"))
        .find((element) => element.dataset.conversationItem === conversationId);
      const selected = activeConversationId == null ? undefined : Array.from(
        document.querySelectorAll<HTMLElement>("[data-conversation-item]"),
      ).find((element) => element.dataset.conversationItem === activeConversationId);
      (item ?? selected ?? (isArchived ? activeViewButtonRef.current : archivedViewButtonRef.current))?.focus();
    };
    if (typeof requestAnimationFrame === "function") requestAnimationFrame(focusTarget);
    else setTimeout(focusTarget, 0);
  };

  const renderConversation = (
    conversation: Conversation,
    rowKey: string,
    options: { dragDisabled?: boolean; showArchivedStatus?: boolean; allowFolderMove?: boolean } = {},
  ) => (
    <ConversationItem
      key={rowKey}
      rowKey={rowKey}
      conversation={conversation}
      active={conversation.id === activeConversationId}
      onSelect={onSelect}
      onRename={onRename}
      onDeleteRequested={onDelete == null ? undefined : requestDelete}
      renaming={renamingId === rowKey}
      renameSaving={renameSaving}
      menuOpen={menuOpenId === rowKey}
      onOpenMenu={(key) => { setRenamingId(null); setMenuOpenId(key); }}
      onCloseMenu={() => { setRenamingId(null); setMenuOpenId(null); }}
      onStartRename={startRename}
      onRenameDone={(id, title) => void finishRename(id, title)}
      onRequestMove={onSetConversationProject == null && (options.allowFolderMove === false || onMoveConversation == null)
        ? undefined
        : openMoveDialog}
      canMoveToFolder={options.allowFolderMove !== false && onMoveConversation != null}
      dragDisabled={options.dragDisabled ?? !dragEnabled}
      onSetPinned={onSetConversationPinned}
      onSetArchived={onSetConversationArchived == null ? undefined : changeArchiveStatus}
      onOpenSystemPrompts={onOpenConversationSystemPrompts}
      showArchivedStatus={options.showArchivedStatus}
    />
  );

  return (
    <DndContext sensors={sensors} onDragEnd={handleDragEnd}>
    <div data-conversation-list="" style={listStyle}>
      <span data-new-chat>
        <shadcn.Button variant="navigation" size="sm" className="w-full justify-start gap-2" onClick={onNewChat}>
          <SquarePenIcon aria-hidden="true" focusable="false" className="size-4" />
          New Chat
        </shadcn.Button>
      </span>
      {!archivedView && onCreateFolder != null && (
        <span data-new-folder>
          <shadcn.Button variant="outline" className="w-full justify-start gap-2" onClick={() => openFolderEditor(null)}>
            <FolderPlusIcon aria-hidden="true" focusable="false" className="size-4" />
            New Folder
          </shadcn.Button>
        </span>
      )}
      {onSearchChange != null && (
        <div
          data-conversation-search=""
          style={{ display: "flex", alignItems: "center", gap: t.spacing.xs }}
          onKeyDown={(event) => {
            if (event.key === "Escape" && searchQuery.length > 0) {
              event.preventDefault();
              onSearchChange("");
            } else if (event.key === "Enter") {
              event.preventDefault();
            }
          }}
        >
          <div className="relative min-w-0 flex-1">
            <SearchIcon aria-hidden="true" focusable="false" className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <shadcn.Input
              type="search"
              aria-label="Search conversations"
              placeholder="Search conversations"
              value={searchQuery}
              onChange={(event) => onSearchChange(event.currentTarget.value)}
              className="h-9 pl-9 pr-10"
            />
            {searchQuery.length > 0 && (
              <shadcn.IconButton
                icon={XIcon}
                label="Clear conversation search"
                tooltip="Clear search"
                size="compact"
                className="absolute right-1 top-1/2 -translate-y-1/2"
                onClick={() => onSearchChange("")}
              />
            )}
          </div>
        </div>
      )}
      <nav aria-label="Conversation views" data-conversation-view-nav="">
        <div role="group" aria-label="Conversation views" className="grid w-full grid-cols-2 gap-1 rounded-md bg-muted p-1">
          <shadcn.Button
            ref={activeViewButtonRef}
            variant={archivedView ? "ghost" : "outline"}
            size="sm"
            aria-current={!archivedView ? "page" : undefined}
            aria-pressed={!archivedView}
            data-conversation-view="active"
            onClick={() => setArchivedView(false)}
            style={archivedView ? undefined : { backgroundColor: "#000000", color: "#ffffff" }}
            className="h-8 w-full text-foreground dark:bg-black dark:text-white dark:hover:bg-neutral-950 dark:aria-pressed:bg-black dark:aria-pressed:text-white dark:aria-pressed:hover:bg-neutral-950"
          >Active</shadcn.Button>
          <shadcn.Button
            ref={archivedViewButtonRef}
            variant={archivedView ? "outline" : "ghost"}
            size="sm"
            aria-current={archivedView ? "page" : undefined}
            aria-pressed={archivedView}
            data-conversation-view="archived"
            onClick={() => setArchivedView(true)}
            style={archivedView ? { backgroundColor: "#000000", color: "#ffffff" } : undefined}
            className="h-8 w-full text-foreground dark:bg-black dark:text-white dark:hover:bg-neutral-950 dark:aria-pressed:bg-black dark:aria-pressed:text-white dark:aria-pressed:hover:bg-neutral-950"
          >Archived</shadcn.Button>
        </div>
      </nav>
      {archiveStatusMessage != null && (
        <span role="status" aria-live="polite" data-conversation-archive-status="" style={{
          position: "absolute", width: 1, height: 1, padding: 0, margin: -1, overflow: "hidden",
          clip: "rect(0, 0, 0, 0)", whiteSpace: "nowrap", border: 0,
        }}>{archiveStatusMessage}</span>
      )}
      {!archivedView && !searchActive && <section data-projects-sidebar="" aria-label="Projects" style={{ display: "grid", gap: t.spacing.xs }}>
        <strong className="px-2 py-1 text-sm font-semibold text-foreground">Projects</strong>
        {projectsLoading && <span role="status" style={{ padding: `${t.spacing.xs}px ${t.spacing.md}px`, color: semantic("muted-foreground") }}>Loading Projects…</span>}
        {projectsError != null && (
          <div role="alert" data-projects-load-error="" style={errorStyle}>
            <span>{projectsError}</span>
            {onRetryProjects != null && <button type="button" onClick={onRetryProjects} style={menuItemStyle}>Retry Projects</button>}
          </div>
        )}
        {projectActionError != null && <div role="alert" data-project-action-error="" style={errorStyle}>{projectActionError}</div>}
        {!projectsLoading && projectsError == null && projects.length === 0 && (
          <span style={{ padding: `${t.spacing.xs}px ${t.spacing.md}px`, color: semantic("muted-foreground"), fontSize: t.font.sizeXs }}>No active Projects</span>
        )}
        {activeProjects.map((project) => {
          const expanded = expandedProjects[project.id] === true;
          const projectItems = (projectConversationIds[project.id] ?? [])
            .map((id) => activeConversationItems.find((conversation) => conversation.id === id))
            .filter((conversation): conversation is Conversation => conversation != null)
            .filter((conversation) => conversation.folderId == null || !folders.some((folder) => folder.id === conversation.folderId));
          return (
            <section key={project.id} data-project-sidebar={project.id} style={{ display: "grid", gap: t.spacing.xs }}>
              <div style={{ display: "flex", alignItems: "center", gap: t.spacing.xs }}>
                <button
                  type="button"
                  aria-label={`${expanded ? "Collapse" : "Expand"} ${project.name}`}
                  aria-expanded={expanded}
                  data-project-toggle={project.id}
                  onClick={() => toggleProject(project.id)}
                  className="rounded-md text-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                  style={{ ...selectStyle, minHeight: 44, flex: 1, padding: `${t.spacing.sm}px ${t.spacing.sm}px`, fontWeight: t.font.weightSemibold }}
                ><RocketIcon aria-hidden="true" focusable="false" className="size-4 shrink-0" /><span style={titleStyle}>{project.name}</span></button>
              {onNewChatInProject != null && (
                  <shadcn.IconButton
                    size="compact"
                    icon={PlusIcon}
                    appearance="row-action"
                    label={`New Chat in ${project.name}`}
                    tooltip="New Chat in Project"
                    disabled={creatingProjectChatId != null}
                    onClick={() => void createProjectChat(project.id)}
                  />
                )}
              </div>
              {expanded && (
                <div style={{ display: "grid", gap: t.spacing.xs }}>
                  {projectConversationLoading[project.id] && <span role="status" style={{ padding: `${t.spacing.xs}px ${t.spacing.md}px`, color: semantic("muted-foreground") }}>Loading conversations…</span>}
                  {projectConversationErrors[project.id] != null && (
                    <div role="alert" data-project-conversation-error={project.id} style={errorStyle}>
                      <span>{projectConversationErrors[project.id]}</span>
                      {onRetryProjectConversations != null && <button type="button" onClick={() => onRetryProjectConversations(project.id)} style={menuItemStyle}>Retry</button>}
                    </div>
                  )}
                  {!projectConversationLoading[project.id] && projectConversationErrors[project.id] == null && projectItems.length === 0 && (
                    <span style={{ padding: `${t.spacing.xs}px ${t.spacing.md}px`, color: semantic("muted-foreground"), fontSize: t.font.sizeXs }}>No conversations</span>
                  )}
                  {projectItems.map((conversation) => renderConversation(conversation, `project:${project.id}:${conversation.id}`, { dragDisabled: true }))}
                </div>
              )}
            </section>
          );
        })}
      </section>}
      {searchLoading && (
        <div role="status" data-conversation-search-loading="" style={{ color: semantic("muted-foreground"), fontSize: t.font.sizeXs }}>
          Searching…
        </div>
      )}
      {searchError != null && (
        <div role="alert" data-conversation-search-error="" style={errorStyle}>
          {searchError}
        </div>
      )}
      {conversationsLoading && !searchActive && (
        <div role="status" data-conversations-loading="" style={{ color: semantic("muted-foreground"), fontSize: t.font.sizeXs }}>
          Loading conversations…
        </div>
      )}
      {foldersLoading && !searchActive && (
        <div role="status" data-folders-loading="" style={{ color: semantic("muted-foreground"), fontSize: t.font.sizeXs }}>
          Loading folders…
        </div>
      )}
      {error != null && error.length > 0 && (
        <div role="alert" data-conversation-error="" style={errorStyle}>
          {error}
        </div>
      )}
      {conversationLoadError != null && (
        <div role="alert" data-conversation-load-error="" style={errorStyle}>
          {conversationLoadError}
          {onRetryConversations != null && (
            <button type="button" onClick={onRetryConversations} style={menuItemStyle}>Retry loading conversations</button>
          )}
        </div>
      )}
      {folderError != null && (
        <div role="alert" data-conversation-folder-error="" style={errorStyle}>
          {folderError}
          {onRetryFolders != null && (
            <button type="button" onClick={onRetryFolders} style={menuItemStyle}>Retry loading folders</button>
          )}
        </div>
      )}
      {moveError != null && <div role="alert" data-conversation-move-error="" style={errorStyle}>{moveError}</div>}
      {folderChatError != null && <div role="alert" data-folder-chat-error="" style={errorStyle}>{folderChatError}</div>}
      {(menuOpenId != null || folderMenuOpenId != null) && (
        <div aria-hidden style={{ position: "fixed", inset: 0, zIndex: 30 }} onClick={() => { setMenuOpenId(null); setFolderMenuOpenId(null); }} />
      )}
      {archivedView ? (
        <section aria-label="Archived conversations" data-archived-conversations="" style={{ display: "grid", gap: t.spacing.xs }}>
          {searchActive && <strong style={{ padding: `${t.spacing.xs}px ${t.spacing.sm}px`, fontSize: t.font.sizeSm }}>Archived</strong>}
          {conversationCollectionSettled && (searchActive ? conversations.filter((conversation) => conversation.isArchived) : archivedConversationItems).length === 0 ? (
            <p data-archived-empty="" style={{ margin: 0, padding: t.spacing.md, color: semantic("muted-foreground"), fontSize: t.font.sizeSm, fontStyle: "italic" }}>
              {searchActive ? `No archived conversations found for “${searchQuery.trim()}”.` : "No archived conversations"}
            </p>
          ) : (searchActive ? conversations.filter((conversation) => conversation.isArchived) : archivedConversationItems)
            .map((conversation) => renderConversation(conversation, `archived:${conversation.id}`, { dragDisabled: true, allowFolderMove: false }))}
        </section>
      ) : searchActive ? (
        <section aria-label="Conversation search results" data-conversation-search-results="" style={{ display: "grid", gap: t.spacing.xs }}>
          {conversationCollectionSettled && searchLoading !== true && searchError == null && conversations.length === 0 ? (
            <p style={{ margin: 0, padding: t.spacing.md, color: semantic("muted-foreground"), fontSize: t.font.sizeSm, textAlign: "center", fontStyle: "italic" }}>
              No conversations found for “{searchQuery.trim()}”.
            </p>
          ) : conversations.map((conversation) => renderConversation(conversation, `search:${conversation.id}`, { dragDisabled: true, showArchivedStatus: true }))}
        </section>
      ) : (
        <div data-active-conversations="" style={{ display: "flex", flexDirection: "column", gap: t.spacing.xs }}>
          {!conversationCollectionSettled ? null : activeConversationItems.length === 0 && folders.length === 0 && activeProjects.length === 0 ? (
            <p style={{ margin: 0, padding: t.spacing.md, color: semantic("muted-foreground"), fontSize: t.font.sizeSm, textAlign: "center", fontStyle: "italic" }}>
              No active conversations
            </p>
          ) : !showFolderSections ? (
            ungrouped.map((conversation) => renderConversation(conversation, `conversation:${conversation.id}`))
          ) : (
            <>
              {folderGroups.map(({ folder, conversations: items }) => {
                const expanded = collapsedFolders[folder.id] !== true;
                return (
                  <ConversationFolderDropTarget key={folder.id} folderId={folder.id} disabled={!dragEnabled}
                    style={{ display: "grid", gap: t.spacing.xs }}>
                    <div style={{ display: "flex", alignItems: "center", gap: t.spacing.xs, position: "relative" }}>
                      <button type="button" aria-label={`${expanded ? "Collapse" : "Expand"} ${folder.name}`}
                        aria-expanded={expanded} data-folder-toggle={folder.id}
                        onClick={() => setCollapsedFolders((current) => ({ ...current, [folder.id]: expanded }))}
                        className="rounded-md text-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                        style={{ ...selectStyle, minHeight: 44, flex: 1, padding: `${t.spacing.sm}px ${t.spacing.sm}px`, fontWeight: t.font.weightSemibold }}>
                        {expanded ? <FolderOpenIcon aria-hidden="true" focusable="false" className="size-4 shrink-0" /> : <FolderIcon aria-hidden="true" focusable="false" className="size-4 shrink-0" />}<span style={titleStyle}>{folder.name}</span>
                      </button>
                      {onRenameFolder != null || onDeleteFolder != null || onOpenFolderSystemPrompts != null || onNewChatInFolder != null ? (
                        <shadcn.IconButton size="compact" icon={EllipsisIcon} appearance="row-action" label={`Folder actions for ${folder.name}`} tooltip="Folder actions"
                          aria-haspopup="menu" aria-expanded={folderMenuOpenId === folder.id}
                          onClick={() => setFolderMenuOpenId((current) => current === folder.id ? null : folder.id)} />
                      ) : null}
                      {folderMenuOpenId === folder.id && (
                        <div role="menu" aria-label={`Folder actions for ${folder.name}`} style={{ ...menuStyle, top: "100%" }}>
                          {onNewChatInFolder != null && <button type="button" role="menuitem" disabled={creatingFolderChatId != null} onClick={() => void createFolderChat(folder.id)} style={menuItemStyle}>{creatingFolderChatId === folder.id ? "Creating…" : "New Chat"}</button>}
                          {onOpenFolderSystemPrompts != null && <button type="button" role="menuitem" onClick={() => { setFolderMenuOpenId(null); onOpenFolderSystemPrompts(folder.id, folder.name); }} style={menuItemStyle}>System Prompts</button>}
                          {onRenameFolder != null && <button type="button" role="menuitem" onClick={() => openFolderEditor(folder)} style={menuItemStyle}>Rename</button>}
                          {onDeleteFolder != null && <button type="button" role="menuitem" onClick={() => { setDeleteFolderTarget(folder); setDeleteFolderError(null); setFolderMenuOpenId(null); }} style={{ ...menuItemStyle, color: semantic("destructive") }}>Delete</button>}
                        </div>
                      )}
                    </div>
                    {expanded && (items.length > 0
                      ? items.map((conversation) => renderConversation(conversation, `folder:${folder.id}:${conversation.id}`))
                      : <span style={{ padding: `${t.spacing.xs}px ${t.spacing.md}px`, color: semantic("muted-foreground"), fontSize: t.font.sizeXs }}>No conversations</span>)}
                  </ConversationFolderDropTarget>
                );
              })}
              <ConversationFolderDropTarget folderId={null} disabled={!dragEnabled} style={{ display: "grid", gap: t.spacing.xs }}>
                <strong style={{ padding: `${t.spacing.xs}px ${t.spacing.sm}px`, fontSize: t.font.sizeSm }}>Ungrouped</strong>
                {ungrouped.length > 0 ? ungrouped.map((conversation) => renderConversation(conversation, `ungrouped:${conversation.id}`)) : (
                  <span style={{ padding: `${t.spacing.xs}px ${t.spacing.md}px`, color: semantic("muted-foreground"), fontSize: t.font.sizeXs }}>No conversations</span>
                )}
              </ConversationFolderDropTarget>
            </>
          )}
        </div>
      )}
      <Modal
        open={moveTarget != null}
        title="Move Conversation"
        primaryAction="Move"
        onPrimaryAction={() => void submitMove()}
        secondaryAction="Cancel"
        onSecondaryAction={() => { if (!moveSaving) setMoveTarget(null); }}
        primaryBusy={moveSaving}
        primaryDisabled={moveDestination === "" || moveSaving}
        onClose={() => { if (!moveSaving) setMoveTarget(null); }}
        closeOnOverlayClick={!moveSaving}
        closeOnEscape={!moveSaving}
      >
        <div style={{ display: "grid", gap: t.spacing.md }}>
          <fieldset disabled={moveSaving} style={{ display: "flex", gap: t.spacing.lg, border: 0, padding: 0, margin: 0 }}>
            <legend style={{ marginBottom: t.spacing.sm, fontWeight: t.font.weightSemibold }}>Move to:</legend>
            {onSetConversationProject != null && <label style={{ display: "flex", alignItems: "center", gap: t.spacing.xs }}>
              <input type="radio" name="conversation-move-type" value="project" checked={moveType === "project"}
                onChange={() => { setMoveType("project"); setMoveDestination(""); setMoveDialogError(null); }} />Project
            </label>}
            {moveTarget?.allowFolder && onMoveConversation != null && <label style={{ display: "flex", alignItems: "center", gap: t.spacing.xs }}>
              <input type="radio" name="conversation-move-type" value="folder" checked={moveType === "folder"}
                onChange={() => { setMoveType("folder"); setMoveDestination(""); setMoveDialogError(null); }} />Folder
            </label>}
          </fieldset>
          <label style={{ display: "grid", gap: t.spacing.xs, fontWeight: t.font.weightSemibold }}>
            Destination:
            <select aria-label="Move destination" value={moveDestination} disabled={moveSaving}
              onChange={(event) => { setMoveDestination(event.currentTarget.value); setMoveDialogError(null); }}
              style={{ width: "100%", minHeight: 38, padding: `${t.spacing.xs}px ${t.spacing.sm}px`, border: `1px solid ${semantic("border")}`, borderRadius: t.radius.md, background: semantic("background"), color: semantic("foreground") }}>
              <option value="">{moveType === "project" ? "Select project…" : "Select folder…"}</option>
              {moveType === "project" ? <>
                {projects.filter((project) => !project.is_archived).map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
                {moveTarget != null && conversations.find((item) => item.id === moveTarget.conversationId)?.projectId != null && <option value="__none__">No Project</option>}
              </> : <>
                {folders.map((folder) => <option key={folder.id} value={folder.id}>{folder.name}</option>)}
                <option value="__ungrouped__">Ungrouped</option>
              </>}
            </select>
          </label>
          {moveDialogError != null && <div role="alert" style={errorStyle}>{moveDialogError}</div>}
        </div>
      </Modal>
      <Modal
        open={folderEditor != null}
        title={folderEditor?.id == null ? "New Folder" : `Rename “${folderEditor.name}”`}
        primaryAction={folderEditor?.id == null ? "Create folder" : "Save folder"}
        onPrimaryAction={() => void saveFolder()}
        secondaryAction="Cancel"
        onSecondaryAction={() => setFolderEditor(null)}
        primaryBusy={folderSaving}
        primaryDisabled={folderEditorName.trim().length === 0}
        onClose={() => { if (!folderSaving) setFolderEditor(null); }}
        closeOnOverlayClick={!folderSaving}
        closeOnEscape={!folderSaving}
      >
        <div style={{ display: "grid", gap: t.spacing.md }}>
          <shadcn.Input aria-label="Folder name" value={folderEditorName} onChange={(event) => setFolderEditorName(event.currentTarget.value)} disabled={folderSaving} />
          {folderEditorError != null && <div role="alert" style={errorStyle}>{folderEditorError}</div>}
        </div>
      </Modal>
      <Modal
        open={deleteFolderTarget != null}
        title={deleteFolderTarget == null ? "Delete folder" : `Delete folder “${deleteFolderTarget.name}”?`}
        primaryAction="Delete folder"
        onPrimaryAction={() => void confirmDeleteFolder()}
        secondaryAction="Cancel"
        onSecondaryAction={() => setDeleteFolderTarget(null)}
        primaryBusy={deletingFolder}
        onClose={() => { if (!deletingFolder) setDeleteFolderTarget(null); }}
        closeOnOverlayClick={!deletingFolder}
        closeOnEscape={!deletingFolder}
      >
        <div style={{ display: "grid", gap: t.spacing.md }}>
          <p style={{ margin: 0 }}>The folder will be removed, but its conversations will not be deleted. They will move to Ungrouped.</p>
          {deleteFolderError != null && <div role="alert" style={errorStyle}>{deleteFolderError}</div>}
        </div>
      </Modal>
      <Modal
        open={deleteTarget != null}
        title={deleteTarget == null ? "Delete conversation" : `Delete “${deleteTarget.title}” permanently?`}
        primaryAction="Delete permanently"
        onPrimaryAction={() => void confirmDelete()}
        secondaryAction="Cancel"
        onSecondaryAction={() => {
          setDeleteError(null);
          setDeleteTargetId(null);
        }}
        primaryBusy={deleting}
        onClose={() => {
          setDeleteError(null);
          setDeleteTargetId(null);
        }}
        closeOnOverlayClick={!deleting}
        closeOnEscape={!deleting}
      >
        <div style={{ display: "grid", gap: t.spacing.md }}>
          <p style={{ margin: 0 }}>
            This will remove the conversation and its messages from AVA and cannot be undone.
          </p>
          {deleteError != null && (
            <div role="alert" data-conversation-delete-error="" style={errorStyle}>
              {deleteError}
            </div>
          )}
        </div>
      </Modal>
    </div>
    </DndContext>
  );
}
