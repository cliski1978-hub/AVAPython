# AVA Phase 5.23 — Run Lifecycle Normalization

Phases 5.19–5.22 made a run's *relationships*, *messages*, *context*, and
*window* well defined. None of them decided what a run's status is allowed to
become. `RunService` called `RunRepository.update_status` directly at five
sites, legality was implicit in the shape of the code, and a late completion
could silently overwrite a cancellation that had already won.

This phase turns that implicit behavior into one explicit, tested, enforced
state machine.

## The gap this closes

Before this phase:

- **Legality was implied by control flow.** "A completed run cannot be
  cancelled" was true only because `cancel_run` happened to return early. A new
  caller writing to a run's status would have no rule to follow and no test that
  would fail if it broke one.
- **Terminal states were not final.** `RunService.start_run` wrote
  `RunStatus.COMPLETED` after an agent returned, and `cancel_run` wrote whatever
  status the agent reported. A run cancelled mid-flight could be overwritten by
  the execution it was meant to stop, and the durable status would then
  disagree with the durable `run_cancelled` event already recorded for it.
- **A status could arrive without its fact.** A run reported `completed` through
  a cancellation race got the status write and no `run_completed` event, so the
  event stream and the run record told different stories.
- **The rules were untestable in isolation.** Every assertion about the state
  machine needed an agent, a provider, and an HTTP request to reach the code
  that expressed the rule.

After this phase:

- One module owns the transition table, the validation, the write, and the
  lifecycle event.
- An illegal transition is a typed, deterministic rejection; a repeated one is
  an idempotent no-op.
- A concurrent terminal write is decided by the database, so exactly one
  terminal state can win.
- The rules are pinned as pure policy, with no agent in the loop.

## Vocabulary

- **Run status** — the authoritative lifecycle state of a run: `pending`,
  `running`, `waiting_for_approval`, `completed`, `failed`, or `cancelled`.
  Stored on the run record and defined once in `RunStatus`.
- **Active status** — a run that has not settled: `pending`, `running`,
  `waiting_for_approval`. `RunStatus.is_active` / `ACTIVE_RUN_STATUSES`.
- **Terminal status** — a settled run: `completed`, `failed`, `cancelled`.
  `RunStatus.is_terminal` / `TERMINAL_RUN_STATUSES`.
- **Transition** — one validated, persisted move of a run from one status to
  another. Every production status change is a transition.
- **Lifecycle event** — the durable fact recorded *by* a transition
  (`run_started`, `run_completed`, `run_failed`, `run_cancelled`). It is a fact
  about what happened, never an authority about what is true now.
- **Idempotent transition** — a request for the status a run already holds. It
  succeeds by doing nothing: no write, no duplicate event, no timestamp churn.
- **Guarded write** — a status write that only lands if the run is still in the
  status the caller last observed (`compare_and_set_status`).
- **Rerun / regeneration** — a second run over the same source user message.
  Each attempt is its own run with its own lifecycle.

## The state machine

The whole model is one table in
`backend/src/ava/services/run_lifecycle_service.py`:

| From | To |
| --- | --- |
| `pending` | `waiting_for_approval`, `running`, `failed`, `cancelled` |
| `waiting_for_approval` | `running`, `failed`, `cancelled` |
| `running` | `completed`, `failed`, `cancelled` |
| `completed` | — |
| `failed` | — |
| `cancelled` | — |

Three properties fall out of that shape, and each is a test rather than a
comment:

- **Terminal is terminal.** The three terminal statuses map to an empty set, so
  a late completion or a post-cancel write is a rejection, not a silent
  overwrite. This is the property the old code lacked.
- **Every active run can still finish.** `pending` and `waiting_for_approval`
  can both reach all three terminal states, so no run can get stuck in a state
  with no way out.
- **Nothing skips execution.** Only `running` can reach `completed`; a `pending`
  run cannot jump straight to a terminal success, because it has not run yet.

### Why `waiting_for_approval` stays

The status has no production writer today. It is still declared in the backend
enum, in the shared TypeScript union, and in the read-time assistant-status
projection, and removing it would change a published contract and the frontend
that consumes it — for no functional gain, in a phase whose job is to normalize
the lifecycle rather than prune its vocabulary.

So the table keeps the edges an approvals flow will need (`pending →
waiting_for_approval → running`, plus cancellation and failure from the waiting
state) and this phase deliberately writes the status nowhere. The alternative —
deleting a declared state — would be a contract change disguised as cleanup.

## Where the authority lives

