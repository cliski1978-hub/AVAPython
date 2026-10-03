# Phase 5.45 — Conversation Archive/Restore Write Path

## Public contract

`PATCH /conversations/{conversation_id}/archive` accepts a dedicated
`SetConversationArchivedRequest` with strict boolean `is_archived` and returns
the normal conversation response. True archives; false restores. Missing,
null, non-boolean, and malformed requests return 422. Unknown IDs use the
existing `conversation_not_found` 404 response.

## Mutation and preservation

The route delegates to `ConversationService.set_archived`, which calls the
narrow `ConversationRepository.set_archived` method. Memory replaces only the
archive field; SQLite updates only the `is_archived` column and reads the
updated row in the same transaction. Repeated archive and restore requests are
idempotent. Rename, pin, and the Phase 5.43 schema are unchanged.

Archive is not delete. Tests prove conversation, message, run, run-event, and
conversation-owned attachment rows/records remain. Pin state, folder ID, title,
creation/update timestamps, and child records are unchanged; renaming while
archived retains archive state. Archive and pin remain independent. List still
returns archived conversations in insertion order.

The typed API client adds `setConversationArchived` with request URL, method,
payload, returned response, and HTTP error coverage. No UI, archive filter,
sorting, delete, folder, search, or Projects behavior is added. Execution paths
remain unchanged.

## Validation

- 103 focused backend tests pass, including conversation repository/service/API,
  Phase 5.42 metadata, Phase 5.43 persistence, and Phase 5.44 pin tests.
- Four new archive tests cover memory and relational idempotency and metadata/
  child preservation, HTTP validation/not-found/unfiltered list behavior, and
  archive plus restore across application restarts.
- Mutation proof: temporarily forced both archive writers to store `false`;
  **4 failures** in the 4 new tests. Restored both implementations and reran:
  **103 passed**.
- API-client: **87 passed**, including 3 archive transport/error tests.
  Contracts: **28 passed**. TypeScript checks pass for both packages.
- Ruff and strict mypy pass on touched backend code. `git diff --check` passes.
  Full canonical suite was not run.

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

Phase 5.45 complete. Phase 5.46 not started.
