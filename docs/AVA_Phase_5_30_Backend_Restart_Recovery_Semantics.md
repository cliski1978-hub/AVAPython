# AVA Phase 5.30 — Backend Restart Recovery Semantics

## Status

Phase 5.30 is complete and formally closed. A durable active run whose execution
owner was lost with the previous backend process is settled at cold start,
through the lifecycle authority, as `failed` with a truthful
`execution_interrupted` fact. It is never left claiming to be `running`, and it
is never reported as `cancelled` without an observed acknowledgement.

## Pre-5.30 behavior

A durable `pending`, `running`, or `waiting_for_approval` run remained active
across a backend restart. Native and OpenHands execution handles are in-memory
task registries, so a fresh process owned none of those runs. Startup performed
no active-run scan; SSE could tail an active snapshot indefinitely, and a
post-restart cancellation could persist intent but could not prove an original
task stopped. No code resumed execution. Phases 5.23 and 5.24 had deliberately
pinned that silence — "startup does no recovery" was the correct statement of
the architecture *then*, and their tests have been updated rather than deleted.

## Stranded-run definition

```text
stranded run = active persisted run whose process-local execution owner is absent
```

This is deliberately narrower than "active run", and the difference matters:

| Concept | Meaning | Owner |
| --- | --- | --- |
| `active persisted lifecycle state` | `pending`, `running`, `waiting_for_approval` | `RunStatus`, the lifecycle vocabulary |
| `restart-stranded execution` | an active run that this process cannot resume | cold-start detection, `RunRecoveryService` |

AVA currently makes those two coincide, because every wired runtime is
process-local. The code does not confuse them: nothing inspects a status to
decide "stranded", and the architecture test forbids recovery from importing
`RunStatus` at all. A future externally-survivable runtime would be a capability
question, not a status question.

## Startup recovery ownership and integration point

`RunRecoveryService` (`backend/src/ava/services/run_recovery_service.py`) is the
application owner. It is constructed in the application factory and invoked from
the FastAPI lifespan, before the app serves anything:

```python
app.state.run_recovery_summary = app.state.run_recovery_service.recover_stranded_runs()
```

Recovery therefore completes before readiness. The first ordinary run read after
startup already observes the settled terminal state; there is no window in which
a client can read a stale `running` snapshot. The `RunRecoverySummary`
(`active_found`, `settled_failed`) is retained on `app.state` for inspection.

Recovery asks the repository which runs are active and then delegates every
settlement to `RunLifecycleService.fail`. It never writes a status itself, never
appends an event itself, and never contacts an agent, runtime, model, or
provider.

## `list_active` contract

Active-run discovery is a repository concern, so it lives on `RunRepository`:

```text
list_run_ids() -> list[str]                     # enumeration primitive
list_active()  -> Collection[RunRecord]         # active snapshots, created/id order
```

`list_active` returns only active runs, in deterministic `created_at, run_id`
order, read-only, and using the canonical classification rather than a second
list of status strings: the default asks each record `record.status.is_active`,
which is the same `RunStatus` property every other layer uses.

### Source-compatible fallback

Neither method is abstract, so a pre-existing lightweight test double still
instantiates — that was the compatibility regression found by the earlier full
suite run.

The fallback is a *correct* default, not an empty one:

* `list_run_ids` raises `NotImplementedError` by default. It is a capability
  probe, not an empty answer.
* `list_active` is a real generic implementation: it enumerates via
  `list_run_ids`, reads each record, keeps the active ones, and sorts them.

An earlier iteration of this closeout shipped `list_active` returning `()` as the
compatibility fix. That was rejected on review and is not what shipped: a
repository holding real active runs would have answered "nothing to recover",
and recovery would have declared a database full of stranded runs healthy. A
loud capability failure is strictly safer than a silent lie, and it still leaves
the port source-compatible.

The principle the final shape implements:

```text
repository contract gains active-run discovery
without forcing existing lightweight doubles to implement a specialized query
```

Implementing `list_run_ids` alone is enough to make a double fully recoverable;
no double has to write a status query.

### Production repository behavior

