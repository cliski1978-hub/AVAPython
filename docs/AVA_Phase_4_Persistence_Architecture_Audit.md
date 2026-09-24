# AVA Phase 4 — Persistence Architecture Audit

**Step:** Phase 4, Step 4.1 — Persistence Architecture Audit
**Type:** Documentation / audit only. No repositories, databases, ORM, migrations, or behavior changes.

This document records where AVA currently holds application state, classifies every
state type by persistence class, and identifies the clean insertion points and
boundaries for the durable-persistence work that Phase 4 will implement. It is the
evidence base for Steps 4.2–4.16; nothing in this step changes production code.

---

## 1. Executive Summary

AVA holds **all** current application state in memory. There is no database, no
ORM, no file-backed store, no repository port, and no persistence library anywhere
in the backend or frontend source tree.

- The **backend** (`backend/src/ava`) keeps runs and run events in two plain in-memory
  stores (`RunStore`, `RunEventStore`); everything else that "remembers" anything
  (workspace registry, model registry, model qualification metadata, model resource
  leases) is likewise an in-process Python `dict` catalog, and the model-qualification
  "persisted" variant was explicitly deferred in Phase 3.
- The **frontend** keeps the conversation (`@ava/agent-ui`) and the document collection
  (`@ava/document-core`) as in-memory React reducer state. There is no
  `localStorage`, `sessionStorage`, or IndexedDB anywhere in the frontend, and no
  conversation/document backend API exists to fall back on. A browser refresh or app
  restart destroys open conversations and documents.
- A **backend** conversation/message/document "domain" does not exist at all — no
  entities, no contracts, no routes. The only conversation-shaped object is an
  adapter-internal `ControlledConversation` inside the OpenHands adapter, which is
  execution-local and not an AVA domain entity.
- The run/event persistence boundary is already **cleanly plugged**: `RunService`
  depends on the `AgentPort` plus two store objects with a tiny, well-tested surface
  (`create`/`update_status`/`get`/`list` and `append`/`get_events`/`get_latest`).
  Replacing those stores with repository ports is a mechanical, low-risk change that
  preserves every current behavior and test.
- The **document loss point** is the `saveDocument` action in
  `@ava/document-core`: it only dispatches `markClean`. There is no server round
  trip; "saving" merely clears a dirty flag.
- Architecture guardrails already forbid `sqlalchemy` (and FastAPI, LangChain, etc.)
  inside `ava.core` and `ava.contracts`, and force `RunService` to stay free of
  models/runtimes/workspaces/security. Phase 4 must keep every new contract and every
  new repository port in the same framework-neutral style, confining the concrete
  database adapter to `ava.infrastructure`.

Recommended outcome of Phase 4 in one sentence: **introduce AVA-owned repository ports
for `Run`, `RunEvent`, `Conversation`, `Message`, and `Document` (with in-memory and
SQLite adapters), compose the SQLite adapters behind the existing services, and wire
`Conversation`/`Message`/`Document` REST endpoints + frontend hydration to them —
without letting any database type escape the infrastructure layer.**

---

## 2. Current State Ownership Map

Persistence classes used below:

| Class | Meaning |
|---|---|
| **PERSISTED** | Survives process/browser restart through some durable mechanism today. |
| **IN-MEMORY BACKEND** | Held by backend service store/registry objects in the server process; lost on backend restart. |
| **IN-MEMORY FRONTEND** | Held by React reducer state in the browser; lost on refresh/app exit. |
| **EXECUTION-LOCAL** | Lives only inside an adapter activation for the duration of a run; not an AVA domain entity. |
| **NOT IMPLEMENTED** | No code path exists (only UI affordances or capability names exist). |
| **PARTIAL** | A subset of the concept exists; the remainder is unimplemented. |

### 2.1 State inventory

