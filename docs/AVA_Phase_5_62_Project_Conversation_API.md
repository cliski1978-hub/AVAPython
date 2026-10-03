# Phase 5.62 — Project Conversation API and Creation Flow

Phase 5.62 exposes Project-scoped conversation reads and creation over the
durable nullable relationship introduced in Phase 5.61. The public API is:

```text
GET  /projects/{project_id}/conversations
POST /projects/{project_id}/conversations
```

The list validates the Project before querying and returns the canonical
`ConversationListResponse`. The repository query filters by exact
`project_id`, preserves the shared order (`is_pinned DESC`, `updated_at DESC`,
`created_at DESC`, `conversation_id ASC`), and includes archived conversations.
Folder metadata is returned unchanged and is independent of Project membership.

Creation reuses `CreateConversationRequest` and the existing default title,
timezone-aware timestamps, and conversation defaults. The service validates
Project existence before generating/persisting a conversation, then writes the
Project ID with the initial conversation insert. A missing Project returns
`404 project_not_found` and cannot leave an orphan. SQLite restart coverage and
a direct database assertion prove the committed row contains the Project ID.

Project archive is informational in the current lifecycle model: archived
Projects remain listable and can receive new conversations. This follows the
existing Project metadata and membership behavior, which does not block updates
or assignments when archived. Project deletion remains Phase 5.61 behavior:
the Project becomes unavailable, conversations survive, and their
`project_id` values are cleared.

The typed `@ava/api-client` exports `listProjectConversations` and
`createProjectConversation`, using the shared conversation contracts and normal
`ApiError` propagation. No Project conversation DTO was added.

Migration 0014 adds `idx_conversations_project` because this phase introduces a
repeated ownership-key lookup, matching existing indexes such as
`idx_runs_conversation`. No Project-specific sort index is added; the query
retains the established ordering while the simple index keeps schema cost low.

This phase does not add Project conversation UI, drag/drop, Chat sidebar
integration, Project files, execution defaults, instruction injection, or RAG.
Those remain outside this step.

Focused route tests invoke handlers directly because the application lifespan
can stall during `TestClient` startup in this environment. The handlers and
router registration are still exercised; this limitation is reported with the
validation results.
