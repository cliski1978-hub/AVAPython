# AVA Phase 5.32 — Stale Event Protection

## Ownership model

Stale work is a valid result for UI ownership that has since been superseded.
It is ignored, rather than treated as a protocol error. AVA uses scoped,
frontend-only ownership dimensions:

```text
conversation load generation -> runEpoch -> run ID/message ID -> event sequence/event ID
```

Conversation load generation protects repeated selection of the same
conversation as well as A-to-B navigation. `runEpoch` protects a newer run in
the same conversation/source-user lineage. Run and assistant-message IDs route
execution facts. Event ID de-duplicates one persisted fact; per-run sequence
orders distinct facts. These dimensions are deliberately separate.

## Existing run protection, formalized

`conversationRun` captures a run epoch before every asynchronous start,
recovery, retry, regenerate, cancellation, event, and reconciliation path.
`isRunCurrent` checks it before state mutation. Event application additionally
requires the expected run and assistant message ID, while `runStreamResume`
accepts only contiguous sequences and serializes one stream attempt at a time.
An AbortController stops observation, but ownership checks remain mandatory
because aborted or mocked work may still resolve late.

Retry/regenerate invalidates and aborts the old observer before binding the new
run. Late old events, terminal events, snapshots, cancellation results, and
errors cannot settle or paint the newer run. A valid recovery-time terminal
event for the still-current run remains accepted.

## Conversation loading

`ConversationProvider` now assigns every explicit selection a local load
generation. A result or failure applies only when both the selected conversation
ID and captured generation still match. This closes the A -> B -> A race where
the first A request could otherwise overwrite the later A request. The
generation is not persisted and does not affect backend state.

## Snapshot and reconnect ordering

Snapshots reconcile only while their captured run epoch remains current. Stream
events advance sequence only after application. Reconnect attempts are
serialized by the shared observer loop; terminal events and intentional aborts
end the loop before a delayed retry can open a replacement stream. Older
bootstrap content remains suppressed by the Phase 5.29 durable-snapshot rule.

## Boundaries

No schema, API, local-storage, timestamp, content, or array-position freshness
heuristic was added. Backend lifecycle CAS and assistant-message ownership keep
late runtime callbacks from altering terminal or different-run state. Protocol
violations (wrong run/message, conflicting ID, reused sequence, or gaps) remain
errors/corrective resume cases, distinct from valid stale UI work.

## Validation and handoff

Focused Agent UI and workspace tests cover stale run epochs, wrong ownership,
strict sequence handling, observer abort, recovery lookup protection, retry/
regenerate supersession, and stale conversation selection. Phase 5.33 should
address conversation-level concurrency policy; it must not weaken these local
ownership boundaries.