| # | State concept | Where it lives today | Persistence class | Survives restart? |
|---|---|---|---|---|
| 1 | **Run** (status, selection) | `backend/src/ava/services/run_store.py` — in-memory `RunStore` (`dict[str, RunRecord]`), owned by `RunService` | IN-MEMORY BACKEND | No |
| 2 | **RunEvent** (event log per run) | `backend/src/ava/services/run_event_store.py` — in-memory `RunEventStore` (`dict[str, list[RunEvent]]`), owned by `RunService` | IN-MEMORY BACKEND | No |
| 3 | **Conversation** (list/title/active) | `frontend/packages/agent-ui/src/state/ConversationProvider.tsx` + `conversationReducer.ts` | IN-MEMORY FRONTEND | No |
| 4 | **Message** (prompt + assistant reply) | `frontend/packages/agent-ui` — `ConversationMessage` in reducer state, hydrated from `RunEvent`s via `runEventProcessor.ts` | IN-MEMORY FRONTEND | No |
| 5 | **Document** (title, HTML content, dirty) | `frontend/packages/document-core/src/state/DocumentProvider.tsx` + `documentReducer.ts` | IN-MEMORY FRONTEND | No |
| 6 | **Document revision / history** | nothing | NOT IMPLEMENTED | — |
| 7 | **Attachment** | nothing (capability not advertised) | NOT IMPLEMENTED | — |
| 8 | **Approval** | `ava/contracts/approvals.py` is a 4-line placeholder; `APPROVAL_REQUESTED` event type exists; `approvals` capability exists but is reported `false` | NOT IMPLEMENTED | — |
| 9 | **Audit / security log** | `AVA_Phase_3_AI_Model_Context.md` records that persistent audit storage is deliberately deferred to the persistence architecture | NOT IMPLEMENTED | — |
| 10 | **App configuration** | `backend/src/ava/configuration/settings.py` (env-driven `Settings`) + `backend/src/ava/core/application.py` (`ApplicationConfig`) | PERSISTED (env + files) | No (env vars re-read on boot; not stored in DB) |
| 11 | **Model qualification metadata** | `backend/src/ava/models/qualifications.py` — in-memory; Step 41 "persisted qualification" explicitly deferred (Phase 3 log) | IN-MEMORY BACKEND / PARTIAL | No |
| 12 | **Model invocation details** (selection, resources) | `RunExecutionSelection` snapshot on the run record; in-memory model resource manager leases (`ava/execution/model_resources.py`) | PARTIAL | Per-run selection survives only as long as the in-memory run record survives |
| 13 | **Workspace catalog** (approved workspaces + permissions) | `backend/src/ava/workspaces/registry.py` — in-memory `WorkspaceRegistry` (`dict[str, ResolvedWorkspace]`) | IN-MEMORY BACKEND | No |
| 14 | **Configured model catalog** | `backend/src/ava/models/model_registry.py` — pure in-process catalog built at composition from settings | PARTIAL (derived from config each boot) | Rebuilt deterministically on boot |
| 15 | **Conversation run linkage** (which run produced which message) | Frontend `ConversationRunState` (`runId`, `backendStatus`, `uiPhase`, `error`) in agent-ui reducer | IN-MEMORY FRONTEND | No |

### 2.2 The three surfaces that must become durable first

Per the canonical plan's Phase 4 guidance (see §12), durability starts with the five
domains already present in memory: **Conversation, Message, Run, RunEvent, Document**.
Of these, only Run/RunEvent have any backend presence today; Conversation/Message/
Document are frontend-only. This asymmetry is the single most important fact in this
audit and drives the recommended sequence.

---

## 3. Current Run Persistence Architecture

### 3.1 Call flow, front to back

```text
Web / Desktop shell (App.tsx, identical)
  └─ @ava/api-client ApiClient (baseUrl http://localhost:8000)
       └─ startRun / getRun / getRunEvents / cancelRun
            └─ FastAPI app (ava/api/app.py, lifespan creates state.run_service)
                 └─ api/routes/runs.py
                      POST   /runs                → RunService.start_run
                      GET    /runs/{id}           → RunService.get_run
                      GET    /runs/{id}/events    → RunService.get_run_events
                      POST   /runs/{id}/cancel    → RunService.cancel_run
                           └─ RunService  (ava/services/run_service.py)
                                ├─ AgentPort.execute(request)      (ava/agents/contracts.py)
                                ├─ RunStore       (in-memory dict)
                                └─ RunEventStore  (in-memory dict)
```

### 3.2 `RunService` ownership

`backend/src/ava/services/run_service.py`:

- **Dependencies** (`__init__`): `agent: AgentPort`, `run_store: RunStore`,
  `event_store: RunEventStore`. That is the entire surface.
- **Owns identity**: `run_id = str(uuid4())` on `start_run`; `message_id = str(uuid4())`
  for the assistant message event; `event_id = str(uuid4())` in `_append`.
  Callers never supply IDs (the `RunRequest` docstring states this explicitly and a
  future `correlation_id` is reserved for requests, not overloaded onto run identity).
- **Publishes events** through `_append`: `RUN_STARTED` … (`MESSAGE_STARTED`,
  `MESSAGE_CONTENT`) … then a single terminal event. The seeded `MESSAGE_CONTENT`
  payload carries the assistant text.
- **Terminal semantics**: `RUN_COMPLETED`, `RUN_CANCELLED`, `RUN_FAILED` are the only
  terminal types; `RunEventStore.append` ignores a _second_ terminal event for a run
  (idempotent seal), and `cancel_run` guarantees cancellation wins over completion.
- **Retrieval is snapshot-only**: `get_run` returns a `RunResponse | None` and
  `get_run_events` returns `list[RunEvent] | None`. There is no streaming; the
  `streaming` capability is truthfully `false`.

### 3.3 Current store contracts (the exact seam Phase 4 replaces)

