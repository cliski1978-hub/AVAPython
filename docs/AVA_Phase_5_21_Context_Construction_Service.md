# AVA Phase 5.21 — Context Construction Service

**Status:** Complete. This step gives AVA one owner for *which durable messages
a run may send to a runtime*. It does not add token budgeting, context-window
management, summarization, retrieval, attachment expansion, or tool-message
semantics; those remain later phases.

## The gap this closes

Before this phase, `RunRequest.prompt` was the entire conversational input.
`NativeRuntime` built `ModelRequest(messages=[ModelMessage(role="user",
content=request.prompt)])`, `OpenHandsRuntime` called
`conversation.send_message(request.prompt)`, and the durable conversation,
message, and run graph that Phases 5.19 and 5.20 had just normalized never
reached either runtime. Two turns of a conversation produced two independent
single-message requests.

Both runtime paths now receive the same neutral sequence, built once by AVA.

## Vocabulary

`ava/contracts/conversations.py` owns the cross-boundary types. They are leaf
contracts: no provider, runtime, or persistence type may appear in them.

```text
ContextMessage   role (AVA MessageRole) + content + optional durable message_id
RunContext       conversation_id + source_user_message_id + messages[]
```

`RunContext.messages` is the canonical, already-ordered execution sequence and
the only history a runtime may use. An **empty** `messages` list means the run
has no durable context (a legacy direct `/runs` caller) — never "history was
dropped". `RunContext` is never accepted from a client: it is constructed
in-process from persisted ids and passed down the execution boundary.

## The context policy

`ContextConstructionService` (`ava/services/context_construction_service.py`) is
the only implementation. The rules, in order:

1. **Conversation scope.** Context is built for `run.conversation_id`. The
   message port is conversation-scoped, so another conversation's messages are
   unreachable.
2. **Canonical order.** Messages come from the durable repository in stable
   append order. No timestamp comparison, array position from a client, or
   text comparison decides anything.
3. **The prefix ends at the source user message.** The context is the durable
   prefix that ends with, and includes, `run.source_user_message_id`. The
   source user message therefore appears exactly once, and any earlier answer
   to that same turn — every prior regeneration — is outside the prefix by
   construction.
4. **Collapse consecutive answers.** Within that prefix, consecutive assistant
   messages collapse to the last one. This is the same structural rule the
   conversation transcript uses to render a regenerated turn
   (`selectTranscriptMessages`), so context and what a reader sees agree.
   Collapsing is positional and identity-based, never textual.
5. **Then keep only complete answers.** After collapsing, an assistant message
   remains only if its resolved status is `complete`. Status is resolved from
   the authoritative run; a message with no resolvable run falls back to its
   own stored status, which is the only status a legacy client-authored message
   has. Because collapse happens first, a superseded answer is **not**
   resurrected when a later answer for the same turn failed: that turn
   contributes its user message only.
6. **The current run's placeholder is excluded.**
   `run.assistant_message_id` — the `pending` assistant message Phase 5.20
   creates before execution — is never its own run's context. In the normal
   ordering it is already beyond the prefix; the explicit exclusion is
   defense in depth.
7. **User and system messages are never hidden, reordered, or merged.**

Nothing else is filtered. A message's stored text is passed through as-is:
no attachment expansion, no tool-message interpretation, no summarization.

### One status projection, not two

`assistant_status_for_run(run_status)` in `ava/contracts/conversations.py` is
now the single `RunStatus` → `MessageStatus` projection. `ConversationService`
and `ContextConstructionService` both call it, so a message cannot read
`complete` in the API and be excluded from context (or the reverse). The
private copy inside `ConversationService` was removed.

### Worked examples

| Durable history | New run sources | Context |
| --- | --- | --- |
| `U1` | `U1` | `U1` |
| `U1, A1, U2` | `U2` | `U1, A1, U2` |
| `U1, A1, U2, A2, U3` | `U3` | `U1, A1, U2, A2, U3` |
| `U1, A1, A2, A3` | `U1` (regenerate) | `U1` |
| `U1, A1, U2` | `U2` (regenerate) | `U1, A1, U2` |
| `U1, A1(complete), A2(failed)` | `U2` | `U1, U2` |
| `U1, A1(pending), U2` | `U2` | `U1, U2` |

## Where it runs

```text
POST /runs
  -> RunService.start_run
       validate relationship (5.19 rules, unchanged)
       context = ContextConstructionService.build_for_source(...)   # before any run state is written
       create run row -> create assistant placeholder -> run_started -> running
       AgentPort.start_run(run_id, request, context=context)
         -> AgentRuntimePort.execute(..., context=context)
              -> NativeRuntime / OpenHandsRuntime translate it
```

The existing `AgentPort` and `AgentRuntimePort` boundaries gained one optional
keyword, `context: RunContext | None = None`. No parallel execution-request
object was introduced, and no public API contract changed. `RunService` holds
the narrow capability and forwards the result; it never reads message records
or imports a runtime. A conversation-linked run **requires** the capability: a
`RunService` without one rejects the relationship with
`invalid_run_relationship` rather than silently executing prompt-only.

## The role of `request.prompt`

Decision: **`prompt` remains the public API contract for the current turn's
text, and is never forwarded to a runtime once durable context exists.**

`execution_context_messages(context, prompt)` in
`ava/contracts/conversations.py` is the single place this is decided, and both
runtimes call it. A non-empty `RunContext` wins outright and `prompt` is never
appended to it — the durable sequence already ends with the source user
message, so appending would duplicate the current turn. With no context (a
legacy unlinked `/runs` caller) the sequence is the single prompt, which keeps
existing single-turn behavior byte-identical.

The prompt is still authoritative for the *public* request: the frontend
submits the user's text, the contract validates it is non-blank, and the mock
agent's deterministic output is still derived from it. It is simply no longer a
second execution authority.

