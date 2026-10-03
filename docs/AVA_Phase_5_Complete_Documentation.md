# Phase 5 — Complete Documentation

**PHASE 5 STATUS: COMPLETE / PASS**

This is the primary human-readable closure document for Phase 5. It describes
what AVA *became* during Phase 5, not a list of commits or test runs. The final
canonical validation evidence is
[AVA_Phase_5_85_Final_Canonical_Validation.md](AVA_Phase_5_85_Final_Canonical_Validation.md);
the earlier 5.40 record remains the authoritative validation for its original
scope. Per-step implementation records are preserved individually and linked
throughout.

The forward roadmap remains
[AVA_CANONICAL_DEVELOPMENT_PLAN_CURRENT_TO_COMPLETION.md](AVA_CANONICAL_DEVELOPMENT_PLAN_CURRENT_TO_COMPLETION.md).
This document does not restate or compete with that roadmap.

---

## 1. Phase 5 overview

Phase 5 began as "make the conversation experience real" and, in the course of
doing that honestly, became two major bodies of work:

```text
A. Production configuration and execution configuration
B. Production conversation, context, and run experience
```

Both were necessary. You cannot have a durable, recoverable, user-configurable
production conversation experience if the system does not know *which* provider,
model, and runtime it is supposed to use, or if that choice is re-derived from
process environment variables every time a run starts. Fixing configuration
first is what made the rest of Phase 5 durable rather than merely reactive.

Phase 5 delivered, in order: persisted execution configuration with credential
references; normalized durable conversation/run/message relationships;
server-authoritative context construction and context-window management; a
normalized run lifecycle with durable cancellation; a streaming transport with a
persisted event sequence and replay; partial assistant persistence; reconnect,
refresh recovery, and explicit backend-restart recovery; retry/regenerate across
durable runs; stale-event protection; one-active-run-per-conversation
enforcement; normalized failure and configuration-remediation UX; Web and
Desktop acceptance; restart/durability integration evidence; and race
hardening.

## 2. Starting state

At the start of Phase 5, AVA was durable (Phase 4) but not production-experience
capable:

```text
conversations, messages, runs, run events persisted
but:
conversation → run relationships were unconstrained
run status was not the single lifecycle authority
there was no event sequence, cursor, or replay
there was no streaming transport at all
the frontend inferred run state from local memory
a browser refresh during a run lost the run
"which provider/model/runtime?" was decided by process environment
there was no partial assistant persistence
no reconnect, no resume, no refresh recovery, no restart semantics
no concurrency rule: two runs in one conversation could collide
no normalized user-facing failure copy
no Settings surface
```

Two Phase 5 documents record this honestly rather than retrospectively: the
Phase 5.18 production conversation architecture audit, which catalogued the
pre-existing gaps before fixing them, and the 5.36/5.37 acceptance records,
which state what could not be proven in their environments.

## 3. Final architecture

```text
Web shell / Desktop shell (thin)
        ↓
@ava/workspace  →  @ava/agent-ui  →  @ava/ui-core / @ava/contracts
        ↓
@ava/api-client (single shared transport)
        ↓
AVA API
        ↓
ConversationService / RunService / RunLifecycleService
        ↓
AgentPort  (stable execution boundary)
        ↓
Execution / runtime layer → model provider → model
        ↓
AVA-owned repositories → SQLite (development) / memory (tests)
```

Permanent separations, unchanged by Phase 5:

```text
Agent Runtime ≠ Model Provider
Model Provider ≠ Model
Provider ≠ Provider Connection
Model ≠ Inference Runtime
Workspace ≠ Runtime
Tool Permission ≠ Runtime Capability
```

`RunService → AgentPort` survived Phase 5 intact, and is now *enforced* rather
than merely intended: the 5.40 validation pass found and removed an illegal
`RunService → ava.execution` import that had been introduced by 5.35. See §27.

Web and Desktop remain thin shells over the shared workspace. `Tiptap` remains
internal to `@ava/document-core`. No additional frontend state-management
library was introduced; the only state libraries in the workspace remain React
state and refs.

## 4. Persistent configuration architecture

AVA now persists four configuration record families plus execution defaults:

```text
ProviderConnection
ModelConfiguration
RuntimeConfiguration
Execution Defaults
```

with credential references held separately from the records themselves
(§7). `ExecutionConfigurationResolver` (5.16) is the *sole* owner of resolving
persisted execution configuration, exposing `resolve_persisted()` and
`resolve_required()` over `ConfigurationRepositories` and returning a
`PersistedExecutionConfiguration`. `ExecutionSelector` adapts that into the
runtime-facing `ResolvedExecution` and stamps it with a `source` of `persisted`
or `bootstrap`, so the system always knows whether a run was configured or
defaulted.

### Distinctions that carry real weight

```text
Provider ≠ Provider Connection
   a provider is a kind of API (openai-compatible, anthropic, ...)
   a connection is a configured, addressable, credentialed instance of one

Model ≠ Provider Model Name
   a model is an AVA-owned record with a stable AVA model_id
   a provider model name is the provider's own string for that model

Runtime Configuration ≠ Runtime Type
   a runtime type is native / openhands / ...
   a runtime configuration is a configured, addressable instance of one

Agent Runtime ≠ Model Provider
   the runtime executes turns; the provider serves inference
   neither may be statically tied to the other
```

Model provider construction is a factory concern
(`ModelProviderFactory` / `ConfiguredModelProviderFactory`), not a place where
a service reaches into provider internals. The `ModelOrchestrator` may receive
a per-call `ModelRegistry` snapshot.

### Persisted settings are authoritative when configured

The rule Phase 5 established, and the one that caused the most design pressure:

```text
Persisted configuration, once configured, is authoritative.
Bootstrap / environment configuration is compatibility and bootstrap
behaviour. It is NOT a silent fallback from invalid persisted settings.
```

If saved defaults are invalid, the run fails with a durable, actionable
configuration error code and the UI offers remediation (§21). It does not
silently fall back to whatever the process environment happens to say.

### The one rule that is easy to get wrong

```text
execution omitted  ≠  execution explicitly selected
```

An omitted `RunRequest.execution` means "use the persisted application
defaults". An explicitly supplied `execution` is a legacy/bootstrap style
selection, used only after the saved defaults have been validated. The two are
never inferred from each other, and never from comparing identifiers.

## 5. Provider / model / runtime configuration

