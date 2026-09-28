# AVA Phase 5.29 — Run Recovery After Refresh

## Status

Phase 5.29 recovers a live backend run after the frontend process reloads. It does not recover an execution after a backend restart, redesign retry or regenerate, or define a conversation-wide concurrency policy.

## Audit: behavior before this phase

Conversation hydration already reloaded conversations, user messages, assistant messages, durable partial assistant content, and the server-projected `streaming` status. `MessageResponse.source_run_id` was already exposed by the API, but the shared frontend mapper discarded it. A new frontend store consequently had no run identity, active-run state, local epoch, stream observer, or cancellation target. The composer could therefore appear idle; no SSE observer restarted, though hydration itself did not create another run or assistant placeholder. Direct route loading and in-app selection had the same missing-link behavior.

## Recovery owner and durable chain

`AgentRunProvider` is the sole recovery owner. On a conversation load it calls the shared `recoverRunForConversation` orchestration. It uses the established durable chain:

```text
Conversation -> visible assistant Message.source_run_id -> Run -> assistant_message_id
```

The frontend retains `sourceRunId` directly from the server message DTO. It does not use text, timestamps, position, an empty placeholder, or a global run scan. `selectTranscriptMessages` remains the one visible-response definition: only its current visible assistant response can be a recovery candidate, so hidden regenerated answers are not revived.

## Lifecycle and local ownership

Only `pending`, `running`, and `waiting_for_approval` snapshots start recovery. Completed, failed, and cancelled snapshots render their durable state and do not observe. The recovered run must name the candidate assistant message; a mismatch is rejected.

Each recovery creates a fresh frontend-only `runEpoch`, binds the existing `run_id` and `assistant_message_id`, and restores the current projected phase and cancellation intent. Neither the epoch nor cursor is persisted to local storage, session storage, IndexedDB, API fields, or schema.

## Bootstrap replay

The observer begins at `after_sequence=0`. `runStreamResume` remains the only owner of sequence validation, deduplication, gap handling, retry, and live continuation. The hydrated durable message content is rendered first. Historical `message_content` snapshots that are older than that durable value are consumed for cursor and event-ID reconstruction but are not rendered; an equal or extending snapshot enters normal processing. This prevents `Hello world` from regressing through `Hel` and `Hello` during replay while allowing a later `Hello world!` event to render.

The durable message snapshot remains authoritative through the documented content/event crash gap. If the latest persisted event is `Hello` but the message row is `Hello world`, recovery retains `Hello world` without synthesizing an event. Fresh reconciliation after an ended stream reads a new run and message snapshot; an earlier bootstrap snapshot is never reused as later truth.

## Interaction and races

Recovery never calls `POST /runs` and never creates an assistant message. The existing cancel action receives the recovered real `run_id`; cancellation intent remains non-terminal and is not resent merely because the page refreshed. A completion, failure, or cancellation observed during recovery settles through the usual event/snapshot path.

Conversation switching aborts only the local controller. It does not cancel the backend run, and the `runEpoch`, run ID, and message ID checks reject late events. Switching back invokes the same conversation-scoped recovery flow. The provider keys the active recovery by conversation, assistant message, and durable run ID, so duplicate initialization and React StrictMode-style repeated effects leave one effective observer. Web and Desktop use the same shared package path.

## Boundaries

No backend route, API contract, schema, migration, global active-run query, subscriber state, or client persistence store was added. Backend restart recovery remains Phase 5.30: this phase only reconnects while the backend execution is still alive.

## Validation

Focused recovery coverage verifies visible regenerated-candidate selection, cursor-zero recovery, fresh epoch binding, no `startRun`, no assistant creation, stale historical-content suppression, future content acceptance, terminal non-observation, and the existing cancellation/event ownership protections. Focused backend relationship, partial-content, streaming, and architecture coverage passed `147` tests. The Agent UI suite passed `190` tests; workspace passed `52` with `4` existing skips; contracts passed `23`; and API client passed `79`.

The required complete backend suite ran in detached `tmux` execution:

```bash
cd /home/bizon/AvaUi/backend && .venv/bin/pytest -q
```

It exited `0` with `1960 passed, 2 skipped, 4 warnings in 55.08s`. `pnpm -r lint`, Web build, Desktop build, Ruff, mypy (`179 source files`), and `git diff --check` passed. Web and Desktop report only Vite's existing bundle-size advisory.

Phase 5.29 is fully closed. Phase 5.30 has not started.

## Phase 5.30 handoff

Phase 5.30 should define what happens when backend execution has stopped during process restart: detect durable stranded active states, classify their terminal outcome or resumability, and preserve the relationship and observer boundaries established here.
