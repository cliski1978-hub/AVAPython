# AVA Phase 5.33 — Conversation-Level Concurrency Rules

## Policy

AVA permits at most one active run per durable conversation. Active means
`pending`, `running`, or `waiting_for_approval`; terminal means `completed`,
`failed`, or `cancelled`. Different conversations remain independent.

Before this phase, the frontend disabled most competing actions, but the
backend creation path could accept concurrent direct or multi-client requests.
Stale-work protections prevented UI corruption but did not make simultaneous
backend execution semantically valid.

## Enforcement

Every production run path uses `RunService.prepare_run`, including normal
submission, retry, and regenerate. Repository creation checks for an active
record with the same `conversation_id` inside its mutation boundary. The
SQLite implementation performs the check and insert under its existing
`BEGIN IMMEDIATE` transaction; memory applies the same rule synchronously.
The losing request raises normalized `409 conversation_run_active` before a
run, assistant placeholder, event, context build, or agent execution starts.

Cancellation is allowed but its durable intent does not free the slot. Only a
terminal lifecycle transition does. Pending and waiting-for-approval runs also
occupy the slot. Retry and regenerate retain their own terminal-target policy,
then pass the same conversation guard.

## Interactions and limits

Frontend busy controls remain UX assistance; backend persistence is final
authority for stale tabs, Web/Desktop, and direct clients. A conflict leaves
the actual active response untouched and creates no ghost user or assistant
message. Existing retry/regenerate orchestration creates no user message,
while normal submission remains frontend-blocked before user persistence.

Legacy conversations containing multiple active runs are conservatively busy:
new creation is rejected and no historical run is automatically selected,
cancelled, or queued. Phase 5.30 still settles all such process-local runs on
restart. The policy does not add distributed leases, queues, automatic
cancellation, schema migrations, or a conversation branching model.

## Context and stale-work boundary

The invariant keeps serial context construction intact: a later user turn
cannot begin while a partial/approval-dependent prior response remains active.
Phase 5.32 still protects old work if it exists; Phase 5.33 prevents normal
product flows from creating competing active work in one conversation.

## Handoff

Phase 5.34 should improve failure and error UX without weakening normalized
creation conflicts or conflating a rejected competing request with a failed
assistant run.