| Repository | `list_active` | Query shape |
| --- | --- | --- |
| `RunStore` (in-memory) | overridden | filters `ACTIVE_RUN_STATUSES`, sorts in memory |
| `RelationalRunRepository` | overridden | `WHERE status IN (...) ORDER BY created_at, run_id` — filters in SQL, one query |
| lightweight double | generic default | enumerate, `get`, filter, sort |

Both production repositories override, so the slower generic path is never used
in production and cold start does not load every run. Parity between the memory
and relational semantics is asserted by a shared behavioral suite.

`RelationalRunRepository` also implements `list_run_ids`, so the production port
is complete rather than relying on a probe it would fail.

## Restart policies

Explicit, not implicit. For each persisted active status:

| State | Survives restart? | Needs lost process-local state? | Preserved? | Transitions to | Persisted reason/event |
| --- | --- | --- | --- | --- | --- |
| `pending` | no | no scheduler survives, so nothing could ever run it | its record, `created_at`, any intent, any content | `failed` | `run_failed` with `execution_interrupted` |
| `running` | no | yes — the asyncio task died with the process | same | `failed` | same |
| `waiting_for_approval` | no | its continuation would need the same lost runtime state, and it has no production writer | same | `failed` | same |

A run is *preserved* in the sense that everything about it survives: the record,
its creation time, its cancellation intent, its partial assistant content, and
its event history. Only the lifecycle status and `updated_at` change.

`waiting_for_approval` is settled, not preserved, and that is a deliberate
finding rather than a convenience: the state is declared and projected in the
vocabulary but has no production writer and no durable continuation. Keeping it
active after a restart would be an even more permanent lie than `running`, since
nothing would ever move it again.

`pending` is settled for the same reason as `running`, in the opposite direction:
it has no lost execution to blame, but it has no durable scheduler that could
ever start one, so leaving it `pending` would strand it forever.

Terminal runs (`completed`, `failed`, `cancelled`) are excluded by the
active-status query and are never visited.

## Normalized interruption reason

AVA-owned, defined once in `run_recovery_service.py`:

```json
{"code": "execution_interrupted", "message": "The backend restarted before this run completed."}
```

It is attached as the `run_failed` payload. No provider, model, runtime, prompt,
or SDK error is exposed, and recovery never catches a runtime failure to report
it, because it never calls one.

## Cancellation-intent policy

For `cancellation_requested_at != null` with an active status at restart, the
final policy is: **preserve the intent, settle as `failed`, and never resend
cancellation.**

The recovery service does not call `cancel_run`, does not fabricate a
cancellation acknowledgement, and does not clear the field. A run recovered with
intent reads `failed` + `cancellation_requested_at != null` — the durable
evidence that a user asked to stop, against an outcome nobody witnessed. A
runtime task that no longer exists is never asked to stop.

## Partial assistant content

Untouched. A stranded run whose assistant message holds `Partial answer...`
keeps exactly that text. Recovery writes only run status, `updated_at`, and one
event. Message content, message status, and the content event history are not
touched, and the frontend then projects the terminal status from the run as it
does for any other settled run.

## Lifecycle transition path

```text
cold start
  -> RunRecoveryService.recover_stranded_runs()
     -> RunRepository.list_active()
     -> RunLifecycleService.fail(run_id, payload=execution_interrupted)
        -> RunRepository.update_status(...)      # status write
        -> RunEventRepository.append(RUN_FAILED) # the matching fact
```

Every settlement goes through `RunLifecycleService`. An architecture test pins
that recovery may not call `update_status`, `compare_and_set_status`, or
`request_cancellation` directly, and may not import `RunStatus` to keep its own
active set.

## Event and timestamp semantics

A recovery settlement appends a **new, truthful** terminal fact at recovery time:

```text
1 run_started
2 message_started
3 message_content
4 run_failed        <- appended at this cold start
```

* correct next sequence — the existing per-run sequence simply continues;
* correct type — `run_failed`, never a synthesized earlier fact;
* normalized payload — `execution_interrupted`;
* timestamps are not backdated — the event timestamp is recovery time.

