# Phase 5.54 — Conversation Folder Persistence and CRUD API

Phase 5.54 makes the flat, organizational `ConversationFolderRecord` durable and exposes folder CRUD plus conversation assignment. A folder remains distinct from a Project: it does not define execution, workspace, or knowledge boundaries. No folder UI, nesting, folder search, or conversation grouping was added.

Migration 0011 creates `conversation_folders(id, name, created_at, updated_at)` and a name-order index. Existing databases advance through the normal migration runner; existing `conversations.folder_id` values remain unchanged, including nulls. SQLite cannot safely add a foreign key to the existing conversations table without reconstructing it, so this phase uses application-level referential enforcement and documents that choice. No broad schema rebuild was attempted.

The `ConversationFolderRepository` port has memory and SQLite adapters. The folder service owns ID/time generation and write semantics: create and rename trim names and reject blank values; creation uses UUID4 and equal initial timestamps; rename preserves identity and creation time while updating `updated_at`. Duplicate names are permitted. Lists sort by Unicode case-folded name, then creation time, then ID.

Conversation assignment accepts a known folder ID or null. It validates the conversation and folder, permits archived conversations and active runs, and changes only `folder_id`; it does not change conversation timestamps, execution state, or children. The API returns the updated standard conversation response. Unknown conversations use `conversation_not_found`; unknown folders consistently use `conversation_folder_not_found`.

Deleting a folder runs `UPDATE conversations SET folder_id = NULL` followed by folder deletion in the same SQLite transaction. Failure rolls back both operations. The in-memory adapter clears references before removing the folder and restores assignments if an operation fails. Folder removal never deletes conversations or their messages, runs, events, or attachments. Hard-deleting a conversation does not remove its folder.

The public API is `POST/GET /conversation-folders`, `GET/PATCH/DELETE /conversation-folders/{folder_id}`, plus `PATCH /conversations/{conversation_id}/folder` with `{ "folder_id": "…" }` or `{ "folder_id": null }`. DELETE returns 204. The typed API client exposes list, get, create, update, delete, and assignment methods.

Focused tests cover memory/SQLite CRUD parity, API shapes and error codes, restart durability, legacy migration, assignment preservation, folder cleanup, and relational rollback. Phase 5.55 UI work has not started.
