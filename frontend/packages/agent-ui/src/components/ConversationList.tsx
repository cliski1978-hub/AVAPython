import {
  Button,
  IconButton,
  Input,
  defaultTheme,
  Modal,
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
      <Input
        ariaLabel="Rename conversation"
        value={value}
        onChange={setValue}
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
        ...(isOver ? { outline: `2px solid ${t.colors.primary}`, outlineOffset: 2, borderRadius: t.radius.md } : {}),
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
  folders,
  onMove,
  projects,
  onSetProject,
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
  folders: ConversationFolder[];
  onMove?: (conversationId: string, folderId: string | null) => void;
  projects: Project[];
  onSetProject?: (conversationId: string, projectId: string | null) => Promise<void>;
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
  const [moveMenuOpen, setMoveMenuOpen] = useState(false);
  const [projectMenuOpen, setProjectMenuOpen] = useState(false);
  const [projectMovePending, setProjectMovePending] = useState(false);
  const [metadataPending, setMetadataPending] = useState(false);
  const [metadataError, setMetadataError] = useState<string | null>(null);
  const showMenu = onRename != null || onDeleteRequested != null || onMove != null || onSetProject != null || onSetPinned != null || onSetArchived != null || onOpenSystemPrompts != null;

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

  const setProject = async (projectId: string | null) => {
    if (onSetProject == null || projectMovePending) return;
    setProjectMovePending(true);
    try {
      await onSetProject(conversation.id, projectId);
      setProjectMenuOpen(false);
      onCloseMenu();
    } finally {
      setProjectMovePending(false);
    }
  };

  return (
    <div
      ref={setNodeRef}
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
                  background: t.colors.primary,
                  flexShrink: 0,
                }}
              />
            )}
            <span style={titleStyle}>{conversation.title}</span>
            {showArchivedStatus && conversation.isArchived && (
              <span data-archived-indicator="" style={{ color: t.colors.mutedText, fontSize: t.font.sizeXs, flexShrink: 0 }}>
                Archived
              </span>
            )}
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
                  menuOpen ? onCloseMenu() : onOpenMenu(rowKey)
                }
              >
                {"\u2026"}
              </IconButton>
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
                  style={{ ...menuItemStyle, color: t.colors.dangerText }}
                  onClick={() => {
                    onCloseMenu();
                    onDeleteRequested(conversation.id);
                  }}
                >
                  Delete
                </button>
              )}
              {onMove != null && (
                <>
                  <button
                    type="button"
                    role="menuitem"
                    aria-haspopup="menu"
                    aria-expanded={moveMenuOpen}
                    data-conversation-move=""
                    style={menuItemStyle}
                    onClick={() => setMoveMenuOpen((open) => !open)}
                  >
                    Move to folder
                  </button>
                  {moveMenuOpen && (
                    <div role="group" aria-label={`Move ${conversation.title} to folder`} data-conversation-move-options="">
                      <button
                        type="button"
                        role="menuitem"
                        aria-label="Move to Ungrouped"
                        disabled={conversation.folderId == null}
                        style={menuItemStyle}
                        onClick={() => { setMoveMenuOpen(false); void onMove(conversation.id, null); }}
                      >Ungrouped</button>
                      {folders.map((folder) => (
                        <button
                          key={folder.id}
                          type="button"
                          role="menuitem"
                          aria-label={`Move to ${folder.name}`}
                          disabled={conversation.folderId === folder.id}
                          style={menuItemStyle}
                          onClick={() => { setMoveMenuOpen(false); void onMove(conversation.id, folder.id); }}
                        >{folder.name}</button>
                      ))}
                    </div>
                  )}
                </>
              )}
              {onSetProject != null && (
                <>
                  <button
                    type="button"
                    role="menuitem"
                    aria-haspopup="menu"
                    aria-expanded={projectMenuOpen}
                    disabled={projectMovePending}
                    style={menuItemStyle}
                    onClick={() => setProjectMenuOpen((open) => !open)}
                  >Move to Project</button>
                  {projectMenuOpen && (
                    <div role="group" aria-label={`Move ${conversation.title} to Project`}>
                      {projects.filter((project) => !project.is_archived).map((project) => (
                        <button
                          key={project.id}
                          type="button"
                          role="menuitem"
                          disabled={projectMovePending || conversation.projectId === project.id}
                          style={menuItemStyle}
                          onClick={() => { void setProject(project.id); }}
                        >{project.name}</button>
                      ))}
                    </div>
                  )}
                  {conversation.projectId != null && (
                    <button
                      type="button"
                      role="menuitem"
                      disabled={projectMovePending}
                      style={menuItemStyle}
                      onClick={() => { void setProject(null); }}
                    >Remove from Project</button>
                  )}
                </>
              )}
            </div>
          )}
          {metadataError != null && <div role="alert" style={{ fontSize: t.font.sizeXs, color: t.colors.dangerText }}>{metadataError}</div>}
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

  const requestProjectMove = async (conversationId: string, projectId: string | null) => {
    if (onSetConversationProject == null) return;
    setProjectActionError(null);
    try {
      await onSetConversationProject(conversationId, projectId);
    } catch {
      setProjectActionError("Unable to move this conversation to the Project. Please try again.");
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

  const changeArchiveStatus = async (conversationId: string, isArchived: boolean) => {
    if (onSetConversationArchived == null) return;
    await onSetConversationArchived(conversationId, isArchived);
    setArchiveStatusMessage(isArchived ? "Conversation archived." : "Conversation restored.");
    if (conversationId === activeConversationId) setArchivedView(isArchived);
    const focusTarget = () => {
      const item = Array.from(document.querySelectorAll<HTMLElement>("[data-conversation-item]"))
        .find((element) => element.dataset.conversationItem === conversationId);
      const selected = activeConversationId == null ? undefined : Array.from(
        document.querySelectorAll<HTMLElement>("[data-conversation-item]"),
      ).find((element) => element.dataset.conversationItem === activeConversationId);
      (item ?? selected ?? (isArchived ? archivedViewButtonRef.current : activeViewButtonRef.current))?.focus();
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
      folders={folders}
      onMove={options.allowFolderMove === false || onMoveConversation == null ? undefined : requestMove}
      dragDisabled={options.dragDisabled ?? !dragEnabled}
      projects={projects}
      onSetProject={onSetConversationProject == null ? undefined : requestProjectMove}
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
        <Button variant="primary" onClick={onNewChat}>
          New Chat
        </Button>
      </span>
      {!archivedView && onCreateFolder != null && (
        <span data-new-folder>
          <Button variant="secondary" onClick={() => openFolderEditor(null)}>
            New Folder
          </Button>
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
          <div style={{ flex: 1, minWidth: 0 }}>
            <Input
              type="search"
              ariaLabel="Search conversations"
              placeholder="Search conversations"
              value={searchQuery}
              onChange={onSearchChange}
            />
          </div>
          {searchQuery.length > 0 && (
            <button
              type="button"
              aria-label="Clear conversation search"
              title="Clear search"
              onClick={() => onSearchChange("")}
              style={{
                flexShrink: 0,
                border: 0,
                background: "transparent",
                color: t.colors.mutedText,
                fontSize: t.font.sizeMd,
                cursor: "pointer",
              }}
            >
              ×
            </button>
          )}
        </div>
      )}
      <nav aria-label="Conversation views" data-conversation-view-nav="" style={{ display: "flex", gap: t.spacing.xs }}>
        <button
          ref={activeViewButtonRef}
          type="button"
          aria-current={!archivedView ? "page" : undefined}
          data-conversation-view="active"
          onClick={() => setArchivedView(false)}
          style={{ ...selectStyle, flex: 1, padding: `${t.spacing.xs}px ${t.spacing.sm}px`, fontWeight: !archivedView ? t.font.weightSemibold : t.font.weightNormal }}
        >Active</button>
        <button
          ref={archivedViewButtonRef}
          type="button"
          aria-current={archivedView ? "page" : undefined}
          data-conversation-view="archived"
          onClick={() => setArchivedView(true)}
          style={{ ...selectStyle, flex: 1, padding: `${t.spacing.xs}px ${t.spacing.sm}px`, fontWeight: archivedView ? t.font.weightSemibold : t.font.weightNormal }}
        >Archived</button>
      </nav>
      {archiveStatusMessage != null && (
        <span role="status" aria-live="polite" data-conversation-archive-status="" style={{
          position: "absolute", width: 1, height: 1, padding: 0, margin: -1, overflow: "hidden",
          clip: "rect(0, 0, 0, 0)", whiteSpace: "nowrap", border: 0,
        }}>{archiveStatusMessage}</span>
      )}
      {!archivedView && !searchActive && <section data-projects-sidebar="" aria-label="Projects" style={{ display: "grid", gap: t.spacing.xs }}>
        <strong style={{ padding: `${t.spacing.xs}px ${t.spacing.sm}px`, fontSize: t.font.sizeSm }}>Projects</strong>
        {projectsLoading && <span role="status" style={{ padding: `${t.spacing.xs}px ${t.spacing.md}px`, color: t.colors.mutedText }}>Loading Projects…</span>}
        {projectsError != null && (
          <div role="alert" data-projects-load-error="" style={errorStyle}>
            <span>{projectsError}</span>
            {onRetryProjects != null && <button type="button" onClick={onRetryProjects} style={menuItemStyle}>Retry Projects</button>}
          </div>
        )}
        {projectActionError != null && <div role="alert" data-project-action-error="" style={errorStyle}>{projectActionError}</div>}
        {!projectsLoading && projectsError == null && projects.length === 0 && (
          <span style={{ padding: `${t.spacing.xs}px ${t.spacing.md}px`, color: t.colors.mutedText, fontSize: t.font.sizeXs }}>No active Projects</span>
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
                  style={{ ...selectStyle, flex: 1, padding: `${t.spacing.xs}px ${t.spacing.sm}px`, fontWeight: t.font.weightSemibold }}
                ><span aria-hidden>{expanded ? "▾" : "▸"}</span>{project.name}</button>
                {onNewChatInProject != null && (
                  <IconButton
                    size="sm"
                    ariaLabel={`New Chat in ${project.name}`}
                    title="New Chat in Project"
                    disabled={creatingProjectChatId != null}
                    onClick={() => void createProjectChat(project.id)}
                  >+</IconButton>
                )}
              </div>
              {expanded && (
                <div style={{ display: "grid", gap: t.spacing.xs }}>
                  {projectConversationLoading[project.id] && <span role="status" style={{ padding: `${t.spacing.xs}px ${t.spacing.md}px`, color: t.colors.mutedText }}>Loading conversations…</span>}
                  {projectConversationErrors[project.id] != null && (
                    <div role="alert" data-project-conversation-error={project.id} style={errorStyle}>
                      <span>{projectConversationErrors[project.id]}</span>
                      {onRetryProjectConversations != null && <button type="button" onClick={() => onRetryProjectConversations(project.id)} style={menuItemStyle}>Retry</button>}
                    </div>
                  )}
                  {!projectConversationLoading[project.id] && projectConversationErrors[project.id] == null && projectItems.length === 0 && (
                    <span style={{ padding: `${t.spacing.xs}px ${t.spacing.md}px`, color: t.colors.mutedText, fontSize: t.font.sizeXs }}>No conversations</span>
                  )}
                  {projectItems.map((conversation) => renderConversation(conversation, `project:${project.id}:${conversation.id}`, { dragDisabled: true }))}
                </div>
              )}
            </section>
          );
        })}
      </section>}
      {searchLoading && (
        <div role="status" data-conversation-search-loading="" style={{ color: t.colors.mutedText, fontSize: t.font.sizeXs }}>
          Searching…
        </div>
      )}
      {searchError != null && (
        <div role="alert" data-conversation-search-error="" style={errorStyle}>
          {searchError}
        </div>
      )}
      {conversationsLoading && !searchActive && (
        <div role="status" data-conversations-loading="" style={{ color: t.colors.mutedText, fontSize: t.font.sizeXs }}>
          Loading conversations…
        </div>
      )}
      {foldersLoading && !searchActive && (
        <div role="status" data-folders-loading="" style={{ color: t.colors.mutedText, fontSize: t.font.sizeXs }}>
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
            <p data-archived-empty="" style={{ margin: 0, padding: t.spacing.md, color: t.colors.mutedText, fontSize: t.font.sizeSm, fontStyle: "italic" }}>
              {searchActive ? `No archived conversations found for “${searchQuery.trim()}”.` : "No archived conversations"}
            </p>
          ) : (searchActive ? conversations.filter((conversation) => conversation.isArchived) : archivedConversationItems)
            .map((conversation) => renderConversation(conversation, `archived:${conversation.id}`, { dragDisabled: true, allowFolderMove: false }))}
        </section>
      ) : searchActive ? (
        <section aria-label="Conversation search results" data-conversation-search-results="" style={{ display: "grid", gap: t.spacing.xs }}>
          {conversationCollectionSettled && searchLoading !== true && searchError == null && conversations.length === 0 ? (
            <p style={{ margin: 0, padding: t.spacing.md, color: t.colors.mutedText, fontSize: t.font.sizeSm, textAlign: "center", fontStyle: "italic" }}>
              No conversations found for “{searchQuery.trim()}”.
            </p>
          ) : conversations.map((conversation) => renderConversation(conversation, `search:${conversation.id}`, { dragDisabled: true, showArchivedStatus: true }))}
        </section>
      ) : (
        <div data-active-conversations="" style={{ display: "flex", flexDirection: "column", gap: t.spacing.xs }}>
          {!conversationCollectionSettled ? null : activeConversationItems.length === 0 && folders.length === 0 && activeProjects.length === 0 ? (
            <p style={{ margin: 0, padding: t.spacing.md, color: t.colors.mutedText, fontSize: t.font.sizeSm, textAlign: "center", fontStyle: "italic" }}>
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
                        style={{ ...selectStyle, flex: 1, padding: `${t.spacing.xs}px ${t.spacing.sm}px`, fontWeight: t.font.weightSemibold }}>
                        <span aria-hidden>{expanded ? "▾" : "▸"}</span>{folder.name}
                      </button>
                      {onRenameFolder != null || onDeleteFolder != null || onOpenFolderSystemPrompts != null || onNewChatInFolder != null ? (
                        <IconButton size="sm" ariaLabel={`Folder actions for ${folder.name}`} title="Folder actions"
                          onClick={() => setFolderMenuOpenId((current) => current === folder.id ? null : folder.id)}>…</IconButton>
                      ) : null}
                      {folderMenuOpenId === folder.id && (
                        <div role="menu" aria-label={`Folder actions for ${folder.name}`} style={{ ...menuStyle, top: "100%" }}>
                          {onNewChatInFolder != null && <button type="button" role="menuitem" disabled={creatingFolderChatId != null} onClick={() => void createFolderChat(folder.id)} style={menuItemStyle}>{creatingFolderChatId === folder.id ? "Creating…" : "New Chat"}</button>}
                          {onOpenFolderSystemPrompts != null && <button type="button" role="menuitem" onClick={() => { setFolderMenuOpenId(null); onOpenFolderSystemPrompts(folder.id, folder.name); }} style={menuItemStyle}>System Prompts</button>}
                          {onRenameFolder != null && <button type="button" role="menuitem" onClick={() => openFolderEditor(folder)} style={menuItemStyle}>Rename</button>}
                          {onDeleteFolder != null && <button type="button" role="menuitem" onClick={() => { setDeleteFolderTarget(folder); setDeleteFolderError(null); setFolderMenuOpenId(null); }} style={{ ...menuItemStyle, color: t.colors.dangerText }}>Delete</button>}
                        </div>
                      )}
                    </div>
                    {expanded && (items.length > 0
                      ? items.map((conversation) => renderConversation(conversation, `folder:${folder.id}:${conversation.id}`))
                      : <span style={{ padding: `${t.spacing.xs}px ${t.spacing.md}px`, color: t.colors.mutedText, fontSize: t.font.sizeXs }}>No conversations</span>)}
                  </ConversationFolderDropTarget>
                );
              })}
              <ConversationFolderDropTarget folderId={null} disabled={!dragEnabled} style={{ display: "grid", gap: t.spacing.xs }}>
                <strong style={{ padding: `${t.spacing.xs}px ${t.spacing.sm}px`, fontSize: t.font.sizeSm }}>Ungrouped</strong>
                {ungrouped.length > 0 ? ungrouped.map((conversation) => renderConversation(conversation, `ungrouped:${conversation.id}`)) : (
                  <span style={{ padding: `${t.spacing.xs}px ${t.spacing.md}px`, color: t.colors.mutedText, fontSize: t.font.sizeXs }}>No conversations</span>
                )}
              </ConversationFolderDropTarget>
            </>
          )}
        </div>
      )}
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
          <Input ariaLabel="Folder name" value={folderEditorName} onChange={setFolderEditorName} disabled={folderSaving} />
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