`backend/src/ava/services/run_store.py` — `RunRecord` (frozen dataclass):
`run_id`, `status: RunStatus`, `created_at`, `updated_at`,
`execution_selection: RunExecutionSelection | None`.

`RunStore` (in-memory): `create(run_id) -> RunRecord` (rejects duplicate),
`update_status(run_id, status) -> RunRecord | None` (None for unknown run),
`set_execution_selection(...)`, `get(run_id) -> RunRecord | None`,
`list_run_ids() -> list[str]`, `clear()`.

`backend/src/ava/services/run_event_store.py` — `RunEventStore` (in-memory):
`append(event) -> RunEvent` (order-preserving; seals after terminal),
`get_events(run_id) -> list[RunEvent]`, `get_latest(run_id) -> RunEvent | None`,
`clear()`.

These two classes are the smallest, best-tested seam in the codebase: Phase 3 already
documented that run/event storage "remains in memory and disappeared when validation
servers restarted." Replacing them with `RunRepository` / `RunEventRepository` ports
is the natural Step 4.2/4.3.

---

## 4. Current Conversation Architecture

### 4.1 Backend: no conversation domain

There are **no** conversation or message entities, contracts, routes, or services in
`backend/src/ava`. Grep across the backend finds conversation-shaped code only inside
the OpenHands adapter (`ControlledConversation`/`ConversationManager`), which is an
execution-local SDK holder for live task dispatch — not an AVA domain entity and not
exposed through any API. `RunEvent.MESSAGE_STARTED`/`MESSAGE_CONTENT` are the only
message-flow artifacts, and they are mechanical (started-event then a `message_content`
payload with the assistant text).

### 4.2 Frontend: the entire conversation lives in React state

`@ava/agent-ui` owns the conversation domain entirely in the browser:

- `state/ConversationProvider.tsx` + `state/conversationReducer.ts` — reducer state
  `conversations: Conversation[]`, `activeConversationId`. Actions:
  `conversation:create`, `conversation:select`, `conversation:addUserMessage`,
  `conversation:addAssistantMessage`, `conversation:updateMessage`,
  `conversation:setRunState`. `createEntityId()` uses `crypto.randomUUID()`.
- `types.ts` — `ConversationMessage { id, role: "user"|"assistant"|"system", content,
  status: "pending"|"complete"|"failed"|"cancelled", sourceUserMessageId, error,
  createdAt }`; `UIRunPhase`; `ConversationRunState { runId, backendStatus, uiPhase,
  error }`; `Conversation`.
- `run/conversationRun.ts` — the `RunAgent` interface (`startRun`, `getRunEvents`,
  `cancelRun`) with the `clientRunAgent` implementation wrapping `@ava/api-client`.
  It keeps message IDs stable across retries and updates the correct conversation when
  a run completes late.
- `run/ConversationRunProvider.tsx` — the higher-level `submitPrompt`, `stopRun`,
  `retryMessage`, `regenerateMessage` API.
- `run/runEventProcessor.ts` — `applyRunEvent` maps backend `RunEvent`s onto reducer
  actions (`message_started` → pending message, `message_content` → content,
  terminal event → complete/cancelled/failed).

**Instantiation**: the `ConversationProvider` holds one per-frontend-instance state
(no persistence hook). Projecting: after a refresh the reducer reinitializes to a fresh
empty conversation list. Sprint 2's documentation states this exactly: "Conversation
persistence not implemented (in-memory; refresh clears state)."

### 4.3 Where conversation data is lost

- On browser refresh / app close (entire state).
- On backend restart, the run/event history is lost too, so even a re-hydration could
  not reconstruct old conversations — the frontend never persisted the mapping anyway.

---

## 5. Current Document Architecture

### 5.1 Pathway (exact loss point)

```text
Web / Desktop shell (App.tsx → @ava/workspace AppWorkspace)
  └─ AppWorkspace keeps Chat + Documents panes permanently mounted
       └─ @ava/workspace → @ava/document-core DocumentProvider (reducer)
            └─ DocumentWorkspace.tsx (sole Tiptap integration)
                 └─ EditorAdapter (AVA-facing editor capability surface)
                      ├─ getContent: DocumentContent (format "html", Tiptap getHTML)
                      ├─ setContent / focus / isEditable
                      └─ TiptapEditorAdapter (HTML conversion at the boundary)
```

- `model/documentContent.ts` — **`DocumentContent { format: "html", value: string }`**:
  serialized HTML is the canonical, serializable document content today.
- `model/document.ts` — `AvaDocument { id, title, content, createdAt, updatedAt,
  isDirty }`; `createAvaDocument()`, `createDocumentId()` via `crypto.randomUUID()`.
- `state/DocumentProvider.tsx` + `state/documentReducer.ts` — in-memory collection +
  `activeDocumentId`; actions `create`, `setActiveDocument`, `updateContent`, `rename`,
  `markClean`, `close`.
