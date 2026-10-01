# AVA Phase 5.31 — Retry / Regenerate Across Persisted Runs

## Status

Phase 5.31 makes attempts durable. Retry and regenerate both create a new run
and a new assistant message; they never reopen, clear, resume, or alter the
prior terminal run.

## Pre-5.31 behavior

The UI had local retry/regenerate affordances, but persisted attempt lineage,
server-side prior-run validation, new-response ownership, and canonical context
rules were incomplete. A fresh page could not safely rely on an old in-memory
run object to establish a new attempt.

## Definitions and eligibility

Retry is a new run for the same durable source user message after `failed` or
`cancelled`. Regenerate is a new run for that source after `completed`. The
sets are disjoint. `execution_interrupted` is ordinary failed history and is
therefore retryable; it is never resumed. Active `pending`, `running`, and
`waiting_for_approval` attempts cannot be superseded.

## Durable lineage

The client uses the existing `POST /runs` contract with `retry_of_run_id`.
`RunService` reads the authoritative prior run, verifies its conversation,
terminal state, durable `source_user_message_id`, and the source user message.
It reconstructs the new request from that durable user message rather than
from UI position or client text. The normal creation path then allocates a
fresh run ID, assistant placeholder/message ID, lifecycle, event log, timestamps,
cancellation field, and execution resolution. No user message is duplicated.

Prior runs, assistant messages, events, error facts, execution selections, and
cancellation intent remain immutable history. New event sequences begin at one
for the new run. The new frontend session receives a new `runEpoch`, and old
observers are aborted/superseded by the existing run/message/epoch guards.

## Transcript and context

All assistant variants remain durable. `selectTranscriptMessages` projects the
latest assistant response for a turn, so retry and regenerate both make their
new response visible while older variants remain hidden history. Backend context
construction follows the same structural lineage: superseded completed variants
are excluded, failed/cancelled/interrupted variants remain excluded, and the
current source user appears exactly once. Earlier completed turns remain normal
history.

## Configuration and lifecycle integration

An attempt is a new execution, so it resolves the execution configuration and
credentials from its own request/current settings. It does not copy a prior
resolved runtime, provider, credential, workspace intent, or failure state.
Streaming, partial content, reconnect, refresh recovery, cancellation, and
backend-restart settlement all use the ordinary Phase 5.24–5.30 paths for the
new run.

## Boundaries

No retry/regenerate endpoint, schema migration, parent-run column, branch tree,
or broad concurrency rule was added. The backend knows only that a terminal
run is being superseded; Retry versus Regenerate remains a UI intent governed by
the shared eligibility policy. Phase 5.32 stale-event work has not begun.

## Validation and handoff

Focused attempt coverage exercises durable lineage, terminal guards, repeated
regeneration, context projection, interruption retry, refresh/restart behavior,
new event sequences, cancellation reset, and old-history immutability. Phase
5.32 should address stale-event protection only, retaining the new run/message/
epoch ownership boundaries established here.
