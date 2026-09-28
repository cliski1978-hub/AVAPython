# AVA Phase 5.28 — Reconnect / Resume

## Status

Phase 5.28 adds same-session SSE reconnect and resume. It does not add page-refresh recovery, backend-restart execution recovery, or retry/regenerate changes.

## Behavior before Phase 5.28

`streamRun` parsed one SSE response and resolved on EOF. `conversationRun` de-duplicated event IDs and tracked a `lastSequence`, but both values lived only inside that one stream invocation. An abort stopped observation; a thrown transport error left backend lifecycle intact and placed a recoverable message in UI state. There was no reconnect loop, resume cursor, or reliable way to bridge a dead stream to a replacement stream. Conversation switching aborted the active controller and did not cancel the backend run.

## Ownership

Transport observation is frontend-owned. `RunStatus` remains backend lifecycle authority; a disconnect never marks a run failed. The new shared `runStreamResume` module owns one in-memory cursor, event-ID map, bounded retry schedule, and one stream at a time for one observing UI session. Web and Desktop reach it through the same `@ava/agent-ui` orchestration.

## Cursor and identity contract

`last_processed_sequence` is scoped to one run and advances only after the event has passed ownership, sequence, and epoch checks and has been applied to frontend state. It is exclusive:

```text
after_sequence=4 -> first possible event is sequence 5
```

Event ID and sequence remain separate. Event ID rejects a repeated fact; sequence establishes order and the processed-through position. A duplicate event ID at a different sequence, a reused sequence for a different event, or a gap causes controlled resume from the last contiguous cursor without applying the questionable event.

The cursor is same-session frontend state only. It is not persisted to AVA storage and therefore does not implement Phase 5.29 refresh recovery.

## Cursor-aware SSE

`GET /runs/{run_id}/stream` now accepts `after_sequence`.

```text
omitted / 0      -> all persisted events, then live tail
N               -> events with sequence > N, then live tail
negative        -> FastAPI validation 422
unknown run     -> normalized 404 run_not_found
cursor > latest -> normalized 409 invalid_resume_cursor
```

The API client exposes this as `streamRun(..., { afterSequence })`; omission remains backward compatible and produces the existing URL.

## Server catch-up and live tail

The SSE generator stores its last emitted sequence and repeatedly calls the existing `RunEventRepository.list_after_sequence` path through `RunService`. It emits each persisted result in ascending order and repeats the query before waiting. An event committed while earlier catch-up facts are emitted is found on the next query, so there is no client-side replay/live handoff gap and no in-memory queue becomes authoritative.

Terminal events are emitted and then close the stream. If a run snapshot is terminal but its terminal event is absent due to the documented cross-repository crash gap, the stream closes without inventing an event. A cursor already at the terminal sequence closes promptly.

## Frontend reconnect algorithm

```text
unexpected EOF/error
  -> retain partial UI and backend lifecycle state
  -> reconcile snapshot after the cursor stream attempt ends
  -> if terminal, settle from snapshot and stop
  -> otherwise reopen SSE with after_sequence=last_processed_sequence
```

The cursor-aware stream itself supplies durable catch-up and live tail, so snapshot reads are a reconciliation safety net rather than an event-transfer bridge. Reconciliation occurs after a stream attempt, avoiding temporary rollback from older full-content snapshots. Backend snapshot status and message content win when the event log is behind because of a documented crash gap.

`message_content` retains Phase 5.27 full-snapshot semantics: resumed content replaces the current bubble text; it is never concatenated. `run_id`, stable assistant `message_id`, and `runEpoch` must all still match before an event can apply.

## Retry and cleanup

Reconnect retries are centralized and bounded: immediate, 50 ms, then 150 ms. Receipt of an event resets the attempt count. Exhaustion records a UI-only live-update disconnect message and never mutates backend `RunStatus` or assistant lifecycle status. `404`, `422`, and `409` are normalized terminal transport/protocol outcomes; an ahead-cursor `409` first reconciles the snapshot.

An aborted controller, changed conversation, unmount, or superseded `runEpoch` stops the loop without reconnecting. The controller remains local to the UI observer. Cancellation remains the separate `POST /runs/{id}/cancel` command and works while observation is reconnecting.

## Partial output, terminal outcomes, and subscribers

Partial content remains visible through reconnect. A resumed full snapshot replaces it once, avoiding `HelloHello world`. Completion, failure, and cancellation received while disconnected arrive through the resumed persisted stream and stop reconnecting. If the terminal event is missing but the snapshot is terminal, reconciliation settles UI without synthetic history.

Subscribers are stateless and independent: each uses its own `run_id` and cursor; neither changes persistence, lifecycle, or another subscriber's position. Backend process restart semantics remain Phase 5.30 work: historical facts and snapshots can be read, but this phase does not continue lost execution.

## Architecture guards and tests

The reconnect loop is shared frontend orchestration. SSE routes remain observer-only and read persisted event history; `RunService` owns no subscriber or reconnect state. Focused coverage verifies exclusive cursor streaming, cursor-ahead rejection, events persisted during catch-up, API-client cursor serialization, resume after EOF, gap correction, terminal snapshot/event gap handling, and intentional abort behavior.

## Phase 5.29 handoff

Phase 5.29 should recover active runs after a page refresh by discovering the durable run/message relationship for the hydrated conversation, reconstructing a new in-memory cursor from persisted events and snapshots, and then using this phase's cursor-aware SSE observer. It must preserve run/message ownership and `runEpoch` protections without treating refresh as backend execution recovery.

## Validation and closure

Focused backend coverage passed: `192 passed in 4.66s` across streaming, run-event, run-service, route, partial-content, and architecture tests. Frontend package suites passed: contracts `23`, API client `79`, agent UI `187`, and workspace `52 passed, 4 skipped`.

The ordinary complete backend suite was run from a detached `tmux` session to avoid foreground process termination:

```bash
cd /home/bizon/AvaUi/backend && .venv/bin/pytest -q
```

It completed with exit code `0`: `1960 passed, 2 skipped, 4 warnings in 51.99s`. `pnpm -r lint`, web build, desktop build, Ruff, mypy (`179 source files`), and `git diff --check` also passed. The builds emit only Vite's existing bundle-size advisory.

Phase 5.28 is fully closed. Phase 5.29 has not started.
