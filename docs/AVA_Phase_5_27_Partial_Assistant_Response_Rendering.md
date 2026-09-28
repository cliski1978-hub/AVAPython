# AVA Phase 5.27 — Partial Assistant Response Rendering

## Status

Phase 5.27 is complete. Partial assistant text is durable, reconstructable from conversation snapshots and run-event replay, and rendered in the existing assistant message while its run remains active.

## Behavior before Phase 5.27

Before this phase, `message_started` and one `message_content` fact were emitted only after an agent returned successfully. The event's `content` field was the complete final response. A linked run's durable assistant placeholder remained empty until completion, when `RunService` replaced its content. The frontend buffered every SSE event until the stream closed and then applied the final content to local state. Live accumulation was therefore ephemeral or absent; refresh during execution recovered an empty placeholder, while replay contained content only after completion.

Native and OpenHands both returned final-only `RuntimeRunResult.content`. Neither runtime exposed a genuine provider-neutral incremental-output interface. OpenHands extracted only the final public agent text from SDK state. The frontend treated `message_started` as informational and kept its own temporary message ID rather than adopting the durable backend ID.

## Ownership decision

The durable assistant `Message.content` is the single authority for current assistant text. `RunEvent` records immutable, ordered facts describing the same content progression. Frontend state is a render projection/cache.

```text
normalized runtime content snapshot
    -> AssistantResponseService
    -> durable assistant Message.content
    -> persisted message_content RunEvent
    -> SSE/replay observers
    -> frontend projection
```

No partial-message entity, client-owned transcript, or second durable content store was added.

## Assistant placeholder and identity

The Phase 5.20 placeholder remains the one durable assistant message from run creation through settlement. `run.assistant_message_id` and `message.source_run_id` retain their existing two-way ownership relationship. `message_started` is now persisted immediately after `run_started` and identifies that message:

```json
{"message_id":"...","role":"assistant"}
```

For legacy unlinked runs, AVA still allocates one event-level message identity without creating a conversation message. Linked runs always use the durable message ID.

The frontend initially creates an optimistic local bubble, then rekeys that same bubble to `RunResponse.assistant_message_id`. Content is routed by run ID and message ID rather than array position, timestamps, text, or “last assistant” inference.

## Content semantics and payload

`message_content` uses **snapshot semantics**. Each event carries the complete assistant text persisted so far:

```json
{"message_id":"...","content":"Hello wor"}
```

The existing `content` field is retained and made explicit, preserving replay compatibility with Phase 5.26 events. No event-version system or migration is needed. A runtime may report a character, multiple tokens, a sentence, or a final blob; AVA makes no tokenizer assumption.

Empty snapshots are ignored. Repeating an identical snapshot is also a no-op, so callback retry does not create another durable write or event. Unicode content is stored and replayed exactly.

## AssistantResponseService

`AssistantResponseService` is the single application write path. It:

- confirms the run exists and remains active;
- confirms `run.assistant_message_id == message_id` for durable messages;
- confirms the message is an assistant linked back through `source_run_id`;
- suppresses empty and identical snapshots;
- replaces the durable current content snapshot;
- appends one matching `message_content` event;
- rejects cross-run ownership with a typed error;
- ignores content arriving after completion, failure, or cancellation.

The module keeps `RunService`, runtime adapters, SSE, replay, and routes from duplicating content rules.

## Repository behavior

The existing `MessageRepository.update_content` operation is the canonical snapshot replacement. The in-memory adapter replaces an immutable `MessageRecord`; the SQLite adapter performs one transactional `UPDATE` and reads back the stored row. Identity, role, source run, created time, and append order do not change.

Snapshot replacement avoids a read-concatenate-write race and matches the existing persisted event shape. SQLite writes remain protected by the database object's transaction lock. No content-version column is required because persisted run-event sequence provides progression order and the message row stores only the current snapshot.

## Runtime integration

`AgentPort.start_run_streaming` and `AgentRuntimePort.execute_streaming` are backward-compatible optional streaming entry points. Their default implementations call the existing final-only methods and emit no callback. A runtime with genuine incremental output may override the method and report AVA-normalized full-text snapshots through `on_content`.

`NativeAgentAdapter` forwards the callback to its selected runtime without interpreting provider data. `NativeRuntime` remains final-only because `ModelProviderPort.generate` currently returns one `ModelResponse`; its final text is reconciled by `RunService` through the same `AssistantResponseService` path.

`OpenHandsRuntime` also remains honestly final-only. The pinned SDK path currently provides a final public agent message after `conversation.run`; AVA does not fake token streaming or expose SDK event types. Its final content follows the same reconciliation path.

The mock adapter can emit deterministic snapshots for tests. This is test behavior and does not claim a provider capability.

## Final-only fallback and reconciliation

Non-streaming providers remain fully supported:

```text
run_started
message_started
message_content(full final snapshot)
run_completed
```

If a streaming runtime's final result equals the last persisted snapshot, reconciliation is a no-op. If it differs, the final result deterministically replaces the current message snapshot and appends one final content fact before `RunStatus.COMPLETED`. Chunks and final output are never concatenated, preventing `HelloHello` duplication.

## Write and event ordering

For every snapshot:

```text
validate active run/message ownership
    -> persist Message.content
    -> append message_content RunEvent
    -> SSE observes persisted event
```

Final reconciliation finishes before the completion transition. SSE continues to poll persisted events, so no ephemeral callback reaches a subscriber before persistence.

The message and event repositories still lack a cross-repository unit of work. A crash can leave newer durable message content without its matching event. The reverse cannot occur through this module: replay never claims content that was not written to the message first. Reads do not synthesize repair events. A generalized unit-of-work framework remains outside this phase.

## Snapshot, replay, SSE, and restart

Conversation snapshot reads expose the current `Message.content`. While its run is active, Phase 5.20 status projection returns `streaming`; the stored message status remains a creation placeholder and does not become a second lifecycle authority.

Replay returns every persisted snapshot in per-run sequence order. Reducing snapshot events means taking the newest applicable `content`; the result equals the durable assistant snapshot whenever no crash gap exists. Exclusive cursor semantics remain unchanged.

SSE emits those same persisted envelopes. Tests compare event identity, sequence, payload, message ID, and order across two subscribers and replay. Subscriber count never creates events.

A file-backed restart test preserves `Message.content == "Hello wor"`, the identical event log, and `RunStatus.RUNNING`. It deliberately does not recover or settle execution.

## Terminal outcomes

Cancellation and failure retain all content persisted before settlement. The message projects `cancelled` or `failed` from authoritative `RunStatus`; partial text remains visible as truthful history and is not presented as complete. A late callback after any terminal outcome is ignored without changing the message or appending an event.

Successful completion keeps the same assistant message and makes its final durable snapshot exact. Cancellation-request history remains independent of terminal outcome.

## Frontend rendering and reconciliation

The shared event processor applies each persisted SSE event as it arrives. `run_started` changes the existing assistant bubble to `streaming`; `message_content` replaces its text snapshot; terminal events settle the same bubble. Empty active content retains the current loading indicator. Partial text, including incomplete Markdown-like text, is rendered as safe plain/pre-wrapped content by the existing renderer.

The orchestrator validates:

- event `run_id` matches the active backend run;
- `event_id` has not already been delivered;
- sequence advances beyond the last applied event;
- the event's `message_id` matches the run's durable assistant message;
- `runEpoch` still identifies the current frontend run.

Duplicate or older delivery cannot duplicate or roll back text. A stale run cannot mutate a newer response. Hydration merges by stable backend message ID, so an authoritative snapshot replaces the matching local projection. Because SSE observes only persisted events, normal live state cannot be ahead of message persistence.

Switching conversations aborts only the local stream subscription. It does not cancel the backend run. Persisted content continues to belong to its durable assistant message, and returning to the conversation loads the latest snapshot. Retry and regenerate behavior is unchanged.

## Context behavior

Active, pending, failed, and cancelled assistant messages remain excluded from model context under the Phase 5.21 policy. Partial output is output state, not context-window input. A successfully completed assistant becomes eligible normally. Phase 5.22 budgeting and truncation are unchanged.

## Schema and operational impact

No schema migration or data backfill is required. The existing message text column stores current partial snapshots, and the existing event payload remains backward compatible. Genuine high-frequency streaming can increase event volume; retention, compaction, and batching are intentionally deferred.

## Architecture guards

Tests pin these ownership rules:

```text
Message.content             = durable current assistant content
RunStatus                   = lifecycle authority
AssistantResponseService    = content mutation authority
RunEvent                    = ordered durable fact
message_content             = one message-owned full snapshot
runtime/provider adapters   = normalized output reporters only
SSE/replay routes           = persisted-fact observers
frontend                    = projection/cache
terminal run                = rejects late content
```

All prior provider/runtime, lifecycle, persistence, streaming, replay, context, and frontend architecture guards remain active.

## Validation

- Focused backend Phase 5.27 matrix: `548 passed`, with four existing external SDK deprecation warnings.
- Frontend affected packages: contracts `23 passed`, API client `78 passed`, agent UI `183 passed`, workspace `52 passed` with four existing opt-in live integration skips.
- Repository-wide frontend lint/type checking: `pnpm -r lint` passed.
- Production builds: `pnpm --filter @ava/web build` and `pnpm --filter @ava/desktop build` passed. Both reported only Vite's advisory for a minified chunk larger than 500 kB.
- Backend lint: `.venv/bin/ruff check .` passed with `All checks passed!`.
- Backend type checking: `.venv/bin/mypy src/ava` passed with `Success: no issues found in 179 source files`.
- Full backend suite: `backend/.venv/bin/pytest -q` completed with exit code `0`: `1957 passed, 2 skipped, 4 warnings in 51.66s`. The skips are the existing opt-in tests; all warnings are the existing OpenHands SDK deprecation warning.
- Patch integrity: `git diff --check` passed.

## Phase 5.28 handoff

Phase 5.28 may add reconnect/resume using the completed durable primitives: authoritative conversation snapshots, stable assistant message IDs, persisted event IDs, and exclusive per-run sequence cursors. It should resume after the client's processed sequence, de-duplicate by event ID, reconcile with the current message snapshot, and preserve `runEpoch`/run ownership checks. Phase 5.27 adds no `Last-Event-ID`, automatic retry, reconnect loop, or transport recovery behavior.
