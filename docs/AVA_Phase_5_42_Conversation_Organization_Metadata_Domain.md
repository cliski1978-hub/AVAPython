# AVA Phase 5.42 — Conversation Organization Metadata Domain

Phase 5.42 adds conversation organization metadata to the canonical
conversation domain and to the public conversation read contract. It is a
domain-and-contract step only: no database column, migration, repository write
method, write endpoint, frontend state, folder entity, project, search, delete,
sorting, or archive filtering was added.

## Fields

```text
ConversationRecord(
    conversation_id,
    title,
    created_at,
    updated_at,
    is_pinned=False,
    is_archived=False,
    folder_id=None,
)
```

The same three fields are exposed on `ConversationResponse`, the public read
contract, and mirrored in the frontend `@ava/contracts` package. All three
default (`False`, `False`, `None`), so every pre-existing construction site and
every existing response keeps its previous shape and behavior.

## Semantics

- `is_pinned` is presentational only. It never affects execution, run
  lifecycle, or durability.
- `is_archived` is a reversible hidden state. The conversation stays in the
  database; archiving never removes messages, runs, or events. Archive is not
  delete. Listing is still unfiltered, so no conversation disappears yet.
- `folder_id` is a nullable, AVA-owned organizational relationship. It is not a
  Project reference, carries no execution semantics, and is not validated
  against any existing folder, because Folder is not modelled yet.

## Where the change lives

- `ConversationRecord` — the canonical conversation domain object
  (`backend/src/ava/repositories/conversation_repository.py`).
- `ConversationResponse` — the backend public read contract
  (`backend/src/ava/contracts/conversations.py`).
- `_conversation_to_response` — the record-to-response mapping
  (`backend/src/ava/services/conversation_service.py`).
- `ConversationResponse` — the shared TypeScript contract
  (`frontend/packages/contracts/src/conversations.ts`), made required because
  the backend always emits the fields.

## Deliberate decisions

- **Persistence is deferred.** The SQLite `conversations` table already exists
  without these columns; defaults mean no migration is required for reads to
  succeed. Durability is a later step so that a schema change and its migration
  land together with the behavior that needs them.
- **No write path.** The repository port explicitly documents that archive,
  unarchive, pin, folder assignment, and delete are absent by design. Extra
  organization fields sent to the rename endpoint are ignored, not applied.
- **No Python client change.** `clients/python` has no conversation model, so
  nothing mirrors this contract there yet.
- **`agent-ui` `Conversation` is untouched.** That type (`src/types.ts`) is a
  UI execution-state model (id, title, messages, run, createdAt), not an API
  mirror. Adding organization fields with no consumer would force hydration
  mapping for no behavior.
- **Folder is not a Project.** `folder_id` is an organizational identifier
  only; it does not reference projects and must not become one.

## Validation

Focused tests cover domain defaults, explicit round-tripping, pin/archive
independence, `replace` stability, response-contract defaults, record-to-response
mapping, organization defaults over HTTP, unfiltered listing order, rename
stability, and the absence of an organization write path. Backend Ruff and mypy,
frontend TypeScript checks for the touched packages, the shared-contract and
workspace test suites, the Python client suite, and `git diff --check` all pass.

## Phase 5.43 implication

Phase 5.43 should persist this exact metadata through the established
repository/migration pattern and add a single explicit write path. It must not
let pin affect execution, must not let archive delete data or filter listing
until a dedicated step says so, and must not turn `folder_id` into a Project
reference.