Bootstrap (5.17) seeds the initial records atomically — one
`BEGIN IMMEDIATE` with savepoints — for native and relational installs,
raising `ConfigurationBootstrapError` on failure and reporting colliding
records as `existing_records` rather than overwriting them. Seeded identities
are `bootstrap-provider-local` and `bootstrap-runtime-native`; the
`local-default` and `openhands-local` presets are retained. The execution
composer starts at "Application default", which is why a plain `POST /runs`
omits `execution` entirely.

Memory and mock installs are deliberately never seeded. Bootstrap does not
create a UUID/source column, an ownership flag, or a migration, and it does not
populate a credential environment field — partial configuration is an operator
decision, and AVA will not invent one.

## 6. Conversation / message / run relationships

Phase 5 normalized the durable relationship (5.19, additive migration
`v0008`):

```text
Conversation
    ↓
Source User Message
    ↓
Run
    ↓
Assistant Message
    ↓
Run Events
```

with durable identifiers:

```text
conversation_id
source_user_message_id
assistant_message_id
source_run_id        (the reverse link on the message)
```

A partial unique index on the assistant message keeps one run from claiming the
same assistant message twice. An attempt to build a run against an inconsistent
relationship is rejected with `422 invalid_run_relationship`.

Historical rows were **not** guessed or backfilled. Where a historical run's
relationship is unknown, it stays unknown. Inventing a plausible link would have
produced a database that looked tidier and lied about the past.

## 7. Credential architecture

```text
credential references may be persisted
secret values are NOT persisted
credentials resolve at execution time
secret exposure happens only at the provider-construction boundary
```

The supported reference pattern includes `env:NAME`. AVA therefore has a
*credential reference* capability, not a secrets vault, and this document does
not claim otherwise. Resolution failures surface as the durable
`credential_unavailable` code, never as a leaked value or a raw exception
string.

## 8. Context construction

The backend durable conversation is authoritative for context. 5.21 introduced
`ContextConstructionService` as the sole owner of *which* durable messages a run
sends, with `build_for_source` and `build_for_run`, producing `RunContext` and
`ContextMessage`. `execution_context_messages(context, prompt)` is the single
place that decides prompt-versus-context.

Eligibility rules:

```text
current source user message is included exactly once
current assistant placeholder is excluded
only eligible completed historical assistant responses are included
failed / cancelled / pending / streaming responses are excluded
cross-conversation content is excluded
regenerate variants are handled through durable relationships, not by guessing
```

The frontend transcript is **not** authoritative model context. The UI is a
projection; if the UI and the server disagree, the server is right.

Failures raise `ContextConstructionError` (with `ContextRunNotFoundError`,
`ContextConversationNotFoundError`, `ContextSourceMessageNotFoundError`,
`ContextSourceMessageRoleError`) and surface as `500 context_construction_failed`.

## 9. Context window management

Trimming is deterministic and model-aware (5.22). `ContextWindowManager` and
`TokenEstimator` window eligible context against `ModelInfo.context_limit`,
read at `NativeAgentAdapter._context_limit`.

```text
unknown context limit  → no artificial trim
reserve output budget  → input_budget_for = limit − reserve
DEFAULT_OUTPUT_RESERVE_TOKENS   = 1024
MAX_OUTPUT_RESERVE_FRACTION     = 0.25
CHARS_PER_TOKEN                = 4
NON_ASCII_CHAR_COST             = 3
MESSAGE_FRAMING_TOKENS          = 4
```

The retained set is the longest suffix of *whole turns*. The current request
and its preamble are mandatory and are never trimmed. If the current request
itself cannot fit, AVA fails **before** calling the provider, with
`ContextWindowExceededError` / "Request exceeds the selected model's context
window", rather than sending an over-budget request and letting the provider
reject it.

The native and OpenHands runtimes use the same bounded context semantics; they
only translate. There is no vendor tokenizer and no summarization — the
estimator is explicitly a character-cost approximation, and an unknown limit
means "do not invent a trim".

## 10. Run lifecycle

`RunStatus` is the authoritative run lifecycle. Message status is a
*projection* of it. 5.23 made `RunLifecycleService` the only durable status
writer, with the transition table, `ACTIVE_RUN_STATUSES` /
`TERMINAL_RUN_STATUSES`, `RunStatus.is_active` / `is_terminal`, and a guarded
`compare_and_set_status` beside the blind `update_status`, raising
`InvalidRunTransitionError`.

Canonical run states:

```text
pending
running
waiting_for_approval
completed
failed
cancelled
```

Assistant projection states:

```text
pending
streaming
complete
failed
cancelled
```

User messages do not have run-lifecycle status. `assistant_status_for_run`
(5.20) computes the projection at read time, which is why the projection cannot
drift from the authority.

Ordering discipline: the status write happens **before** the event append. A
crash can therefore leave a *missing* event, but never a contradicting one.

## 11. Cancellation

Cancellation is durable *intent*, not a synchronous kill (5.24).
`RunRecord.cancellation_requested_at` (exposed as `cancellation_requested`) is
the only stored intent, written through the guarded
`RunRepository.request_cancellation`, in migration `v0009_run_cancellation_request`,
and signalled by the nonterminal `run_cancel_requested` event. A rejected
request raises `CancellationRequestError` → HTTP `503
cancellation_request_failed`.

Only a *terminal* transition frees the conversation slot; a cancellation request
is not an outcome. The OpenHands runtime cannot synchronously stop its own SDK
worker thread, so a cancel against a running OpenHands run honestly reports
that it is still running rather than pretending otherwise.

## 12. Streaming and event replay

### Transport (5.25)

```text
POST /runs
    → 202 Accepted
    → durable run identity returned before execution begins

GET  /runs/{run_id}
    → authoritative run snapshot

GET  /runs/{run_id}/stream
    → SSE observer transport

GET  /runs/{run_id}/events?after_sequence=N
    → persisted replay
```

The SSE envelope carries `run_id`, `event_id`, `sequence`, `event_type`,
`timestamp`, `payload`, and `contract_version`, served as `text/event-stream`
with `Cache-Control: no-cache` and `Connection: keep-alive`, polling at 100 ms.
The client side is `streamRun` / `RunStreamEvent` / `AbortSignal`.

**Streaming transport is observational.** Disconnecting a stream does not cancel
a run. Cancellation is a separate command (`POST /runs/{run_id}/cancel`). A
fresh subscription replays everything available, i.e. at-least-once delivery.

### Event authority (5.26)

```text
RunEvent.sequence
```