## Runtime translations

Neither runtime selects, orders, drops, or re-derives messages. Each only
renders the sequence AVA handed it.

**Native** maps each `ContextMessage` to `ModelMessage(role, content)`. Role
and text are preserved exactly, and the provider request carries the full
ordered turn history.

**OpenHands** is constrained by the pinned SDK 1.47.0:
`LocalConversation.send_message` asserts `message.role == "user"` ("Only user
messages are allowed to be sent to the agent") and the SDK exposes no public
way to seed prior turns. The adapter therefore renders a multi-turn context as
one labelled transcript:

```text
Earlier messages in this conversation (oldest first):

User: U1

Assistant: A1

User: U2
```

Documented fidelity limit: message **order and text are preserved exactly**,
but prior assistant turns reach the model as transcript text inside a single
user message instead of SDK assistant events. A single user message is
forwarded unchanged, so single-turn and legacy prompts are untouched. The
rendering inspects no status, visibility, or conversation state — which
messages belong in the transcript was already decided by AVA — and it persists
nothing and queries no repository.

Parity is therefore semantic: identical ordered content reaches both runtimes,
in each runtime's own request shape. Provider-specific concerns (message
packing, tool calls, context limits) remain downstream and provider-specific.

## Errors

`ContextConstructionError` (a `ValueError`) with deterministic subclasses:

| Error | Condition |
| --- | --- |
| `ContextRunNotFoundError` | no run for the id |
| `ContextConversationNotFoundError` | the run names a conversation that does not exist |
| `ContextSourceMessageNotFoundError` | the source message is missing, or belongs to another conversation |
| `ContextSourceMessageRoleError` | the source message is not a user message |

A linked run never silently degrades to prompt-only. `POST /runs` maps a
`ContextConstructionError` to a deterministic `500`
`context_construction_failed` / `internal` error. Relationship validation
failures keep their existing `422 invalid_run_relationship` mapping. Because
context is built *before* the run row, placeholder, or any event is written, a
failure leaves no half-started run.

## Legacy compatibility

Migration v0008 added nullable `conversation_id`, `source_user_message_id`,
and `assistant_message_id` and backfilled nothing, so historical runs carry
all three as `NULL`. Rules:

- **Unlinked run (all three null).** `build_for_run` returns an empty
  `RunContext`; the runtime uses the single prompt. Unchanged behavior.
- **Linked run with a null source message.** Cannot arise through `RunService`,
  which writes the pair together, but is handled defensively: the context is
  the conversation's own visible transcript (same collapse and complete rules)
  **through its last user message**. Nothing claims to know which turn the run
  continues, so no later answer with no following question is included. A
  conversation with no user message yields no context.
- **Old conversations with valid history.** Fully supported: history is read
  from the existing message rows in append order.
- **Client-authored assistant messages** (no `source_run_id`, e.g. the
  pre-5.19 client `POST` path) keep their stored status, so a stored `complete`
  legacy answer is usable context and a stored `failed` one is not.

## Preserved boundaries

Unchanged by this phase: the public `RunRequest`/`RunResponse` contract and
the OpenAPI schema, execution selection and configuration resolution (5.16),
execution configuration bootstrap (5.17), durable run relationships (5.19),
assistant status projection and the `pending` placeholder (5.20), run event
sequences, cancellation, the frontend transcript rule, and the test-environment
isolation boundary. Frontend behavior needs no change because the public
contract did not change: the backend already owns history, and a client that
posts extra fields cannot influence execution (covered by a test).

## Deliberate non-goals

No context window or token counting, no truncation, no summarization, no
retrieval or document injection, no attachment or tool-message semantics, no
re-prompting or instruction engineering, no changes to how system instructions
are produced. Those are separate phases; 5.22 owns context-window management.

## Tests

`tests/test_context_construction_service.py` (30 tests) pins the policy over
durable graphs: first turn, multi-turn ordering, source-user exactly once,
system messages, collapse-to-latest, positional (not textual) collapse,
non-collapse across turns, every non-complete status, failure not resurrecting
a superseded answer, legacy client statuses, placeholder exclusion,
conversation isolation, determinism across calls, stability against later
appends, and each deterministic error.

`tests/test_context_execution_integration.py` (12 tests) proves the context
reaches execution: a real durable conversation/message/run graph through a fake
Native provider inspecting the provider request; the prompt-duplication
regression where `prompt` equals its own source message; client-supplied
history being ignored; unlinked prompt-only behavior; a failed regeneration
never reaching the model; the run's own placeholder never entering its context;
a linked run without the capability rejected; a broken context reported as a
deterministic 500; the OpenHands controlled SDK seam for the rendered
transcript, byte-identical single turns, and unlinked fallback; and a
cross-runtime parity test.

`tests/test_architecture.py` adds four guards: the context service may import
only contracts and repositories; agents and runtimes may import no repository,
service, API, or infrastructure module; `RunService` may import no runtime and
never lists messages; and the context vocabulary stays a leaf contract.

## Validation

- Full backend suite with the repository `.env`: 1725 passed, 2 skipped.
- Full backend suite in a hostile environment (`env -i`, no inherited `.env` or
  AVA variables): 1725 passed, 2 skipped — the isolation boundary still holds.
- Context-focused suites: 42 passed (30 policy + 12 integration).
- `ruff check .`: clean. `mypy src/ava`: clean (175 source files).
  `git diff --check`: clean.
- Frontend, unchanged but re-verified: `tsc --noEmit` and vitest clean in
  `@ava/contracts` (23 tests) and `@ava/agent-ui` (174 tests).
- No network calls: the Native path uses a fake provider and the OpenHands
  path uses the controlled SDK seam.
