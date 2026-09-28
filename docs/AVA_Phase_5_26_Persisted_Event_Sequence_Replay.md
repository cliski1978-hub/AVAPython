# AVA Phase 5.26 — Persisted Event Sequence / Replay

## Status

Phase 5.26 is complete. AVA exposes one durable event-history interface:

```text
GET /runs/{run_id}/events
GET /runs/{run_id}/events?after_sequence=N
```

Both forms read persisted `RunEvent` facts. The second form applies an exclusive replay cursor. No `/replay`, `/history`, or `/resume` endpoint was added.

## Canonical sequence contract

`RunEvent.sequence` is the persisted ordering authority. It is allocated per run, begins at `1`, and advances contiguously for every successful append:

```text
Run A: 1, 2, 3, 4
Run B: 1, 2, 3
```

Sequences are unique within a run, monotonically increasing, independent between runs, and durable across process/database restart. Timestamp ties do not affect ordering. Replay always orders by sequence.

`RunEvent.event_id` remains the stable identity used for de-duplication. Sequence and event identity are deliberately separate: a consumer says “I processed through N” with `sequence` and recognizes a redelivered fact with `event_id`.

## Allocation and concurrency

The in-memory repository allocates the next position from its per-run event list. The relational repository calculates `MAX(seq) + 1` and inserts the event inside one SQLite `BEGIN IMMEDIATE` transaction. The initial schema already enforces `UNIQUE(run_id, seq)`, which also supplies the required lookup index.

`SqliteDatabase.transaction()` uses an instance-scoped `RLock` around the shared connection. This prevents threads using the same database object from interleaving transaction setup. It is reentrant so nested repository work uses the existing savepoint path without self-deadlock. The lock is neither global nor shared by unrelated database instances, and it supplements SQLite transaction and uniqueness guarantees.

Concurrency coverage proves:

- 20 simultaneous successful appends to one run persist 20 events with the exact sequence `1..20` and no duplicate or missing positions.
- 10 simultaneous appends to each of two runs produce `1..10` independently for both runs.
- Nested transactions release savepoints without committing an outer unit of work; rolling back the outer transaction removes both writes.

## Cursor semantics

The cursor is exclusive:

```text
events 1,2,3,4,5

after_sequence=0  -> 1,2,3,4,5
after_sequence=1  -> 2,3,4,5
after_sequence=2  -> 3,4,5
after_sequence=4  -> 5
after_sequence=5  -> []
after_sequence=99 -> []
```

A negative HTTP cursor returns `422`. An unknown run returns the normalized `404 run_not_found` response, including when a cursor is supplied; it never looks like a known run with an empty log.

The TypeScript client retains both call forms:

```text
getRunEvents(client, runId)
getRunEvents(client, runId, afterSequence)
```

It omits the query for a full-log read, encodes a positive cursor, preserves the typed array order, and rejects a negative or non-integer cursor before an HTTP request.

## Restart durability

A file-backed restart test persists sequences `1,2,3`, disposes and recreates the database/repository composition, and appends sequence `4`. Reads after restart verify the full log, an intermediate cursor, the latest cursor, stable event IDs, and stable payloads. Replay durability is a read guarantee; it does not restart execution or alter the run.

## Lifecycle replay

Completed, failed, and cancelled runs are created through their normal service/lifecycle paths. Their complete histories remain ordered and end with the persisted `run_completed`, `run_failed`, or `run_cancelled` fact. Snapshot status agrees with the terminal outcome, but replay does not infer that fact from status.

Failure replay exposes the existing AVA-safe event payload and does not reveal raw adapter exceptions. Cancellation replay preserves `run_cancel_requested` before `run_cancelled`, without requiring adjacency, and an intermediate cursor still reaches the terminal fact.

Phase 5.24 race coverage now also validates replay. A durable cancellation request may be followed by any actual winner:

```text
run_cancel_requested ... run_completed
run_cancel_requested ... run_failed
run_cancel_requested ... run_cancelled
```

For completion and failure winners, `cancellation_requested_at` remains set while status records the real terminal outcome. History is not rewritten into cancellation merely because cancellation was requested.

An active-run test persists `run_started` with status `running`. Replay returns only that fact and does not add a terminal event or recover execution. A deliberate crash-gap fixture also sets a terminal status without a matching event and confirms replay returns an empty event log. Reads never synthesize `run_completed`, `run_failed`, `run_cancelled`, or `run_cancel_requested`.

## SSE and replay parity

SSE and replay expose the same persisted AVA envelopes in the same sequence order. Parity coverage compares `event_id`, `sequence`, `event_type`, and `payload` for completed, failed, and cancelled outcomes. Only SSE framing, heartbeat comments, and HTTP transport metadata differ.

Early subscription still observes the initial fact after `POST /runs` returns `202`; late subscription emits an already-persisted terminal history; two subscribers observe equivalent envelopes. Subscription, disconnection, and subscriber count never append events or mutate lifecycle state.

Replay from an older cursor can intentionally redeliver facts. Consumers use `event_id` for de-duplication and `sequence` for their processed-through cursor.

## Ownership and append-only policy

The architecture remains:

```text
RunStatus              = lifecycle authority
RunLifecycleService    = lifecycle mutation authority
RunEvent               = immutable persisted fact
RunEvent.sequence      = persisted ordering authority
RunEvent.event_id      = stable identity
RunEventRepository     = append/replay persistence boundary
SSE and replay routes  = observers
```

The repository port exposes `append`, `get_events`, `get_latest`, and `list_after_sequence`. It has no update, delete, resequence, or reorder operation. Architecture tests pin this append-only surface, keep both routes observer-only, prevent lifecycle reconstruction from events, and preserve the provider/runtime boundary. Frontend code, runtimes, providers, and adapters do not allocate persisted sequence or own replay.

## Atomicity limitation

Lifecycle status and event append currently cross two repository ports:

```text
status update -> lifecycle event append
cancellation intent update -> run_cancel_requested append
```

A process crash can therefore leave a committed status without its lifecycle event, or committed cancellation intent without its request event. A clean atomic fix requires a cross-repository unit-of-work boundary, which is outside this phase. The current write order ensures an event cannot grant a lifecycle state that authoritative `RunStatus` denies. Replay reports the historical gap exactly and never rewrites it during a read.

## Schema and compatibility

The original `run_events` schema already contains `seq` and `UNIQUE(run_id, seq)`. Every existing relational row uses that schema, so no migration or legacy backfill is needed. Existing clients that call the event endpoint without a cursor retain full-log behavior. The durable `POST /runs -> 202`, authoritative snapshot, and SSE contracts remain unchanged.

## Validation

- Focused backend Phase 5.26 matrix: `424 passed`.
- Affected frontend packages: contracts `23 passed`, API client `78 passed`, agent UI `178 passed`, workspace `52 passed` with four existing opt-in live integration skips.
- Repository-wide TypeScript validation: passed.
- Web production build: passed.
- Desktop production build: passed.
- Ruff: passed.
- mypy: passed across 178 source files.
- `git diff --check`: passed.
- Full backend suite: `1948 passed, 2 skipped, 4 warnings in 52.05s`, exit code `0`. It ran as the exact `backend/.venv/bin/pytest -q` suite in detached `tmux`, with output and exit code redirected to files so the process survived the foreground execution limit.

## Deferred behavior

This phase does not implement partial assistant response persistence/rendering (Phase 5.27), automatic SSE reconnect, `Last-Event-ID`, or cursor resume orchestration (Phase 5.28), or stranded-run execution recovery after restart (Phase 5.30).
