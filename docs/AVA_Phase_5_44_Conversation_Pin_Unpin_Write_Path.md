# Phase 5.44 — Conversation Pin/Unpin Write Path

## Public contract

`PATCH /conversations/{conversation_id}/pin` accepts
`{"is_pinned": true}` or `{"is_pinned": false}` and returns the normal
`ConversationResponse`. `SetConversationPinnedRequest` requires a strict JSON
boolean: missing, null, numeric, string, array, and object values are rejected
with 422. Unknown identifiers use the existing `conversation_not_found` 404.

The existing update contract and route explicitly implement rename, with a
required nonblank title. The narrow pin route preserves that contract and
avoids introducing mixed rename/metadata updates. Empty mutations remain
invalid. Extra fields follow existing contract behavior (ignored); archive,
folder, and title values cannot be changed through the pin route.

## Application and persistence path

The thin route delegates to `ConversationService.set_pinned`, which calls
`ConversationRepository.set_pinned` and maps its snapshot to the usual response.
Both memory and relational implementations return `None` for unknown IDs.
Memory replaces only `is_pinned`; SQLite updates only the `is_pinned` column
and reads the updated snapshot inside the same transaction. No migration is
needed beyond Phase 5.43.

Repeated pin or unpin requests succeed with identical state. All other fields,
including `updated_at`, `created_at`, title, archive state, and opaque folder ID,
are preserved. Tests also preserve messages, runs, and run events. An archived
conversation may be pinned. Renaming a pinned conversation retains its pin.
Pin and unpin both survive application shutdown and restart against the same DB.

The typed API client adds `setConversationPinned` and the shared TypeScript
contract adds `SetConversationPinnedRequest`. Existing rename calls stay intact.
No UI or Agent UI execution-state changes are introduced. List ordering stays
in insertion order; no archive/restore, folder mutation, delete, search,
Projects, or sorting behavior is added. Runtime/model selection, context
construction, run creation, and streaming production code are untouched.

## Validation

- 99 focused backend tests pass, including conversation service, repository,
  HTTP, all Phase 5.42 metadata tests, and all Phase 5.43 persistence tests.
- `test_conversation_pinning.py` adds 12 cases covering both backends, exact
  metadata preservation, idempotency, unknown IDs, validation, API reads,
  unchanged ordering, rename compatibility, and restart in both directions.
- Existing repository fakes implement the new port method; the Phase 5.42
  no-write test now explicitly describes the rename route. Existing test
  typing issues were corrected without changing production behavior.
- Mutation proof: temporarily forcing both repositories to persist `false`
  produced **5 assertion failures / 7 passes** in the 12 new cases. Restored
  both implementations and reran the focused suite: **99 passed**.
- API-client: **84 passed**, including 3 new transport cases. Contracts:
  **28 passed**. TypeScript `tsc --noEmit` passes for both packages.
- Ruff and strict mypy pass on all 12 backend files touched in this step.
  `git diff --check` passes. The full canonical suite was not run.

## Production files changed

- `backend/src/ava/contracts/conversations.py`
- `backend/src/ava/contracts/__init__.py`
- `backend/src/ava/api/routes/conversations.py`
- `backend/src/ava/repositories/conversation_repository.py`
- `backend/src/ava/services/conversation_service.py`
- `backend/src/ava/services/conversation_store.py`
- `backend/src/ava/infrastructure/persistence/repositories/conversation_repository.py`
- `frontend/packages/contracts/src/conversations.ts`
- `frontend/packages/api-client/src/conversations.ts`

Phase 5.44 complete. Phase 5.45 not started.