- `editor/initialDocument.ts` — one initial in-memory `Untitled Document`.
- **`saveDocument` only dispatches `markClean`.** There is no HTTP call, no storage
  API, no backend. "Saving" flips the dirty flag; the bytes exist only in the reducer.
  This is the exact loss point: refresh or app exit loses every document.

### 5.2 Backend: no document domain

No document contract, route, or service exists in `backend/src/ava`. The contract
placeholder `ava/contracts/approvals.py` and the `CapabilityName.DOCUMENT_OPERATIONS`
(`document_operations`) and `APPROVAL_REQUESTED`/`DOCUMENT_CHANGE_PROPOSED`/
`ARTIFACT_CREATED` event types exist, but the capability discovery reports
`document_operations: false`. There is no `GET/POST /documents`, no revision history,
no sanitization boundary for stored HTML.

### 5.3 Where document data is lost

- On browser refresh / app close (entire state).
- Nothing is written anywhere at `saveDocument` time — the loss is immediate, not
  gradual: the document simply does not exist outside the reducer.

---

## 6. Current Composition and Dependency Injection

### 6.1 Backend composition root

- `backend/src/ava/api/app.py` — FastAPI factory `create_app()`; the lifespan builds
  `app.state.run_service` via the infrastructure composition helpers; routers are
  registered for `capabilities`, `health`, `execution_profiles`, `model_providers`,
  `models`, `runs`, `runtimes`, `workspaces`.
- `backend/src/ava/infrastructure/composition.py` — the only sanctioned construction
  site for concrete adapters/registries (agent adapter, command-execution policy,
  model orchestrator, model-provider registry, qualification store, model registry,
  model resource manager, runtime registry, sandboxed command runner, workspace
  registry, workspace resolver). Adapter choice is driven by the env-driven
  `Settings` (`AVA_AGENT_PROVIDER=mock` default; `AVA_MODEL_PROVIDER=local`).
- `backend/src/ava/configuration/settings.py` — env-driven `Settings` dataclass with
  helpers `_env_str/_env_int/_env_bool/_env_hosting_mode`; lives under
  `backend/src/ava/configuration/`.
- `backend/src/ava/core/application.py` — framework-neutral `ApplicationConfig`
  dataclass (no FastAPI types).

### 6.2 Why this is a clean seam

Everything a Phase 4 persistence adapter touches is constructed in ONE place
(`composition.py`). `RunService` already receives its stores by injection. The
pattern for a Phase 4 repo is identical to the existing registry pattern:
define a port in a repository layer, provide an in-memory implementation and a
SQLite implementation under `ava/infrastructure/persistence/`, and wire the selected
one in `composition.py`. No route, service, or contract file needs to change to swap
the engine.

### 6.3 Frontend composition

Web and Desktop shells are identical thin wrappers: they construct an `ApiClient`
and render `<AppWorkspace>` from `@ava/workspace`. `AppWorkspace` mounts
`ConversationProvider` and `DocumentProvider`. Frontend "dependency injection" is
React context; the persistence-decision point for the frontend (Step 4.5+) is either
(a) hydrate from backend at mount and write through a document/conversation client, or
(b) a local-first store — a design decision the audit leaves open, but the backend
endpoints decided in Steps 4.4–4.8 are needed regardless of choice.

---

## 7. Existing Contracts Suitable for Persistence

All of the following already exist, are framework-neutral (Pydantic/StrEnum/dataclass,
stdlib only), carry `contract_version: "v1"`, and can be serialized today. They should
be **reused** verbatim by the persistence layer — not duplicated:

| Contract | File | Why it persists cleanly |
|---|---|---|
| `RunStatus` (`pending/running/waiting_for_approval/completed/cancelled/failed`) | `backend/src/ava/contracts/responses.py:69` | The canonical status vocabulary for `RunRecord`. |
| `RunResponse` (`run_id`, `status`, `execution_selection`) | `backend/src/ava/contracts/responses.py:80` | Existing DTO for `GET /runs/{id}`. |
| `RunExecutionSelection` / `RunExecutionOverride` | `backend/src/ava/contracts/execution.py` | Per-run execution identity snapshot (`runtime_id`, `model_provider_id`, `model_id`, `hosting_mode`). |
| `RunEvent` + `EventType` (12 types incl. `MESSAGE_STARTED`, `MESSAGE_CONTENT`, `APPROVAL_REQUESTED`, `DOCUMENT_CHANGE_PROPOSED`, `ARTIFACT_CREATED`, 3 terminal) | `backend/src/ava/contracts/events.py` | Serializable event envelope (`event_id`, `run_id`, `event_type`, `timestamp`, `payload: dict[str, JsonValue]`). |
| `RunRequest` (`prompt`, `execution`, `workspace_id`) | `backend/src/ava/contracts/requests.py` | Existing write contract; docstring explicitly reserves future `correlation_id` and message/conversation/document-reference fields. |
| `JsonValue` | `backend/src/ava/contracts/json_types.py` | Portable JSON type for the event `payload` column. |
| `ErrorResponse` / `ErrorCategory` | `backend/src/ava/contracts/errors.py` | Structured error vocabulary for repository failure surfaces. |
| `CapabilityName` (`document_operations`, `approvals`, …) | `backend/src/ava/contracts/capabilities.py` | The honest capability flags persistence will flip to truthful values. |
| `CONTRACT_VERSION` (`"v1"`) | `backend/src/ava/contracts/version.py` | Capacity flag on every stored DTO. |
| `WorkspaceInfo` (`workspace_id`, `display_name`, `kind`) | `backend/src/ava/workspaces/contracts.py` | The public-safe workspace identity (workspace discovery reuses it). |
| `ExecutionProfile` / `RuntimeDiscoveryItem` / `ModelInfo` / `ModelProviderHealth` | `backend/src/ava/contracts/responses.py`, `models.py` | Reuse for future persisted execution-profile/qualification records. |

