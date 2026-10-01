# AVA Phase 5.34 — Failure and Error UX

## Scope and pre-5.34 audit

Phase 5.34 keeps the durable run lifecycle defined by Phases 5.23–5.33. Before
this change, assistant bubbles already distinguished pending, failed, and
cancelled states and preserved partial content. The gaps were error ownership:
some action and observation paths exposed status-oriented or server-provided
text, a `run_failed` event did not project its normalized metadata into the
assistant response, and a conversation load failure was visible only in the
sidebar strip.

## Error model

The frontend separates three scopes:

* **Durable run failure** is the backend's terminal `failed` state. It belongs
  to the existing assistant response, survives ordinary transcript hydration
  as a failed status, and remains retryable under Phase 5.31.
* **Transport/observation failure** means SSE, replay, or snapshot observation
  could not continue. It is held in frontend run state only and never changes
  a run to `failed`.
* **Action failure** means a request was rejected before it created a run, or
  an action such as cancellation or conversation loading could not complete.
  It is localized feedback and is not durable history.

All public wording goes through `errorPresentation.ts`. Known AVA error codes
receive product-owned copy; unknown action and transport errors use a stable
fallback rather than HTTP status text, SDK messages, provider payloads, or
exception details.

## Run and transcript behaviour

`run_failed` now projects a normalized, AVA-owned explanation onto the same
assistant message that owns the run. Partial content remains above the failure
state. A no-content failure remains a visible assistant shell with status,
explanation, and Retry. Unknown durable failures say “Something prevented this
response from completing.” `execution_interrupted` says that AVA restarted and
remains a normal failed, retryable attempt.

Cancelled responses remain visually neutral and distinct from failed responses;
their partial content and Retry remain available. A running response with a
durable cancellation intent continues to use the existing stopping state until
the backend reports a terminal status. A failed cancellation request restores
observation of the active run and reports action feedback without claiming the
run was cancelled.

When initial run creation is rejected, no durable run exists. The frontend now
removes its local optimistic assistant shell, leaves the persisted user prompt
available, returns the conversation to idle, and shows localized action
feedback. Retry and regenerate already create no placeholder until acceptance,
so a rejected retry/regenerate preserves its prior visible response. A
`conversation_run_active` conflict maps to a concise busy notice and creates
no failed assistant response; Phase 5.33 remains the authority for durable
reconciliation and concurrency.

## Observation, loading, and stale ownership

Temporary disconnect, exhausted reconnect, malformed event, and snapshot
reconciliation problems remain observation errors. They preserve last known
assistant content and durable run status, are cleared by a subsequent run
start or successful observation, and do not survive refresh. Stream ownership
and error suppression keep using the Phase 5.32 run epoch checks, so a late
error cannot overwrite a newer run or conversation.

Conversation list and message-load errors use the shared normalization layer.
The active transcript now has a local alert with Retry; loaded content stays
visible. The existing selection/generation checks prevent a failed old load
from appearing after another conversation or a newer same-conversation load
owns the UI. A missing recovery run is reported as a restoration issue and
does not create a replacement run.

## Accessibility and parity

Assistant state uses text labels in addition to color and retains named Retry
and Regenerate controls. Conversation load feedback uses `role="alert"` and a
visible Retry control. All work is in shared `agent-ui`/`workspace` packages,
so Web and Desktop receive the same behavior. No backend lifecycle, API
contract, schema, migration, retry policy, concurrency policy, or
configuration-specific Settings integration changed.

## Validation

Focused shared UI validation:

```text
pnpm --filter @ava/agent-ui test
17 files passed, 192 tests passed
```

Phase 5.35 handoff: add configuration-specific structured remediation only by
extending the shared failure action slot; preserve the generic lifecycle and
error boundaries above.