`created_at` is unchanged. `updated_at` reflects the settlement. The event
timestamp reflects recovery time. The repository owns these clocks; recovery
invents no timestamp.

## Idempotence and terminal-run preservation

```text
restart #1   active run   -> failed + one run_failed fact
restart #2   terminal run -> untouched
```

Verified: no second failure event, no content change, no repeated error
mutation, and no `updated_at` churn on the already-settled run. Startup
convergence is therefore safe to run on every boot.

## Crash-gap behavior

The lifecycle status write and the event append still cross two repository
ports, as documented in Phase 5.26. If the status write succeeds and the append
fails, the run is `failed` with no terminal event. A later startup finds a
terminal run, has nothing to converge, and does **not** synthesize the missing
fact. Replay reports the gap exactly, which preserves 5.26's rule:

```text
replay = persisted facts only
```

## Replay and reconnect after recovery

`GET /runs/{run_id}/events?after_sequence=0` returns the original facts plus the
real recovery event, and nothing else. Because the recovery fact is a genuine
persisted event, a client whose cursor stopped before it resumes directly onto
it:

```text
cursor = 1, recovery event = 2  ->  run_failed, then the stream closes
```

This is 5.28's cursor-aware SSE meeting 5.30 with no special-casing: the stream
delivers the terminal fact and closes on it because it is terminal.

## Frontend interaction (5.29)

No frontend change was required. `recoverRunForConversation` starts an observer
only when the run snapshot is in `ACTIVE_RUN_STATUSES`; after startup
convergence the snapshot is `failed`, so a refresh:

* hydrates the durable partial content from the conversation snapshot;
* projects the server's `failed` status;
* starts no observer, creates no run, and creates no assistant message.

No frontend special case for backend restart exists, and none was added. One
agent-ui test was added to pin this specific case, since the existing terminal
test covered `completed`.

## No automatic execution

Recovery is lifecycle convergence only. It never calls agent execute, model
generation, provider generation, tool execution, runtime start, retry, or
regenerate. This is proven by instrumenting the agent's `start_run`,
`start_run_streaming`, and `cancel_run`, plus the runtime registry and the
provider registry, and asserting that none was reached during a real startup
pass.

It equally needs no model selection, provider connection, credential resolution,
context construction, or context-window calculation.

## Runtime-neutrality and current survival assumptions

There is no named-runtime logic in the recovery path — no `native`/`openhands`
branching. Neutrality comes from the documented current assumption instead:

| Runtime | Execution handle | Survives backend process restart? |
| --- | --- | --- |
| `NativeRuntime` | `self._run_tasks` (in-process `asyncio.Task`) | no |
| `OpenHandsRuntime` | `self._contexts` revocation flags (in-process) | no |
| `MockAgentAdapter` | in-process active-id set | no |

Both production runtimes keep their handles in process memory, which is *why*
startup recovery may classify persisted active runs as stranded. The extension
point for a future externally-survivable runtime is an explicit runtime
capability, not a status: such a runtime would report that its executions
outlive the process, and recovery would skip its runs. That capability is not
implemented, deliberately.

## Multi-process limitation

```text
current Phase 5.30 semantics assume single backend process/worker ownership
```

If AVA is ever run with multiple workers, a worker's own startup would fail runs
that another live worker is actively executing, because in-process task
ownership is not visible across processes. This phase does not pretend to solve
that: no distributed lease, heartbeat, or owner-registration system was
introduced. Multi-worker orphan detection is future work and would require
durable execution ownership, which is a different phase.

## Startup failure behavior

```text
strong preference, and the implemented behavior: startup fails
```

If recovery raises a persistence error, the exception propagates out of the
lifespan and the application does not become ready. Runs already settled before
the failure stay settled; the next startup finds them terminal and retries only
what is still active. This is fail-fast and per-run, not all-or-nothing: there
is no cross-run transaction, and inventing one would mean claiming an atomicity
the persistence layer does not provide.

Serving a half-converged process would expose `running` snapshots for executions
that no longer exist, which is the exact lie this phase removes. A concurrent
terminal writer that wins the CAS raises `InvalidRunTransitionError`, which is
caught and skipped — that is a lost race, not a failure.