is the canonical per-run ordering and cursor:

```text
first sequence = 1
monotonic
contiguous for successful appends
unique within run           (UNIQUE(run_id, seq))
event_id provides stable identity and de-duplication
```

`MAX(seq) + 1` is taken inside `BEGIN IMMEDIATE`, so allocation is safe against
a second process. The port surface is `append`, `get_events`, `get_latest`,
`list_after_sequence`. The `after_sequence` cursor is **exclusive**. A negative
cursor is `422`; an unknown run is `404 run_not_found`.

Replay returns persisted facts only. It does not synthesize missing history and
does not reconstruct state that was never written.

## 13. Partial assistant responses

`Message.content` is the durable authority for assistant content (5.27).
`AssistantResponseService` is the single write path, and it writes
`MessageRepository.update_content` plus exactly one `message_content` event per
snapshot. `message_started` is persisted after `run_started` with
`{"message_id", "role": "assistant"}`; `message_content` carries the full
snapshot `{"message_id", "content"}`.

Streaming is supported at the port level
(`AgentPort.start_run_streaming` / `AgentRuntimePort.execute_streaming` with
`on_content`), and partial text is persisted *before* its corresponding change
event.

That ordering has a consequence worth stating plainly: **across a crash gap the
durable message may be newer than the durable event log.** Replay is not
rebuilding the durable message from scratch. The message is the authority; the
event log is an ordered record of changes to it.

## 14. Reconnect / resume

`runStreamResume` (5.28) owns reconnect: an in-memory exclusive
`last_processed_sequence`, an event-ID map for de-duplication, and bounded
retries (immediate, 50 ms, 150 ms). Resume uses
`GET /runs/{run_id}/stream?after_sequence=N`; an ahead-of-history cursor is
rejected with `409 invalid_resume_cursor`, an unknown run is `404 run_not_found`,
and a negative cursor is `422`.

The cursor is same-session frontend state only. It is never persisted and is
never treated as an authority.

## 15. Refresh recovery

On refresh, the frontend reconstructs its observer from durable server state
(5.29). `AgentRunProvider.recoverRunForConversation` follows:

```text
Conversation
→ visible Assistant Message
→ source_run_id
→ Run
→ assistant_message_id
```

bootstrapping with an `after_sequence=0` replay and a fresh `runEpoch`.
Recoverable active states are `pending`, `running`, and `waiting_for_approval`.

No `localStorage`, `sessionStorage`, or `IndexedDB` is used as run-recovery
authority — verified in Phase 5.36 acceptance and re-verified by the frontend
architecture guards.

## 16. Backend restart recovery

The current policy is explicit rather than aspirational (5.30). **Current
in-process runtimes cannot survive backend process death.** Therefore
`RunRecoveryService.recover_stranded_runs()` runs in the FastAPI lifespan before
readiness, and every active run discovered at cold start is settled to:

```text
status    = failed
error_code = execution_interrupted
```

with the payload
`{"code": "execution_interrupted", "message": "The backend restarted before this run completed."}`.
The summary is exposed as `RunRecoverySummary(active_found, settled_failed)` on
`app.state.run_recovery_summary`. Settlement goes through the lifecycle service;
the recovery service never calls an agent to "continue" anything.

Preserved across restart:

```text
partial assistant content
run identity
message identity
source relationships
cancellation intent   (preserved, never re-sent)
event ordering
```

This is settled failure, **not** resumed execution, and the documentation does
not describe it as such. Externally survivable runtimes are a deliberate
extension point, not currently implemented. Single backend process/worker is
assumed; a multi-worker deployment would incorrectly fail runs another worker is
executing.

## 17. Retry / regenerate

```text
retry:
  failed or cancelled run  → new run

regenerate:
  completed run           → new run
```

Both reuse `POST /runs` with `retry_of_run_id`, and `RunService` re-anchors the
request to the durable source user message rather than trusting the client to
have said the right thing. `execution_interrupted` is ordinary retryable failed
history, not a special case.

Every attempt gets its own:

```text
new run ID
new assistant message
new event sequence
new frontend epoch (runEpoch)
independent cancellation state
```

The previous attempts remain durable and immutable. Retry and regenerate never
modify the run they descend from. There is deliberately no retry endpoint, no
parent-run column, and no branch tree: the durable relationship is the durable
user message.

## 18. Stale event protection

Two layers, both deliberate (5.32).

**Run level:**

```text
runEpoch
run identity
assistant-message identity
event-ID de-duplication
monotonic sequence checks
serialized reconnect
snapshot reconciliation
```

**Conversation level:** `ConversationProvider`'s `loadGenerationRef`, which
closes the A→B→A / same-conversation asynchronous loading race.

The full ownership chain is:

```text
conversation load generation
        ↓
runEpoch
        ↓
run / message ID
        ↓
event sequence / event ID
```

Stale work is *ignored*, not an error. Crucially, there is no
timestamp heuristic, no array-position heuristic, and no schema-based freshness
field: freshness is determined by identity and ordering only, because those are
the things the server actually guarantees.

## 19. Conversation concurrency

The final policy (5.33):

```text
at most one active run per conversation
different conversations may run independently
```

**The backend enforces this.** It is checked in `RunService.prepare_run` and
again in the repository `create` under `BEGIN IMMEDIATE`. The losing request
gets `409 conversation_run_active` before any row, event, context build, or
execution occurs. Frontend correctness is not relied upon as the concurrency
authority.

There are no distributed leases, queues, or auto-cancellation, and a legacy
conversation that already has multiple active runs is conservatively treated as
busy.

## 20. Failure and error UX

AVA owns normalized failure presentation. 5.34 established three error scopes —
durable run failure, transport, and action — with all copy routed through
`errorPresentation.ts`. A `run_failed` event projects an AVA-owned explanation
onto the owning assistant message. `execution_interrupted` stays generic and
retryable; `conversation_run_active` renders a busy notice with *no* failed
bubble, because nothing failed. The Retry control is a `role="alert"` alert so
assistive technology announces it.

Important durable codes:

```text
execution_interrupted
conversation_run_active
configuration_missing
configuration_invalid
provider_connection_unavailable
model_unavailable
runtime_unavailable
credential_unavailable
```

Raw backend or provider exception strings are never displayed as user-facing
error copy. Unmapped execution-configuration failures stay `agent_failed`
rather than being given an invented code.

## 21. Configuration remediation UX

A configuration failure can offer `Open Settings`, targeting one of four
sections depending on the durable failure code (5.35):

