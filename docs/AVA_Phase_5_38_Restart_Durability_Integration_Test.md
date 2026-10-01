# AVA Phase 5.38 — Restart/Durability Integration Test

## 1. Test objective

Certify, end to end against real relational persistence, that AVA's persisted
conversation, message, run, run-event, configuration-failure, and
restart-recovery semantics remain truthful across a cold process boundary.

This phase changes no policy. Phase 5.30 decided what happens to a run that is
still active when a fresh process starts. Phase 5.38 proves that decision is
real rather than in-memory bookkeeping, by making the restart boundary
physical: instance A writes durable state to a SQLite file, A is disposed and
discarded, and a brand-new composition B reads the same file cold and settles
the run.

## 2. Persistence backend used

`AVA_PERSISTENCE=relational` — the durable SQLite adapters
(`RelationalRunRepository`, `RelationalRunEventRepository`,
`RelationalConversationRepository`, `RelationalMessageRepository`, plus the
configured-record repositories) over one shared `SqliteDatabase`, created by
the production `create_application_persistence` composition and migrated by the
production migration runner on every cold start.

Every test uses an isolated temporary database under pytest's `tmp_path`. The
developer's `backend/ava.sqlite3` is never opened.

`AVA_ATTACHMENT_STORAGE` stays `memory` in this harness: Phase 4.14 already
certified attachment content durability, and this phase certifies conversation,
run, event, and configuration durability.

## 3. Cold-instance simulation method

Two independent full production application compositions (`create_app`) over one
shared SQLite file:

```
Instance A: create_app(settings) → TestClient → real services write to the file
            → persistence.dispose() → application discarded
Instance B: create_app(settings) → brand-new service graph over the same file
            → recovery runs → state read back
```

A new service graph against the same database is the persistence boundary that
matters, because AVA keeps no state outside these repositories. No repository,
service, connection, or in-memory object is carried from A to B; only plain
durable ids (strings) are carried into the assertions, and the harness asserts
that B's repository and service objects are *different objects* from A's.

No OS process was spawned. The `TestClient` lifespan did **not** hang in this
sandbox — the existing Phase 4.15 and Phase 5.30 restart tests using the same
path pass in under a second — so the real production lifespan was used as the
primary path rather than avoided.

## 4. Instance A setup

Each scenario seeds through the production conversation API and the production
lifecycle / assistant-content services:

1. `POST /conversations` → durable conversation `C1`.
2. `POST /conversations/{C1}/messages` → durable user message `U1`.
3. `RunLifecycleService.create_run` → run `R1` opened in `pending`, linked to
   `C1` and `U1`.
4. `set_assistant_message_id` → `R1.assistant_message_id = A1`.
5. `MessageRepository.append` → durable assistant placeholder `A1` in
   `pending`, `source_run_id = R1`.
6. `RunLifecycleService.start` → `R1` becomes `running` (or the scenario's
   target active status).
7. `AssistantResponseService.start_message` + `.record_snapshot` → `A1` streams
   partial content through the canonical assistant-content path, which also
   appends the matching `message_content` event.

Event history is produced by the service layer, never hand-written to look
plausible.

## 5. Durable IDs and relationships asserted before restart

Every id and link is asserted through the production API **before** the
boundary, so the post-restart assertions compare against known-good durable ids
rather than against values read from the same object graph under test:

```
R1.conversation_id       == C1
R1.source_user_message_id == U1
R1.assistant_message_id  == A1
A1.source_run_id         == R1
R1.status                == the scenario's active status
R1.cancellation_requested_at == None
```

## 6. Active run state before restart

`running` is the primary case. `pending` and `waiting_for_approval` are covered
by the same parametrized test, because the recovery loop is generic and each
active status must settle identically:

| Status | Pre-restart event history | Pre-restart content |
| --- | --- | --- |
| `running` | `run_started`, `message_started`, `message_content` | partial content |
| `waiting_for_approval` | `run_started`, `message_started`, `message_content` | partial content |
| `pending` | none — never dispatched | empty |

