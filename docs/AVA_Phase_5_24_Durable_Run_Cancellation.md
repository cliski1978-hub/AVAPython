# AVA Phase 5.24 — Durable Run Cancellation

## Audit before completing the partial implementation

The shared frontend `cancelActiveRun` sets a local stopping indicator, calls
`POST /runs/{run_id}/cancel` through the API client, then reads the event snapshot.
The route delegates to RunService, which calls AgentPort.cancel_run. NativeAgentAdapter
forwards to its selected runtime using an in-memory execution map and remembers
terminal results in memory. NativeRuntime cancels an asyncio provider task.
MockAgentAdapter removes an active id. OpenHands revokes its tool context, but
its synchronous SDK worker running through asyncio.to_thread cannot be stopped
by that flag; execution checks the flag when control returns.

Before 5.24, no request intent was persisted. Unknown runs returned a cancelled
no-op; terminal runs returned their recorded outcome. Runtime acknowledgements
were passed to RunLifecycleService, whose CAS allowed only one terminal outcome.
A backend crash between requesting runtime cancellation and writing the terminal
state lost the request. Runtime exceptions had no normalized cancellation-specific
response. In-memory handles disappeared on restart. Adapters incorrectly treated
missing handles as evidence of cancellation; OpenHands also acknowledged a stop
before its worker returned.

The partial implementation already supplied a nullable request timestamp, guarded
repository writes, migration 9, and a request event. Remaining work found during
this audit: missing-handle semantics, truthful OpenHands acknowledgement, fresh
status reads after runtime errors/nonterminal replies, normalized persistence
failures, shared contracts, focused tests, and validation.

## Model, migration, and persistence

`RunRecord.cancellation_requested_at: datetime | None` is the only stored intent.
It is AVA-owned and associated with the existing run identity. There is no new
RunStatus, mutable requested boolean, user identity, or command journal. The
Python convenience property `cancellation_requested` derives from the timestamp;
the wire contract exposes only the nullable timestamp.

Additive migration `v0009_run_cancellation_request` adds a nullable TEXT timestamp
and a partial lookup index. Existing rows remain NULL, with all prior state and
relationships preserved. Serialization round-trips aware UTC timestamps.

`RunRepository.request_cancellation(run_id, requested_at=...)` is a guarded write:
only active runs with a NULL timestamp can change. SQLite checks both conditions
in one UPDATE under its normal transaction. RunStore implements the same guard
synchronously with no await, following its existing single-event-loop convention.
A rejected write returns None; the lifecycle re-reads to distinguish duplicates,
terminal races, and unknown identities. Other record mutations retain intent.
The first timestamp remains stable across repeated clicks and later outcomes.

## Ordering and state behavior

1. Read the run; preserve the existing unknown-run no-op contract.
2. RunLifecycleService persists cancellation intent atomically if still active.
3. Append the optional cancellation-request observation.
4. Attempt cancellation, then record a known outcome through RunLifecycleService.

| State or condition | Result |
| --- | --- |
| Unknown run | HTTP 200 cancelled no-op, NULL intent, no created run; GET still 404. |
| Already terminal | Return recorded state and existing timestamp; never add a new request. |
| Pending | Persist intent, settle cancelled locally without invoking an agent. |
| Waiting for approval | Same as pending; current architecture has no executing approval work or production writer for this state. |
| Running with a live handle | Persist intent, forward to AgentPort; settle only a reported terminal outcome. |
| Running with missing handle | Persist intent, remain running; no evidence of a stop is fabricated. |
| Runtime cancellation raises | Keep intent, return the freshly read authoritative status, normally running. No SDK exception reaches the response. |
| Runtime cancellation is still in flight | Keep intent and return freshly read status, normally running. |
| Intent persistence fails | Raise typed CancellationRequestError; HTTP 503 cancellation_request_failed with a safe message; no runtime call. |

Duplicate active requests can retry the best-effort runtime operation; they do
not rewrite the timestamp or append duplicate request observations. Request
idempotence does not depend on a disabled frontend button.