```text
Providers
Models
Runtimes
Defaults
```

The mapping is `settingsSectionForFailure` → `SettingsSectionId` →
`SettingsWorkspace initialSection`, and it is carried to the client through
`MessageResponse.error_code` ← the persisted `run_failed` payload's
`error_code`.

The UI does **not** automatically retry, and does **not** automatically open an
edit modal. It navigates the user to the right place and stops. `SettingsSectionId`
ownership, ownership of navigation, and the `@ava/agent-ui` ↔
`@ava/settings-core` boundary are covered in §22.

## 22. Settings architecture

The main Settings surface is exactly four sections:

```text
Providers
Models
Runtimes
Defaults
```

Add / Edit / View flows use modal dialogs. Configuration forms are not
scattered through the chat UI, and configuration is not edited by a run
failing.

Boundaries:

```text
SettingsSectionId is owned by @ava/ui-core
@ava/settings-core re-exports it for compatibility
@ava/agent-ui does NOT depend on @ava/settings-core implementation
@ava/workspace owns navigation
```

The Settings surface reaches the backend only through `@ava/api-client` and
exposes exactly seven writes, with no delete or remove — retirement is done by
disabling, so a record stays findable and re-enableable. These boundaries are
enforced by 15 dedicated architecture-guard tests.

## 23. Web and Desktop architecture

Both shells continue to consume the shared implementation packages.
`@ava/desktop` is a thin Tauri shell over `@ava/workspace` → `@ava/agent-ui`,
configurable through `VITE_API_BASE_URL` with a `http://localhost:8000` fallback
and dev port 5174. No Desktop-specific conversation persistence, run
persistence, streaming implementation, configuration store, or credential
store was introduced. Web and Desktop consume the same backend contracts and the
same durable state.

## 24. Concurrency hardening

Phase 5.39 found and fixed a **severe** defect that focused suites had missed.
The issue was not missing locks in the abstract — it was that
`SqliteDatabase` used a single shared connection with
`check_same_thread=False`, and only *transaction* paths were locked. Reads
raced freely against other use of the same connection.

The fix holds the existing reentrant lock (`_transaction_lock`) across the
entire body of `SqliteDatabase.connect()`, so connection use is serialized.

This is **not** distributed concurrency support. Current ownership remains
single-process / single-worker. Contention is serialized, not eliminated. Also
still true after 5.39: `SELECT MAX(seq) + 1` is O(n) and unmeasured, the crash
gap is unfixed, and fairness/starvation is untested.

5.39 also added 96 backend race tests across three new files
(`test_run_lifecycle_races.py`, `test_run_event_concurrency.py`,
`test_run_creation_races.py`) covering 33 race classes, plus frontend
`runStreamResumeRaces.test.ts` and conversation-selection race coverage.
`ContestedReads` exists specifically to make lost races reachable rather than
theoretical.

## 25. Restart and durability evidence

5.38 certifies restart across two `create_app` instances over one SQLite file
(`AVA_PERSISTENCE=relational`, `AVA_ATTACHMENT_STORAGE=memory`), asserting
`active_found=1` / `settled_failed=1` then `0`/`0`, that `conn-local`,
`model-local`, and `runtime-local` defaults survive, and that only the
`env:LOCAL_API_KEY` *reference* persists.

That step also caught and corrected a defect: the restart interruption payload
was using the wrong key, and now carries `error_code`.

Its stated limits are kept in view: the cold boundary is a new service graph
rather than a spawned OS process, the crash gap was reproduced rather than
induced, retry was verified against the mock agent, and `pending` /
`waiting_for_approval` share one parametrized fixture.

## 26. Final validation

Authoritative source: [AVA_Phase_5_40_Full_Validation.md](AVA_Phase_5_40_Full_Validation.md).

```text
Backend
2153 collected
2151 passed
0 failed
2 skipped
4 warnings

Frontend
69 test files
685 passed
0 failed
4 skipped
689 collected

Backend architecture          124 passed
Frontend architecture guards   17 passed
Ruff                          PASS
mypy                          PASS — 181 backend files
Frontend lint/typecheck       PASS — 10/10 packages
Python client                 10 passed, Ruff PASS, mypy PASS
Web build                     PASS — 199 modules
Desktop build                 PASS — 199 modules
./scripts/test_all.sh         PASS — exit 0
```

Phase 5.40 deliberately did *not* rerun suites to produce this table once per
layer; 5.40D's aggregate harness independently reproduced the 5.40A and 5.40B
counts, and all static results agreed with 5.40C.

## 27. The defect validation found

Full validation was worth running precisely because it found something focused
suites had missed. `RunService` imported `ExecutionConfigurationError` from
`ava.execution.persisted_execution`, which crossed the documented service
dependency direction. The codebase is explicit that the native agent *adapter*
is the seam permitted to depend on execution; the run service is not.

The fix moved the error's ownership to the contract both sides share:

```text
ExecutionConfigurationError now lives in ava.agents.contracts
ava.execution.persisted_execution re-exports the SAME class object
RunService imports from ava.agents.contracts
```

Behavior is unchanged, class identity is retained (both import paths resolve to
one object, so every existing `except` still matches), the architecture test was
not weakened, no allow-list entry was added, and no test was edited. This is
positive evidence that the architecture guards are effective rather than
decorative.

## 28. Architectural decisions

The decisions that shaped Phase 5, in the order they had to be made:

1. **Server authority, always.** Lifecycle, context eligibility, concurrency,
   and failure copy are decided by the backend. The frontend is a projection.
2. **Status before fact.** Write the durable status, then append the event. A
   crash may lose an event; it can never leave a contradiction.
3. **Intent is not outcome.** `cancellation_requested_at` is a request. Only a
   terminal transition ends a run.
4. **The message is the authority for content; the event log is a record of
   change.** This is why replay is not reconstruction.
5. **Concurrency rules live in SQL, not process memory.** CAS writes,
   `BEGIN IMMEDIATE` check-and-insert, and unique terminal-event sealing mean a
   second process cannot bypass them.
6. **Configure, then bootstrap.** Persisted settings are authoritative when
   configured; environment configuration is compatibility, not a silent
   fallback.
7. **Identity-based freshness.** `loadGenerationRef → runEpoch → run/message ID
   → sequence/event ID`. No timestamps, no array positions.
8. **The frontend is not the concurrency authority.** Enforced server-side,
   before any state is created.