Frontend mirrors of `RunStatus`, `RunRequest`, `RunExecutionSelection/Override`,
`RunResponse`, `EventType`, `RunEvent`, `ErrorCategory`, `ErrorResponse` exist in
`frontend/packages/contracts/src/{runs,events,errors}.ts` and are used by
`@ava/api-client`; the persistence layer introduces no parallel client vocabulary.

---

## 8. Missing Persistence Contracts

These do not exist and Phase 4 must create them (all Pydantic/StrEnum, `sqlalchemy`-free,
`contract_version`-carrying, exported through `ava.contracts` and
`frontend/packages/contracts`):

| Missing contract | Notes |
|---|---|
| **Conversation** (`id`, `title`, `created_at`, `updated_at`, `message_ids`, maybe `workspace_id`) | There is literally no backend entity today. Frontend `Conversation` (agent-ui `types.ts`) is the de-facto shape. |
| **Message** (`id`, `conversation_id`, `role`, `content`, `status`, `source_user_message_id` / parent linkage, `created_at`) | Decision needed (Step 4.12): store messages as **derived projection of RunEvents** vs **first-class store**. The frontend `ConversationMessage` already mirrors the desired shape. |
| **Document** (`id`, `title`, `content: DocumentContent`, `created_at`, `updated_at`) | Canonical content format is serialized HTML. Needs a **server-side HTML sanitization contract** before any durable store accepts Tiptap output (stored-XSS surface). |
| **DocumentRevision** (`document_id`, `revision`, `content`, `author`, `timestamp`) | `AvaDocument` has no revision lineage; HTML diffs are the natural future form. |
| **Attachment** (`id`, `conversation_id`/`message_id`, `filename`, `mime_type`, `size`, storage ref) | None at any layer today. |
| **ApprovalRequest / ApprovalResponse** (`id`, `run_id`, `subject`, `decision`, `decided_by`, `timestamp`) | `approvals` capability and `APPROVAL_REQUESTED` event exist but are placeholder/false. |
| **AuditLogEntry** (`id`, `actor`, `action`, `entity`, `timestamp`, `payload`) | Explicitly deferred by Phase 3 (see §11). |
| **Correlation IDs on requests** | `RunRequest` docstring reserves a `correlation_id`; persistence of request correlation is a future nicety. |

---

## 9. Recommended Repository Boundaries

Mirror the existing layer rules rather than inventing new ones. The current enforced
direction is `API / Infrastructure → Services → Core / Ports / Contracts`.

```text
ava.repositories               ← NEW: framework-neutral persistence ports (Protocol/ABC)
    └─ run_repository.py          RunRepository
    └─ run_event_repository.py    RunEventRepository
    └─ conversation_repository.py ConversationRepository
    └─ message_repository.py      MessageRepository
    └─ document_repository.py     DocumentRepository

ava.infrastructure.persistence  ← NEW: concrete adapters + schema
    └─ memory/                    In-memory impls (migrate existing RunStore/RunEventStore behavior)
    └─ sqlite/                    sqlite3 adapters, migrations, row mappings
      (MSSQL/other engines later; ports remain engine-agnostic)

ava.services                     ← existing; RunService gains repo-por dep; new
    └─ conversation_service.py      ConversationService
    └─ message_service.py / document_service.py
ava.contracts                    ← existing + new conversation/message/document/... DTOs
ava.api.routes                   ← existing runs routes unchanged + new conversations/documents routes
```

Rules to encode in `test_architecture.py`:

1. `ava.repositories` may import only `ava.contracts` (+ stdlib, pydantic). **No**
   `infrastructure`, `services`, `api`, `sqlalchemy`, `aiosqlite`, drivers.
2. `ava.infrastructure.persistence` may import `ava.repositories` and `ava.contracts`
   and the chosen driver; nothing upward (never `api`/`services`).