## Races and assistant response

A completion that wins before the request UPDATE prevents a new timestamp.
Completion or failure after the UPDATE may win the terminal CAS and retain the
request timestamp. Cancellation that wins rejects late completion/failure.
The response re-reads after asynchronous cancellation, including nonterminal
replies and exceptions, so it does not return a stale pre-await running snapshot.
RunLifecycleService remains the sole terminal authority; adapters report outcomes
and repositories persist guards without introducing transition policy.

The assistant placeholder is retained. Its public status still projects only
from RunStatus: running → streaming, completed → complete, failed → failed,
cancelled → cancelled. Intent alone changes neither content nor message status.
No partial-content persistence, retry/regenerate change, or execution-default
change was introduced. Omitted execution remains distinct from explicit selection.

## Runtime capabilities

Native retains its asyncio task cancellation and known terminal-result handling.
NativeAgentAdapter retains execution selection, handle ownership, and resource
cleanup. Missing agent/runtime handles now report an unknown nonterminal outcome
as running, leaving the service's persisted status authoritative.

OpenHands revokes its existing tool context, blocking subsequent tool access.
It cannot synchronously stop the SDK worker thread or guarantee interruption of
an in-flight provider request. Its cancel response therefore remains running.
The existing execute path checks revocation when SDK control returns and reports
cancelled then, or failed if execution throws. No new worker or runtime design
was added. The controlled SDK test confirms tools remain revoked while the thread
survives and execution eventually reports cancellation.

## API, events, and frontend

POST cancel and GET run return `cancellation_requested_at` alongside actual
`status`; start-run responses also preserve the timestamp. A running response
with a timestamp means accepted durable intent, not a cancellation guarantee.
Clients can answer whether and when cancellation was requested without events.

`run_cancel_requested` is a nonterminal observation, appended only by the winner
of the request guard. It is not request authority. Examples include
`run_started → run_cancel_requested → run_cancelled` and the same sequence ending
in `run_completed` or `run_failed`.

The request write commits before event append. A crash or event-store failure can
leave intent without an observation; an append failure is logged and does not
prevent the best-effort runtime stop. Duplicate requests do not repair missing
events. Under concurrent writers a terminal event can precede the delayed request
observation. Consumers must not treat request-event ordering as terminal state.
No cross-repository transaction or replay protocol was added; stronger event
atomicity and ordering guarantees remain Phase 5.26.

Shared TypeScript contracts include the timestamp and request event. Shared UI
run state retains the returned timestamp without inferring cancelled status.
The existing event processor safely ignores the new informational event. Repeated
cancel remains safe; no polished cancellation UI or hydration recovery was added.
The existing POST-run endpoint still awaits execution and does not provide an
early run id to this UI. Fixing live transport is separate work.

## Restart and deferred work

A fresh application over the same database reads the exact running status and
request timestamp. It takes no startup action. A second cancel after restart
retains that timestamp and does not mistake the absent handle for success.

Phase 5.25 should first define the runtime-neutral streaming transport contract:
early run identity, normalized event envelope/order, cursor semantics, terminal
signaling, and the shared API-client boundary, grounded in persisted events.
Choose SSE/WebSocket only after that audit. Preserve snapshot reads, durable
intent, and lifecycle authority. Implement replay guarantees in 5.26, partial
content in 5.27, and stranded-run recovery in 5.30. None was started here.

## Tests and architecture guards

`test_durable_run_cancellation.py` covers both persistence adapters, every status,
first timestamp stability, pending/waiting without agent invocation, runtime
ordering and failures, all terminal race winners, stale replies after awaits,
terminal-before-request CAS, safe persistence errors, event-append failure,
application restart, missing handles, API first/duplicate/terminal/unknown
responses, v8→v9 migration, concurrent SQLite connections, and linked assistant
placeholders/content/status under all three terminal races.

