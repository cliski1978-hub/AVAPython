# AVA Phase 4 Implementation Log

Step-by-step record of the Phase 4 implementation. Each entry documents what
was built, the contracts introduced, and the validation results. Entries for
later steps are added only when those steps are actually implemented.

---

## Step 4.2 — Persistence Repository Ports

**Status: COMPLETE**

### Goal

Introduce the minimum AVA-owned persistence repository **port** layer (contracts
only) required to support durable application state in later Phase 4 steps.

No database, ORM, SQL, migrations, connection strings, persistence settings, or
adapter implementations were added. The existing in-memory `RunStore` /
`RunEventStore` were **not** migrated or rewritten; `RunService` and the entire
Phase 3 execution architecture are unchanged.

### Repository ports introduced

New package `backend/src/ava/repositories/`:

- `RunRepository` — `backend/src/ava/repositories/run_repository.py`
  - `create(run_id: str) -> RunRecord` — open a new **pending** run; a duplicate
    run id raises `ValueError`.
  - `get(run_id: str) -> RunRecord | None` — current frozen snapshot or `None`.
  - `update_status(run_id: str, status: RunStatus) -> RunRecord | None` — move a
    run to a new status, refreshing `updated_at`.
  - `set_execution_selection(run_id, selection: RunExecutionSelection | None) -> RunRecord | None`
    — record the resolved execution identity for a run.
- `RunRecord` — frozen dataclass relocated from `RunStore` as the shared,
  framework-neutral run-state record: `run_id`, `status: RunStatus`,
  `created_at`, `updated_at` (timezone-aware UTC), `execution_selection`.
- `RunEventRepository` — `backend/src/ava/repositories/run_event_repository.py`
  - `append(event: RunEvent) -> RunEvent` — append in order; a terminal event
    for an already-terminal run is ignored (idempotent).
  - `get_events(run_id: str) -> Collection[RunEvent]` — ordered immutable
    snapshot (empty for an unknown run).
  - `get_latest(run_id: str) -> RunEvent | None` — most recent event, if any.
- `TERMINAL_EVENT_TYPES` — the canonical `frozenset[EventType]` of
  `run_completed` / `run_cancelled` / `run_failed`, relocated from
  `RunEventStore` so port, store, and future adapters share one definition.

Both ports are `abc.ABC` with `@abstractmethod` bodies, matching the existing
`AgentPort` convention. They are exported through `ava.repositories.__init__`.

### Exact responsibilities

Expressed against the **existing semantic needs of `RunService`** (`run_service.py`),
derived 1:1 from current `RunStore` / `RunEventStore` behavior — no redesign of run
lifecycle, IDs, or terminal-event semantics:

- run identity stays caller-supplied; a repository never mints run IDs;
- event order preservation and single-terminal-event enforcement are part of the
  event contract;
- retrieval remains snapshot-only (no streaming; Phase 5 handles reconnect);
- no persistence-specific concepts (session, transaction, ORM entity, database
  row, query, table) appear anywhere in the ports;
- observability helpers (`list_run_ids`, `clear`) are deliberately **not** part
  of the ports — they remain concrete-store concerns.

### Architectural decisions

1. **Port type discipline.** Repository ports import only `ava.contracts`,
   sibling `ava.repositories` modules, stdlib, and Pydantic-free dataclasses. No
   SQL/ORM/driver, no FastAPI, no runtime/model/provider implementations.
2. **Single source of truth for shared types.** `RunRecord` and
   `TERMINAL_EVENT_TYPES` were relocated into the repositories package; the
   in-memory stores import them from there and continue to expose them under
   their existing module paths (`ava.services.run_store.RunRecord`,
   `ava.services.run_event_store.TERMINAL_EVENT_TYPES`) — no duplicate DTOs.
   This is the "minimal conformance adjustment" permitted by the step spec; the
   stores' behavior is unchanged and every pre-existing test passes verbatim.
3. **No wiring.** `RunService` still constructs `RunStore()` / `RunEventStore()`
   directly (`api/app.py:184`, `run_service.py` defaults). The ports are
   contracts with tests only. Store conformance is Step 4.3.
4. **Boundary direction encoded.** `ava.repositories` is added to
   `INTERNAL_BOUNDARIES` in the architecture tests: it may import only
   `contracts` and `repositories`, never `api / infrastructure / services /
   agents / models / core`. Services may (later) depend on the ports; the ports
   never depend on services.
5. **Guard for the inevitable.** A 4.2 guard asserts `RunService` and `AgentPort`
   import no `ava.repositories` — proving persistence did not alter the
   `RunService → AgentPort` path. A second guard asserts no database module is
   imported anywhere under `backend/src/ava` and `infrastructure/persistence`
   does not exist. Both are explicitly documented as removable in Step 4.3.

### Tests

New `backend/tests/test_repository_ports.py` (11 tests):

- both ports are abstract (cannot be instantiated directly);
- both ports are implementable by framework-free in-memory fakes mirroring the
  current store semantics (pending create, duplicate rejection, status update,
  execution-selection storage, ordered append, terminal sealing, per-run
  isolation);
- `RunRecord` is a frozen, AVA-owned snapshot;
- run identity is caller-supplied and never minted; duplicate create raises;
- event IDs and run association are preserved and jobs stay isolated per run;
- `TERMINAL_EVENT_TYPES` matches the documented terminal vocabulary;
- the existing `RunStore` produces the same `RunRecord` type as the port (no
  duplicated record type) and already exposes every port method with matching
  parameter names (shape pre-validation for 4.3 — stores are NOT conformance-
  declared this step);
- every type annotation on every port method resolves to AVA-owned or stdlib
  modules only (no provider/framework/database type crosses the boundary).

Updated `backend/tests/test_architecture.py` (+4 tests, +`REPOSITORIES_DIR`,
+`REPOSITORY_FORBIDDEN_MODULES`, +`repositories` in `INTERNAL_BOUNDARIES`):

- repository ports import no forbidden/database modules;
- repository ports depend only on contracts and sibling ports;
- `RunService` / `AgentPort` remain free of repository imports (execution path
  unaltered; the `RunService → AgentPort` dependency is unchanged);
- no database implementation is introduced anywhere in `ava` (top-level import
  scan) and `infrastructure/persistence` does not exist.

### Validation

- Targeted: `pytest tests/test_repository_ports.py` — 11 passed.
- Southern wall: `pytest tests/test_architecture.py tests/test_run_events.py` —
  70 passed.
- Full backend: `pytest` — **606 passed, 2 skipped** (baseline 591 + 15 new).
- `ruff check src tests` — clean (isort + SIM300 fixes applied).
- `mypy src` (strict) — clean, 96 files.
- Aggregate: `./scripts/test_all.sh` — full gate green (see Step report).

### Files changed

- `backend/src/ava/repositories/__init__.py` — new; exports the ports and types.
- `backend/src/ava/repositories/run_repository.py` — new; `RunRecord`,
  `RunRepository`.
- `backend/src/ava/repositories/run_event_repository.py` — new;
  `TERMINAL_EVENT_TYPES`, `RunEventRepository`.
- `backend/src/ava/services/run_store.py` — `RunRecord` relocated (imported,
  re-exported); store body unchanged.
- `backend/src/ava/services/run_event_store.py` — `TERMINAL_EVENT_TYPES`
  relocated (imported); store body unchanged.
- `backend/tests/test_repository_ports.py` — new; port contract tests.
- `backend/tests/test_architecture.py` — new repository-port guard tests.
- `docs/AVA_Phase_4_Implementation_Log.md` — new; this entry.

### Deferred work

- Adapting `RunStore` / `RunEventStore` to conform to the ports (Step 4.3).
- SQLite (or other) durable adapters, migrations, schema, connection handling,
  settings (Step 4.3+).
- Conversation / Message / Document / Attachment / Approval / Audit repository
  ports — deferred until their backend domain models/contracts exist (per the
  Step 4.1 audit).
- Streaming / event replay — Phase 5.

---

## Step 4.3 — In-Memory Stores Adopt the Repository Ports; RunService Dependency Inversion

**Status: COMPLETE**

### Goal

Make the in-memory stores explicit implementations of the Step 4.2 repository
ports and invert `RunService`'s state dependency so it programs against the
ports, never concrete stores. Behavior and run lifecycle are unchanged; this is
a structural/typing step only.

### What changed

1. **Store conformance (declaration only).**
   - `RunStore(RunRepository)` — `backend/src/ava/services/run_store.py`
   - `RunEventStore(RunEventRepository)` — `backend/src/ava/services/run_event_store.py`
   - Method bodies, semantics, invariants, and extra observability helpers
     (`list_run_ids`, `clear`) are untouched. Step 4.2's shape pre-validation
     meant this was one inheritance declaration per store.
2. **RunService dependency inversion** — `backend/src/ava/services/run_service.py`:
   - Imports `RunRepository` / `RunEventRepository` from `ava.repositories`
     instead of `RunStore` / `RunEventStore` from `ava.services`.
   - Constructor: `RunService(agent, *, run_repository, run_event_repository)`
     with **required** keyword-only ports. The previous default store
     construction is removed; composition is now the only place concrete
     stores are named. This keeps `RunService` unaware of repository
     implementation classes (the "no concrete import" guard).
   - Internal attributes renamed `_run_store` / `_event_store` →
     `_run_repository` / `_run_event_repository`.
   - `get_run_events` materializes the port's `Collection[RunEvent]` into the
     existing `list[RunEvent] | None` public return type.
   - Behavior, ID ownership, event sequences (success / cancelled / failed),
     terminal-event enforcement, and snapshot-only retrieval are unchanged;
     the diff renames dependencies without touching control flow.
3. **Composition injection** — `backend/src/ava/api/app.py:186`:
   `RunService(agent_port, run_repository=RunStore(), run_event_repository=RunEventStore())`.
   This is exactly the "application composition may instantiate the stores and
   inject them" case from the step spec; the API layer now names the concrete
   in-memory stores once, at startup.
4. **Test setup edits (mechanical).** Every `RunService(...)` construction in
   the test suite was updated to the new kwarg names
   (`run_store=` → `run_repository=`, `event_store=` → `run_event_repository=`)
   and to inject fresh stores where the old defaults were relied on:
   `test_runs.py`, `test_run_events.py`, `test_run_service.py`,
   `test_native_agent.py`, `test_workspace_live_integration.py`.

### Architectural decisions

1. **Ports stay the only contract; stores stay in `ava.services`.** No
   `infrastructure/persistence` package, database, ORM, or new runtime wiring.
   The stores remain the live in-memory adapters for this phase; Step 4.4+
   can introduce durable adapters behind the same ports without touching
   `RunService`.
2. **Required injection beats silent defaults.** Optional ports with `RunStore()`
   defaults would require `RunService` to import the concrete stores, violating
   the port/unaware-of-implementation boundary. Making the ports required moves
   construction to composition — the dependency-inversion point of the step.
3. **Port contract untouched.** `get_events -> Collection[RunEvent]` is kept as
   designed in 4.2; the service adapts with `list(...)` (the public API already
   promised a list). The `AgentPort` execution contract remains persistence-free.
4. **Guards reflect the new reality.** The 4.2 guard "RunService/AgentPort
   import no repository ports" is replaced by three guards:
   - `AgentPort` still imports no repository ports (execution contract purity);
   - `RunService` imports the repository **ports** and never the concrete
     `ava.services.run_store` / `ava.services.run_event_store` modules (which is
     why the constructor cannot default to fresh stores);
   - `RunService` keeps its `AgentPort` dependency alongside the ports.
   Plus a conformance guard (`issubclass` for both stores) and the retained
   no-database guard.

### Tests

- `backend/tests/test_repository_ports.py`: updated for conformance — new
  `test_run_store_now_implements_run_repository`,
  `test_run_event_store_now_implements_run_event_repository`; the 4.2 shape
  pre-validation test stays on as a shape regression guard.
- `backend/tests/test_architecture.py`: obsolete 4.2 execution-path guard
  replaced with the port-but-not-concrete guards described above; store
  conformance declared in architecture tests.
- All Phase 3 run-service / run-events / runs-API / native-agent /
  workspace-live-integration tests continue to pass unchanged in behavior;
  only construction lines were edited for the new constructor signature.

### Validation

- Targeted: `pytest test_repository_ports.py test_architecture.py
  test_run_service.py test_run_events.py test_runs.py test_native_agent.py
  test_workspace_live_integration.py` — 136 passed.
- Full backend: `pytest` — **611 passed, 2 skipped** (4.2: 606 + 5 new:
  +3 arch guards, +2 port conformance tests).
- `ruff check src tests` — clean.
- `mypy src` (strict) — clean, 96 files.
- Aggregate: `./scripts/test_all.sh` — full gate green (backend pytest/ruff/mypy,
  frontend tests + tsc lint, python client pytest/ruff/mypy).

### Files changed

- `backend/src/ava/services/run_store.py` — `class RunStore(RunRepository)`.
- `backend/src/ava/services/run_event_store.py` — `class RunEventStore(RunEventRepository)`.
- `backend/src/ava/services/run_service.py` — repository-port imports, required
  port constructor args, attribute renames, `list(...)` materialization.