## Persistence interaction

Recovery uses the same instance-scoped `RLock` and reentrant savepoint path
introduced in Phase 5.26. A recovery settlement inside an enclosing transaction
participates via savepoint and rolls back with it: no self-deadlock, and no
committed status that the enclosing transaction then discards. Verified
explicitly, alongside the existing nested-transaction suite.

## Schema and migration impact

None. `list_active` reads the existing `runs` table; no column, index, or
migration was added in this phase.

## Compatibility regression found and fixed

The first full-suite run of this phase failed on repository ports used by
lightweight test doubles, because `list_active` had been made abstract. The
interim fix made it default to an empty tuple. Review rejected that: an empty
default silently hides active runs and would defeat restart recovery for any
repository that did not override it. The final state is:

* `list_active` — correct generic implementation, not empty;
* `list_run_ids` — new enumeration primitive, raising by default as a capability
  probe;
* production repositories — optimized overrides unchanged;
* pre-5.30 doubles — still instantiable, and now either fully recoverable (by
  adding `list_run_ids`) or loudly non-discoverable.

Regression coverage pins that a minimal pre-5.30 double remains instantiable and
that it is never answered with an empty active set while holding active runs.

## Test evidence

Final validation for this closeout:

- Focused Phase 5.30 + compatibility matrix (`test_run_recovery`,
  `test_repository_ports`, `test_repository_behavior_compatibility`,
  `test_architecture`, `test_persistence_activation`, `test_persistence_database`,
  `test_relational_run_repository`, `test_relational_run_event_repository`,
  `test_run_lifecycle`, `test_run_lifecycle_integration`,
  `test_durable_run_cancellation`, `test_run_streaming`,
  `test_restart_recovery_integration`, `test_partial_assistant_content`,
  `test_persisted_execution_integration`): **444 passed in 12.65s**.
- `tests/test_run_recovery.py`: **16 passed** — convergence policy for all three
  active states, cancellation intent, terminal preservation, crash gap,
  default-listing correctness, pre-5.30 double compatibility, generic-path
  recovery, replay after recovery, cursor resume after recovery, no-execution
  instrumentation, startup ordering/readiness, multi-run independence, partial
  recovery failure, transaction rollback, and startup failure.
- Transaction/savepoint/database subset: **55 passed**.
- Full backend suite via the proven detached `tmux` method
  (`cd backend && .venv/bin/pytest -q`): **exit code 0**, `1994 passed, 2
  skipped, 4 warnings in 55.33s`. No backend file changed during the run.
- Frontend: `@ava/contracts` **23 passed**, `@ava/api-client` **79 passed**,
  `@ava/agent-ui` **191 passed**, workspace **52 passed / 4 skipped** (the four
  are the existing opt-in live integration skips).
- `pnpm -r lint`: passed. Web build: passed. Desktop build: passed. Both report
  only Vite's existing bundle-size advisory.
- `ruff check .`: passed. `mypy src/ava`: passed, 180 source files.
  `git diff --check`: clean.

## Known limitations

1. Single backend process/worker is assumed; see the multi-process section.
2. There is no cross-repository unit of work, so a status write can commit
   without its event. Documented, tested, and left to 5.26's eventual fix.
3. `waiting_for_approval` is settled on restart even though it has no production
   writer today; the policy is chosen for a future approvals flow, not observed
   behavior.
4. Recovery treats every active run as stranded. A runtime that could survive a
   restart would need the capability described above before this stays correct.

## Phase 5.31 handoff

Phase 5.31 — Retry / Regenerate Across Persisted Runs — should add user-triggered
retry and regenerate semantics for persisted terminal runs. It must not alter the
cold-start convergence policy: a run settled by recovery is `failed` with a
`cancellation_requested_at` that may or may not be set, and a retry must treat
that as ordinary terminal history rather than as evidence the user asked to
stop, and rather than as an invitation to restart execution that recovery
deliberately did not resume.

**Phase 5.30 is fully closed. Phase 5.31 has not started.**
