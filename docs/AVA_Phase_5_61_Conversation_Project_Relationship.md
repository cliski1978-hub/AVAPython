# Phase 5.61 — Conversation ↔ Project Relationship

**Status: COMPLETE**

This step adds a durable, nullable relationship from each Conversation to at
most one Project. A Conversation may have no Project. Conversation Folder
membership remains a separate, independent dimension; both references may be
present, either may be absent, and assignment to one never changes the other.

## Domain and persistence

`ConversationRecord` now carries `project_id: str | None`, defaulting to
`None`. The existing `ConversationResponse` and shared TypeScript
`ConversationResponse` expose the same nullable `project_id`; neither embeds a
Project object. The Python client defines no typed Conversation model, so it
needed no production change.

Migration **0013**, `v0013_conversation_project_relationship.py`, appends a
nullable `project_id TEXT` column to `conversations`. As with `folder_id`, the
relationship is enforced by application services rather than a SQLite foreign
key. Existing version 0012 rows receive SQL `NULL`; the migration does not
rebuild the table. The row mapper converts SQL `NULL` to `None` and also
defaults to `None` when reading legacy row projections without the column.

The in-memory and SQLite conversation repositories both support
`set_project(conversation_id, project_id)`. Assignment validates that a
non-null Project exists; a missing Conversation follows the existing
`conversation_not_found` API behavior, and a missing Project uses the existing
`project_not_found` error. Setting `None` is idempotent, and assigning a new
Project directly moves the Conversation in one update.

The generic `PATCH /conversations/{conversation_id}/project` route and typed
`setConversationProject` client function expose assignment and unassignment.
No Project conversation collection routes were added.

## Metadata and lifecycle behavior

Project assignment, movement, and unassignment do not update the
Conversation's `updated_at` and therefore do not change its canonical sort
position. They preserve its identity, title, pin/archive state, Folder
membership, messages, runs, run events, and attachment associations. Assignment
does not cancel or restart an active run. Project archive changes only Project
metadata and leaves memberships intact.

Deleting a Project preserves its Conversations and children while clearing
their `project_id`. The SQLite Project repository performs both the membership
cleanup and Project deletion in one transaction. The memory repository
performs matching cleanup with rollback restoration if a step fails. Hard
deleting a Conversation continues to operate on that Conversation and does not
delete its Project.

Conversation search remains title-only, canonical sorting remains
`is_pinned DESC, updated_at DESC, created_at DESC, conversation_id ASC`, and
Project instructions remain inert. No Project UI, sidebar integration,
drag/drop, Project files, execution defaults, or RAG behavior was added.

## Migration and validation evidence

The migration test starts from schema version 0012 with a Project, Folder,
Conversation metadata, a message, a run, a run event, and an attachment. After
0013, all existing records and metadata remain, `project_id` is `NULL`, a
second migration run is a no-op, and SQLite reports `integrity_check = ok` and
an empty `foreign_key_check`.

The focused backend tests cover memory/SQLite parity, assignment, movement,
unassignment, missing identities, Folder independence, Conversation metadata
plus rename/pin/archive preservation, active-run preservation, Project archive
and deletion, atomic rollback, assignment and deletion durability across reopen,
and migration compatibility. A load-bearing mutation that forced the SQLite
row mapper to return `project_id = None` was rejected by the relationship tests.
