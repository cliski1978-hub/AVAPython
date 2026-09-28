# AVA Phase 5.18 — Production Conversation Architecture Audit

**Status:** Complete — audit only.  No production behavior changed.

## Scope and method

This audit traces the current production conversation path after the Phase 5.16
configuration resolver and Phase 5.17 application-default UI migration.  It
inspects the AVA contracts, services, repository ports and SQLite adapters,
routes, native and mock agent boundaries, shared API client path, and shared
`@ava/agent-ui` state/orchestration.  It also maps existing tests to the next
Phase 5 steps.

Phase 5.18 deliberately does **not** normalize schema relationships, add
streaming or reconnect, change execution behavior, or begin Phase 5.19.

## Current persisted model

| Domain | Durable representation | Current relationship / authority |
| --- | --- | --- |
| Conversation | `conversations`: AVA `conversation_id`, title, timestamps | Independent aggregate; service creates and renames it. |
| Message | `messages`: AVA `message_id`, `conversation_id`, role, status, content, optional `source_run_id`, timestamps | Append-only within a conversation, ordered by SQLite surrogate `id`. `ConversationService` verifies the conversation exists before append. |
| Run | `runs`: AVA `run_id`, status, timestamps, optional resolved `execution_selection` | Independent lifecycle record. It has no `conversation_id`, source-message id, or assistant-message id. |
| Run event | `run_events`: AVA `event_id`, `run_id`, type, monotonic `seq`, timestamp, payload, contract version | Append-only per run, ordered by `seq`; it has no conversation or durable message relation. |

The present schema intentionally has no foreign keys between these tables.
`messages.source_run_id` is an optional scalar, but it is not constrained to
`runs`, is not populated by the normal frontend assistant-save path, and does
not establish the reverse causality required to find a run from a conversation
or user message.  This is the principal Phase 5.19 gap.

`RelationalMessageRepository` persists messages verbatim and
`RelationalRunRepository` persists only status and execution selection.  The
conversation and run services use separate repository pairs and perform no
cross-aggregate transaction.  A client can therefore persist a user message,
then fail before creating its run; it can also complete a run and fail when
persisting the assistant message.  The frontend surfaces the latter as a save
warning while retaining the completed local response.  That behavior avoids a
false failed run, but it is not durable execution causality.

## Current execution and event path

```text
ConversationProvider
  create conversation / append durable user message
      -> local pending assistant placeholder + frontend run epoch
      -> POST /runs { prompt, execution?, workspace_id? }
          -> RunService -> AgentPort -> NativeAgentAdapter
              -> ExecutionSelector / configured-or-bootstrap execution
              -> runtime/provider
          <- terminal RunResponse
      -> GET /runs/{run_id}/events (complete snapshot)
      -> apply events to local placeholder
      -> POST /conversations/{conversation_id}/messages (assistant, completed)
```

`POST /runs` awaits the agent and returns only after a terminal outcome.  The
subsequent event request retrieves the full persisted sequence.  Neither route
is a background, SSE, WebSocket, or long-poll transport.  The API client uses
ordinary request/response calls; it has no event cursor, subscription, resume,
or replay-deduplication protocol.

`RunService.start_run` creates a pending run, appends `run_started`, marks it
running, then awaits `AgentPort.start_run`.  A completion creates a generated
event-only `message_id`, appends `message_started` and `message_content`, marks
the run completed, and appends `run_completed`.  Failure persists a failed run
and normalized generic `run_failed` payload.  Cancellation persists
`run_cancelled`; a cancellation that wins before the agent result suppresses
message and completion events.  The event repository permits only one terminal
event per run and preserves event order by explicit sequence, backed by a
partial unique SQLite index.

The event `message_id` is not the frontend pending placeholder id and is not a
row in `messages`.  `@ava/agent-ui` treats `message_started` as informational,
using the placeholder captured when the user submitted.  This is correct for
the current snapshot-only UI, but confirms that backend event/message identity
is not yet a durable shared association.

`NativeAgentAdapter` owns execution selection, compatibility validation,
workspace binding, resource leases and runtime cancellation forwarding.
`RunService` remains cleanly limited to `AgentPort`, `RunRepository` and
`RunEventRepository`.  It never receives model/provider/configuration
repositories.  This remains a strength and must be preserved during the
conversation work.

## Conversation, context, and regenerate behavior

`ConversationService` offers create/list/get/rename and append/list/get
message operations.  It persists all appended messages as `complete`; the
backend has no message-authoring or transition service.  `pending`, `failed`,
and `cancelled` exist in the contract vocabulary but are not currently written
by the service.