`RunLifecycleService` is the only component that writes a run's durable status.
It holds the table, the event mapping, the validation, and the write.

`RunService` still *asks* for states — it cannot orchestrate an execution without
saying "start" and "complete" — but it holds no rules. It has no table, no
terminal list, no local status collection, and no direct
`RunRepository.update_status` call. An architecture test enforces each of those
individually, because each one is a way a second state machine could grow back.

The repositories keep both write primitives:

- `update_status` — the blind write. It stores a status and refreshes
  `updated_at`. It is what repository behavior tests use to set up a state, and
  it decides nothing about legality.
- `compare_and_set_status` — the guarded write. It lands only if the run is
  still in the status the caller observed, which is what makes a lost race
  detectable.

Keeping the blind primitive is deliberate. A repository that refused illegal
transitions would be enforcing a rule it does not own, and every future storage
backend would have to re-implement it.

## Status first, then the fact

A lifecycle event is appended only after the status write succeeds. The ordering
is the guarantee: an event can never claim a state the authoritative run does
not have, so a consumer of events can never believe something `Run.status`
denies.

A cross-repository transaction does not exist in the current repository design,
so the strongest available guarantee is that divergence can only ever be a
*missing* event — a process dying between the two writes — and never a
contradicting one. Phase 5.26 owns stronger event guarantees.

Because the guarded write precedes the append, at most one writer can ever
append a terminal event for a run, and the event it appends is the one that
matches the status that actually persisted.

## Exactly one terminal state can win

A late completion and a cancellation can both be in flight for the same run.
Both read `running`, both decide they are first, and both try to settle it.

Validating a read-then-write is not enough, because the window between the read
and the write is exactly where the damage happens. The write is therefore a
compare-and-swap on the status that read observed:

- The relational adapter puts the guard in the `WHERE` clause
  (`... WHERE run_id = ? AND status = ?`), so the database decides. Two
  concurrent writers cannot both match; the loser updates zero rows.
- The in-memory store checks and writes without awaiting, so nothing can
  interleave and the guard is exact.

When the guarded write loses, the lifecycle re-reads and reports what actually
happened:

- The run reached the status this caller asked for — the other writer made the
  same move. That is convergence, not failure: the request succeeds and no
  duplicate event is appended.
- The run reached some *other* status — this caller is told the real
  `from_status` and `to_status` in an `InvalidRunTransitionError`.

Either way the loser never overwrites the winner, and a `run_completed` event
can no longer sit beside a `cancelled` status.

## Ordering that AVA guarantees

`RunService.start_run` executes in this order, and an integration test observes
each step against a real database:

1. The relationship is validated and the durable context is built — before any
   run record exists, so a rejected request leaves no run behind.
2. The run is created `pending`.
3. The durable assistant placeholder is created and linked.
4. The run becomes `running`; `run_started` is recorded.
5. The agent executes, and the final assistant content is persisted *before* the
   run is completed — a `completed` run can never be missing its response.
6. The terminal status is written, then its lifecycle event.

Cancellation that wins stops the run: no message events and no `run_completed`
are emitted afterwards, and the response reports the cancellation that actually
landed.

## Failures

Every failure the lifecycle sees — an unavailable execution, a context window
that cannot fit, a configuration that does not resolve, a provider or runtime
exception — lands in the same terminal state, `failed`, with one stable error
body. The lifecycle has no reason to distinguish them, and it never sees a
provider SDK exception: an agent adapter converts an execution failure into an
AVA-level outcome before the lifecycle is involved.

The distinction between a configuration problem, a context problem, and a
provider problem is real, and it belongs in the run's log and in richer error
reporting (Phase 5.34), not in the state machine.

## Assistant status stays a projection

An assistant message row is created with the stored status `pending` as a
creation placeholder. The public status is derived at read time from the
authoritative run (`assistant_status_for_run`), so a stored placeholder can
never contradict the run that owns it, and one rule covers every message
regardless of which run produced it.

This phase does not change that. It does mean the lifecycle and the projection
cannot drift: the projection asks `RunStatus`, and the lifecycle validates
against the same enum.

## Timestamps

`runs` has `created_at` and `updated_at` and nothing else, and this phase adds
no migration.

- `created_at` is written once at run creation and never rewritten.
- `updated_at` refreshes on every repository write. It is a generic last-write
  clock, not a lifecycle timestamp: recording a resolved execution after a run
  completes legitimately refreshes it.
- **The moment a run settled is therefore the timestamp on its terminal
  lifecycle event.** A terminal event is appended once, is protected against
  duplication by the run-event port, and is never rewritten — so it is the only
  write-once record of when the run ended.

