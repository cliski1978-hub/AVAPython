# AVA Phase 5.25 — Streaming Transport Contract

## Previous live-update path

Before this phase, `POST /runs` waited for agent completion. The shared UI then fetched `GET /runs/{id}/events` as a complete snapshot; cancellation fetched the same snapshot after its normal HTTP request. There was no polling loop, SSE, WebSocket, long-polling endpoint, in-memory callback, or streaming helper. `runEpoch` already prevented stale snapshots from overwriting a newer run.

## Contract and transport

AVA now exposes `GET /runs/{run_id}/stream` using Server-Sent Events. SSE fits the current one-way server-to-client requirement; cancellation remains the durable `POST /runs/{run_id}/cancel` API. WebSockets would add a bidirectional protocol without a current need.

Each `data:` record is the AVA-owned `RunEvent` envelope:

```text
run_id, event_id, sequence, event_type, timestamp, payload, contract_version
```

`event_id` is AVA's persisted event identity. `sequence` is the monotonic per-run repository order, now exposed in both repository adapters. SSE `id:` uses `event_id`; SSE `event:` uses the persisted `event_type`; `data:` is one JSON envelope. The event names are the existing AVA vocabulary, including `run_started`, `run_cancel_requested`, `message_started`, `message_content`, `run_completed`, `run_failed`, and `run_cancelled`. No streaming-only event vocabulary exists.

Terminal events are explicit: `run_completed`, `run_failed`, and `run_cancelled`. Connection close, unsubscribe, heartbeat, server shutdown, and network failure carry no lifecycle meaning. Clients must use a terminal event or a later snapshot to settle UI state.

## Endpoint behavior

`POST /runs` now creates, links, and starts a run before returning `202` with its `run_id`, status, and linked conversation/source/assistant IDs. Execution is scheduled after response delivery, allowing a client to subscribe as soon as it receives the stable identity. Existing direct service callers retain `RunService.start_run`, which still waits for a result for unit/integration use.

The stream validates that its run exists before opening. It observes only that run and streams all events currently available at subscription, then polls the persisted event repository at a bounded 100ms interval for new events. This avoids a broker and keeps persistence authoritative. It emits in persisted sequence order and closes after it yields a terminal event or observes client disconnect. It uses `text/event-stream`, `Cache-Control: no-cache`, and `Connection: keep-alive`; a comment heartbeat is emitted after prolonged idle periods and is not an AVA event.

Multiple subscribers independently read the same event history. Backpressure is ordinary async-generator/SSE backpressure; there is no per-subscriber queue. Disconnect cleanup is generator cancellation/return and never mutates a run.

## Delivery scope and deferred replay

A fresh subscription begins with all events available when it opens, including the terminal fact for a late subscription. Sequence and identity make duplicate delivery de-duplicable; clients should tolerate at-least-once delivery. This phase does not inspect `Last-Event-ID`, resume from a cursor, promise replay after disconnect, or build a broker. Phase 5.26 owns persisted replay; 5.28 owns reconnect/resume. There is no partial assistant persistence (5.27), no backend restart recovery (5.30), and no change to cancellation durability.

## Client and UI

`@ava/api-client` owns SSE request/framing/JSON validation in `streamRun`. It exposes typed `RunStreamEvent`, supports `AbortSignal`, and treats a normal close as transport completion rather than run completion. Abort unsubscribes only the stream and never invokes cancellation.

The shared run orchestrator starts a stream after the early run response and de-duplicates by `event_id`. It passes the ordered collected transport events through the existing AVA event processor when the transport closes, preserving the current complete-response rendering and persistence behavior. Its `runEpoch` check remains before state changes, so a superseded stream cannot update a newer run. Stream interruption leaves backend status untouched and surfaces a recoverable live-update error; the snapshot reads used by cancellation remain reconciliation authority.

## Architecture boundaries

The stream route does not create messages, transition status, cancel runs, or interpret provider/runtime data. The lifecycle service still owns status; the repository owns persisted order; the API client owns SSE parsing; and UI code only consumes typed AVA events. No provider SDK type crosses the contract.

## Tests

`test_run_streaming.py` covers early identity, unknown-run rejection, envelope shape/identity/order, completed/failed/cancelled late subscriptions, cancellation facts, and independent multiple subscribers. Existing event/repository tests cover deterministic sequence persistence. API-client and agent-ui tests cover framing, malformed data, abort, terminal handling, and stale-event protection.

Validated for this phase with focused backend suites, the complete frontend workspace (640 tests, with four existing browser integration tests skipped), frontend TypeScript checks, Ruff, mypy, and `git diff --check`.

## Closeout migration

Legacy lifecycle, context-window, persisted-execution, workspace, restart, and configuration tests now assert `202 Accepted` from creation and read `GET /runs/{run_id}` for the terminal status, resolved execution selection, and durable message relationships. SSE tests continue to use the stream only when transport behavior is under test. This preserves the finalized distinction between accepted creation, snapshot authority, and live transport.

## Final closure

The ordinary backend suite completed under the normal repository environment with **1935 passed, 2 skipped, and 4 external-SDK deprecation warnings** (`52.66s`, exit code `0`). All legacy terminal-POST and pre-sequence event equality assertions are migrated. Production callers use accepted identity followed by SSE or authoritative snapshots; no synchronous completion caller remains. Frontend tests and Web/Desktop builds, Ruff, mypy, and `git diff --check` are clean. **Phase 5.25 is fully closed. Phase 5.26 has not started.**