A `pending` run has no execution to lose, so there is no partial content to
preserve. Recovery still settles it, and the empty content is left alone.

## 7. Partial content before restart

`A1.content == "Partial answer before restart"`, written through
`AssistantResponseService.record_snapshot` — the same path a live run uses. The
matching `message_content` event is appended by that same call, so the content
and its event cannot disagree.

## 8. Pre-restart event sequence

For the executing scenarios: sequences `1, 2, 3` for
`run_started`, `message_started`, `message_content`. The harness captures the
actual sequence list and event-id list before the restart so both can be
compared afterwards.

## 9. Instance B construction

`create_app(settings=settings)` against the same
`persistence_database_url`. Instance B gets a new
`SqliteDatabase`, new repository adapters, new services, and a new
`RunRecoveryService`. The harness asserts object identity separation:

```
A.run_repository          is not B.run_repository
A.run_event_repository    is not B.run_event_repository
A.conversation_repository is not B.conversation_repository
A.run_recovery_service    is not B.run_recovery_service
A persistence_database_url == B persistence_database_url
```

## 10. Production recovery path invoked

Primary path: the real FastAPI lifespan. `_app_lifespan` calls
`app.state.run_recovery_service.recover_stranded_runs()` before readiness, so
`app.state.run_recovery_summary` is the production result and every read
afterwards is a cold read.

Secondary path: a separate test invokes
`second.state.run_recovery_service.recover_stranded_runs()` directly — the exact
production-composed object and method the lifespan calls — with no HTTP adapter
involved, and reads the result through
`app.state.conversation_service` rather than through a route. This proves the
settlement is a production service call and not a `TestClient` artifact.

## 11. RunRecoverySummary

`RunRecoverySummary(active_found=..., settled_failed=...)`, using the real
shape from `ava.services.run_recovery_service`. Across the restart boundary:
`active_found == 1`, `settled_failed == 1`. On the idempotent second recovery:
`active_found == 0`, `settled_failed == 0`.

## 12. Final run status

`R1.status == "failed"` after recovery, for all three active statuses.

## 13. `execution_interrupted` payload

The durable `run_failed` event payload is exactly:

```json
{
  "error_code": "execution_interrupted",
  "message": "The backend restarted before this run completed."
}
```

This is `RESTART_INTERRUPTION_PAYLOAD` from `run_recovery_service.py`.

### Defect found and fixed: the classification key

The payload originally used `"code"` instead of `"error_code"`. That was a real
defect, not a test artifact:

* `RunService` writes `error_code` for every other run failure;
* `ConversationService._message_to_response` reads `payload.get("error_code")`
  to hydrate the message's `error_code` after a reload;
* the frontend `runEventProcessor` reads `error_code` from the `run_failed`
  payload to pick the user-facing wording.

So the restart reason was durable but **invisible**: the conversation projection
returned `error_code: None`, and a reloaded client would have shown a generic
failure instead of "The response was interrupted because AVA restarted." The
integration test caught this because it asserted the projection, not just the
stored payload.

Fix: one line in `run_recovery_service.py`, changing the key to the canonical
`error_code`, with a comment explaining why the key is load-bearing.

## 14. Failure message result

`"The backend restarted before this run completed."` is persisted verbatim in
the `run_failed` payload. It is the safe wording: it states what happened
without blaming the user and without exposing provider or runtime internals.

## 15. Terminal event sequence continuation

The `run_failed` event is durable and continues the run's existing sequence:

| Scenario | Pre-restart | After recovery |
| --- | --- | --- |
| `running` / `waiting_for_approval` | `1, 2, 3` | `1, 2, 3, 4` |
| `pending` | none | `1` |

No sequence is renumbered and no pre-restart event id changes.

## 16. Event ordering and uniqueness

After recovery the harness asserts:

* sequences are contiguous from 1 (`1..n`);
* the pre-restart prefix is unchanged (`post[:len(pre)] == pre`);
* the last sequence is exactly `len(pre) + 1`;
* pre-restart event ids are preserved as a prefix;
* all event ids in the log are unique.

## 17. Partial assistant content preservation

`A1.content == "Partial answer before restart"` after recovery, unchanged. The
status projection becomes `failed` and `error_code` becomes
`execution_interrupted`, but the streamed text is never erased — partial output
is real user-visible history, and losing it would be a data-loss bug disguised
as a restart outcome.

## 18. Message/run/conversation linkage

After recovery:

```
A1.source_run_id         == R1
R1.assistant_message_id  == A1
R1.source_user_message_id == U1
R1.conversation_id       == C1
```

No relationship is broken by recovery. The normalized `C1 → U1 → R1 → A1`
chain is asserted before and after the boundary.

## 19. Conversation snapshot after recovery

Read through the production conversation projection — both the HTTP route and,
in the direct-composition test, `app.state.conversation_service.list_messages`:

* `U1` is still present, with its id unchanged;
* `A1` is still present, with its id unchanged;
* `A1.content` is the persisted partial content;
* `A1.status` is `failed`;
* `A1.error_code` is `execution_interrupted`.

This also verifies that the Phase 5.35 durable hydration path works for restart
recovery failures, which it previously did not: the projection returned no error
code at all because of the key defect above.

## 20. Refresh-safe error-code projection

The error code is not derived from anything transient. It is read back from the
durable `run_failed` event every time the conversation is read, so a reload, a
second restart, or a different client all see the same `error_code`. The
idempotency test re-reads the assistant message after a *second* recovery and
still sees the same content, status, and error code.

## 21. No Settings remediation inferred

`execution_interrupted` is not a configuration failure, so the frontend must not
offer an "Open Settings" action for it.

`settingsSectionForFailure("execution_interrupted")` returns `undefined`, and
`presentRunFailure` returns "The response was interrupted because AVA
restarted."

This mapping was previously unpinned by any test. A focused test was added at
`frontend/packages/agent-ui/src/lib/errorPresentation.test.ts` asserting the
mapping in **both** directions — untargeted for `execution_interrupted` and the
other non-configuration codes, still targeted for the five real configuration
codes — so an empty result cannot pass by making the function return nothing
everywhere.

## 22. Retry semantics

The interrupted run remains eligible under the existing retry rules, and Retry
after recovery creates a **new** run. The new attempt is started through
`POST /runs` with `retry_of_run_id` naming the interrupted run, against the
deterministic mock agent adapter — no real runtime, provider, or credential is
contacted.

* the new run has a different `run_id`;
* it inherits the same durable `source_user_message_id` and `conversation_id`
  as the interrupted attempt — the durable lineage, with no parent-run column;
* `R1` is untouched: same status, same events, same content, still exactly one
  `run_failed` event;
* the original partial content and its failure code remain readable.

Nothing is auto-retried. A restart does not retry on the user's behalf.

## 23. Cancellation intent behavior

Tested. A `running` run with a durable `cancellation_requested_at` (recorded via
`POST /runs/{id}/cancel`) is restarted, and:

* `cancellation_requested_at` is preserved exactly;
* the run settles to `failed`, **not** `cancelled`;
* the event log contains `run_cancel_requested` and ends in `run_failed`, and
  contains no `run_cancelled`;
* the assistant message is `failed` with `error_code = execution_interrupted`.

The distinction is the point: a cancellation request is intent, and after a
restart there is no runtime left to acknowledge it. Claiming the cancellation
succeeded would be a lie.

## 24. Idempotent second recovery

Mandatory, and tested. A third composition over the already-recovered file
reports `active_found == 0`, `settled_failed == 0`, and leaves:

