# AVA Phase 5.20 — Message Status Normalization

**Status:** Complete. This step defines conversation-facing assistant status;
it does not add streaming transport, replay, context construction, durable
cancellation, or a broad run-lifecycle rewrite.

## Decision and vocabulary

The run is the sole authoritative lifecycle record. Assistant message status is
a derived projection of its durable `source_run_id`, not a second mutable
state machine. The public vocabulary is `pending`, `streaming`, `complete`,
`failed`, and `cancelled`.

| Run status | Assistant status |
| --- | --- |
| `pending`, `waiting_for_approval` | `pending` |
| `running` | `streaming` |
| `completed` | `complete` |
| `failed` | `failed` |
| `cancelled` | `cancelled` |

User messages remain durable submitted content and receive no new lifecycle.
Regenerate visibility also remains separate: old completed responses stay
`complete`; transcript derivation selects the latest response structurally.

## Creation and persistence

For a linked run, `RunService` now creates its assistant message before
execution with empty content and persisted `pending`, records the durable
relationship, then replaces content on completion. The stored initial status
is not authoritative: `ConversationService` derives the exposed status from
the run whenever it reads a linked assistant message. No schema migration was
needed because the existing message status column already stores the creation
placeholder and Phase 5.19 provides the durable run link.

This permits failed and cancelled linked runs to retain an identifiable
assistant response whose displayed state follows the run. It does not persist
partial tokens. Current `POST /runs` awaits terminal completion, so clients do
not yet observe a live streaming response over transport; `streaming` is the
stable projection reserved for the existing persisted `running` state.

## Refresh and restart

After refresh or restart, linked messages are re-read with their source run and
derive the same status. A stranded persisted `running` run derives
`streaming`, never false completion. Phase 5.29 still owns active-run refresh
recovery and Phase 5.30 must classify executions interrupted by backend
restart.

## Preserved boundaries and handoff

The frontend remains cache/interaction state, not durable lifecycle authority.
Events communicate transitions but do not determine status. Phase 5.21 should
use complete visible messages as the conservative context input rule until its
own explicit policy is implemented. Phase 5.23 owns transition validation;
5.24 cancellation durability; 5.27 partial content; 5.34 detailed failure UX.