Native and Mock adapter tests pin truthful missing-handle semantics. Native
integration covers a persisted running run without a live handle. OpenHands'
controlled worker test now pins a running cancellation acknowledgement followed
by a cancelled execution and revoked tools. Existing run-event tests include the
new observation. Architecture guards keep intent out of RunStatus and terminal
event types, confine request writes to the orchestration boundary, and prohibit
runtime adapters from interpreting the persisted timestamp. Existing lifecycle,
repository, dependency, projection, and execution-default guards remain intact.

Frontend tests verify repeated accepted requests remain active, including failed
event retrieval, and that completion can win despite durable intent.

## File inventory

This workspace already contained uncommitted Phases 5.1–5.23 and a partial 5.24.
Those changes were preserved. The Phase 5.24 implementation spans the following
files (including the inherited partial implementation):

- `backend/src/ava/contracts/responses.py`, `contracts/events.py`
- `backend/src/ava/repositories/run_repository.py`
- `backend/src/ava/services/run_store.py`, `run_lifecycle_service.py`, `run_service.py`
- `backend/src/ava/infrastructure/persistence/repositories/run_repository.py`
- `backend/src/ava/infrastructure/persistence/serialization.py`
- `backend/src/ava/infrastructure/persistence/migrations/versions/__init__.py`
- `backend/src/ava/infrastructure/persistence/migrations/versions/v0009_run_cancellation_request.py`
- `backend/src/ava/api/routes/runs.py`
- `backend/src/ava/agents/contracts.py`, `agents/adapters/native/native_agent.py`,
  `agents/adapters/mock/mock_agent.py`
- `backend/src/ava/runtimes/contracts.py`, `runtimes/adapters/native/native_runtime.py`,
  `runtimes/adapters/openhands/openhands_runtime.py`
- `backend/tests/test_durable_run_cancellation.py` (new)
- `backend/tests/test_architecture.py`, `test_native_agent.py`, `test_mock_agent.py`,
  `test_openhands_file_tools.py`, `test_native_runtime.py`
- Existing partial-implementation compatibility updates in
  `backend/tests/test_contracts.py`, `test_runs.py`, `test_repository_ports.py`,
  `test_run_events.py`, `test_run_service.py`, `test_persistence_migrations.py`,
  `test_persistence_activation.py`, `test_persistence_database.py`
- `frontend/packages/contracts/src/runs.ts`, `events.ts`
- `frontend/packages/agent-ui/src/types.ts`, `run/conversationRun.ts`,
  `run/conversationRun.test.ts`
- `docs/AVA_Phase_5_24_Durable_Run_Cancellation.md` (new)

The tracked development database and other pre-existing workspace changes were
not used as test fixtures or reset. Test databases are temporary.

## Validation results — complete

- Required focused backend suites: **445 passed**. Additional Native runtime and
  persistence-activation regression suites: **35 passed** (480 focused tests total).
- New durable-cancellation test module: **49 cases**, including memory/relational
  parity and restart with no automatic recovery.
- Ordinary full backend `pytest -q`, with repository `.env` present and existing
  conftest unchanged: **1928 passed, 2 skipped**, four SDK deprecation warnings.
  No manual environment neutralization was used.
- `ruff check .`: **passed**.
- `mypy src/ava`: **passed**, 178 source files.
- Affected frontend suites: contracts **23**, API client **73**, agent UI **177**
  tests passed (**273 total**).
- Affected package TypeScript checks: **passed**.
- `pnpm build`: Web and Desktop TypeScript checks and Vite builds **passed**;
  Vite retained its bundle-size advisory.
- `git diff --check`: **clean**.

Restricted-sandbox API tests stalled in TestClient's thread/event-loop startup;
the focused and full backend suites were run successfully with approved sandbox
escalation. Initial full-suite failures were legacy expectations for missing
handles and the old cancellation event sequence; updated assertions passed the
focused rerun and the ordinary full suite.

**Phase 5.24 is complete. Stop here. Phase 5.25 has not begun.**