There is no backend context-construction service.  The submitted run carries
only `prompt`, optional `execution`, and optional `workspace_id`.  The native
adapter and runtime receive that prompt; neither queries conversation history,
filters superseded assistant responses, calculates token budget, nor records a
context snapshot.  Durable history is therefore display history, not model
input context.

The shared frontend records `sourceUserMessageId` only in local
`ConversationMessage` state.  On hydration it reconstructs missing
associations by assigning each assistant message the nearest preceding user
message in append order.  `selectTranscriptMessages` then shows only the last
consecutive assistant response for a turn, preserving durable history such as
`U1 → A1 → A2 → A3` while rendering `U1 → A3`.  Retry and regenerate reuse the
source user prompt and assistant slot locally, then persist a new assistant
row after completion.

That achieves useful current UX and avoids text/order guesses during a live
run, but the hydration association and transcript collapse are frontend-owned
inference.  They are not durable source-of-truth relationships, cannot name
the producing run, and rely on append order/consecutive assistant rows.  Phase
5.19 must replace only the facts the backend can authoritatively store while
preserving append-only regenerate history and its visible-last-response rule.

## Existing frontend safeguards and limits

`ConversationRunProvider` captures the originating conversation and message
ids before asynchronous work.  It permits one active **frontend** run per
conversation (`starting`, `running`, `stopping`), blocks duplicate submits and
reruns in that state, and routes completion to the captured conversation even
after the user changes selection.

Each new run claims a local `runEpoch` before its first await.  Event
application and assistant persistence compare that epoch to fresh reducer
state; a superseded completion does not repaint state, flip its phase, or save
the older assistant output.  This is a focused, well-tested client guard for
the current single-process UI.  It is not persisted, transmitted to the
backend, or usable after refresh/restart, and `cancelActiveRun` currently
applies its fetched events without an epoch argument.  Phase 5.32 must make
staleness an authoritative run/event rule rather than relying solely on this
local epoch.

Cancellation is forwarded to the backend once a `run_id` exists.  The UI enters
`stopping`, then fetches events and trusts their final state; if cancellation
transport fails it attempts an event snapshot before restoring a visible
running state with an error.  This is sound reconciliation for a live page.
There is no durable cancelling intent/state, no process-restart policy, and no
relationship that lets a reloaded conversation discover its active run.

Initial conversation hydration fetches all conversation summaries and then
messages for each.  Selecting a conversation fetches its message snapshot and
uses a selected-id guard to ignore a late response for an old selection.
Hydration merges server messages without discarding local in-flight
placeholders.  It does not query runs, active run state, or events; a refresh
therefore reconstructs completed durable messages only and cannot reconcile a
live run.

## Execution-default invariant from 5.16–5.17

The conversation orchestration keeps an absent execution override absent:
`startRunForPrompt` only includes `execution` in `RunRequest` when an override
was supplied.  The workspace shell emits `undefined` for **Application
default**, `{ mode: "auto" }` for an explicit Auto selection, and explicit
legacy runtime/model/provider fields for a custom/profile selection.

This distinction is material.  The Phase 5.16 resolver uses omitted execution
to select authoritative persisted defaults, while an explicit selection
preserves the legacy/bootstrap path (after persisted configuration validation).
Future conversation/run work must carry this intent unchanged; it must never
infer “default” by comparing selected ids or turn an omitted override into
Auto.

## Recovery, restart, and streaming assessment

| Scenario | Current result | Gap to close |
| --- | --- | --- |
| Completed run, same page | Full stored event snapshot is applied, then assistant response is appended. | Event and durable message identities are separate. |
| Completed conversation reload | Messages reload in append order and transcript derivation selects the last response. | No durable run/message causality or run history reconstruction. |
| UI refresh during an active run | Local placeholder, epoch, and run id disappear; hydration does not query active runs. | No refresh recovery, replay position, or active-response reconstruction. |
| Temporary transport loss | Per-request errors are surfaced; cancel tries a snapshot fallback. | No live transport, resume/cursor, connectivity model, or missed-event replay. |
| Backend restart during active run | SQLite may retain `running` run and early events. Runtime in-memory execution maps and terminal bookkeeping are lost. | No startup reconciliation; runs can remain indefinitely running. |
| Late/superseded local completion | Current epoch guard blocks UI write/persistence when used by normal start flow. | Not durable or generalized across reload, replay, cancellation, or multiple clients. |

The persisted event sequence is already the right primitive for Phase 5.26:
it is ordered by `(run_id, seq)` rather than timestamps and has unique event
ids.  The current public contract omits `seq`, however, and the route always
returns the entire list.  A resume cursor and client deduplication boundary
still need design.  The repository technically permits non-terminal events
after a terminal event; `RunService` avoids that in its own normal flows, but a
future event writer needs lifecycle-transition enforcement at the domain
boundary.