3. `ava.services` may depend on `ava.repositories` ports but never on
   `ava.infrastructure.persistence` (engine stays a composition decision).
4. Extend `FORBIDDEN_IMPORTS` behavior (already contains `sqlalchemy`) with a new
   repository-port guard so a driver can never leak into a port/DTO.
5. `RunService` keeps its existing guards (no `models`, `runtimes`, `workspaces`,
   `execution`, `infrastructure`); it may only *add* a dependency on a `RunRepository`
   / `RunEventRepository` port.

---

## 10. Migration Map

| Step | Domain | Current | Target | Concrete change |
|---|---|---|---|---|
| 4.2 | Run | `RunStore` in-memory dict | `RunRepository` port + in-memory impl | Extract the exact `RunStore` method surface into a Protocol; keep in-memory impl byte-for-byte; `RunService` type moves to the port. |
| 4.3 | RunEvent | `RunEventStore` in-memory dict | `RunEventRepository` port + in-memory impl | Same extraction; preserve order-preserving append and terminal-event sealing. |
| 4.4 | Conversation | frontend-only reducer state | `ConversationRepository` port + in-memory impl + backend entity | First backend conversation entity/contract; `POST /conversations`. |
| 4.5 | Message (reading) | frontend hydration from run events | `MessageRepository` + `GET /conversations/{id}/messages` | Hydration endpoint; decide projection-vs-store later (4.12). |
| 4.6 | Document identity | `crypto.randomUUID()` frontend-only | persisted document id, no naming restrictions | Backend-owned `document_id`; "Untitled Document" collision naming rule. |
| 4.7 | Document storage | `markClean` only | HTML-serialized `DocumentRepository`; `POST/GET/PUT /documents` | Replace the frontend save no-op with a real write path **+ server-side HTML sanitization**. |
| 4.8 | Document versioning | none | `DocumentRevision` + `GET /documents/{id}/revisions` | Revision model; the first version persists the initial content. |
| 4.9 | Attachments | none | `AttachmentRepository` (per-phase scope) | Contracts + port; storage engine decision (filesystem vs blob column) stays in infrastructure. |
| 4.10 | Audit | none | `AuditLogEntry` contract + repo | Seeded by run/document writes; no public audit API (Phase 3 constraint). |
| 4.11 | Engine integration | in-memory | SQLite adapter replacing memory adapter by config | Composition switch `AVA_PERSISTENCE=memory|sqlite`; migration runner in `infrastructure/persistence`. |
| 4.12 | Message authoring | inline in `RunService` event emission | `MessageService` writes first-class messages | RunService stays event-owner; a message-authoring consumer (in scope of ConversationService) persists messages. |
| 4.13 | Hydration API | none | `GET /conversations/{id}` returns conversation + message/history | Controller composes ConversationRepository + MessageRepository; CLIENTS unchanged shape-wise. |
| 4.14+4.15 | Lifecycle | — | endpoint mapping + lifecycle policy + revalidation + expunge | Ties storage lifecycle to run terminal state; capacity/metadata rechecks; remove dead records policy. |
| 4.16 | Beyond Phase 4 | — | iteration plan | Repository/engine roadmap (MSSQL, filesystem docs, qualification persistence). |

Cross-layer rule for every row: the **frontend never talks to a database.** All durable
state enters through `@ava/api-client` endpoints; the frontend keeps its reducer as an
in-memory projection with explicit hydrate/persist actions.

---

## 11. Risks and Coupling to Avoid

1. **Database types leaking out of infrastructure.** Highest-priority invariant. Every
   new contract and repository port must be pure Pydantic/stdlib. `sqlalchemy` is
   already in `FORBIDDEN_IMPORTS` for `core`/`contracts`; extend the guard to
   `ava.repositories` §9.1. All driver types (SQLAlchemy rows, sqlite3 cursors) stay
   inside `ava.infrastructure.persistence`.
2. **`RunService` scope creep.** `RunService` currently owns run + event identity and
   event publication and is guarded to stay free of models/runtimes/workspaces/
   security. It may gain repository ports but must not gain conversation/document/
   approval/audit responsibilities. New orchestration belongs in `ConversationService`
   / `DocumentService` / a future `ApprovalService`.
3. **Terminal-event sealing idempotency.** In memory, a second terminal event is
   ignored. A durable append must enforce the same rule (DB-level guard/transaction),
   and `cancel wins over completion` must survive a completed+cancelled race.
4. **Event ordering.** The in-memory store preserves append order in a `list`. SQLite
   needs an explicit monotonically increasing sequence column per run (or a composite
   `(run_id, seq)` unique key) to preserve the documented event sequence
   `run_started → message_started → message_content → terminal`.
5. **Per-run vs global identity.** `RunEvent.event_id` and `RunRecord.run_id` use UUID
   strings `str(uuid4())`. Persistence must not renumber or shorten them; indexes
   should be created for `(run_id)` lookups.