* `R1`'s full run record byte-identical to after the first recovery;
* `R1`'s event log byte-identical — no duplicate `run_failed`;
* the assistant message's content unchanged.

## 25. Terminal-run no-op behavior

A completed run seeded in instance A is verified after recovery to be
completely unchanged: the same run record (status, timestamps, execution
selection) and the same event log. Recovery only considers active runs, so a
terminal run is not a target and its history is not rewritten.

## 26. Crash-gap / no-synthesis rule

Phase 5.23/5.26 documented a known crash gap: the status write and the event
write are not one unit of work, so a process can die between them and leave a
**terminal** run whose terminal event was never persisted.

Phase 5.38 explicitly does **not** invent repair logic. The test reproduces the
gap against real SQLite — a run driven to `failed` with the `run_failed` event
deliberately not appended — restarts, and asserts:

* recovery reports `active_found == 0` (a terminal run is not active);
* the run is still `failed`;
* `run_failed` is still **absent** — recovery did not backfill it.

The gap remains a gap and is asserted rather than hidden. Repairing it would
require a unit-of-work redesign, which this phase is not doing. The assistant
projection for that run therefore carries no `error_code`, which is the honest
result of a missing fact rather than a synthesized one.

## 27. Persisted execution-settings behavior

Checked. Instance A persists a provider connection, a model configuration, a
runtime configuration, and the application execution defaults. Instance B
reads back:

```
default_provider_connection_id   == "conn-local"
default_model_id                 == "model-local"
default_runtime_configuration_id == "runtime-local"
```

equal to what A saved, via the production
`ExecutionDefaultsRepository`. A restart does not reset a configured deployment.

This is a persistence assertion only. It is not a Settings retest: no provider
is contacted, no model is resolved, and no runtime is started.

## 28. Credential persistence statement

Only the credential **reference** is persisted. After restart, the
`GET /settings/providers` projection carries exactly these fields:

```
provider_connection_id, provider_id, display_name, endpoint,
enabled, credential_reference, contract_version
```

There is no field that could carry a secret value — no `api_key`, `secret`,
`token`, `password`, `credential`, or `credentials` field — and the persisted
value is the opaque reference string `env:LOCAL_API_KEY`, resolved only at
execution time. No live secret or provider is used anywhere in this harness.

## 29. Focus and scope of validation

Focused tests run, per the phase's validation policy:

| Suite | Why |
| --- | --- |
| `test_restart_durability_integration.py` | the new Phase 5.38 harness (9 tests) |
| `test_run_recovery.py`, `test_run_lifecycle*.py`, `test_run_attempts.py` | directly affected by the payload-key fix |
| `test_restart_recovery_integration.py`, `test_conversation_service.py`, `test_conversation_run_relationships.py`, `test_partial_assistant_content.py`, `test_durable_run_cancellation.py`, `test_run_events.py` | directly affected conversation/run projection behaviour |
| `pnpm --filter @ava/agent-ui test` | carries forward the closed suites and covers the new error-mapping test |

The full backend suite was not run. No sandbox timeout or environment
limitation was encountered; `TestClient` lifespan worked throughout.

## 30. Exact test results

| Command | Result |
| --- | --- |
| `pytest tests/test_restart_durability_integration.py` | **9 passed** in 2.24s |
| `pytest tests/test_run_recovery.py tests/test_run_lifecycle_integration.py tests/test_run_attempts.py tests/test_run_lifecycle.py` | **156 passed** in 12.89s |
| `pytest tests/test_restart_recovery_integration.py tests/test_conversation_service.py tests/test_conversation_run_relationships.py tests/test_partial_assistant_content.py tests/test_durable_run_cancellation.py tests/test_run_events.py` | **104 passed** in 4.58s |
| `pnpm --filter @ava/agent-ui test` | **197 passed** in 18 files (193 pre-existing + 4 new) |
| `ruff check .` | **All checks passed** |
| `mypy src/ava` | **Success: no issues found in 181 source files** |
| `pnpm --filter @ava/agent-ui lint` | **exit 0** |
| `git diff --check` | **exit 0** |