9. **Failure copy is AVA-owned.** Durable codes, normalized presentation, and
   remediation — never a raw provider exception.
10. **Thin shells, shared implementation.** Web and Desktop differ only in
    transport and packaging.

## 29. Explicit non-goals

Phase 5 did **not** implement any of the following. Nothing in this document
should be read as claiming otherwise:

```text
enterprise authentication / authorization
RAG / vector knowledge platform
normalized general tool framework
plugin marketplace
distributed run ownership
Redis leases
leader election
multi-worker execution ownership
voice UI
Databricks persistence
SQL Server production adapter
agent-driven document operations
advanced engineering workflows
adaptive learned routing
model training / evolution systems
```

In the canonical roadmap these remain later phases (Phase 6 Complete Document
Platform, Phase 8 Review and Approval, Phase 9 AVA Tool Framework, Phase 10
Knowledge/RAG, Phase 12 Authentication/Authorization, Phase 13
Python/Databricks, and Phase 23 Advanced Model Evolution Research).

Phase 5 also explicitly did not introduce a `cancelling` state, a
retry/regenerate endpoint or branch tree, distributed leases or a job queue,
summarization, a vendor tokenizer, a global active-run query, or a
`Last-Event-ID` SSE mechanism.

## 30. Known non-blocking issues

### 30.1 Crash-gap semantics (intentional limitation, not a hidden defect)

The state write and the event write are not currently one cross-repository
transaction. A crash can therefore leave durable state **newer** than durable
event history, in areas such as lifecycle/event or cancellation/event
transitions. Recovery does not invent the missing events.

This is a known architectural limitation of the current design and is
recorded as such. No unit-of-work system was introduced during Phase 5.

### 30.2 Single-owner execution

Runs are owned by a single backend process/worker. A multi-worker deployment
would incorrectly fail runs another worker is actively executing. Future
externally survivable runtimes are an extension point.

### 30.3 Accepted warnings

```text
4 × OpenHands/LiteLLM DeprecationWarning  (third-party, pre-existing, unsuppressed)
1 × Vite chunk-size advisory             (pre-existing, unchanged, unsuppressed)
```

No warning category was suppressed for a clean report.

### 30.4 Accepted skips

```text
2 × opt-in local-model backend qualification tests   (AVA_RUN_LOCAL_MODEL_QUALIFICATION=1)
4 × opt-in live-backend frontend integration tests  (AVA_LIVE_BACKEND_URL)
```

Both are deliberate live/opt-in gates, not broken tests. No skip drift remains
unexplained.

### 30.5 Repository hygiene observations (not Phase 5 blockers)

```text
backend/ava.sqlite3 is tracked in git
the Vite shared bundle exceeds the advisory threshold
```

A committed local SQLite database is a hygiene concern and the single large
bundle is a performance observation. Neither is a validation failure. Neither
was changed during Phase 5, and Phase 5.41 did not add `manualChunks` or untrack
the database.

## 31. Phase 5 exit criteria

```text
✓ Persisted provider/model/runtime/default configuration
✓ Credential-reference separation
✓ Durable conversation/run/message relationships
✓ Server-authoritative context construction
✓ Context-window management
✓ Normalized durable run lifecycle
✓ Durable cancellation intent
✓ Persisted ordered event replay
✓ Streaming transport
✓ Partial assistant persistence
✓ Reconnect/resume
✓ Refresh recovery
✓ Explicit backend restart recovery semantics
✓ Retry/regenerate across durable runs
✓ Stale event protection
✓ One-active-run-per-conversation enforcement
✓ Normalized failure UX
✓ Configuration-remediation UX
✓ Web acceptance
✓ Desktop acceptance
✓ Restart/durability integration coverage
✓ Race/concurrency hardening
✓ Full backend/frontend/static/build validation
✓ Canonical aggregate validation harness green
```

**PHASE 5 STATUS: COMPLETE / PASS**

## 32. Next phase

Per the canonical plan, the next phase is:

```text
Phase 6 — Complete Document Platform
```

Phase 6 begins only on explicit instruction. No Phase 6 implementation,
planning, tool framework, approval entity, or tool schema was started during
Phase 5 or during this closure.

### Subsequent Phase 5 extensions through Project Files

The Phase 5 extension sequence includes Project Files persistence/API/client (5.76) and its validation/stabilization record (5.76A). Phase 5.76 is certified under the documented external-blocker policy: focused and workspace checks plus a disposable SQLite/ASGI lifecycle passed, while canonical TestClient and loopback-server checks were blocked by the sandbox. See [AVA_Phase_5_76A_Project_Files_Validation_Stabilization.md](AVA_Phase_5_76A_Project_Files_Validation_Stabilization.md) for exact evidence and limits.

Phase 5.77 is complete: the existing Project workspace Files tab provides typed-client list/upload/download/delete UX with per-Project transient state, retry and failure handling, duplicate-filename-safe ID actions, and no attachment, execution-context, or RAG coupling. See [AVA_Phase_5_77_Project_Files_UI.md](AVA_Phase_5_77_Project_Files_UI.md). Phase 5.78 defines the future provider-neutral Knowledge/RAG boundary, source identity, explicit scope, provenance, and lifecycle invariants without implementing RAG behavior. See [AVA_Phase_5_78_Future_Knowledge_RAG_Boundary.md](AVA_Phase_5_78_Future_Knowledge_RAG_Boundary.md). Knowledge/RAG implementation remains unstarted.

Phase 5.79 implementation and Phase 5.79A validation are complete: the Chat sidebar uses dnd-kit for conversation-to-Folder and conversation-to-Ungrouped movement, retains accessible menu actions, and creates Folder-scoped conversations atomically without coupling Folder and Project membership. Automated validation passed; live-browser and canonical full-harness validation were independently blocked by this sandbox, as detailed in [AVA_Phase_5_79A_Folder_Drag_Drop_Validation.md](AVA_Phase_5_79A_Folder_Drag_Drop_Validation.md).

Phase 5.80 is complete: the Chat sidebar separates Active and Archived views, derives both from canonical conversation state, excludes archived conversations from active Folder/Ungrouped and Project lists, and avoids duplicate Folder+Project rows. Existing archive/restore writes preserve selection, pin, Folder/Project relationships, transcript, and run observation; search continues to include archived matches with an Archived marker. See [AVA_Phase_5_80_Archive_Views_Sidebar_Cleanup.md](AVA_Phase_5_80_Archive_Views_Sidebar_Cleanup.md) for the chosen visibility behavior and validation record.