A dedicated `started_at` / `completed_at` pair would read better in a database
dashboard, and a future phase may add it. It is not required to make the
lifecycle correct, so this phase does not.

## Preserved boundaries

- **Cancellation baseline (Phase 5.24's to change).** An unknown run reports
  `cancelled`; a terminal run reports its recorded status; an active run asks
  the agent, then records the outcome. Cancelling twice records one fact.
- **Regeneration.** A rerun is a new run over the same source message. Older
  runs are history: their status and timestamps never move again, and a rerun's
  context never includes an answer to the turn it is re-answering.
- **Restart durability.** Every status and timestamp survives a process restart
  unchanged. Startup does no recovery: a stranded `running` run stays `running`,
  because recovering it is Phase 5.30's decision to make.
- **Execution semantics.** An omitted execution and an explicit execution
  selection remain distinct, and a run's execution selection is still recorded
  when the run reports its outcome.
- **Context construction and windowing.** Phases 5.21 and 5.22 are upstream of
  this phase and untouched.
- **Frontend.** The frontend already consumes the backend's status through
  total mapping functions and guards against a stale response with a run epoch.
  No frontend change was needed, and none was made.

## Deliberate non-goals

- **No durable cancellation.** There is no `cancelling` state, no cooperative
  cancellation token, and no restart-resumable cancel. A `cancelled` run is a
  record that cancellation was requested and settled.
- **No recovery or retry lifecycle.** A failed run is not restarted, and a run
  is not resumed after a crash. Both are separate phases.
- **No streaming or replay.** Event retrieval is still snapshot retrieval.
- **No cross-repository transaction.** Status and event writes remain two
  operations, ordered rather than atomic.
- **No `started_at` / `completed_at` columns.**
- **No new event types.** `pending` and `waiting_for_approval` have no lifecycle
  event in the current vocabulary, so those transitions write the status only.

## Tests

- `tests/test_run_lifecycle.py` (75) — the state machine as pure policy: table
  completeness, every legal edge, every illegal edge, idempotence for all six
  statuses, timestamp rules, the terminal-event timestamp, unknown runs, the
  guarded-write guarantee, lost and converged races, reported terminal
  statuses, and Python/TypeScript vocabulary parity.
- `tests/test_run_lifecycle_integration.py` (20) — the real thing, over SQLite:
  creation and start ordering, placeholder existence, completion ordering,
  context-window / configuration / provider failures, the failure fact, the
  cancellation baseline, cancellation of a genuinely in-flight run, the
  complete-versus-cancel races, independent regeneration, restart persistence
  for all six statuses, a stranded run after restart, and execution semantics.
- `tests/test_architecture.py` (6 new, 115 total) — only the lifecycle authority
  writes or guards a run status; `RunService` holds no policy; agents,
  runtimes, and routes cannot import the authority; repositories stay blind;
  events are facts and never authority.
- `tests/test_relational_run_repository.py` (4 new) — the SQL guard: a matching
  guard applies, a stale guard refuses without overwriting, an unknown run
  refuses.

## Validation

- Full backend suite with the repository `.env`: 1876 passed, 2 skipped.
- Full backend suite in a hostile environment (`env -i`, no inherited `.env` or
  AVA variables): 1876 passed, 2 skipped — the isolation boundary still holds.
- `ruff check src tests`: clean. `mypy src/ava`: clean (177 source files).
- Frontend, unchanged but re-verified: `tsc --noEmit` and vitest clean in
  `@ava/contracts` (23 tests) and `@ava/agent-ui` (174 tests).
- No network calls: the Native path uses a fake provider and the OpenHands path
  uses the controlled SDK seam.

## Follow-ups this phase deliberately leaves

- **Recovering a stranded run.** A process that dies mid-run leaves `running`
  runs behind. Deciding whether to fail, resume, or expire them is Phase 5.30.
- **Stronger event guarantees.** Status and event writes are ordered, not
  atomic. Phase 5.26 owns making the pair transactional.
- **Real cancellation.** `cancelling`, cooperative cancellation, and durable
  cancel requests are Phase 5.24.
- **Richer failure reporting.** One stable `agent_failed` body for every cause
  today; distinguishing configuration, context, and provider failures for
  clients is Phase 5.34.
- **Lifecycle timestamps.** `started_at` / `completed_at` would make the state
  machine readable straight from a query. The terminal event's timestamp is
  sufficient until something needs to sort or filter on it.