Carried forward, unchanged and not rerun: Web acceptance CLOSED, Desktop
acceptance CLOSED, `@ava/workspace` 53 passed / 4 skipped, `@ava/desktop` 11
passed. No frontend or shared production code changed, so no builds were
rerun.

## 31. Defects discovered

One production defect, found by the integration test and fixed:

**`execution_interrupted` was persisted under the wrong key.** The
`run_failed` payload written by `RunRecoveryService` used `"code"`, while the
canonical classification key everywhere else is `"error_code"`. The effect was
that the restart reason never reached either consumer that reads it: the
durable conversation projection returned `error_code: None`, and a reloaded
client would have shown a generic failure message instead of AVA's
restart-specific wording. The user was told a run failed but never why.

Not fixed, by design:

* The Phase 5.23/5.26 crash gap (terminal status without its terminal event)
  remains a gap. Documented and asserted in section 26, not repaired.

## 32. Production fixes made

One line, in `backend/src/ava/services/run_recovery_service.py`:
`RESTART_INTERRUPTION_PAYLOAD` now uses `"error_code"` instead of `"code"`,
with a comment recording that the key is load-bearing for both the durable
projection and the frontend event processor.

No other production code changed. No schema change, no migration, no service
restructure, and no new abstraction. This phase is certification, not redesign.

## 33. Files changed

* `backend/src/ava/services/run_recovery_service.py` — payload key fix.
* `backend/tests/test_restart_durability_integration.py` — new, 9 tests.
* `frontend/packages/agent-ui/src/lib/errorPresentation.test.ts` — new, 4 tests.
* `docs/AVA_Phase_5_38_Restart_Durability_Integration_Test.md` — this document.

## 34. Known limitations

* The cold boundary is a new service graph over the same file, not a spawned OS
  process. This is sufficient for AVA's durability model (no state lives outside
  the repositories) but it does not exercise OS-level effects such as fsync
  durability guarantees or a process killed mid-write.
* The crash-gap scenario in section 26 reproduces the gap by writing the status
  and then deliberately omitting the event. It does not kill a process at that
  exact instant.
* Retry-after-recovery is verified against the deterministic mock agent. A real
  runtime is out of scope for a persistence test, and live-provider behaviour
  belongs to provider acceptance.
* `pending` and `waiting_for_approval` are covered by the same parametrized
  scenario rather than by separate fully-populated event histories. That is
  deliberate: the recovery loop is generic, and duplicating the fixture three
  times would add no evidence.

## 35. Handoff to Phase 5.39

Phase 5.39 (Race/Concurrency Hardening) can rely on the following now-certified
facts:

* Recovery reads active runs through a SQL-filtered `list_active()` on every
  cold start, and a second recovery is a verified no-op — the idempotency
  guarantee that a concurrent-recovery race would need is already in place.
* The lifecycle authority rejects a duplicate terminal transition with
  `InvalidRunTransitionError`, and `RunRecoveryService` already catches it and
  skips the run rather than appending a duplicate fact. The lost-race path in
  `RunLifecycleService._resolve_lost_race` is the seam a concurrency phase would
  exercise harder.
* The relational run-event repository already enforces at most one terminal
  event per run in SQL, so a duplicate `run_failed` is prevented at the storage
  layer as well as the service layer.
* Cancellation intent is durable and separate from cancellation outcome, which
  is the distinction concurrency work around cancel must preserve.

The natural Phase 5.39 target is concurrent writers during recovery — a
terminal writer racing `RunRecoveryService` — which this phase has already shown
is safe in its simplest form but has not stress-tested.

## 36. Phase 5.38 closure

Phase 5.38 is fully closed. Restart and durability semantics are certified
truthful across a cold process boundary against real SQLite persistence, and one
real defect — an invisible failure classification — was found and fixed.