Phase 5.81 cross-feature deletion/cleanup integration is complete. Conversation, Folder, Project, Project File, and CORE prompt ownership boundaries are documented and exercised across memory and SQLite persistence, including relationship survival, archived-conversation hard delete, exact Project File content refs, assignment cleanup, restart durability, and SQLite integrity. Frontend deletion tombstones prevent delayed Conversation/Folder/Project list responses from resurrecting resources; search and run-event late-response regressions are covered. See [AVA_Phase_5_81_Cross_Feature_Deletion_Cleanup_Integration.md](AVA_Phase_5_81_Cross_Feature_Deletion_Cleanup_Integration.md).

Phase 5.82 restart/durability certification is complete. A disposable SQLite database and configured local content roots were reopened through fresh FastAPI compositions; durable graph snapshots, CORE/execution projections, Project File bytes, attachment cleanup, stranded-run recovery, deletion absence, and SQLite integrity were verified. The canonical harness's TestClient stall and unavailable live browser were independently reproduced/documented; no production defect or migration was introduced. See [AVA_Phase_5_82_Restart_Durability_Certification.md](AVA_Phase_5_82_Restart_Durability_Certification.md).

Phase 5.83 migration certification covers the real v1–v18 registry through disposable historical SQLite baselines, including legacy conversation graph preservation, nullable/INHERIT defaults, Project and Folder links, Project File metadata separation, integrity checks, real repository composition, and idempotent current-schema startup. No production migration or schema change was needed. See [AVA_Phase_5_83_Backward_Compatibility_Migration_Certification.md](AVA_Phase_5_83_Backward_Compatibility_Migration_Certification.md).

Phase 5.83A is complete. A controlled backend outage reproduced settled Conversation, Folder, and Document failures; explicit retry, empty-versus-error states, and generation guards now recover without a page reload. StrictMode/out-of-order tests, a live outage/recovery, repeated backend restarts, frontend and full-stack restarts, direct Project reload, rapid navigation, and HMR passed. Web Vite now refuses port fallback to Desktop's 5174. No backend or database change was needed. The canonical all-backend harness still stalls at the known sandbox TestClient/loopback boundary; focused migration/durability certification passed. See [AVA_Phase_5_83A_Shared_Loading_Regression_Recovery.md](AVA_Phase_5_83A_Shared_Loading_Regression_Recovery.md).

Phase 5.84 and Phase 5.84A are **complete**. Web and Desktop shared-backend acceptance passed; native Tauri acceptance was closed using the actual X11 window, Chat/Projects/Documents/Settings workflows, data mutation, backend outage/retry, repeated restarts, and the built release executable. The Tauri all-target build declares the existing 512×512 app icon and produces DEB, RPM, and AppImage bundles. See [AVA_Phase_5_84_Web_Desktop_Acceptance_Pass.md](AVA_Phase_5_84_Web_Desktop_Acceptance_Pass.md) and [AVA_Phase_5_84A_Native_Tauri_Acceptance_Closure.md](AVA_Phase_5_84A_Native_Tauri_Acceptance_Closure.md).

Phase 5.85 final canonical validation is **complete**. The full aggregate harness passed after outdated v17 schema expectations were reconciled with the current v18 registry; the final run covered backend, frontend, TypeScript, and Python client checks. Web live smoke, Web/Desktop builds, the all-target native Tauri build, live database integrity, migration history, and the Phase 5 architecture boundaries were rechecked. Native pointer drag and Project File download remain explicitly accepted evidence gaps from 5.84A; no BLOCKER or MAJOR defect remains. Phase 5 is **READY FOR PHASE 6**. The complete inventory, exact results, accepted limitations, deferred scope, and Phase 6 stable-entry boundary are in [AVA_Phase_5_85_Final_Canonical_Validation.md](AVA_Phase_5_85_Final_Canonical_Validation.md).

### Final Phase 5 architecture and capability summary

The finished Phase 5 extension keeps Conversation Folders organizational and
Projects contextual: a Conversation may independently belong to both. Projects
carry separately persisted instructions, per-axis execution defaults, and
Project Files. CORE prompt definitions remain separate from scoped assignments;
the resolver composes them beneath AVA's immutable root prompt, with Project
instructions injected afterward. Runtime and model selection resolve
independently through explicit run choice, Project preference, application
preference, then bootstrap fallback.

Conversation Attachments and Project Files retain separate ownership and
storage lifecycles. The provider-neutral Knowledge/RAG boundary remains
architecture-only. Archive is reversible; hard delete follows the certified
ownership cleanup matrix. SQLite v18 is the current durable schema, and the
backend remains authoritative across restart. Shared Web/Desktop packages
project the same API state and recovery patterns. dnd-kit is the shared
drag/drop infrastructure for Conversation/Folder organization.

By capability, Phase 5 delivers durable Conversations and run recovery;
searchable, sortable, pinnable, archivable, deletable Chat organization;
Folders; Projects and Project conversation/instruction context; CORE prompt
management/resolution/injection; application and Project execution selection;
Project Files; retryable shared loading; and Web, Desktop, and native Tauri
acceptance. It does not deliver Knowledge/RAG execution or Phase 6's complete
Document Platform.

Deferred beyond Phase 5 are Knowledge/RAG ingestion, embeddings, vector storage
and retrieval; the complete Document Platform; nested Folders; manual
conversation ordering; broader future drag/drop layouts and resource types; and
distributed/multi-worker run ownership. Phase 6 may assume the shared
Web/Desktop shell, conversation foundation, backend persistence, Projects and
Folders, prompt resolution, execution selection, Project Files, schema v18, and
loading/recovery behavior are stable. Phase 6 has not started.

---

## Related documentation