6. **Snapshot-only semantics.** Retrieval is snapshot-only and the `streaming`
   capability is truthfully `false`. Durability must not silently introduce a
   streaming/SSE path, or the capability contract must be updated deliberately and
   tested.
7. **Stored XSS via HTML documents.** `DocumentContent` is Tiptap-generated HTML.
   A durable document store becomes a stored-XSS sink unless the server sanitizes
   HTML on every write. Sanitization must be a Phase 4 requirement (part of Step 4.7),
   not a Phase 6 idea.
8. **Derived-message trap.** Do not let message persistence drift from run-event
   truth. Either messages are a stored first-class entity (4.12) or a live projection
   of stored events — pick one and make it explicit and tested; never both silently.
9. **Frontend "save" semantics.** Documents currently "save" as `markClean`. The
   Phase 4 write path must keep the dirty lifecycle honest (dirty on edit, clean only
   after a confirmed backend write), and document UI must not claim persistence until
   the write is confirmed.
10. **Qualification/persistence deferral.** Phase 3 explicitly deferred persisted model
   qualification, execution-profile persistence, and audit storage. Phase 4 may seed
   audit (4.10) but must not silently fold qualification/execution-profile storage in —
   those are separate, later decisions tied to Steps 19–21.
11. **Workspace vs document confusion.** `WorkspaceRegistry` = approved execution
   workspaces (server side). Frontend "Documents" tab = user documents. Keep the two
   worlds separate; do not reuse workspace status for document status.
12. **Contract churn.** Frontend and backend contracts are already mirrored by hand.
   New contracts (conversation/message/document) must be added to both sides together
   and to `ava.contracts`/`frontend/packages/contracts` index files, and must stay
   `contract_version: "v1"`.

---

## 12. Recommended Phase 4 Step Sequence (Validated)

The canonical plan (`AVA_CANONICAL_DEVELOPMENT_PLAN_CURRENT_TO_COMPLETION.md`,
§27 "Immediate Next Development Phase") scopes Phase 4 narrowly:

> Define AVA-owned repository ports and persistence ownership — start with the domains
> already present in memory (Conversation, Message, Run, RunEvent, Document) — then add
> the first concrete persistence adapter. Do **not** begin RAG, adaptive routing,
> additional runtimes, model training, or enterprise integration.

The detailed 4.1–4.16 step list is validated against that scope and against this
audit's facts. Every step is either **VALIDATED** (grounded in what exists) or
**REVISED** (this audit changes the approach it implies), with the revision reasoning
inline. Nothing in this section permits Steps 4.2+ to start in this step.

| Step | Title | Audit verdict | Notes grounded in this audit |
|---|---|---|---|
| 4.1 | Persistence architecture audit | ✅ **VALIDATED — this document** | Audit-only; no code. |
| 4.2 | Run repository hooks and tests | ✅ VALIDATED | `RunStore` surface (§3.3) is the exact seam; extract port, keep in-memory impl, add architecture guard. |
| 4.3 | SQLite run store (and run-event store) | ✅ VALIDATED | Move to `infrastructure/persistence/sqlite`; preserve idempotent terminal seal, ordering, `str(uuid4())` ids (§11.3–11.5). |
| 4.4 | Conversation repository + hook | ✅ VALIDATED | First backend conversation entity; frontend `Conversation` (§4.2) is the de-facto shape. |
| 4.5 | Conversation/message GET-by-id API | ✅ VALIDATED | `GET /conversations/{id}` + `/messages`; snapshot-only like runs (§11.6). |
| 4.6 | Persistent document identity (+ name rules) | ✅ VALIDATED | Replace frontend-only `crypto.randomUUID()` with backend-owned id; keep "Untitled N" collision rule. |
| 4.7 | HTML-serialized document store | ✅ VALIDATED | Replace `markClean` no-op with real write; add server-side sanitization requirement (§11.7). |
| 4.8 | Document version/revision | ✅ VALIDATED | `DocumentRevision` (§8); first revision captured on first write. |
| 4.9 | Attachment store | ⚠️ REVISED | Scope to contracts + repository port **only** in Phase 4; physical blob storage (filesystem vs column) deferred to Phase 6. |
| 4.10 | Audit store | ⚠️ REVISED | Phase 3 constraint: seed an `AuditLogEntry` table from run/document writes; **no public audit API/UI, no RBAC** (§11.10). |
| 4.11 | RDBMS integration + conflict handling | ✅ VALIDATED | `AVA_PERSISTENCE=memory\|sqlite` composition switch; engine-agnostic ports for future MSSQL; dedupe/upsert semantics (§11.3–11.4). |
| 4.12 | Message-authoring ("conversation in scope") service | ✅ VALIDATED | Decide stored-message vs projection explicitly (§11.8); `ConversationService` composes `MessageRepository`. |
| 4.13 | Conversation + responses hydration controller | ✅ VALIDATED | Hydrate frontend from `GET /conversations/{id}`; clients keep the current message shape (§4.2). |
| 4.14 | Lifecycle step / endpoint mapping / lifecycle policy | ✅ VALIDATED | Tie storage lifecycle to terminal run states; mapping of lifecycle→endpoints. |
| 4.15 | Revalidation after lifecycle policy / expunge / consolidation | ✅ VALIDATED | Remove dead records; re-verify capability flags truthfully. |
| 4.16 | Iteration plan + repository beyond Phase 4 | ✅ VALIDATED | Engine/domain roadmap (MSSQL, qualification persistence, attachments physical storage). |