- `backend/src/ava/api/app.py` — composition injects `RunStore()` /
  `RunEventStore()`.
- `backend/tests/test_run_service.py`, `test_run_events.py`, `test_runs.py`,
  `test_native_agent.py`, `test_workspace_live_integration.py` — construction
  sites updated to the new kwargs.
- `backend/tests/test_architecture.py` — guards replaced/extended.
- `backend/tests/test_repository_ports.py` — conformance tests + wording refresh.
- `docs/AVA_Phase_4_Implementation_Log.md` — this entry.

### Deferred work (unchanged from Step 4.1 audit)

- Durable (e.g. SQLite) repository adapters, migrations, schema, connection
  handling, persistence settings — later Phase 4 steps; the ports + stores now
  provide the seam for them.
- Conversation / Message / Document / Attachment / Approval / Audit repository
  ports — deferred until their backend domain models/contracts exist.
- Streaming / event replay — Phase 5.
---

## Step 4.4 — Conversation and Message Backend Domain

**Status: COMPLETE**

### Goal

Introduce the AVA-owned backend **conversation and message** domain, wired as
minimal REST endpoints, with the same architecture as the run domain: frozen
commit records + repository ports → in-memory stores → a port-injecting
`ConversationService` → thin routes. In-memory only: no database, ORM, SQL,
migrations, or persistence settings. Step 4.4 is **backend-only** — no frontend
packages are imported or modified, and nothing in Step 4.5 (Document domain,
relational adapters) or beyond was started.

Scope: create/get/list conversation, rename/update metadata, append message,
get message, and list messages in stable append order. Deliberately absent:
archive/delete lifecycle (`archived_at`), attachments, RAG, streaming, auth,
approvals, and message authoring/streaming pipelines.

### Model decisions

- **Backend-owned vocabulary.** `MessageRole` (`USER`/`ASSISTANT`/`SYSTEM`) and
  `MessageStatus` (`PENDING`/`COMPLETE`/`FAILED`/`CANCELLED`) live in
  `ava.contracts.conversations`; their string values deliberately mirror the
  frontend reducer's message shape (`user|assistant|system`,
  `pending|complete|failed|cancelled`) so a future client mapping is 1:1. They
  are **not** the frontend TypeScript types and are never imported from
  frontend packages.
- **`MessageStatus.PENDING`** is reserved for messages awaiting a terminal run
  outcome (a future authoring pipeline); today stored messages are stamped
  `COMPLETE` because there is nothing to await.
- **Identity is service-owned.** `ConversationService` mints `str(uuid4())`
  identifiers; clients never supply them. Timestamps are authoritative,
  timezone-aware UTC values (`datetime.now(UTC)`), never client-supplied.
- **No `archived_at` / deletions.** Lifecycle management is out of scope; the
  repository port exposes only `create/get/list/update_title`.
- **Run linkage.** `MessageRecord` carries optional `source_run_id` — the
  minimum message↔run linkage requested by the step. `RunService` itself is
  untouched and stays free of conversation persistence.

### Ports and records

- `ConversationRepository` — `backend/src/ava/repositories/conversation_repository.py`
  - `ConversationRecord` (frozen): `conversation_id`, `title`, `created_at`,
    `updated_at`.
  - `create(conversation_id, *, title) -> ConversationRecord` (duplicate id →
    `ValueError`), `get`, `list` (insertion order), `update_title` (refreshes
    `updated_at`).
- `MessageRepository` — `backend/src/ava/repositories/message_repository.py`
  - `MessageRecord` (frozen): `message_id`, `conversation_id`, `role`,
    `content`, `status`, `created_at`, `updated_at`, `source_run_id: str | None = None`.
  - `append(message) -> MessageRecord` (duplicate id → `ValueError`), `get`,
    `list_for_conversation` (append order). Message persistence is
    conversation-**agnostic** (mirrors `RunEventRepository`): unknown
    conversations yield empty lists; the service enforces existence.

### In-memory implementations and service

- `ConversationStore` / `MessageStore` — `backend/src/ava/services/...`
  explicit subclasses of the ports (following the established `RunStore` /
  `RunEventStore` naming convention; the step's `InMemory*Repository` naming was
  set aside in favor of "established naming conventions"). Duplicate-id
  `ValueError`, frozen snapshots, stable ordering, `clear()` for tests.
- `ConversationService` — `backend/src/ava/services/conversation_service.py`
  - Required keyword-only ports (`conversation_repository`, `message_repository`);
    no defaultdict stores, so composition must inject them.
  - Domain errors: `ConversationNotFoundError`, `DuplicateConversationError`,
    `DuplicateMessageError` (repository `ValueError` collisions mapped).
  - Default title: blank/omitted → `"New Conversation"`. `append_message`
    defaults role `USER`, stamps `COMPLETE`, enforces conversation existence
    before appending. Reads return `None` for unknown conversations.

### Contracts and routes

- `ava/contracts/conversations.py` (re-exported from `ava.contracts`):
  `CreateConversationRequest` (`title: str | None`), `ConversationResponse`,
  `UpdateConversationRequest` (title validated non-blank → 422),
  `CreateMessageRequest` (`content` validated non-blank; `role` default `user`;
  `source_run_id`), `MessageResponse`, `ConversationListResponse`,
  `ConversationMessagesResponse`. Responses carry `contract_version`.
- `backend/src/ava/api/routes/conversations.py` — thin, `request.app.state`
  routes:
  - `POST /conversations` → **201**; `GET /conversations`;
  - `GET /conversations/{id}` → 200/404 `conversation_not_found`;
  - `PATCH /conversations/{id}` → 200/404;
  - `POST /conversations/{id}/messages` → **201**/404/409;
  - `GET /conversations/{id}/messages` → 200/404 (unknown conversation).
  - **201 for POST creates** is a documented deviation from `POST /runs` (200
    with the terminal outcome), since conversation/message creation creates a
    distinct resource.
  - `404s` use `conversation_not_found` / `NOT_FOUND`; duplicate collisions map
    to **409** `VALIDATION` (`conversation_id_conflict` / `message_id_conflict`)
    as defense-in-depth (clients never supply ids, so `409` is defensive).
    Invalid role/content → 422 via the contract.
- Composition: `app.py` registers `app.state.conversation_service =
  ConversationService(conversation_repository=ConversationStore(),
  message_repository=MessageStore())` and the router. `ErrorCategory` unchanged
  (no `CONFLICT` member added).

### Guards

- `test_repository_stores_conform_to_their_ports` extended with
  `issubclass(ConversationStore, ConversationRepository)` /
  `issubclass(MessageStore, MessageRepository)`.
- `test_conversation_service_depends_on_repository_ports_not_concrete_stores` —
  the service imports the repository ports and never the concrete stores.
- `test_run_service_stays_free_of_conversation_persistence` — `RunService`
  imports no conversation repositories/stores/service.
- `test_conversation_sources_import_no_frontend_or_vendor_packages` —
  the seven conversation source files import nothing from `@ava/*`, Tauri, or
  React-family packages (stdlib + ava + pydantic + fastapi only).
- `test_conversation_repository_ports_import_only_contracts_and_records` —
  the new ports' AVA imports are limited to `ava.contracts`.
- Existing guards (repository ports import no DB/framework modules, repository
  ports depend only on contracts + sibling ports, no-database-implementation,
  `INTERNAL_BOUNDARIES`) auto-cover the new files unchanged.

### Tests

- `backend/tests/test_conversation_repositories.py` — port contract tests:
  abstract ports not instantiable; implementable by framework-free fakes;
  frozen records; caller-supplied identity; stores conform to the ports;
  store isolation/`clear`; boundary type discipline (AVA-owned or stdlib only).
- `backend/tests/test_conversation_service.py` — default/custom/blank titles;
  service-minted UUIDs; aware-UTC timestamps; insertion order; rename +
  blank-title rejection; duplicate → domain errors; append defaults
  (role `user`, status `complete`); unknown conversation → not-found;
  messages scoped to their conversation.
- `backend/tests/test_conversations.py` — API: 201 shapes (conversation +
  message), default title, UUID ids, UTC ISO timestamps, empty/all lists,
  404 `conversation_not_found`, 404 unknown-conversation messages, blank
  title/content → 422, invalid role → 422, duplicate collisions → 409.

### Validation

- Targeted: `pytest test_conversation_repositories.py test_conversation_service.py
  test_conversations.py test_architecture.py test_repository_ports.py
  test_runs.py` — 151 passed.
- Full backend: `pytest` — **673 passed, 2 skipped** (4.3: 611 + 62 new).
- `ruff check src tests` — clean.
- `mypy src` (strict) — clean, 103 files (4.3: 96).
- Aggregate: `./scripts/test_all.sh` — full gate green (backend pytest/ruff/mypy,
  frontend tests + tsc lint, python client pytest/ruff/mypy); no frontend files
  changed.

### Files changed

- New: `backend/src/ava/contracts/conversations.py`,
  `backend/src/ava/repositories/conversation_repository.py`,
  `backend/src/ava/repositories/message_repository.py`,
  `backend/src/ava/services/conversation_store.py`,
  `backend/src/ava/services/message_store.py`,
  `backend/src/ava/services/conversation_service.py`,
  `backend/src/ava/api/routes/conversations.py`,
  `backend/tests/test_conversation_repositories.py`,
  `backend/tests/test_conversation_service.py`,
  `backend/tests/test_conversations.py`.
- Modified: `backend/src/ava/contracts/__init__.py`,
  `backend/src/ava/repositories/__init__.py`, `backend/src/ava/api/app.py`
  (composition + router), `backend/tests/test_architecture.py` (guards),
  `docs/AVA_Phase_4_Implementation_Log.md` (this entry).

### Deferred work (not started)

- Step 4.5 and the Document/Attachment/Approval/Audit domains — later steps.
- Durable (relational/SQLite) conversation + message adapters, migrations,
  schema — later Phase 4 steps; the ports + stores now provide the seam.
- Frontend connection + frontend contract types (e.g. `ConversationMessage`),
  event sourcing / streaming message authoring — later steps.


## Step 4.5 — Document Backend Domain

**Status: COMPLETE**

### Goal

