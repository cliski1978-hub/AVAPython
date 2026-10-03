# Phase 5.63 — Project Conversation UI

Phase 5.63 makes Project membership visible in Chat and replaces the Project
workspace Conversations placeholder with a list backed by the existing
Project conversation API. Project conversations remain canonical
conversations: the UI selects and opens their existing IDs through the normal
Chat path and reads messages/run state from the shared conversation provider.

## Chat sidebar

The existing Chat sidebar now includes an Active Projects section above
Folders. It loads Projects independently with `listProjects`; failure displays
a Project-only retry state and leaves ordinary conversation and Folder UI
available. Project conversations load on first expansion through
`listProjectConversations`. Expanded IDs are cached in workspace/sidebar state,
and a refresh requested during an in-flight load is queued so successful
mutations cannot leave an older list snapshot in place.

Archived Projects are omitted from the primary Project section. Their
conversations remain reachable in normal Folder or Ungrouped organization;
the Projects workspace remains the archive-management surface. Project and
Folder are independent organization dimensions, so a conversation with both
IDs appears in both groups. Each row keeps a context-specific menu key to
prevent duplicate copies from opening the wrong menu.

The Project API's result order is retained. Project conversation actions can
pin/unpin and archive/restore; pin changes refresh the canonical conversation
order, and both metadata updates preserve `project_id`. Rename updates the
canonical title and refreshes the affected Project list. Hard delete removes
the canonical conversation, so it immediately disappears from Project and
Folder views.

## Creation and organization

`New Chat in {Project}` calls `createProjectConversation` directly and selects
the returned conversation ID. This matches the existing global New Chat
behavior, which creates a conversation immediately. The composer then submits
its first prompt against that selected ID. Global New Chat continues to use
`createConversation` and therefore creates an unassigned conversation; there
is no sticky Project context to leak into later chats.

Conversation menus support moving a conversation into another active Project
or removing it from its current Project through `setConversationProject`.
Moves update only Project membership in canonical state and refresh only the
affected Project conversation lists. They do not recreate or reselect the
conversation, alter Folder membership, replace transcript messages, or touch
run observer ownership. Assignment failures preserve the previous state and
show a safe error. Project-not-found responses refresh Project metadata, while
conversation-not-found responses reconcile the stale conversation.

## Project workspace and search

The Project workspace Conversations section now lists API-returned IDs resolved
against canonical conversation state. Its New Chat action uses the same
Project-scoped creation path as the sidebar. Opening an item navigates to Chat
and selects that same conversation ID, preserving the shared transcript and
run lifecycle. Files and Settings remain placeholders; Instructions remain
inert. No instruction injection, execution defaults, Project files, RAG, or
drag/drop behavior was added.

Global conversation search remains backed by the existing conversation search
API, whose results include Project conversations. Search results still select
the canonical conversation. Project list and per-Project conversation failures
are isolated from global search, Folder listing, and Chat.

## Validation

Focused coverage exercises Project loading and expansion, Project-scoped
creation and first-prompt routing, global creation isolation, Project moves and
removal, Folder independence, selection/transcript and active-run preservation,
pin/archive metadata, Project workspace listing/open/create, and isolated
Project failures. A mutation replacing Project-scoped creation with global
creation caused the focused creation test to fail because
`createProjectConversation(client, projectId)` was never called; the mutation
was restored and the test passed.

Live verification used a temporary relational SQLite database and local
backend/web servers. It confirmed Project creation/listing, Project sidebar
visibility, lazy conversation listing, Project New Chat, the first `hello`
message and mock response on its new ID, global New Chat with
`project_id: null`, Project assignment, Project workspace open through Chat,
and simultaneous Project/Folder membership. Temporary services and database
were removed after verification.

Phase 5.63 adds frontend behavior and tests only; backend and API-client
production contracts were unchanged. Phase 5.64 was not started.