**Non-goals for all of Phase 4** (repeat of canonical §27): RAG, adaptive routing,
additional runtimes, model training, enterprise integration, auth/RBAC, persisted
qualification, public audit API.

---

## Appendix A — Architecture Questions Answered

1. **Where does each state type currently live?** §2.1 inventory: backend store/registry
   objects (§3.3, §6.1), frontend reducer state (§4.2, §5.1), execution-local adapter
   objects (§4.1).
2. **What is the classification of each state type?** §2.1, §2.2 — five target domains;
   the only backend classes are IN-MEMORY BACKEND; Conversation/Message/Document are
   IN-MEMORY FRONTEND; approvals/attachments/audit are NOT IMPLEMENTED.
3. **Where is data lost today?** §3/§4.3/§5.3 — backend restart loses run/event history;
   browser refresh loses conversations and documents; `saveDocument` is a no-op.
4. **Which stores/services currently own state?** §3.3 — `RunService` + `RunStore` +
   `RunEventStore`; §6.1 — registries; §4.2/§5.1 — `ConversationProvider` and
   `DocumentProvider`.
5. **Are conversations/messages in the backend?** No — §4.1: backend has no conversation/
   message domain; only run events carry message text.
6. **Are documents in the backend?** No — §5.2: no document contract/route/service.
7. **What are the clean insertion points for persistence?** §6.2/§9/§10 — the store
   constructor seam and `composition.py`; new repository ports; new routes for
   conversations/documents.
8. **Do existing repositories/ORM/config exist?** No database/library of any kind
   (§1, verified: no sql/orm import in `backend/src`, `clients/python/src`, or
   `frontend/packages`). Config is env-driven `Settings` (§6.1).
9. **Which existing contracts can be reused?** §7 — `RunStatus`, `RunResponse`,
   `RunRequest`, `RunEvent`/`EventType`, `RunExecutionSelection/Override`, `JsonValue`,
   `ErrorResponse`/`ErrorCategory`, `CapabilityName`, `WorkspaceInfo`, `CONTRACT_VERSION`.
10. **Which contracts must be created?** §8 — Conversation, Message, Document,
    DocumentRevision, Attachment, ApprovalRequest/Response, AuditLogEntry.
11. **What architecture guards exist?** `test_architecture.py` — `FORBIDDEN_IMPORTS`
    (incl. `sqlalchemy`) for core+contracts, port-only access for agents/models,
    `RunService` freedom from models/runtimes/workspaces/security, engine-localized
    construction. Verified green: 46 architecture tests pass.
12. **What must NOT change?** §11 — database types must not escape infrastructure; the
    run event lifecycle/ordering/sealing; snapshot-only retrieval; `RunService`'s
    limited scope; capability flags stay truthful; qualifiation/execution-profile
    persistence stays deferred.
13. **What is the recommended Phase 4 sequence?** §12 — validated 4.1–4.16 table with
    REVISED notes on attachments (4.9) and audit (4.10).

---

## Appendix B — Validation Performed (baseline for this documentation-only step)

Step 4.1 makes no production changes; the following confirms the audited baseline is
the running state and that this step altered nothing:

- Backend: `pytest -q` → **591 passed, 2 skipped** (matches Phase 3 documented count);
  `ruff check src tests` → clean; `mypy src` (strict) → clean (93 files).
- Frontend: `pnpm -r test` → all packages pass (agent-ui 125, document-core 11,
  workspace 12 passed + 4 skipped integration; contracts/UI-core/api-client pass).
  TypeScript checks pass for every package/app.
- Python client: `pytest -q` → 10 passed; ruff → clean; mypy (strict) → clean.
- Aggregate: `./scripts/test_all.sh` → exit 0 across backend tests/ruff/mypy, frontend
  tests/typecheck, and Python client checks.
- Environment note: the AnyIO/FastAPI `TestClient` limitation called out in Phase 3
  diagnostics did not reproduce here; `tests/test_runs.py` (TestClient) runs and passes
  (23 tests). Reports above therefore reflect the real host execution.
- No baseline restrictions broken: working tree before/after this step are identical
  outside this document (see Step completion report).