# Phase 5.46 — Conversation Hard-Delete Service

## Ownership map

| Record | Relationship | Delete behavior |
| --- | --- | --- |
| Conversation | `conversation_id` root | Permanently delete |
| Message | `messages.conversation_id` | Delete all rows for the conversation |
| Run | nullable `runs.conversation_id`; message IDs and `source_run_id` also link history | Delete directly owned runs and exclusive legacy runs linked by an unambiguous message reference; retain legacy runs referenced by another conversation |
| Run event | `run_events.run_id` | Delete events for deleted runs before deleting those runs |
| Attachment metadata | Generic `(owner_type, owner_id)`; conversation or message owner | Delete conversation-owned records and unambiguous message-owned records |
| Attachment content | Opaque storage key, separate content store | Delete content only for attachment metadata removed by the transaction |
| Future Project data | No implemented relationship | No Project rows or behavior introduced |

There are no database foreign keys or cascades among conversations, messages,
runs, run events, or attachments. Message IDs are unique only within one
conversation. If an attachment's message owner ID is also used by a surviving
conversation, its metadata is detached and retained rather than deleting
potentially shared content. Surviving messages that refer to a deleted run
have `source_run_id` cleared to avoid dangling references.

## Service behavior

`ConversationService.delete_conversation` delegates to a deletion
coordinator and returns false when the conversation is unknown. The SQLite
coordinator deletes the relational graph in one database transaction. The
in-memory coordinator snapshots its stores and restores them if deletion
fails. Attachment content cleanup uses the returned keys after metadata
commit; both built-in content stores implement idempotent deletion, and the
local store validates the opaque key beneath its configured root before
unlinking. A run in any active lifecycle state blocks deletion with the typed
`ConversationHasActiveRunError`; deletion never attempts cancellation. Terminal
runs are removed with their events. Legacy runs without a conversation ID are
associated only through unambiguous message links and retained if another
conversation also references them. The operation returns
`false` for an unknown or already deleted conversation. There is no public
DELETE route.

The relational transaction removes run events, clears surviving messages'
references to those runs, removes runs, removes exclusively associated
attachment metadata, removes messages, and finally removes the conversation.
Conversation and message attachment metadata with an ambiguous message owner
is retained but detached. Physical blobs are removed after the relational
transaction commits and only for the metadata records the transaction proved
exclusive: attachment storage keys are unique in the metadata table. Other
conversation blobs and ambiguous detached content remain.

Archive remains reversible and is not used for hard deletion. This step adds
no delete UI, archive filtering, folders, search, sorting, or Projects behavior.

## Verification

Tests cover the memory and SQLite adapters, archived/pinned deletion, active
run rejection, second/unknown deletion, preservation of another conversation,
ambiguous message attachment retention, shared legacy-run preservation,
transaction rollback, restart durability, attachment cleanup, direct orphan
checks, `PRAGMA integrity_check`,
and `PRAGMA foreign_key_check`. No public delete route or UI was added.

The new deletion suite and focused conversation/message/run/attachment
repository suites pass (156 tests). Ruff, mypy, and `git diff --check` pass.
The prior Phase 5.42–5.45 integration suites did not return a completion
summary in this environment and were stopped after partial progress, so those
suite results remain unverified here.

Phase 5.47 is not started.