## Strengths to preserve

- AVA-owned UUIDs and UTC timestamps for conversations, messages, runs, and
  events; clients never mint backend identities.
- Clear repository ports, SQLite adapters, and stable append order for both
  messages and events.
- `RunService → AgentPort` isolation from providers, runtime internals,
  selection, workspace policy, and credentials.
- Normalized events, event payload serialization, explicit event ordering, and
  one-terminal-event protection.
- The Phase 5.16–5.17 omitted-versus-explicit execution contract.
- Shared Web/Desktop frontend orchestration and provider-neutral event
  interpretation.
- Captured conversation/message ids, selected-conversation hydration guard,
  local run epoch, and no fabricated assistant persistence on failed/cancelled
  runs.
- Append-only regenerate history with a deterministic visible active response.

## Gap map and recommended sequencing

| Future step | Audit finding / minimum design question |
| --- | --- |
| 5.19 Relationships | Add the minimum durable links for conversation → source user message → run → produced assistant response. Decide one source of truth for regenerate/supersession without duplicating all message data. Link event message identity to that model. |
| 5.20 Message statuses | Define backend-owned state transitions only after 5.19 establishes which message is being authored. Current persisted messages are always complete. |
| 5.21 Context service | Introduce an AVA-owned ordered-context builder. It should select active responses deterministically and receive explicit conversation/run inputs. |
| 5.22 Context window | Add model-aware deterministic budgeting/truncation to the context service; preserve full durable history separately. |
| 5.23 Lifecycle | Centralize legal run transitions, including whether `cancelling` and an interruption terminal state are required; reject stale/illegal writes. |
| 5.24 Cancellation | Persist cancellation intent/outcome and reconcile late runtime completion against the lifecycle state. |
| 5.25 Transport | Choose SSE/WebSocket only after defining a normalized ordered event subscription that remains backed by persisted events. |
| 5.26 Replay | Expose sequence/cursor semantics and idempotent client application; do not use timestamps as a cursor. |
| 5.27 Partial output | Persist/derive partial response state so an interruption cannot fabricate a completed message. |
| 5.28 Reconnect | Resolve run state, replay from a durable position, and rebuild visible output with duplicate suppression. |
| 5.29 Refresh recovery | Query active runs by durable conversation relation and replay their events after hydration. |
| 5.30 Backend restart | At startup, classify in-flight runs whose runtime execution cannot survive restart; never leave them indefinitely running. |
| 5.31 Retry/regenerate | Move source-message/run/response association from frontend reconstruction to durable facts while retaining U1 → A1 → A2 history and visible A2. |
| 5.32 Stale events | Extend the local epoch protection into durable run identity/version and event-application rules, including replay and cancel races. |
| 5.33 Concurrency | Enforce one active run per conversation authoritatively, while allowing distinct conversations to run concurrently. |
| 5.34 Failure UX | Map normalized configuration/runtime/transport/context/replay errors to honest, recoverable UI state without raw internals or false success. |
| 5.35 Config integration | Preserve Phase 5.16 failure behavior: invalid saved configuration fails visibly and never silently changes to bootstrap/default routing. |

The dependency order is intentional: relationships first, then message/run
state and context, then cancellation/transport/replay/recovery, then durable
retry/stale/concurrency/error integration.  Streaming before durable causality
would force the client to continue owning facts it cannot recover after a
refresh.

## Current focused coverage

Existing tests already cover the Phase 5.18 audit boundaries without requiring
production changes:

- Backend conversation service and relational repository tests cover generated
  ids, known-conversation enforcement, append order, role/status round trips,
  timestamps, and `source_run_id` storage.
- Run service, route, store, and relational repository tests cover snapshots,
  completion/failure/cancellation lifecycles, cancellation winning completion,
  event isolation/order, execution selection persistence, and one terminal
  event.
- Shared frontend tests cover active-run submit guards, cancel fallback,
  completed-only assistant persistence, retry/regenerate association, stale
  epoch suppression, transcript selection, and idempotent message hydration.

They do not yet prove cross-table causality, restart reconciliation, active-run
rehydration, streaming/replay cursor semantics, or backend-enforced
conversation concurrency because those capabilities do not exist.  Those are
the focused tests to introduce with their corresponding future step rather
than speculative tests in this audit.

## Conclusion

AVA has a solid durable snapshot foundation and a careful live-page frontend
orchestrator.  The production boundary is currently between independent
conversation/message persistence and independent run/event persistence.  The
next implementation step is to join those durable facts minimally and
explicitly, while retaining Phase 5.17 execution intent semantics and the
existing `RunService → AgentPort` boundary.