| Document | Role |
| --- | --- |
| [AVA_Phase_5_40_Full_Validation.md](AVA_Phase_5_40_Full_Validation.md) | Authoritative Phase 5.40 validation record |
| [AVA_Phase_5_81_Cross_Feature_Deletion_Cleanup_Integration.md](AVA_Phase_5_81_Cross_Feature_Deletion_Cleanup_Integration.md) | Cross-feature deletion ownership and cleanup certification |
| [AVA_Phase_5_82_Restart_Durability_Certification.md](AVA_Phase_5_82_Restart_Durability_Certification.md) | Fresh application restart, durable state, content stores, and recovery certification |
| [AVA_Phase_5_83_Backward_Compatibility_Migration_Certification.md](AVA_Phase_5_83_Backward_Compatibility_Migration_Certification.md) | Historical SQLite upgrade matrix, ownership boundaries, migration inventory, and compatibility evidence |
| [AVA_Phase_5_83A_Shared_Loading_Regression_Recovery.md](AVA_Phase_5_83A_Shared_Loading_Regression_Recovery.md) | Forced shared-loading failure, retry recovery, StrictMode/race coverage, restart matrix, and live certification |
| [AVA_Phase_5_84_Web_Desktop_Acceptance_Pass.md](AVA_Phase_5_84_Web_Desktop_Acceptance_Pass.md) | Complete Web/Desktop acceptance record and shared-backend validation |
| [AVA_Phase_5_84A_Native_Tauri_Acceptance_Closure.md](AVA_Phase_5_84A_Native_Tauri_Acceptance_Closure.md) | Native window, interaction, outage/retry, restart, release artifact, cleanup, and final acceptance evidence |
| [AVA_Phase_5_85_Final_Canonical_Validation.md](AVA_Phase_5_85_Final_Canonical_Validation.md) | Final phase inventory, architecture/migration audit, full-stack validation, limitations, and Phase 6 stable-entry boundary |
| `AVA_Phase_5_40A/B/C/D_*_Notes.md` | Per-layer working notes behind the validation record |
| `AVA_Phase_5_16_Execution_Configuration_Resolver.md` … `AVA_Phase_5_39_Race_Concurrency_Hardening.md` | Per-step implementation records (5.16–5.39) |
| [AVA_Phase_5_Reopened_P1_Remediation.md](AVA_Phase_5_Reopened_P1_Remediation.md) | Post-closure P1 defect remediation (Defects A–I) |
| [AVA_Phase_5_42_Conversation_Organization_Metadata_Domain.md](AVA_Phase_5_42_Conversation_Organization_Metadata_Domain.md) | Conversation organization metadata domain (pin/archive/folder, read-only) |
| [AVA_Phase_5_43_Conversation_Organization_Metadata_Persistence.md](AVA_Phase_5_43_Conversation_Organization_Metadata_Persistence.md) | Durable conversation organization metadata, migration, and restart preservation |
| [AVA_Phase_5_44_Conversation_Pin_Unpin_Write_Path.md](AVA_Phase_5_44_Conversation_Pin_Unpin_Write_Path.md) | Narrow pin/unpin write path, preservation, and restart durability |
| [AVA_Phase_5_45_Conversation_Archive_Restore_Write_Path.md](AVA_Phase_5_45_Conversation_Archive_Restore_Write_Path.md) | Narrow archive/restore write path, child preservation, and restart durability |
| [AVA_Phase_5_46_Conversation_Hard_Delete_Service.md](AVA_Phase_5_46_Conversation_Hard_Delete_Service.md) | Internal conversation hard-delete service and owned-record cleanup |
| [AVA_Phase_5_47_Conversation_Delete_API.md](AVA_Phase_5_47_Conversation_Delete_API.md) | Public conversation DELETE API and typed client method |
| [AVA_Phase_5_48_Conversation_Delete_UI.md](AVA_Phase_5_48_Conversation_Delete_UI.md) | Confirmed permanent-delete UI, local reconciliation, and observer cleanup |
| [AVA_Phase_5_49_Conversation_Rename_UX_Audit.md](AVA_Phase_5_49_Conversation_Rename_UX_Audit.md) | Rename flow audit, stale-404 reconciliation, and duplicate-submit guard |
| [AVA_Phase_5_50_Conversation_Search_Backend_Client.md](AVA_Phase_5_50_Conversation_Search_Backend_Client.md) | Title-only conversation list search, repository parity, and typed client query encoding |
| [AVA_Phase_5_51_Conversation_Search_UI.md](AVA_Phase_5_51_Conversation_Search_UI.md) | Debounced sidebar search backed by the conversation title-search API |
| [AVA_Phase_5_52_Conversation_Sorting.md](AVA_Phase_5_52_Conversation_Sorting.md) | Canonical pin/activity/creation/identity order across repositories, API, search, and sidebar |
| [AVA_Phase_5_53_Conversation_Folder_Domain.md](AVA_Phase_5_53_Conversation_Folder_Domain.md) | Flat organizational folder record and public read/write contracts; no persistence or routes |
| [AVA_Phase_5_54_Conversation_Folder_Persistence_CRUD.md](AVA_Phase_5_54_Conversation_Folder_Persistence_CRUD.md) | Durable folder storage, CRUD/assignment API, transactional unassignment, and typed client support |
| [AVA_Phase_5_55_Conversation_Folder_Sidebar_UX.md](AVA_Phase_5_55_Conversation_Folder_Sidebar_UX.md) | Sidebar folder sections, Ungrouped conversations, CRUD actions, move/unassign, and selection/run preservation |
| [AVA_Phase_5_56_Project_Domain.md](AVA_Phase_5_56_Project_Domain.md) | Independent Project domain record and public contracts; no persistence, routes, or UI |
| [AVA_Phase_5_57_Project_Persistence.md](AVA_Phase_5_57_Project_Persistence.md) | Project schema migration 0012, memory/SQLite repositories, composition, and restart durability |
| [AVA_Phase_5_58_Project_CRUD_Service_API.md](AVA_Phase_5_58_Project_CRUD_Service_API.md) | Project lifecycle service, CRUD/archive API, typed client, and standalone metadata deletion |
| [AVA_Phase_5_59_Project_List_Page_Navigation.md](AVA_Phase_5_59_Project_List_Page_Navigation.md) | Projects navigation, backend-ordered list, metadata actions, and placeholder Project route |
| [AVA_Phase_5_60_Project_Detail_Workspace_Shell.md](AVA_Phase_5_60_Project_Detail_Workspace_Shell.md) | Project detail workspace sections, overview metadata, route loading, and deferred capability boundaries |
| [AVA_Phase_5_61_Conversation_Project_Relationship.md](AVA_Phase_5_61_Conversation_Project_Relationship.md) | Nullable durable Conversation-to-Project membership, assignment semantics, and Project-delete cleanup |
| [AVA_Phase_5_72_Project_Execution_Defaults.md](AVA_Phase_5_72_Project_Execution_Defaults.md) | Independent persisted Project runtime/model preferences; no execution precedence or UI |
| [AVA_Phase_5_73_Project_Execution_Default_Resolution.md](AVA_Phase_5_73_Project_Execution_Default_Resolution.md) | Per-axis explicit → Project → application → bootstrap selection, canonical conversation membership, and stale Project preference fallback |
| [AVA_Phase_5_74_Project_Execution_Defaults_UI.md](AVA_Phase_5_74_Project_Execution_Defaults_UI.md) | Project Settings runtime/model default controls using the existing APIs and per-axis precedence |
| [AVA_Phase_5_75_Project_Files_Domain.md](AVA_Phase_5_75_Project_Files_Domain.md) | Project file ownership, metadata/content boundary, domain port, and storage-neutral public contracts |
| [AVA_Phase_5_76_Project_Files_Persistence_API_Client.md](AVA_Phase_5_76_Project_Files_Persistence_API_Client.md) | Migration 0018, memory/SQLite metadata, local opaque-reference content storage, Project-scoped API, typed client, rollback, and restart behavior |
| [AVA_Phase_5_76A_Project_Files_Validation_Stabilization.md](AVA_Phase_5_76A_Project_Files_Validation_Stabilization.md) | Formatting audit, focused and frontend validation, disposable ASGI/SQLite lifecycle, and canonical sandbox-blocker evidence |
| [AVA_Phase_5_77_Project_Files_UI.md](AVA_Phase_5_77_Project_Files_UI.md) | Project workspace Files tab lifecycle UI, isolation/race behavior, ID-safe duplicate handling, tests, and no-execution/RAG boundary |
| [AVA_Phase_5_78_Future_Knowledge_RAG_Boundary.md](AVA_Phase_5_78_Future_Knowledge_RAG_Boundary.md) | Provider-neutral Knowledge/RAG domain and ports, Project File source identity, scope/provenance and future lifecycle invariants; no RAG implementation |
| [AVA_Phase_5_79_Folder_Drag_Drop_New_Chat.md](AVA_Phase_5_79_Folder_Drag_Drop_New_Chat.md) | dnd-kit conversation-to-Folder/Ungrouped movement, Project/run/selection preservation, and atomic New Chat in Folder |
| [AVA_Phase_5_79A_Folder_Drag_Drop_Validation.md](AVA_Phase_5_79A_Folder_Drag_Drop_Validation.md) | Full Phase 5.79 validation, regression evidence, and sandbox blockers |
| [AVA_Phase_5_80_Archive_Views_Sidebar_Cleanup.md](AVA_Phase_5_80_Archive_Views_Sidebar_Cleanup.md) | Active/Archived sidebar views, organization filtering, restore preservation, and validation evidence |
| [AVA_Phase_5_62_Project_Conversation_API.md](AVA_Phase_5_62_Project_Conversation_API.md) | Project-scoped conversation list/create APIs, atomic membership creation, and typed client methods |
| [AVA_Phase_5_63_Project_Conversation_UI.md](AVA_Phase_5_63_Project_Conversation_UI.md) | Chat sidebar Projects, lazy Project conversation lists, scoped creation, Project assignment, and Project workspace Conversations UI |
| [AVA_Phase_5_64_Project_Instructions_Persistence.md](AVA_Phase_5_64_Project_Instructions_Persistence.md) | Audit and regression coverage for durable inert Project instructions, including exact text and omitted-versus-null updates |
| [AVA_Phase_5_65_Project_Instructions_UI.md](AVA_Phase_5_65_Project_Instructions_UI.md) | Project Instructions editor, draft/save/null semantics, canonical state reconciliation, and execution boundary |
| [AVA_Phase_5_66_CORE_System_Prompt_Domain.md](AVA_Phase_5_66_CORE_System_Prompt_Domain.md) | Reusable CORE prompt definition domain/contracts and future assignment/resolution/execution boundaries |
| [AVA_Phase_5_67_CORE_Prompt_Persistence_CRUD.md](AVA_Phase_5_67_CORE_Prompt_Persistence_CRUD.md) | CORE prompt migration, memory/SQLite repositories, CRUD and enable API, typed client, and inert execution boundary |
| [AVA_Phase_5_67A_Project_Conversation_Regression_Fix.md](AVA_Phase_5_67A_Project_Conversation_Regression_Fix.md) | Stale backend/schema-12 diagnosis, data-preserving migration, live Project list/create verification, and retry regression evidence |
| [AVA_Phase_5_68_Scoped_CORE_Prompt_Assignment.md](AVA_Phase_5_68_Scoped_CORE_Prompt_Assignment.md) | Explicit CORE prompt scoped enable/disable assignments, migration 0016, target cleanup, public API, typed client, and resolution/execution boundaries |
| [AVA_Phase_5_69_System_Prompt_Selection_UI.md](AVA_Phase_5_69_System_Prompt_Selection_UI.md) | System Prompts definition management and explicit Global/Project/Folder/Conversation/Runtime/Capability assignments; no resolution or execution integration |
| [AVA_Phase_5_70_Effective_Prompt_Resolver.md](AVA_Phase_5_70_Effective_Prompt_Resolver.md) | Deterministic read-only CORE prompt resolution, scoped precedence, provenance, and structured preview API; no execution injection |
| [AVA_Phase_5_71_Execution_Context_Injection.md](AVA_Phase_5_71_Execution_Context_Injection.md) | Application-owned root prompt, effective CORE prompt and Project instruction injection into normal/streaming execution, and provider/runtime translation |
| [AVA_Phase_5_71A_Execution_Validation_Stabilization.md](AVA_Phase_5_71A_Execution_Validation_Stabilization.md) | Attachment restart-recovery stall isolation, hard-delete composition boundary repair, schema-16 live execution checks, and complete canonical certification |
| `AVA_Phase_5_18_Production_Conversation_Architecture_Audit.md` | The pre-fix gap audit |
| `AVA_Phase_5_30_Backend_Restart_Recovery_Semantics.md` | Explicit restart policy |
| `AVA_Phase_5_36_Web_Acceptance.md`, `AVA_Phase_5_37_Desktop_Acceptance.md` | Shell acceptance |
| `AVA_Phase_5_38_Restart_Durability_Integration_Test.md` | Restart/durability evidence |
| [AVA_CANONICAL_DEVELOPMENT_PLAN_CURRENT_TO_COMPLETION.md](AVA_CANONICAL_DEVELOPMENT_PLAN_CURRENT_TO_COMPLETION.md) | Forward roadmap |
| `AVA_Phase_4_Implementation_Log.md` | Phase 4 evidence (preserved) |
