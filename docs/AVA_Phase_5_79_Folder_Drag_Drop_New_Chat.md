# Phase 5.79 — Folder Drag/Drop + New Chat in Folder

## Scope

Phase 5.79 completes the deferred Folder sidebar interactions. Folder membership
continues to be conversation organization metadata and remains independent from
Project membership, transcript contents, execution settings, and active runs.
No nested Folders, manual conversation ordering, or Folder instructions were
added.

## Drag/drop infrastructure and behavior

AVA uses `@dnd-kit/core` for shared drag/drop primitives and includes
`@dnd-kit/sortable` in the shared `@ava/agent-ui` package for future sortable
surfaces. Phase 5.79 uses no sortable-list behavior. The Conversation sidebar
registers conversations by `conversation.id`, folders by Folder ID, and the
explicit Ungrouped target by a stable sentinel. Pointer and keyboard sensors
are active; a Folder-target keyboard coordinate getter moves between drop
targets. Search results and the Folder-loading state disable drag operations.
Existing menu actions remain available for keyboard and non-drag use.

Dropping a conversation in a different Folder calls the existing typed Folder
assignment client. Dropping into its current Folder is a no-op; Ungrouped sends
`folder_id: null`. The handler changes only the folder assignment, so Project
membership, pin state, selected conversation, transcript, and active-run
observation remain intact. Failed moves leave canonical state in place and
surface a localized retryable error.

Moves are serialized per conversation. If a newer destination is requested
while the prior request is pending, the newest destination is sent after the
first request settles; an earlier response cannot overwrite the later choice.
The backend response is treated as canonical. A deleted destination rejected by
the API triggers folder and assignment reconciliation. Folder sections retain
their current collapsed state after a drop.

Project conversations remain eligible for Folder assignment wherever they are
represented in the shared Folder/ungrouped list. The Project list representation
does not register a duplicate draggable ID; its existing move menu remains
available. Folder movement never changes `project_id`.

## New Chat in Folder

Folder actions now include New Chat. The existing general conversation-create
contract accepts an optional `folder_id`, allowing creation to attach the Folder
in the same request. The service validates that Folder and creates the
conversation atomically with that assignment. The new conversation has no
Project membership unless a Project-specific creation flow was used. On
success, the new conversation is selected and the chat workspace is shown; on
failure, the Folder menu reports an error without creating a phantom row.

Global New Chat and Project New Chat retain their existing flows and do not
inherit stale Folder context. First-message/run behavior continues through the
existing conversation state and execution architecture.

## Validation

Full validation and environment limits are recorded in
[AVA_Phase_5_79A_Folder_Drag_Drop_Validation.md](AVA_Phase_5_79A_Folder_Drag_Drop_Validation.md).