Introduce the AVA-owned backend **document** domain, wired as minimal REST
endpoints, with the same architecture as the run/conversation domains: frozen
commit records + a repository port → an in-memory store → a port-injecting
`DocumentService` → thin routes. In-memory only, with a **server-side HTML
content safety boundary** (the audit's stored-XSS requirement, §12.7) before
any document content becomes trusted backend state. Step 4.5 is
**backend-only** — no frontend packages are imported or modified, and nothing
in Steps 4.6+ (relations, attachments, approvals, audits, revisions) was
started.

Scope: create/get/list document, rename, update content — the operations the
frontend `documentReducer` already has (`create`, `setActiveDocument`,
`updateContent`, `rename`). Deliberately absent: archive/delete (`close` is a
frontend-only dirty-state concern), document revisions (reserved for later —
the audit's 4.8/`DocumentRevision`), agent edit operations, import/export,
attachments, RAG, and durable storage.

### Model decisions

- **Backend-owned identity.** `document_id` is always a service-minted
  `str(uuid4())`; clients never supply identifiers. This replaces the
  frontend's `crypto.randomUUID()` (audit 4.6) once a future step hydrates the
  frontend from the backend.
- **Canonical content representation.** Content is stored as flat
  serialized-HTML: `content: str` + `content_format: ContentFormat`. No
  editor objects, no `{format, value}` wrapper in the repository/service
  layer. `ContentFormat(StrEnum)` has one member, `HTML = "html"`, matching the
  frontend's `DocumentContent.format`. The content the frontend editor
  produces today (`editor.getHTML()`) is exactly the content the backend
  stores.
- **Timestamps.** `created_at`/`updated_at` are timezone-aware
  `datetime.now(UTC)` produced by the store; renaming or content updates
  refresh `updated_at` and preserve `created_at` (snapshot semantics, like
  conversations).
- **Default title.** `DEFAULT_DOCUMENT_TITLE = "Untitled Document"` matches
  the frontend's default. The frontend's "Untitled Document N" deconfliction
  remains client-side; the backend stores a flat title and never races the
  client over numbering (that rule survives into persistent storage, audit
  4.6).
- **Errors.** Unknown document → repository returns `None` → route `404
  document_not_found` (deliberately *no* `DocumentNotFoundError` class — the
  not-found path is data flow, not control flow). Repository `ValueError` on
  duplicate id → `DuplicateDocumentError` → `409 document_id_conflict`.
  Content-policy violations → `InvalidDocumentContentError` → `422
  invalid_document_content`. Blank-titled updates are rejected by the update
  contract (422) and defended again in `rename_document` (raises `ValueError`,
  unreachable via HTTP today).
- **Unknown vs invalid precedence.** `update_document_content` resolves
  existence *before* validating content: an unknown document returns `None`
  (404) even when the payload is policy-violating — 404 wins over 422, the
  same rule conversation updates use.
- **Unsupported `content_format`** is gated at the contract (enum → 422) and
  defended in the service (`_enforce_supported_format`, raising
  `InvalidDocumentContentError`) — unreachable until a second format exists;
  the contract gating is the tested normalization.
- **No revision vocabulary** anywhere in the document records/ports (frontend
  `AvaDocument` has no revision lineage; `DocumentRevision` is a later step).

### HTML content policy (server-side safety boundary)

`backend/src/ava/services/html_content_policy.py` — an AVA-owned, editor- and
framework-neutral sanitization contract implemented with **stdlib
`html.parser` only** (no new dependency; `bleach`/`nh3`/`DOMPurify` are
documented as an upgrade path when durable persistence arrives). Policy is
**reject-on-violation** (allowed-tags allowlist), never silent stripping:

- Non-empty content that parses as ≥1 element; `text-only`, whitespace,
  doctype, and processing-instruction input is rejected.
- `ALLOWED_TAGS` = the Tiptap StarterKit vocabulary: `p h1-h6 strong em s
  code pre blockquote ul ol li br hr a` (+ `b i sub sup mark` aliases).
- Only attribute allowed is `href`, only on `<a>`; `SAFE_HREF_PROTOCOLS` =
  `http https mailto tel` plus `#`-fragments; `javascript:`, `vbscript:`,
  `data:`, scheme-less `//host`, and relative hrefs are rejected (case- and
  entity-insensitive).
- `BANNED_ATTRIBUTE_PREFIXES = ("on",)` — inline event handlers rejected even
  on allowed tags; `style`, `class`, `id`, `src`, etc. rejected (future
  `link` extension support must extend `ALLOWED_ATTRIBUTES` + href checks in
  the same policy, keeping the reject-on-violation rule).
- Tags must be explicitly balanced/nested (void `br hr` exempt); malformed
  input is rejected, never auto-fixed.
- HTML comments are tolerated (inert text); drawbacks of the strict approach
  (modern-Tiptap extensions, e.g. `link`/custom nodes, need an allowlist
  update) are documented rather than silently accepted.

### Repository port

`backend/src/ava/repositories/document_repository.py` — `DocumentRecord`
(frozen: document_id, title, content, content_format, created_at, updated_at;
no revision fields) + `DocumentRepository` ABC: `create` (raises `ValueError`
on duplicate), `get`, `list` (stable insertion order), `update_title`,
`update_content`.

### Store

`backend/src/ava/services/document_store.py` — `DocumentStore(DocumentRepository)`,
dict keyed by id, `ValueError` on duplicate create, immutable snapshots via
`dataclasses.replace`, insertion-ordered `list()`, updates refresh
`updated_at` via `datetime.now(UTC)`, `clear()` test/observability helper.
Registered in the store conformance guard.

### Service

`backend/src/ava/services/document_service.py` — `DocumentService(document_repository=...)`
ports to `DocumentRepository` only (never the concrete store; composition
injects it). Owns id minting, default title resolution, policy enforcement
(`HtmlContentError` → `InvalidDocumentContentError`), duplicate normalization,
and unknown-document `None` semantics. Never sees editor objects — strings
only.

### Contracts & routes

`backend/src/ava/contracts/documents.py` — `ContentFormat` (`html`),
`CreateDocumentRequest` (title optional; content required non-blank),
`UpdateDocumentRequest` (title/content optional, `model_validator` requires
at least one, blank-when-present is rejected), `DocumentResponse`
(document_id, title, content, content_format, created_at, updated_at,
contract_version), `DocumentListResponse`.

`backend/src/ava/api/routes/documents.py` — `GET/POST /documents` (POST →
**201**) and `GET/PATCH /documents/{document_id}`. PATCH applies title first,
then content (final `updated_at` reflects the content change); unknown
document → 404 regardless of payload. Handlers are thin: orchestration lives
in the service; normalized error helpers return `ErrorResponse`
(`document_not_found`, `document_id_conflict`, `invalid_document_content`).
Composition in `backend/src/ava/api/app.py`: `app.state.document_service =
DocumentService(document_repository=DocumentStore())` + router registration.

### Frontend compatibility findings (recorded; frontend NOT modified)

- `AvaDocument { id, title, content: DocumentContent, createdAt, updatedAt,
  isDirty }`; `DocumentContent { format: "html", value: string }`
  (`frontend/packages/document-core`). Backend content maps to
  `content.value`; `content_format` maps to `content.format`.
- Frontend `id` = `crypto.randomUUID()` with `ava-document-...` fallback;
  backend id = `str(uuid4())` — same UUID shape, interchangeable keys.
- `INITIAL_DOCUMENT = "<h1>AVA Document Workspace</h1><p>This is an AVA
  document.</p>"` and new-document content `"<p></p>"` both **pass** the HTML
  policy unchanged (covered by tests).
- Backend timestamps are authoritative (aware-UTC ISO); the frontend stamps
  `updatedAt` locally (including on `markClean`) — a future hydration step
  reconciles the two. `isDirty`/`markClean` stay frontend-only.
- The audit labels document work as 4.6 (identity) and 4.7 (storage +
  sanitization); this running-plan step "4.5 Document backend domain"
  implements those two together, which is why both audit rows are satisfied
  here rather than in separate steps.

### Architecture guards (`test_architecture.py`)

- `test_repository_stores_conform_to_their_ports` — extended with
  `issubclass(DocumentStore, DocumentRepository)`.
- `test_document_service_depends_on_repository_port_not_concrete_store` —
  service imports `ava.repositories.document_repository`, never the store or
  infrastructure.
- `test_document_repository_port_imports_only_contracts_and_records` —
  port's AVA imports limited to `ava.contracts`.
- `test_run_service_stays_free_of_document_domain` — RunService imports no
  document repo/store/service/policy.
- `test_document_sources_import_no_frontend_or_vendor_packages` — the six
  document files import nothing from `@ava`, Tiptap, ProseMirror, React-family,
  or Tauri (stdlib + ava + pydantic + fastapi only).
- `test_html_content_policy_is_editor_neutral_and_stdlib_only` — the policy's
  top-level imports ⊆ `{html}`; zero `ava` imports. Sanitization can never
  depend on the editor that produced the content.
- Existing guards (repository ports import no DB/framework modules,
  no-database-implementation, `INTERNAL_BOUNDARIES`) auto-cover the new files
  unchanged.

### Tests

- `backend/tests/test_document_content_policy.py` — security: initial frontend
  document and `<p></p>` pass byte-for-byte; StarterKit vocabulary accepted;
  `script`/`img onerror`/`svg`/`iframe`/`style`/`div`/`table`/`textarea`/
  `form` rejected; `javascript:`/`data:`/`vbscript:`/`//host` hrefs rejected
  (case-insensitive); `on*`/`style`/`class` attributes rejected; doctype/PI/
  text-only/whitespace/malformed input rejected.
- `backend/tests/test_document_repositories.py` — frozen snapshot records; no
  revision fields; duplicate create → `ValueError` without clobbering; get/list
  insertion order; caller-isolated list copies; updates preserve `created_at`,
  refresh `updated_at`; unknown → `None`; `clear()`; port conformance.
- `backend/tests/test_document_service.py` — default/trimmed titles; UUIDs;
  aware-UTC timestamps; policy enforcement on create/update; `None` on unknown;
  unknown-wins-over-invalid; duplicate → `DuplicateDocumentError`; strings-only
  boundary (no editor objects).
- `backend/tests/test_documents.py` — API: 201 shape + contract_version,
  default title, UUID ids, UTC ISO timestamps, empty/all lists, 404
  `document_not_found`, PATCH title/content/both (title-first), 404-wins,
  422 blank/empty/missing/at-least-one/unsupported-format/dangerous content,
  409 `document_id_conflict`.

### Validation

- Targeted: `pytest test_document_content_policy.py
  test_document_repositories.py test_document_service.py test_documents.py
  test_architecture.py` — 152 passed.
- Full backend: `pytest` — **768 passed, 2 skipped** (4.4: 673 + 95 new).
- `ruff check src tests` — clean.
- `mypy src` (strict) — clean, 109 files (4.4: 103).
- Aggregate: `./scripts/test_all.sh` — full gate green (backend pytest/ruff/
  mypy, frontend tests + tsc lint, python client pytest/ruff/mypy); no
  frontend files changed.

### Files changed

- New: `backend/src/ava/contracts/documents.py`,
  `backend/src/ava/repositories/document_repository.py`,
  `backend/src/ava/services/document_store.py`,
  `backend/src/ava/services/document_service.py`,
  `backend/src/ava/services/html_content_policy.py`,
  `backend/src/ava/api/routes/documents.py`,
  `backend/tests/test_document_content_policy.py`,
  `backend/tests/test_document_repositories.py`,
  `backend/tests/test_document_service.py`,
  `backend/tests/test_documents.py`.
- Modified: `backend/src/ava/contracts/__init__.py`,
  `backend/src/ava/repositories/__init__.py`, `backend/src/ava/api/app.py`
  (composition + router), `backend/tests/test_architecture.py` (guards +
  store conformance), `docs/AVA_Phase_4_Implementation_Log.md` (this entry).

### Deferred work (not started)

- Step 4.6+ (Attachments, Approvals, Audits), frontend hydration to the
  document API, `markClean`-time flush, durable (relational/SQLite) document
  adapters + migrations — later Phase 4 steps; the port + store + policy now
  provide the seam.
- `DocumentRevision`/history and later revisions capture (audit 4.8) —
  reserved for a later step; records deliberately carry no revision fields.
- HTML sanitization upgrade path — swap `html_content_policy` internals for
  `bleach`/`nh3` (or `DOMPurify` on the client) when durable persistence
  arrives; the reject-on-violation API surface stays stable.
- Document delete/archive lifecycle and agent edit operations — not part of
  this step's scope.

---

## Step 4.6 — Concrete Relational Persistence Adapter

**Status: COMPLETE**

### Goal

Introduce the first concrete **relational** persistence infrastructure: a
SQLite-backed implementation for each of the five existing repository ports
(Run, RunEvent, Conversation, Message, Document), plus the database lifecycle,
storage models, serialization rules, an optional composition seam, and
architecture guards. Production defaults and behavior are unchanged — the
application still boots on the in-memory stores; this step only makes the
relational adapters available, tested, and durable.

### Database decision (and dependency decision)

- **Database: SQLite.** The audit's reference shape (§2 "SQLite type",
  §9 "engine: sqlite3", §12 `AVA_PERSISTENCE=memory|sqlite`) endorses SQLite
  as the concrete relational engine; it needs no server, gives deterministic
  tests, and matches the current minimal-dependency posture. MSSQL remains the
  audit's (§1) future enterprise target — the engine-agnostic ports and the
  `SqliteDatabase` lifecycle seam exist specifically so that swap stays behind
  the adapters.
- **Persistence library: stdlib `sqlite3` only — no new third-party
  dependency.** The current dependency policy (minimal MIT dependencies, only
  `>=` pins) and the audit's "if new persistence dependencies are required"
  framing leave `sqlite3` as the established Python binding for SQLite. The
  audit's recommended migration path (`Alembic`, and an ORM if ever needed) is
  documented as the **future upgrade path**; the row-mapper design keeps SQL
  statements centralized so that upgrading to SQLAlchemy/Alembic later is a
  confined change. `pyproject.toml` gained nothing.
- **Numbering note / deviation from the audit:** the audit's own step numbers
  (4.2 run ports, 4.3 in-memory stores, 4.11 engine integration / MSSQL) differ
  from the running plan used here (4.2/4.3 run ports + memory, 4.4
  conversations, 4.5 documents, 4.6 relational adapter, 4.8–4.10 activation).
  This entry follows the running plan; the audit facts are not rewritten.

### Package structure

New package `backend/src/ava/infrastructure/persistence/` — the only AVA code
authorized to import database drivers/ORMs:

- `errors.py` — `PersistenceError` (database failure outside port semantics).
- `models.py` — storage-only DDL: `SCHEMA_STATEMENTS` for exactly five tables.
- `serialization.py` — UTC timestamp / enum / JSON helpers + row mappers.
- `database.py` — `SqliteDatabase` lifecycle (engine/session factory seam),
  transaction boundaries, and `translate_database_error`.
- `composition.py` — `PersistenceRepositories` +
  `create_relational_repositories(url)`.
- `repositories/` — the five concrete adapters.

Services never receive a database object; adapters receive only the
`SqliteDatabase` handle.

### Lifecycle design (`SqliteDatabase`)

- Lazily opens a single shared `sqlite3` connection on first use
  (`isolation_level=None` autocommit, `Row` factory, `check_same_thread=False`).
- `connect()` context manager yields the shared connection; `transaction()`
  wraps writes in explicit `BEGIN IMMEDIATE … COMMIT/ROLLBACK`.
- Schema bootstrap is idempotent `CREATE TABLE IF NOT EXISTS` on connect —
  a schema initialization, **not** a migration system (migrations/Alembic land
  in Step 4.7). `create_schema=False` defers bootstrap to `ensure_schema()`.
- `dispose()` closes the connection; a `:memory:` database restarts empty,
  a file-backed database reuses its durable content.

### Storage models (five tables only)

`runs`, `run_events`, `conversations`, `messages`, `documents`. No later-phase
tables exist (no migration tables, revisions, metadata). Domain id (`run_id`,
`event_id`, `conversation_id`, `message_id`, `document_id`) is the key;
events/messages/conversations/documents carry a technical surrogate `id`
rowid, invisible to contracts/services, for stable insertion ordering.
`run_events` adds `UNIQUE(run_id, seq)` (monotonic per-run sequence) plus a
partial `UNIQUE` index enforcing at most one terminal event per run;
`messages` has `UNIQUE(conversation_id, message_id)`, matching the
in-memory store's per-conversation scoping.

### Adapters (`Relational*Repository`, five ports exactly)

Behavioral parity with the in-memory stores, proven by the shared compatibility
suite: duplicate → `ValueError` (same messages), unknown → `None`,
insertion-order listing, terminal-event idempotent sealing, updates refreshing
`updated_at`, messages stored verbatim (timestamps never re-minted). Storage
mapping: enums as `.value` strings, timestamps as ISO-8601 aware-UTC strings
(`also +00:00`), `RunEvent.payload` and `RunRecord.execution_selection` as
deterministic JSON (`sort_keys=True, separators=(",", ":")`); restore via
`Enum(value)`, `datetime.fromisoformat`, `model_validate_json` — no pickling,
no vendor objects. Deliberate, documented tightening over the in-memory stores:
event `event_id` uniqueness (unreachable in the uuid4 service flow) and the
DB-level terminal constraint.

### Error translation

`signed translate_database_error`: `sqlite3.IntegrityError` →
`ValueError("{entity} already exists: {key}")`; any other `sqlite3.Error` →
`PersistenceError`. Services/routes never see raw driver exceptions or table/
connection details.

### Configuration

- `AVA_PERSISTENCE` → `Settings.persistence_provider` (default `memory`,
  validated `memory|relational` like `_env_hosting_mode`; anything else raises).
- `AVA_PERSISTENCE_DATABASE_URL` → `Settings.persistence_database_url`
  (default `ava.sqlite3`).
- `.env.example` documents both. The default stays `memory`; `app.py` is
  unchanged and still composes in-memory stores.

### Architecture guards (new/changed)

- Replaced the old "no database may exist" guard with
  `test_database_imports_are_confined_to_infrastructure_persistence`: DB/ORM
  imports (`sqlite3`, `sqlalchemy`, `aiosqlite`, `sqlmodel`, …) only inside
  `infrastructure/persistence`.
- `test_services_do_not_import_database_modules` and
  `test_contracts_do_not_import_database_modules`.
- `test_persistence_layer_imports_only_repositories_and_contracts` (stdlib +
  `ava` only; inward siblings).
- `test_relational_repositories_conform_to_their_ports` (issubclass × 5).
- `test_persistence_schema_introduces_no_later_phase_tables` (CREATE TABLE set
  is exactly the five; later-phase vocabulary forbidden).
- Existing guards (repository ports import no DB modules, service ports-only
  dependency, boundary direction) auto-cover the new files unchanged.

### Tests

- `test_persistence_database.py` — schema bootstrap + idempotence, terminal
  constraint, transaction commit/rollback, `dispose` semantics, error
  translation, timestamp/JSON/execution-selection serialization and row
  mapping.
- `test_relational_run_repository.py` / `run_event_repository.py` /
  `conversation_repository.py` / `message_repository.py` /
  `document_repository.py` — parity with each in-memory store: duplicates,
  unknown→`None`, ordering, terminal sealing, payload/timestamp round-trips,
  aware-UTC timestamps.
- `test_persistence_durability.py` — the adapter-level restart proof: write
  full state through all five adapters to a temp-file DB, `dispose()`, reopen a
  fresh `SqliteDatabase` + adapter set, and read the same records back; an
  in-memory control shows the file is what carries the state.
- `test_repository_behavior_compatibility.py` — the same representative
  semantics parameterized over in-memory stores vs relational adapters, so any
  semantic drift fails a test.
- `test_relational_composition.py` — factory sanity: five conforming adapters
  over one shared database, port round-trips, idempotent `dispose()`.
- settings tests for both new env vars (defaults, overrides, invalid provider).

### Validation

- Targeted: new relational/durability/compatibility/composition +
  `test_architecture.py` + `test_settings.py` — **188 passed**.
- Full backend: `pytest` — **884 passed, 2 skipped** (4.5: 768).
- `ruff check src tests` — clean.
- `mypy src` (strict) — clean, 121 files (4.5: 109).
- Aggregate: `./scripts/test_all.sh` — full gate green (backend pytest/ruff/
  mypy, frontend tests + tsc lint, python client pytest/ruff/mypy); no
  frontend/client files changed.

### Files changed

- New: `backend/src/ava/infrastructure/persistence/{__init__,errors,models,
  serialization,database,composition}.py`,
  `backend/src/ava/infrastructure/persistence/repositories/{__init__,
  run_repository,run_event_repository,conversation_repository,message_repository,
  document_repository}.py`,
  `backend/tests/test_persistence_database.py`,
  `backend/tests/test_relational_run_repository.py`,
  `backend/tests/test_relational_run_event_repository.py`,
  `backend/tests/test_relational_conversation_repository.py`,
  `backend/tests/test_relational_message_repository.py`,
  `backend/tests/test_relational_document_repository.py`,
  `backend/tests/test_persistence_durability.py`,
  `backend/tests/test_repository_behavior_compatibility.py`,
  `backend/tests/test_relational_composition.py`.
- Modified: `backend/src/ava/configuration/settings.py`,
  `backend/tests/test_architecture.py` (guards),
  `backend/tests/test_settings.py` (`_AVA_VARS` + persistence tests),
  `.env.example`, `docs/AVA_Phase_4_Implementation_Log.md` (this entry).
- Dependencies: **none added.**

### What stays in-memory

Production composition (`app.py`) is untouched: the default
`AVA_PERSISTENCE=memory` path still builds the in-memory stores, and the
relational adapters are not wired in. Run/model orchestration, OpenHands,
security, API routes, frontend, and the python client are unaffected.

### Deferred work (not started)

- Step 4.7 — migrations/Alembic (the schema bootstrap is explicitly not a
  migration system).
- Steps 4.8–4.10 — activating durable persistence from configuration
  (`create_relational_repositories` → services) and database selections.
- Audit steps (4.11 onward / MSSQL) and all later-phase tables (metadata,
  revisions) — reserved; the guard test forbids them from the Step 4.6 schema.

---

## Step 4.7 — Database Migration Foundation

**Status: COMPLETE**

### Goal

Replace Step 4.6's idempotent "create-if-missing" schema bootstrap with a
version-controlled, AVA-owned **migration system**: the single authoritative
mechanism for creating and evolving the relational schema. A metadata table
records what has been applied; a fresh database bootstraps through migration
v0001; an existing Step 4.6 database (five tables, no metadata) is adopted by
validating its exact structure and stamping it — data untouched; anything
unknown or newer fails closed (no downgrades, no destructive rewrites). No
behavioral or configuration change: the production default stays
`AVA_PERSISTENCE=memory`, no new environment variables, no new dependencies.

### Numbering note / deviation from the audit

The running plan schedules this as **4.7**; the audit's own numbering (§10)
lists engine migration integration as **4.11**. This entry follows the running
plan; audit facts are not rewritten (same deviation note as Step 4.6).

### Migration system architecture

New package
`backend/src/ava/infrastructure/persistence/migrations/` — inside the
persistence package (the sanctioned database boundary), never imported by
ports, contracts, services, API, core, agents, or configuration.

- **`migration.py`** — `Migration` (frozen dataclass: `version`, `name`,
  `up(connection)`, optional `verify(connection)`, `expected_tables`) plus the
  error hierarchy:
  - `MigrationError(PersistenceError)` — generic migration/runtime failures;
  - `SchemaValidationError(MigrationError)` — schema does not match the
    expected structure (unknown/incompatible legacy database, malformed
    metadata table);
  - `UnsupportedSchemaVersionError(MigrationError)` — database is at a version
    newer than the running application supports; downgrade is never performed.
- **`registry.py`** — `MigrationRegistry`, the deterministic, deduplicated
  migration sequence. Registration order is irrelevant: application order is
  always ascending **explicit version**. Duplicate versions and non-positive
  versions are rejected; `verify()` cross-checks stored entries; iteration is
  ascending.
- **`versions/v0001_initial_schema.py`** — version 1, "initial application
  persistence schema"; its `STATEMENTS` reproduce the Step 4.6 five-table
  schema **byte-for-byte**: `runs`, `run_events`, `conversations`, `messages`,
  `documents`, plus the `idx_run_events_one_terminal` partial unique index and
  `idx_messages_conversation_order`. **No foreign keys** — matching Step 4.6
  exactly is what makes legacy adoption safe; FKs are a candidate future
  migration. `verify_structure` validates tables, exact column sets, no
  unexpected tables, the unique keys (runs.run_id, run_events.event_id,
  run_events(run_id, seq), conversations.conversation_id,
  messages(conversation_id, message_id), documents.document_id) and both
  critical indexes.
- **`versions/__init__.py`** — `default_registry()` registers the v1
  migration: the application's authoritative sequence.
- **`validation.py`** — bounded SQLite introspection helpers
  (`table_exists`, `present_tables`, `table_columns`, `has_unique_index_on`,
  `has_named_index`, `is_unique_index`) used by verification only.
- **`runner.py`** — `MigrationRunner(database, registry)` and
  `AppliedMigration`:
  - `migrate()` → versions applied this call (`[]` if already current);
  - `current_version()`, `applied_migrations()`, `pending_migrations()`;
  - **fresh database** (no metadata, no schema): apply pending migrations in
    ascending version order;
  - **legacy Step 4.6 database** (no metadata, initial-schema tables present):
    validate the exact expected structure, then stamp version 1 — data is
    preserved;
  - **database newer than the code**: recorded version(s) beyond the registry
    → `UnsupportedSchemaVersionError`, no downgrade attempted;
  - **inconsistent history**: gaps or extra unknown versions inside the known
    range → `MigrationError`;
  - **metadata table** (`ava_schema_migrations`):
    `version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL`;
    created lazily only when first recording a migration; malformed structure
    fails closed with `SchemaValidationError`;
  - **per-migration transaction**: each migration + its metadata record run in
    one `BEGIN IMMEDIATE … COMMIT`; a failure rolls back fully and the database
    remains at its prior valid version.

### Schema ownership and lifecycle changes

- Schema evolution is now **owned by migrations**. `SqliteDatabase` keeps
  connections/transactions/dispose only.
- `SqliteDatabase(url, auto_migrate=True)` connects and brings the schema to
  the latest supported version on first open; `auto_migrate=False` defers to an
  explicit `ensure_schema()`, which delegates to
  `MigrationRunner(self, default_registry()).migrate()`.
- The Step 4.6 contract `create_schema` flag is replaced by `auto_migrate`.
- `create_relational_repositories(url, *, run_migrations=True)` eagerly runs
  the migration system before constructing the five adapters;
  `run_migrations=False` leaves that to the caller.
- `models.py` (the Step 4.6 `SCHEMA_STATEMENTS` bootstrap) is **deleted** —
  its sole importer was `database.py`; the schema now lives only in
  `migrations/versions/`.

### Architecture guards (new/changed)

- Schema DDL (`CREATE TABLE`/`CREATE INDEX`) appears only under
  `infrastructure/persistence/migrations`.
- The initial migration creates only the five Step 4.6 domain tables and two
  indexes; no later-phase vocabulary (attachments, approvals, audit, revisions,
  model_invocation, qualification) in any migration file.
- `ava.infrastructure.persistence.migrations` is imported only from within the
  persistence package; repository ports, services, and contracts never name
  the migration system.
- `ava_schema_migrations` appears only inside `infrastructure/persistence`.
- Default `AVA_PERSISTENCE` remains `memory`.

### Tests

`backend/tests/test_persistence_migrations.py` — 17 tests covering fresh-database
bootstrap (metadata record, structure), idempotence on already-current
databases, Step 4.6 legacy adoption with data preserved (directly and through
`create_relational_repositories`), unknown-legacy rejection without destructive
rewrite, failed-migration rollback (partial table absent, prior version and
history intact), deterministic version-order application despite shuffled
registration, successful retry applying only the pending migration, duplicate /
non-positive version rejection, registry iteration, database-newer-than-code
rejection with no downgrade, applied-history gap rejection, malformed metadata
rejection, file-backed durability across reopen, and the v0001 statement set.

Updated: `test_persistence_database.py` (`auto_migrate` flag + metadata table
assertions), `test_architecture.py` (new guards above; the "no later-phase
tables" guard now scans the migration module instead of the deleted
`models.py`). All Step 4.6 repository/behavior/durability tests run unchanged.

### Validation results

- Backend: **906 passed, 2 skipped** (was 884/2 after Step 4.6).
- Focused: 105 passed (`test_persistence_migrations.py`,
  `test_persistence_database.py`, `test_architecture.py`).
- `ruff check src tests` — clean.
- `mypy src` — clean, 127 files (was 121).
- `./scripts/test_all.sh` — full gate green (backend pytest/ruff/mypy,
  frontend tests + tsc lint, python client pytest/ruff/mypy); no frontend or
  client files changed.

### Files changed

- New: `backend/src/ava/infrastructure/persistence/migrations/{__init__,migration,
  registry,runner,validation}.py`,
  `backend/src/ava/infrastructure/persistence/migrations/versions/{__init__,
  v0001_initial_schema}.py`, `backend/tests/test_persistence_migrations.py`.
- Modified: `backend/src/ava/infrastructure/persistence/{database,composition,
  __init__}.py`, `backend/tests/test_persistence_database.py`,
  `backend/tests/test_architecture.py`, `docs/AVA_Phase_4_Implementation_Log.md`
  (this entry).
- Deleted: `backend/src/ava/infrastructure/persistence/models.py`.
- Dependencies: **none added** (stdlib `sqlite3` only). No new environment
  variables.

### What stays in-memory (unchanged scope)

Production composition (`app.py`) is untouched; `AVA_PERSISTENCE=memory`
remains the default and the relational adapters are not wired into services.
Run/model orchestration, OpenHands, security, API routes, frontend, and the
python client are unaffected.

### Deferred work (not started)

- Step 4.8–4.10 — activating durable persistence from configuration
  (`create_relational_repositories` → services) and database selections
  (versions 4.8+ of the migration sequence when those tables land).
- Audit steps (4.11 onward / MSSQL engine). The engine-agnostic migration
  runner and registry are designed to port to a future SQLAlchemy/MSSQL
  backend without rework.
- Later-phase tables (attachments, approvals, audit, revisions, RAG/
  telemetry) — reserved; guards forbid them from the schema.

---

## Step 4.8 — Persist Runs and Events (activation)

**Status: COMPLETE**

### Goal

Activate durable run/run-event persistence through application composition.
`AVA_PERSISTENCE=memory` (the default) keeps installing the in-memory stores;
`AVA_PERSISTENCE=relational` now routes `RunService`'s two repository ports to
the relational adapters backed by `persistence_database_url`, proving that runs,
event streams, and a run's execution selection survive a full application
restart. No schema, migration, API surface, frontend, or client change: the
existing five-table schema (migration v0001) is reused unchanged.

### Numbering note / deviation from the audit

The running plan schedules this as **4.8** (run/run-event persistence
activation). The audit document's own **4.8** labels *document versioning* — an
unrelated, later domain step. This entry follows the running plan; audit facts
are not rewritten (same deviation note as Steps 4.6/4.7).

### Composition changes

- **`create_run_persistence(settings, *, run_migrations=True)`** in
  `ava.infrastructure.composition` (the sanctioned selection seam):
  - `memory` → `RunStore()` / `RunEventStore()`, owned resource `None`;
  - `relational` → `create_relational_repositories(settings.persistence_database_url)`
    (runs the migration system at startup), extracting the run/run-event
    adapters and the owned `SqliteDatabase`;
  - any other provider → `ValueError` (fail closed; the application never
    silently falls back to an unconfigured implementation).
  - The selector lives in composition, not in `ava.infrastructure.persistence`,
    because the guard `test_persistence_layer_imports_only_repositories_and_contracts`
    forbids the persistence package from importing `ava.services` (the in-memory
    stores).
- **`RunPersistence`** frozen dataclass: `run_repository`, `run_event_repository`,
  `database: SqliteDatabase | None`, and `dispose()` (closes the owned database
  exactly once; memory mode is a no-op; calling it again is safe).
- **`create_app(..., settings: Settings | None = None)`** — optional explicit
  `Settings` (resolves to `get_settings()` when omitted). Tests inject
  relational settings directly instead of mutating per-test environment
  variables (the project's preferred pattern). `app.state.run_persistence`
  holds the composed bundle; `RunService` receives only the two repository
  ports; the lifespan shutdown disposes `run_persistence` after closing model
  providers.
- **Behavior unchanged**: `RunService` programming was already port-based; this
  step only changes what composition injects. Conversation, message, and
  document services remain wired to their in-memory stores.

### Run durability semantics (now proven end to end)

- A completed run and its exact event sequence
  (`run_started → message_started → message_content → run_completed`)
  survive `dispose()` and are re-read through a second application over the
  same database file.
- Failed and cancelled runs persist the same way (`run_started → run_failed`
  with the safe payload; `run_started → run_cancelled`).
- Multiple runs stay event-isolated across restarts.
- A run's execution selection
  (`runtime_id`/`model_provider_id`/`model_id`/`hosting_mode`) round-trips
  with full fidelity through the relational column.
- Terminal-runs are sealed, unknown-run reads/cancellation, and redundant
  terminal event appends are behaviorally identical between memory and
  relational compositions (parameterized equivalence tests).
- Relational startup failure (e.g. an unopenable database) raises at
  application construction — the server fails to start rather than degrade.

### Architecture guards (new/changed)

- Run/run-event persistence selection is created only in
  `ava.infrastructure.composition`; `app.py` consumes `create_run_persistence`
  and never imports the concrete stores or relational adapter modules.
- Concrete `Relational*` adapter modules are imported only inside the
  persistence package; outside it, only `infrastructure/composition.py` may
  import the persistence package.
- `RunPersistence` carries exactly the run + run-event ports (no
  conversation/message/document repositories); `app.py` still wires
  `ConversationStore()`, `MessageStore()`, `DocumentStore()` for those domains.
- Step 4.8 introduces **no migrations**: `migrations/versions/` still contains
  exactly `v0001_initial_schema.py`.
- Default `AVA_PERSISTENCE` remains `memory` (existing guard, unchanged).

### Tests

New `backend/tests/test_persistence_activation.py` — 24 tests: composition
selection (memory default, relational selection via injected settings,
unknown-provider `ValueError`, unopenable-database startup failure, idempotent
`dispose`), application-restart durability (completed / failed / cancelled runs,
multi-run event isolation), behavioral equivalence across memory vs relational
(completed/failed/cancelled lifecycles, terminal sealing, unknown-run
reads/cancel, redundant terminal append), and execution-selection durability.

Updated `backend/tests/test_architecture.py` — 4 new guards (selection
localization, relational-adapter confinement, run-only port selection +
in-memory conversation/message/document wiring, no-new-migrations).

### Validation results

- Backend: **934 passed, 2 skipped** (was 906/2 after Step 4.7).
- Focused: 203 passed (run service/routes/events, relational composition,
  persistence durability, migrations, database, settings, architecture).
- `ruff check src tests` — clean.
- `mypy src` — clean, 127 files (unchanged count; composition/app additions
  type-checked in place).
- `./scripts/test_all.sh` — full gate green (backend pytest/ruff/mypy,
  frontend tests + tsc lint, python client pytest/ruff/mypy); no frontend or
  client files changed.

### Files changed

- Modified: `backend/src/ava/infrastructure/composition.py` (`RunPersistence`,
  `create_run_persistence`), `backend/src/ava/api/app.py` (`settings` kwarg,
  composition-driven run persistence, lifespan dispose),
  `backend/src/ava/infrastructure/persistence/composition.py` (docstring:
  run/run-event now wired; conversation/message/document still deferred),
  `backend/src/ava/services/run_service.py` (docstrings: composition injects
  memory stores by default or durable adapters under relational),
  `backend/src/ava/configuration/settings.py` (comment: run activation landed),
  `backend/tests/test_architecture.py`,
  `docs/AVA_Phase_4_Implementation_Log.md` (this entry).
- New: `backend/tests/test_persistence_activation.py`.
- Dependencies: **none added** (stdlib `sqlite3` only). No new environment
  variables beyond the existing `AVA_PERSISTENCE` / `AVA_PERSISTENCE_DATABASE_URL`.

### What stays in-memory (unchanged scope)

Conversation, message, and document services remain on their in-memory stores;
the relational adapters for those domains exist but are not selected. Model
orchestration, OpenHands, security, API routes, frontend, and the python client
are unaffected. No streaming is introduced; `GET /runs/{id}/events` remains
snapshot retrieval.

### Deferred work (not started)

- Step 4.9 — conversation/message persistence activation; Step 4.10 — document
  persistence activation (same selection seam, reusing `create_relational_repositories`).
- Audit steps (4.11 onward / MSSQL engine); audit 4.8 (document versioning).
- Later-phase tables (attachments, approvals, audit, revisions, RAG/
  telemetry) — reserved; guards forbid them from the schema.

---

## Step 4.9 — Persist Conversations and Messages (activation)

**Status: COMPLETE**

### Goal and scope

Activate durable conversation/message persistence through the existing
composition seam. `AVA_PERSISTENCE=memory` remains the default and selects
`ConversationStore` / `MessageStore`. `AVA_PERSISTENCE=relational` selects
`RelationalConversationRepository` / `RelationalMessageRepository` alongside
the Step 4.8 run/run-event adapters. Document persistence remains explicitly
memory-backed until Step 4.10; no migration, frontend, client, or API change
is made.

### Numbering note

The running plan calls this conversation/message activation **4.9**. The
persistence audit's own 4.9 is attachments; this log follows the running plan
without changing the audit's historical numbering.

### Composition and lifecycle

- `RunPersistence` / `create_run_persistence` were narrowly renamed to
  `ApplicationPersistence` / `create_application_persistence`.
- The frozen composition bundle owns run, run-event, conversation, message,
  and document repository ports plus an optional `SqliteDatabase`.
- Relational mode uses one `create_relational_repositories(...)` bundle: its
  run, run-event, conversation, and message adapters share one database,
  migrations run before serving, and shutdown disposes that database once.
- Document always receives a fresh `DocumentStore()` in both modes. The
  relational document adapter remains unselected.
- `ConversationService` and conversation routes remain persistence-neutral;
  they receive only repository ports through `app.state.persistence`.

### Durability and compatibility coverage

`test_conversation_message_activation.py` covers application recreation for
created/renamed conversations and ordered user/assistant messages; exact IDs,
timestamps, title, role, status, content, conversation membership, and append
order survive. It also covers multiple-conversation isolation, memory versus
relational parity for unknown conversations and duplicate conflicts, and a
cross-domain restart over one database for Run, RunEvent, Conversation, and
Message. Existing migration `v0001_initial_schema.py` supplies the tables and
ordering index; no schema change is needed.

### Architecture guards

- Persistence selection is confined to `ava.infrastructure.composition`.
- Relational adapters remain confined to the persistence package.
- `ApplicationPersistence` contains exactly the five application ports and
  optional database resource; relational composition selects only the four
  activated adapters and keeps Document memory-backed.
- Conversation routes depend on `ConversationService`, not stores, ports, or
  relational types.
- Migration guard continues to require only `v0001_initial_schema.py`.

### Deferred work

Step 4.10 activates only document persistence. Attachments, streaming,
frontend conversation state, and all other persistence domains remain out of
scope.

---

## Step 4.10 — Persist Documents (activation)

**Status: COMPLETE**

### Composition

`ApplicationPersistence` now activates all five existing Phase 4 repository
ports. Memory mode continues to construct `DocumentStore()`. Relational mode
uses `bundle.document_repository` from the existing
`create_relational_repositories(...)` result, so Run, RunEvent, Conversation,
Message, and Document adapters share one `SqliteDatabase`; the application
still disposes that resource once through `ApplicationPersistence.dispose()`.
No application, service, route, contract, migration, or schema redesign was
needed.

### Semantics and durability

The `DocumentService` remains the only normal write path and remains
repository/persistence neutral. It continues to mint IDs, control timestamps,
and enforce the existing reject-first HTML content policy before invoking the
selected repository. Relational restart coverage proves exact serialized HTML
and `html` content format, title/content updates, identity, stable listing
order, and aware-UTC `created_at`/`updated_at` round-trip. Unknown-document
behavior remains `None` at the service boundary; existing route normalization
remains unchanged.

One full composition restart test now stores and retrieves a Run, RunEvent,
Conversation, Message, and Document from the same relational database.

### Guards and validation

- Updated the application-persistence architecture guard to require all five
  selected ports and require relational Document selection from the shared
  bundle.
- Existing guards continue to prove that DocumentService uses only the port,
  relational adapters stay in persistence infrastructure, document sources
  remain frontend/Tiptap neutral, and no additional migrations exist.
- Added `test_document_persistence_activation.py` for memory/relational
  selection, shared database ownership, document restart/update/timestamp
  round-trips, safety enforcement, ordering/unknown semantics, and five-domain
  restart durability.
- Focused validation: 146 passed across document, relational-document,
  migration, and architecture tests; Ruff and mypy are clean.

The local FastAPI `TestClient` still deadlocks on context entry even for an
empty application, so route-level restart tests remain valid but cannot be
executed here. No dependency or application-lifecycle change was made to work
around that host-level limitation. Frontend persistence, document revisions,
attachments, and Step 4.11+ remain deferred.

---

## Step 4.11 — Frontend Conversation Integration

**Status: IN CLOSURE**

Shared frontend contracts and `@ava/api-client` now own conversation/message
transport. `ConversationProvider` hydrates durable conversations/messages,
creates and renames conversations from backend-authoritative responses, and
reloads selected threads. User messages persist before runs; successful final
assistant messages persist and replace their local placeholders with backend
identities. Retry and regenerate reuse the existing source user message.

Failure/cancellation do not persist successful assistant output; an assistant
persistence failure is recorded without changing a completed run to failed.
Web and Desktop inherit this behavior through shared Workspace/Agent UI code.

Validation so far: frontend tests and lint pass; Web and Desktop Vite builds
pass. `frontend/packages/workspace/src/step411.architecture.test.ts` adds two
local architecture guards, both passing. The Workspace suite reports 14 tests
passed with 4 integration tests skipped. The guards prohibit direct
conversation/message HTTP construction, backend persistence implementation
references/configuration, and `EventSource`/`WebSocket` usage in frontend
production source; they also ensure Web and Desktop retain their shared
`@ava/workspace` composition. The final aggregate harness remains outstanding.
No document frontend persistence, revisions, attachments, streaming,
reconnect, auth, RAG, voice, or model/runtime work was added.

---

## Step 4.12 — Frontend Document Integration

**Status: COMPLETE**

### Transport

`@ava/contracts` owns the document request/response vocabulary and
`@ava/api-client` owns document HTTP transport:

- `DocumentContentFormat` (html)
- `DocumentResponse`, `DocumentListResponse`
- `CreateDocumentRequest`, `UpdateDocumentRequest`
- typed `listDocuments()`, `getDocument()`, `createDocument()`, `updateDocument()`

`createDocument`/`updateDocument` requests carry only `title`, `content`, and
`content_format`; `document_id`, `created_at`, and `updated_at` stay
backend-owned. There is explicitly **no `deleteDocument()`** because the
backend exposes no delete route.

### Mapping and hydration

`DocumentResponse → mapDocumentResponse() → frontend document model`:

- `document_id → id`
- `title → title`
- `content`/`content_format → DocumentContent { format, value }`
- `created_at`/`updated_at →` frontend timestamps
- hydrated documents are `isDirty: false`

On `DocumentProvider` mount, `GET /documents` runs and the backend list becomes
authoritative. A non-empty response selects the first document. An empty
response leaves an empty collection with no active document, no
`INITIAL_DOCUMENT`, and no automatic `POST`. A failed hydration records a
truthful error and never invents a fake document.

### Durable creation

New Document issues one `POST /documents`; the backend-generated ID and
timestamps are authoritative, the response is mapped and inserted once, and the
new document becomes active and clean. `crypto.randomUUID()` was removed from
the durable creation path (a focused test asserts it is not called). A failed
create inserts nothing and leaves selection unchanged.

### Durable save

A dirty document's `saveDocument()` sends one `PATCH /documents/{id}` with a
single `title`/`content`/`content_format` snapshot; the backend response is
authoritative and the document becomes clean only after success. A failed save
preserves local edits, keeps the document dirty, and leaves selection
unchanged. Concurrent-edit safety: snapshot A sent, edit B made, then A's
response returning cannot overwrite B — the document stays dirty.

### Selection semantics

`GET /documents` already returns complete canonical content, so selection is a
local state switch over authoritative hydrated snapshots — **no
`GET /documents/{id}`**. Dirty edits survive switching away and back.

### Operation-state hardening

Truthful `loading` (hydration), `isCreating`, `isSaving`, and `error` states
are modeled in the reducer and enforced in the provider. Duplicate creates are
dropped via `creatingRef`, duplicate saves via `savingRef` (no request queue).
A later successful equivalent operation clears a stale error, including across
operation types (e.g. a stale save error is cleared by a successful create).
New Document is disabled while creation is pending; Save is disabled while
saving. Reducer-level tests lock every transition and isolation property.

### Workspace integration

Workspace-level tests prove startup hydration, empty durable state, one-POST
creation, one-PATCH save with the backend ID and serialized HTML, failed-save
preservation with the workspace still mounted, close without any document
request, and selection without a per-document GET. `AppWorkspace` passes a
single shared `ApiClient` into `ConversationProvider` and `DocumentProvider`.

### Architecture guards

`frontend/packages/workspace/src/step411.architecture.test.ts` protects the
Step 4.12 boundaries alongside Step 4.11: no direct
`conversations`/`messages`/`documents` endpoint `fetch` outside `@ava/api-client`;
no backend persistence tokens (`sqlite3`, `SQLite`, `SqliteDatabase`,
`Relational*Repository`, `AVA_PERSISTENCE`, `ava.infrastructure.persistence`);
no `EventSource`/`WebSocket`; no `deleteDocument` reference; no `@tiptap/`
imports outside `@ava/document-core` (Tiptap stays internal); and Web/Desktop
retain the shared `@ava/workspace` composition.

### Validation (final closure run)

- `@ava/document-core`: 40 tests / 7 files PASS
- `@ava/workspace`: 21 passed / 4 integration skipped
- architecture guards: 2/2 PASS
- full frontend suite: contracts 13, api-client 27, agent-ui 132, document-core
  40, workspace 21 (+4 skipped), ui-core 20 — PASS
- full frontend lint/typecheck (`tsc --noEmit` across all packages incl. Web,
  Desktop, mobile): PASS
- Web production build: PASS
- Desktop production build: PASS

### Explicitly deferred

Step 4.12 implemented none of: document revisions/history (→ Step 4.13),
attachment metadata (→ Step 4.14), restart/recovery integration (→ Step 4.15),
Phase 4 hardening (→ Step 4.16), delete, autosave, collaboration, streaming,
reconnect/event replay, auth, RAG, voice, model routing, or agent-runtime
changes. No database schema or migration changes were introduced.

The aggregate `./scripts/test_all.sh` was run: backend pytest (963 passed, 2
skipped), backend Ruff and mypy, frontend tests and lint, and the Python client
checks all pass. One stale Step 4.9 activation test
(`test_document_repository_stays_memory_backed_in_relational_mode`) asserted
document persistence was not yet activated; Step 4.10 deliberately activated
it, and Step 4.10's own coverage owns mode selection, so that stale guard was
removed. The host's known FastAPI `TestClient` context-entry deadlock did not
recur during this closure run.

## Step 4.13 — Document Revision Foundation

**Status: COMPLETE**

### Goal

Append-only, immutable document revision history end-to-end: a backend
write-path that records every current-state change as a numbered snapshot, a
read API, and a frontend document-core seam that can enumerate history
without coupling the UI to revision vocabulary. No restore/revert, no history
UI, no compare/diff, no mutation of history.

### Model decisions

A revision is an **immutable full snapshot**, not a delta and not a
reference: `revision_id` (globally unique, backend-owned UUID), owning
`document_id`, a backend-assigned monotonic `revision_number` per document,
and the exact `title`/`content`/`content_format`/`created_at` values that were
applied to the current state. `contract_version` is a transport-level number
carried separately on responses and is **independent** of
`revision_number` — the frontend mapper deliberately ignores it. Revisions
are referenced by `revision_id` (stable) and ordered by `revision_number`
(ascending); ordering is never derived from timestamps.

### Ownership split

- The **service** (`DocumentService`) owns what a repository must not:
  `revision_id` generation, aware-UTC snapshot timestamps, and the call into a
  `DocumentWriteCoordinator` port.
- The **revision repository port** owns `revision_number` assignment and
  durability; its API is exactly `append`, `list_for_document`, `get`,
  `get_latest` — no `update`/`replace`/`rename`/`delete`.
- The **write coordinator port** owns the current-vs-history atomic step.
- The **current-document repository port** stays revision-free: `create`,
  `get`, `list`, `update_title`, `update_content` and a `DocumentRecord` with
  no revision vocabulary.

Two new architecture guards lock these boundaries (contained in the existing
`test_architecture.py`, same style, no second guard framework):
`test_document_revision_repository_port_is_append_only` asserts the port's
public method set is exactly `{append, get, get_latest, list_for_document}`,
and `test_document_repository_port_stays_revision_free` asserts the
current-document port exposes exactly `{create, get, list, update_title,
update_content}` and its record carries no `revision`-named fields.

### Generation rules

- `POST /documents` writes the current state **and revision 1 atomically**;
  an existing document before this step never has revisions
  (migration v0002 does **no backfill**); its first successful post-migration
  update appends revision 1.
- Every successful `PATCH /documents/{id}` appends **exactly one** next
  revision — a title-only, content-only, combined title+content, or no-op
  request each produce exactly one snapshot.
- A failed write (any rollback) leaves both the current state and the history
  untouched — no partial revision.

### Persistence

- **In-memory** (`InMemoryDocumentRevisionStore` + coordinator): appends the
  next revision and the current-state update as one atomic step; a duplicate
  `revision_id` raises.
- **Relational** (`RelationalDocumentRevisionRepository` + coordinator over
  `SqliteDatabase`): table `document_revisions` with a stable surrogate `id`,
  `revision_id TEXT NOT NULL UNIQUE`, `UNIQUE(document_id,
  revision_number)`, and `created_at` as the authoritative aware-UTC
  timestamp. `revision_number` is assigned inside the write transaction as
  `MAX(revision_number) + 1`, never caller-supplied; the unique constraints
  back numbering under concurrency. Migration `v0002` adds exactly this table
  on top of an unchanged v0001; no downgrade migration exists.
- `list_for_document` returns revisions in `revision_number` ascending order
  and yields `[]` for an unknown history; `get` resolves only through the
  owning document (a revision never resolves globally by id).

### Backend API surface

- `GET /documents/{document_id}/revisions` → 200 list (snake_case wire
  fields, `revision_number` ascending); unknown document → 404
  `document_not_found`; known document with no history → `[]`.
- `GET /documents/{document_id}/revisions/{revision_id}` → exact
  document-scoped snapshot; 404 for an unknown document, an unknown revision,
  or a revision belonging to a different document.
- No restore/revert/create-revision/delete/pagination/filter endpoints.
  `DocumentService(document_repository, document_revision_repository,
  document_write_coordinator)` programs against ports only; composition in
  `create_app` injects the implementations.

### Frontend surface

`@ava/contracts` owns the response vocabulary (`DocumentRevisionResponse`,
`DocumentRevisionListResponse`); `@ava/api-client` owns the HTTP reads
(`listDocumentRevisions(client, documentId)`,
`getDocumentRevision(client, documentId, revisionId)` — no body, both ids
`encodeURIComponent`-escaped, errors propagate as `ApiError`). Step 4.11's
architecture guard regex already covers `/documents/.../revisions` in
`fetch`-owned paths, so no guard change was needed on the transport side.

### Document-core seam

`@ava/document-core` introduces `AvaDocumentRevision` (the revision-domain
type: `revisionId`, `documentId`, `revisionNumber`, `title`,
`content: DocumentContent`, `createdAt`) and `DocumentProvider.loadRevisions(
documentId): Promise<AvaDocumentRevision[]>` — async, shared-client, no
dispatch, errors reject (no `[]` fallback), no provider-global error
pollution, and **lazy**: nothing is fetched on mount/select/create/save.
`DocumentProvider` is also async-lazy from the start (its prepare step
started listening instead of fetching) so it does not block hydration. The
mapper reproduces the server's HTML byte-for-byte and preserves the server's
revision ordering. There is **no reducer revision state**: history lives only
transiently inside `loadRevisions` calls. This is protected behaviorally by
the provider tests (state-isolation via `state` reference equality) and by
`DocumentState` being exhaustively constructed in tests, rather than by a
brittle exact-keys type assertion.

The repository runs through the shared `@ava/api-client` seam; no
`fetch(`/`EventSource`/`WebSocket` appears in document-core production code.

### Explicitly not implemented

Step 4.13 implemented none of: restore/revert, history UI, compare/diff,
revision caps/culling, server-side pagination/filtering, global revision
listing, attachments (→ Step 4.14), restart/recovery integration (→ Step
4.15), or Phase 4 hardening (→ Step 4.16).

### Architecture guards

- Backend (`test_architecture.py`): the two new Step 4.13 boundary guards
  plus the existing 79 guards: `DocumentService` imports no
  `ava.services.document_store`/`ava.infrastructure`; the in-memory store and
  relational adapter conform to the revision port; database imports stay
  confined to `infrastructure/persistence`; composition wires
  `document_revision_repository` and `document_write_coordinator` into
  `DocumentService`; migration versions are exactly v0001 + v0002; relational
  adapters are constructed only inside the persistence package.
- Frontend: workspace `step411.architecture.test.ts` unchanged — its
  `documents` endpoint regex already covers `/documents/.../revisions` paths,
  and no new reducer/state vocabulary was introduced.

### Validation (final closure run)

- Backend `test_architecture.py`: 79 PASS
- Focused Step 4.13 suites (revision repository, revision store, write
  coordinator, migrations, relational revision/write-coordinator/service,
  document service, document routes, persistence activation, contracts, GUI
  helpers, integration): PASS
- Full backend suite: pytest PASS, `ruff check src tests` PASS, `mypy src`
  PASS
- Frontend: `@ava/document-core` (48 tests), `@ava/contracts`,
  `@ava/api-client`, `@ava/workspace`, `@ava/agent-ui`, `@ava/ui-core` PASS;
  full `tsc --noEmit` PASS; `pnpm -r lint` PASS
- Web production build: PASS
- Desktop production build: PASS
- Aggregate `./scripts/test_all.sh`: PASS (backend pytest, Ruff, mypy, frontend
  tests + lint, Python client checks)

### Files changed (reference)

- Backend: `ava/contracts/documents.py`, `ava/repositories/document_revision_repository.py`,
  `ava/repositories/document_write_coordinator.py`, `ava/services/document_write_coordinator.py`,
  `ava/services/document_service.py`, `ava/api/routes/documents.py`,
  `ava/api/app.py`, `ava/infrastructure/persistence/` (repositories, `database.py`,
  `migrations/versions/v0002_document_revisions.py`, `composition.py`),
  `tests/test_architecture.py` (+2 boundary guards), plus Step 4.13 test files.
- Frontend: `@ava/contracts` `documents.ts`, `@ava/api-client` `documents.ts`,
  `@ava/document-core` (`model/documentRevision.ts`, `model/index.ts`,
  `index.ts`, `state/documentMapper.ts`, `state/DocumentProvider.tsx`,
  `state/documentMapper.test.ts`, `state/DocumentProvider.test.tsx`).

## Step 4.14 — Attachment Metadata Foundation

**Status: COMPLETE**

### Goal

Stand up the attachment platform capability end-to-end — from frontend wire
contract and api-client transport through the backend API, lifecycle
service, metadata repositories, and physical content store — as a stable but
**not yet integrated** capability. No attachment UI, no chat/document workflow
wiring. The foundation ends at transport readiness; consumption lands in later
steps. Delivered as slices 4.14.A–4.14.G with this entry closing 4.14.H
(validation, boundary review, restart smoke, log/documentation).

### Architectural summary

The design follows the Step 4.14 attachment audit (`AVA_Phase_4_Attachment_Architecture_Audit.md`).
Two independent ports, mirroring the established port/adapter pattern:

```
Frontend contracts/api-client
        ↓
Backend attachment API        → transport only
        ↓
AttachmentService             → lifecycle/orchestration only
        ↓
AttachmentRepository          → metadata only   (memory | relational)
AttachmentContentStore        → physical bytes  (memory | local)
```

- **Attachment metadata abstraction** (`AttachmentRecord`): frozen, provider-neutral
  record with `attachment_id` (backend-owned UUID), `file_name` (display-only),
  `media_type`, `size_bytes`, opaque logical `storage_key`, nullable
  `owner_type`/`owner_id` pair, lifecycle `status`, aware-UTC `created_at`.
  No filesystem path, SQLite row id, bucket, container, or provider SDK type
  anywhere in the record or wire contracts.
- **Content-store abstraction** (`AttachmentContentStore` port): storage-neutral,
  stream-oriented from day one — `put(key, BinaryIO) -> StoredContentInfo` (the
  authoritative `size_bytes`), `open(key) -> BinaryIO`, `exists(key) -> bool`,
  and nothing else (`delete` deliberately absent). Never a whole-file `bytes`
  API, never Base64, never text conversion.
- **Memory + relational metadata**: `InMemoryAttachmentRepository` and
  `RelationalAttachmentRepository` conform to the same port over the shared
  `SqliteDatabase`; migration **v0003** adds the `attachments` table (unique
  `attachment_id`/`storage_key`, `CHECK size_bytes >= 0`, owner-type
  vocabulary CHECK, no-orphan-id CHECK, owner index) on top of v0001/v0002.
  No attachment backfill, no v0004.
- **Memory + local content**: `InMemoryAttachmentContentStore` and
  `LocalAttachmentContentStore`. The local adapter keeps an explicit configured
  root (never implicit CWD), enforces resolved-path containment (absolute keys,
  `..`, symlink escapes, prefix confusion rejected), and writes via a temp file
  on the destination filesystem + `os.replace` atomic finalize with best-effort
  cleanup, so duplicate/failed writes never clobber. Metadata mode and content
  mode are independently selectable: all four `memory|relational` ×
  `memory|local` combinations are valid.
- **Service lifecycle** (`AttachmentService`): owns `attachment_id` minting,
  authoritative timestamps, the per-attachment `storage_key`
  (`attachments/{attachment_id}/content` — never derived from the filename),
  and the order pending → put → verify-exists → available. `available` is only
  ever emitted after the content store confirmed the bytes and reports the
  authoritative stored size. Handled failures mark the record `failed`;
  `pending`/`failed` never expose content. Two-resource work (metadata DB +
  content store) cannot share a transaction; the final-transition-failure path
  is spelled out and reported truthfully, and orphan reconciliation is deferred
  to Step 4.16.
- **Backend API** (`/attachments`, Step 4.14.F): `POST` (multipart, 201),
  `GET /{id}` (200/404), `GET` owner-scoped list (both owner params required,
  422 otherwise), `GET /{id}/content` (streamed bytes, 200; 404 unknown; 409
  pending/failed; 500 storage inconsistency). `storage_key` is never on the
  wire; `Content-Disposition` is download-only, single-line, quote/backslash/
  control-byte neutralized, RFC 5987 `filename*` for unicode. `python-multipart`
  declared in `backend/pyproject.toml`.
- **Frontend transport** (Step 4.14.G): `@ava/contracts` `attachments.ts`
  mirrors the backend wire shape exactly (`AttachmentResponse` without
  `storage_key`, owner-scoped `AttachmentListResponse`, exact owner/status
  vocabularies); `@ava/api-client` gains `createAttachment` (FormData,
  runtime-boundary boundary, owner-pair validation, explicit `fileName` +
  `File.name` fallback, pre-network `AttachmentInputError`), `getAttachment`,
  owner-scoped `listAttachments` (URLSearchParams-safe query encoding), and
  `getAttachmentContent` returning a `Blob` (explicit binary mode,
  `requestBlob`); 404/409/500 map to `ApiError`. No delete/rename/global-list/
  download-to-disk helpers; JSON request behavior unchanged.
- **Security boundaries**: storage-key confidentiality (`storage_key` lives only
  inside `AttachmentRecord` and service/repository/store behavior, never on any
  public contract); filenames remain display-only; local-store containment and
  atomic-write guarantees pinned by tests; attachment transport vocabulary
  (FastAPI `UploadFile`/`File(`/`Form(`) confined to `ava/api`; direct
  `/attachments` `fetch` forbidden outside `@ava/api-client`.

### Confirmations (4.14.H closure review)

Provider neutrality, storage-key confidentiality, backend-owned identity
(`attachment_id`/`storage_key`/`created_at` never client-submitted; `size_bytes`
from the content store), the pending/available/failed lifecycle, availability
invariant (`available` ⇒ bytes verified), truthful two-resource failure
reporting, delete absence (no delete on either port, no delete routes/helpers),
the document/conversation/message owner model (`owner_type` is None ⇔
`owner_id` is None; no run/workspace/agent/rag owner), no attachment fields
embedded in `DocumentRecord`/`MessageRecord`/`ConversationRecord`/`RunRequest`,
`Document.content` still canonical HTML with immutable `DocumentRevision`
history, and the v1/v2/v3 migration + settings closure
(`AVA_ATTACHMENT_STORAGE=memory|local`, default memory, local requires root,
unknown modes fail clearly) were all verified by inspection and pinned tests.

### New closure coverage (4.14.H)

- Local-store restart durability: a brand-new `LocalAttachmentContentStore` over
  the same root returns byte-exact original content (binary + zero-byte).
- Attachment-specific restart/recovery smoke: the real relational-metadata +
  local-content chain (route → service → repository → content store) uploads,
  reads, lists, and streams back exact bytes, then survives a full app +
  persistence dispose and recreation over the same SQLite database and content
  root — metadata restored (`available`, size exact, owner exact) and content
  streamed byte-exact.
- Backend API end-to-end smoke and zero-byte end-to-end (`available`, `size=0`,
  empty content GET, survives restart) against the relational + local chain.
- Hostile-filename confinement under local storage: path/quote-laden display
  names never become storage keys, physical placement stays under the
  configured root, download headers remain safe.

### Explicitly deferred work (not defects)

Step 4.14 intentionally implements none of: attachment delete workflow,
orphan-content reconciliation/sweeper (→ Step 4.16), upload size limits,
checksum/integrity hashing, malware scanning, MIME verification/sniffing,
Range/resumable transfer, cloud content-store adapters (S3/Azure/Unity Catalog
Volume), auth/authorization, RAG ingestion, OCR, attachment UI, chat composer
integration, and the document attachment browser. The audit documents each as a
later capability, not a missing feature.

### Architecture guards

Backend (`test_architecture.py`) pins: `AttachmentContentStore` has exactly
`{put, open, exists}`; `AttachmentRepository` is metadata-only with exactly
`{create, get, list_for_owner, update_state}`; the local content adapter lives
in `ava.infrastructure`; `AttachmentService` programs against contracts + ports
only (no `ava.infrastructure`, no concrete stores); FastAPI upload vocabulary
stays in `ava/api` and `python-multipart` stays declared; the migrations package
ships exactly v0001/v0002/v0003; relational adapters are constructed only inside
the persistence package; composition wires `attachment_repository` into the
bundle. Frontend: the workspace `step411.architecture.test.ts` forbidden-fetch
regex now covers `/attachments` across `agent-ui`, `workspace`, `web`, and
`desktop`; `@ava/contracts` tests pin the exact `AttachmentResponse`/list field
sets and the absence of `storage_key`/path/provider fields.

### Validation (final 4.14.H closure run)

- Full backend suite: pytest **1302 passed, 2 skipped, 4 warnings** (was
  1258 after Step 4.13; 1298 after 4.14.F; +4 new closure tests in 4.14.H);
  `ruff check src tests` PASS; `mypy src` PASS (143 source files).
- Frontend packages: `@ava/contracts` 23, `@ava/api-client` 64, `@ava/ui-core`
  20, `@ava/agent-ui` 132, `@ava/document-core` 48, `@ava/workspace`
  21 passed | 4 skipped — all PASS.
- Repo-wide `pnpm -r --if-present lint` (`tsc --noEmit`): all packages + web/
  desktop/mobile apps PASS. Web production build PASS; Desktop production
  build PASS.
- Aggregate `./scripts/test_all.sh`: PASS (backend pytest, Ruff, mypy, frontend
  tests + lint, Python client 10 tests + Ruff + mypy).
- Live application smoke (relational metadata + local content, temporary
  locations, port 8199): backend started, upload 201 `available`
  (`size_bytes` = 18 exact), GET metadata identical, owner-scoped list correct,
  GET content streamed byte-exact (non-UTF8 binary preserved), physical file
  confined to the content root. The pre-existing `--reload` dev server on port
  8000 was untouched.

### Files changed (4.14.H, closure slice)

- Backend: `tests/test_attachment_content_store_local.py` (+1 local restart
  durability test), new `tests/test_attachment_restart_recovery.py` (relational+
  local API end-to-end restart smoke, zero-byte restart, hostile-filename local
  confinement). No production code changed in the closure slice.
- Docs: this entry.

## Step 4.15 — Restart / Recovery Integration Test

**Status: COMPLETE**

### Goal

Prove the entire Phase 4 durable-state story recovers correctly when the
application is disposed, discarded, and reconstructed over the same real
durable stores — file-backed SQLite (relational metadata) plus a
local-filesystem content root — end to end through the live HTTP API. This is
an integration/verification step: no new migrations (schema stays at v0003),
no recovery service, and no production-code changes. The existing per-domain
restart tests (runs, conversations/messages, documents, attachments) were
reviewed first; the gap they left — one full-application scenario covering all
six state domains at once across *two* restart boundaries with a durable write
in between — is what this step adds.

### Scenario and coverage

Two tests in `backend/tests/test_restart_recovery_integration.py`, both under
`AVA_PERSISTENCE=relational` + `AVA_ATTACHMENT_STORAGE=local` with a temporary
SQLite file (never `:memory:`) and a temporary content root, driving the real
FastAPI application (`create_app`) through `TestClient` — real relational
repositories, the real `LocalAttachmentContentStore`, the real mock-agent path
for the run. No mocks of the durable adapters anywhere.

- `test_seeded_durable_state_survives_a_clean_restart` (A→B): a manifest of
  every seeded entity (identities, timestamps, event payloads, revision
  history, attachment bytes) is captured *before* restart, then verified
  bit-exact after a full dispose/recreate:
  - conversation (non-default title), a user message, a **completed run with
    its four ordered events** (`run_started → message_started → message_content
    → run_completed`, status `completed`), an **assistant message linked to the
    run** via `source_run_id` (cross-domain reference), a document with **two
    immutable revisions**, and **two stored attachments** (document-owned
    binary + conversation-owned small) whose bytes stream back exactly.
  - list counts stay 1/2 per domain — no duplicates, nothing synthesized on
    startup; revision history unchanged; attachment metadata/status/size
    unmutated; physical bytes still at the id-derived key under the same root.
  - every startup asserts the migration runner applied exactly `[1, 2, 3]`
    with nothing pending (schema version 3, normal bootstrap, no bypass).
- `test_recovered_application_continues_writing_across_a_second_restart`
  (A→B→C): after recovery into B (with no startup synthesis asserted first),
  the recovered application performs new durable writes — one document update
  (appends exactly revision 3; revisions 1 and 2 stay bit-identical) and one
  new message — then a **second** restart into C preserves the original state
  *and* the post-recovery writes (3 revisions, 3 messages, still exactly one
  conversation/document, run + events unchanged, schema still v3).

The recovery reads run through the API (`GET` routes), which doubles as the
frontend hydration contract (list conversations/documents after restart). Every
assertion message is domain-prefixed for diagnosable failures.

### Validation

- Backend suite: pytest **1304 passed, 2 skipped, 4 warnings** (was 1302
  after 4.14.H; +2 new integration tests); `ruff check src tests` PASS;
  `mypy src` PASS (143 source files).
- Frontend regression (unchanged, must stay green — no frontend changes in this
  step): `@ava/contracts` 23, `@ava/api-client` 64, `@ava/ui-core` 20,
  `@ava/agent-ui` 132, `@ava/document-core` 48, `@ava/workspace` 21 passed |
  4 skipped — all PASS.
- Repo-wide `pnpm -r --if-present lint` (`tsc --noEmit`): PASS. Web and Desktop
  production builds PASS.
- Aggregate `./scripts/test_all.sh`: PASS (backend pytest, Ruff, mypy; frontend
  tests + lint; Python client 10 tests + Ruff + mypy).
- Live process-boundary restart smoke (port 8199, temporary SQLite + content
  root, mock agent): a real uvicorn process seeded a conversation + message +
  document over the HTTP API, was **terminated** (SIGTERM) and discarded, and a
  **brand-new uvicorn process** over the same database file and content root
  recovered the seeded state byte-exact with counts stable — proving
  process-level (not just in-process) durability. The developer on port 8000
  was not running during this step; port 8000 was left untouched.

### Known limits (as designed)

This step does not exercise (and does not claim): power-loss/crash recovery,
disk-corruption repair (migrations fail closed), multi-process concurrent
access/failover, cross-machine or distributed deployment, backup/restore,
rollback of applied migrations, live-inference execution-selection durability
(the completed run carries `execution_selection: null`, pinned as recorded),
attachment content on cloud content stores, orphan reconciliation (Step 4.16),
or a dedicated recovery coordinator service (deliberately absent by design).

### Files changed

- Backend: new `tests/test_restart_recovery_integration.py` (2 integration
  tests + shared manifest/seed/assert helpers; no production code changed).
- Docs: this entry.

## Step 4.16 — Hardening and Documentation (final Phase 4 closure)

**Status: COMPLETE**

### Goal

Close out Phase 4: re-audit the Phase 4 architecture and boundary invariants
against the delivered code, document the final Phase 4 state (including the
attachment orphan policy and known non-goals), and fix the stale comments and
config docs the review surfaced. This is a hardening/verification step by
design: no new product features, no new UI, no new persistence domains, and no
new migration (schema stays at v0003). Only review-driven corrections were
made; an audit finding pointed at genuinely wrong or stale Phase 4 commentary,
never at missing behavior, and any such fix is listed below.

### Invariant and boundary review results

- **Repository-port surfaces stay closed.** Reviewed every public phase
  repository port; none exposes delete/truncate/global attachment
  listing/revision mutation/generic update/restore primitives. Ports:
  `RunRepository{create,get,list,update_status,set_execution_selection}`,
  `RunEventRepository{append,get_events,get_latest}`,
  `ConversationRepository{create,get,list,update_title}`,
  `MessageRepository{append,get,list_for_conversation}`,
  `DocumentRepository{create,get,list,update_title,update_content}`,
  `DocumentRevisionRepository{append,list_for_document,get,get_latest}`,
  `AttachmentRepository{create,get,list_for_owner,update_state}`,
  `AttachmentContentStore{put,open,exists}` (no delete). Attachment content
  lifecycle is service-owned only.
- **SQLite error boundary is uniform.** Every relational adapter catches
  `sqlite3.Error` at its own boundary and routes through the shared
  `translate_database_error` — `ValueError` for integrity violations,
  `PersistenceError` otherwise. The `sqlite3` library is confined to
  `ava.infrastructure`; the backend architecture guard pins the forbidden
  lists (`aiosqlite`, `sqlite3`) and that repositories/ports use only
  AVA-owned types and contracts.
- **Transactions are isolated.** The relational `DocumentWriteCoordinator`
  advances current document state + appends exactly one revision inside one
  `BEGIN IMMEDIATE` transaction via the connection-accepting seams; the
  migration runner applies each migration in its own transaction and fails
  closed on unknown newer versions.
- **Migration closure.** `default_registry` is exactly v0001/v0002/v0003. On a
  fresh database the runner applies `[1, 2, 3]`; an existing v1/v2 database is
  upgraded to v3; a current v3 database starts with nothing pending; a
  legacy Step 4.6 five-table schema is adopted. Proven again during 4.16
  validation (every restart test asserts `applied == [1,2,3]`, `pending == []`).
- **Config fails closed.** `AVA_PERSISTENCE` (memory|relational),
  `AVA_PERSISTENCE_DATABASE_URL`, `AVA_ATTACHMENT_STORAGE` (memory|local), and
  `AVA_ATTACHMENT_STORAGE_ROOT` are strictly validated in `Settings` and at the
  composition seams. Unknown values raise `ValueError` — never a silent
  downgrade to memory; `local` storage without a root fails construction.
  Memory mode never constructs a `SqliteDatabase` (`persistence.database is
  None`, pinned by activation tests); relational mode shares one
  `SqliteDatabase` across all six metadata domains plus the write coordinator.
- **Frontend boundaries hold.** `step411.architecture.test.ts` keeps
  transport/persistence/editor/scope tokens and raw API fetch calls out of the
  UI shells; the backend `test_architecture.py` keeps provider/DB/editor
  internals out of core, contracts, and ports. Attachment contracts never
  expose `storage_key` (frontend contracts test pins it); the api-client wraps
  all four attachment routes with encoded ids/query params; the composer's
  attachment affordance is explicitly inert ("Attachments are not available
  yet") because chat-composer attachments are deferred (ie. no UI in Phase 4).
- **Attachment HTTP-hardening behavior is pinned by tests:**
  `test_attachment_restart_recovery.py` asserts `content-disposition` contains
  no CR/LF; `test_attachments.py` pins `storage_key` absence from responses,
  owner-pair validation (`422`), missing-filename `422`, CR/LF stripping +
  `filename*` fallback, `409` for pending/failed content, stream cleanup, and
  generic storage-failure `500` messages that leak no storage internals.
- **Local content store confinement is pinned.** `test_attachment_content_store_local.py`
  rejects absolute keys, empty keys, `..` traversal, symlink escapes, and
  keys resolving onto the root; both adapters reject duplicate storage keys.

### Attachment orphan policy

Documented here authoritatively. Attachment state is a two-resource
transaction: metadata rows in the repository (pending → available | failed)
and physical bytes in the content store, advanced by `AttachmentService` in
the crash-ordered sequence recorded in the attachment audit (§25): mint →
insert `pending` metadata → stream bytes to the content store (atomic
temp-file replace, store-authoritative size) → verify → advance to
`available`. Because the two resources cannot be mutated atomically, exactly
two anomalies can exist:

- **Orphaned content** — bytes exist in the content store but the process died
  between content commit and the metadata advance to `available`: a record
  stays `pending` (or `failed`) while its committed bytes remain under the
  id-derived `storage_key`. Content is unreachable forever after the failed
  record (`get` metadata still works; content returns `409`).
- **Dangling metadata** — an `available` record whose bytes were lost (e.g. the
  storage root was manually deleted). Content returns a storage failure.

Both are accepted for Phase 4 and documented as **future work** (no delete or
sweep exists on any port): a scan/reconciliation pass that detects orphaned
content, recovery of stale `pending` records (they are indistinguishable from
legitimately in-flight uploads without a heartbeat, hence they are simply
leavable), cleanup of terminal `failed` records, and an eventual content
delete/reap workflow. `available` remains, by design, the only content-bearing
state, so an orphan can never be served. No automated reconciliation exists in
Phase 4.

### Upload-size and MIME policy (documented)

No global upload-size limit exists: attachments stream from the multipart
request directly to the content store in 64 KiB bounded chunks and are never
fully buffered in memory, and `GET /content` streams out the same way. No MIME
sniffing or allowlist exists: the stored `media_type` is echoed verbatim for
`available` attachments and `Content-Disposition` is pinned to `attachment`
(download, never inline-execute), so the size/MIME capabilities are the ones
designed in the attachment audit (§11/§12) — documented, un-enforced limits.
Malware scanning and content-type validation remain deferred non-goals.

### Final Phase 4 architecture (canonical summary)

Services (`ava.services.*`) program against ports (`ava.repositories.*`):
persistence composition respects `AVA_PERSISTENCE` — `memory` (default)
composes the in-memory stores for every domain plus the in-memory write
coordinator; `relational` composes the durable SQLite adapters for run,
run-event, conversation, message, document, document revision, and attachment
over one shared `SqliteDatabase` (schema v0003). Physical attachment content
respects `AVA_ATTACHMENT_STORAGE` independently — `memory` (default) composes
`InMemoryAttachmentContentStore`; `local` composes
`LocalAttachmentContentStore` over an explicit, validated root. Every
`memory | relational` x `memory | local` combination is valid; composition
fails closed on anything else. The API factory composes `ApplicationPersistence`
and the attachment content store once at startup; `AttachmentService` consumes
both through ports. SQLite is the concrete durable relational adapter and the
local filesystem the concrete durable physical adapter, each designed to be a
replaceable seam (a future engine or cloud content store pins the same ports).

### Comment / config corrections applied (review-driven only)

- `.env.example`: persistence comment no longer claims the relational SQLite
  adapters are "available but not yet activated" — final Phase 4 wording lists
  every durable domain; the memory default and the `relational` trigger are
  documented.
- `configuration/settings.py`: `_env_persistence_provider` docstring and the
  field comment updated from "activated by a later Phase 4 step"/partial
  activation roster to the complete seven-domain durable set.
- `api/app.py`: composition comment fixed — relational installs durable
  adapters for *every* Phase 4 domain (it incorrectly said document "stays
  in-memory (Step 4.10)"); attachment content comment dropped the stale
  "future AttachmentService (4.14.E)" wording.
- `infrastructure/composition.py`: attachment content seam docstring — the
  `AttachmentService` reference is present-tense (the service is composed in
  the same factory).
- `infrastructure/persistence/composition.py`: module docstring now credits
  document revision and attachment alongside the original five domains.
- `infrastructure/persistence/repositories/document_write_coordinator.py`:
  removed the stale claim that the coordinator was "deliberately not wired into
  DocumentService yet"; it has been wired since Step 4.13.D and selected by
  composition for `relational`.
- Repository port docstrings (`document_repository`, `conversation_repository`,
  `document_revision_repository`, `run_event_repository`): "a later Phase 4
  step" / "future durable adapters" phrasings corrected — the durable SQLite
  adapters exist and satisfy these contracts today.
- Stale/checked items outside Phase 4 scope (e.g. the native-runtime seed
  docstring "not yet composed in production") were classified as unrelated and
  left untouched.

### Known limits (final, carried from design)

Clean-restart durability is proven end to end (Step 4.15). Not claimed:
power-loss/crash recovery, disk-corruption repair (migrations fail closed),
multi-process concurrent access/failover, cross-machine/distributed
deployment, backup/restore, rollback of applied migrations, live-inference
execution-selection durability beyond `execution_selection: null`, cloud
attachment content stores, attachment orphan reconciliation/delete (orphan
policy above), revision restore/revert/diff/retention, streaming
reconnect/event-streaming (Phase 5), and any authentication or authorization
on attachment or other Phase 4 endpoints.

### Validation

- Backend suite: pytest **1304 passed, 2 skipped, 4 warnings** (unchanged code
  count — this step added no tests because every candidate hardening gap was
  already pinned; the count is identical to 4.15); `ruff check src tests` PASS;
  `mypy src` PASS (143 source files).
- Frontend regression (unchanged, stays green): `@ava/contracts` 23,
  `@ava/api-client` 64, `@ava/ui-core` 20, `@ava/agent-ui` 132,
  `@ava/document-core` 48, `@ava/workspace` 21 passed | 4 skipped — all PASS.
- Repo-wide `pnpm -r --if-present lint` (`tsc --noEmit`): PASS. Web and Desktop
  production builds PASS.
- Aggregate `./scripts/test_all.sh`: PASS (backend pytest, Ruff, mypy; frontend
  tests + lint; Python client 10 tests + Ruff + mypy).
- `git diff --check`: clean.
- Live startup smoke (port 8199, temporary SQLite + content root, mock agent,
  `AVA_PERSISTENCE=relational` + `AVA_ATTACHMENT_STORAGE=local`): application
  boots, migration runner reports `[1,2,3]` applied / nothing pending, and the
  health endpoint responds — proving the relational+local composition starts
  and shuts down cleanly outside the test harness. Port 8000 not touched.

### Files changed

- Production: comment/docstring corrections only in the eight files listed
  above (`.env.example`, `settings.py`, `api/app.py`,
  `infrastructure/composition.py`, `infrastructure/persistence/composition.py`,
  `document_write_coordinator.py`, and the four repository port docstrings).
  No behavior changed.
- Docs: this entry.

### Phase status

**Phase 4 — Durable Application State: STATUS: COMPLETE.**

All Phase 4 slices (Steps 4.1–4.16) are delivered and validated.

**Next Phase: phase 5 — Production Conversation / Context / Runs.** Not
started. Phase 5 is expected to cover production conversation and run features
event streaming/reconnect, execution-selection durability for live runs, and
the attachment/revision deferred capabilities above as they become product
priorities.
