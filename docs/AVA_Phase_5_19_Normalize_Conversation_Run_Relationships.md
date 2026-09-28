# AVA Phase 5.19 — Normalize Conversation / Run Relationships

**Status:** Complete.  This step normalizes durable IDs only; it does not add
message lifecycle states, streaming, replay, reconnect, cancellation redesign,
or context construction.

## Pre-5.19 model

Conversations/messages and runs/events were independently durable.  A message
could carry optional `source_run_id`, but `runs` had no conversation, source
user message, or assistant response identity.  The frontend created a local
assistant placeholder and inferred its source user message during hydration.
The backend could not reliably reconstruct which conversation caused a run.

## Normalized model

`runs` now owns three nullable stable AVA IDs:

```text
Run.conversation_id
Run.source_user_message_id
Run.assistant_message_id
```

For a conversation-originated run they form:

```text
Conversation -> source user Message -> Run -> assistant Message
                                      -> RunEvent*
```

`RunEvent.run_id` was already correct and remains the event ownership link.
`messages.source_run_id` remains the reverse link from a generated assistant
message to its producing run.  No conversation object, message content, array
position, timestamp, or frontend temporary id is duplicated as authority.

Legacy direct `/runs` callers remain supported: all three new columns are
nullable when the caller has no conversation context.  The migration never
guesses missing relationships for historical rows.

## Creation and consistency

`RunRequest` accepts `conversation_id` and `source_user_message_id` together.
`RunService` validates that the conversation exists, that the source message
belongs to it, and that its role is `user`.  A partial pair, a cross-conversation
message, or an assistant/system source is rejected with normalized `422
invalid_run_relationship` output.

For a linked successful run, `RunService` creates exactly one durable assistant
message, records its `source_run_id`, writes the new `assistant_message_id` to
the run, and emits that same message id in `message_started` and
`message_content`.  The database enforces that no two runs can name the same
non-null assistant message.  Run/message creation remains separate repository
writes, so this step does not claim full lifecycle atomicity; Phase 5.23 owns
transactional lifecycle normalization.  The order avoids a visible completed
linked run without first creating its durable assistant response.

The existing run-event repository continues to persist every event under one
run id in monotonic sequence order.  No event schema or replay behavior changed.

## Migration and compatibility

Migration **v0008** adds nullable `conversation_id`,
`source_user_message_id`, and `assistant_message_id` columns to `runs`, plus
lookup indexes for conversation and source message and a partial unique index
for assistant message.  It is additive and preserves every existing row.  Old
runs therefore remain explicitly unlinked instead of receiving fabricated
relationships.

## API and frontend

`RunRequest` and `RunResponse` now expose the three relationship ids.  They are
backward-compatible optional fields.  The shared conversation UI sends its
already durable conversation and user-message ids when starting a run.  When a
response reports a durable assistant id, it keeps the local placeholder for
the live terminal snapshot but skips the old client-side assistant `POST`; a
subsequent hydration reads the server-owned assistant message.  Execution is
still omitted for Application Default and is only sent for explicit Auto or
custom/profile selection.

## Regenerate and visible history

Regenerate creates a new run and a new assistant message for the original user
message.  Earlier assistant messages and runs stay append-only and durable:

```text
U1 -> Run1 -> A1
U1 -> Run2 -> A2
U1 -> Run3 -> A3
```

The existing derived transcript rule is unchanged: durable `U1, A1, A2, A3`
continues to render `U1, A3`.  No `is_visible` field or second transcript is
stored.

## Restart reconstruction

After reopening SQLite, `GET /runs/{id}` returns the same conversation, source,
and assistant IDs; conversation messages retain their reverse `source_run_id`;
and events retain their owning run id and sequence.  This removes frontend-only
knowledge from relationship reconstruction.  Active-run recovery itself remains
Phase 5.29 work.

## Preserved architecture and next steps

`RunService` remains isolated from concrete persistence, conversation services,
stores, providers, runtime selection, and frontend state.  It uses only the
existing conversation/message repository ports to validate and persist stable
relationship facts.  No message statuses were added or reinterpreted.

Phase 5.20 can now define message lifecycle states for a known durable
assistant response.  Phase 5.21 can build context from a known source message
and durable history, but still needs its own explicit context policy and window
budgeting.
