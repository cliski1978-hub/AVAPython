# AVA Phase 5.22 — Context Window Management

Phase 5.21 decided *which* durable messages a run may send. It did not decide
how much of that context a model can actually accept: a conversation that is
perfectly eligible can still exceed the selected model's context window, and
until this phase AVA sent the whole thing and let the provider reject it.

This phase adds the missing half. AVA measures the eligible context against the
selected model's context window, keeps the most recent whole turns that fit, and
fails a request that cannot fit at all — before any provider is called, for
either runtime.

## The gap this closes

Before this phase:

- The provider was the only component that knew a request was too large. The
  failure arrived as a vendor error, after workspace setup, after resource
  acquisition, and shaped like a provider problem.
- Nothing in AVA could tell whether a long conversation was safe to send, so
  there was no place to add a policy, no way to test one, and no way to reason
  about the tradeoff between old history and the current question.
- The two runtimes were free to diverge: each one received the full context and
  could have made its own trimming decision.

After this phase:

- One AVA-owned policy decides the bounded sequence, in one pure module, before
  the runtime boundary.
- The limit comes from the model that was actually selected for the run.
- An impossible request is a deterministic, typed failure with no provider call.

## Vocabulary

- **Context window** — the total number of tokens a model accepts, covering both
  the input it is sent and the output it generates.
- **Input budget** — the context window minus the output reserve: the number of
  input tokens AVA may spend.
- **Output reserve** — headroom AVA leaves for the generated answer.
- **Eligible context** — the sequence Phase 5.21 produced: lifecycle-filtered,
  collapsed, ordered, ending at the run's source user message.
- **Bounded context** — the eligible context after windowing: the longest recent
  suffix of whole turns that fits the input budget.
- **Turn** — a user message plus the assistant (or system) messages that answer
  it. This is the structure Phase 5.21 leaves behind after collapsing
  regenerations.
- **Preamble** — messages appearing before any user message. In practice a
  leading system instruction, which is kept and billed separately from history.

## Where the limit comes from

The budget follows the model selected by the backend:

- `ModelConfiguration.context_window_tokens` is the optional AVA-owned model
  setting. It is stored with the configured model and cannot be overridden by a
  run request.
- `ModelInfo.context_limit` remains an authoritative provider-reported maximum
  when available. The effective limit is the lower of that maximum and the
  configured value. With no configured value AVA uses the provider maximum; if
  neither is usable, the existing unbounded compatibility behavior applies.
- The resolved `ModelProfile` carries the configured value, so the same rule
  applies to application, Project, and explicit model selections.
- `ModelRequest.max_output_tokens` exists but AVA sets it nowhere today. There is
  no production output-token configuration, so the reserve is AVA's policy
  constant rather than a request value.

### Provider metadata availability

The context window is reported by a *provider adapter*, not by a model profile.
Today each provider instance is built for one configured model, so the reported
window is accurate for the model that provider serves. If a provider adapter
serves several models, the per-model AVA setting supplies the window and the
provider's metadata still constrains it when available.

`ModelDiscoveryService` does not currently surface `context_limit` on `/models`.
The Settings editor therefore allows a model window to be entered directly;
runtime preview and execution still apply any provider maximum on the backend.

### An unknown limit is not a failure

A model that reports no usable limit (`None` or a non-positive value) executes
with its full eligible context, exactly as before this phase. This is a
deliberate compatibility choice, not an oversight:

- Refusing to run would make a missing metadata field a hard outage.
- Guessing a window would let AVA truncate a conversation on a number it invented.
- The provider remains the authority that rejects oversized input, which is the
  pre-existing behavior.

The operational consequence is documented, not hidden: an unconfigured window
means AVA does not trim, so a long conversation on such a model can still fail
at the provider. The fix is provider configuration, not a policy change.

## The estimate

AVA ships a deterministic, model-agnostic estimate. It is not a tokenizer, and
the module deliberately has no tokenizer dependency:

```
tokens(message) = 4 + ceil((ascii characters + 3 × non-ASCII characters) / 4)
```

- `CHARS_PER_TOKEN = 4` — average characters per token for ordinary prose in a
  byte-pair vocabulary.
- `NON_ASCII_CHAR_COST = 3` — non-ASCII code points are charged three times a
  Latin character, because non-Latin scripts and emoji commonly cost one to
  three tokens each.
- `MESSAGE_FRAMING_TOKENS = 4` — a fixed per-message allowance for the chat
  framing a provider adds, so a conversation of many short messages does not
  estimate as nearly free.

The estimate is additive, so a turn's cost is the sum of its messages' costs and
a prefix is never measured differently from the same messages alone. The two
biases both point the safe way: it over-estimates rather than under-estimates,
which trims slightly early, and it never depends on a favorable vendor
vocabulary.

`TokenEstimator` is a port. A future model-specific or vendor-supplied counter
implements it and is injected into `ContextWindowManager`; the policy itself
never imports a tokenizer. The shipped estimator ignores `model_id` on purpose —
the policy is model-agnostic by design, and the model id exists for a future
model-aware implementation and for failure diagnostics.

## The budget

A model's window covers input *and* output, so spending all of it on input would
leave the model nothing to answer with:

```
input_budget = context_limit - output_reserve
```

- `DEFAULT_OUTPUT_RESERVE_TOKENS = 1024` — the reserve when no request
  configures an output-token limit, which is every request today.
- `MAX_OUTPUT_RESERVE_FRACTION = 0.25` — the reserve never exceeds a quarter of
  the window, so a small model still has a usable input budget instead of
  rejecting every run. The cap applies to an explicit reserve too: no caller may
  reserve away the entire input budget and turn every run into a hard failure.
- A negative explicit reserve is a `ValueError`.

`input_budget_for` is a pure function of two integers, and `ContextWindowResult`
reports the budget, the limit, the post-windowing estimate, and the number of
dropped messages and turns. Nothing in execution reads those diagnostic fields
to make a decision; they exist for logging, tests, and a future UI indicator.

## The trimming policy

1. **Whole messages only.** A response is never cut mid-text, so an answer can
   never be separated from its question.
2. **Whole turns, oldest first.** The context is partitioned into a preamble and
   turns, then the longest recent suffix of turns that fits the budget is kept.
   Trimming is deterministic: identical input yields an identical sequence.
3. **The current turn is never dropped.** The run's source user message and
   everything grouped with it are mandatory. If the mandatory context alone
   exceeds the budget, the run fails rather than truncating or discarding the
   user's question.
4. **The preamble is mandatory.** Leading system messages are instructions, not
   history: they are always kept and always billed. Nothing in AVA creates or
   edits a system instruction, and a preamble that does not fit is a failure
   like any other mandatory content.
5. **Eligibility is never revisited.** The manager uses the sequence it is given.
   A message Phase 5.21 excluded — superseded, incomplete, cancelled, orphaned —
   cannot reappear because trimming only ever removes from the front.

A result that fits, or a model with no reported window, returns the messages
unchanged, so a short conversation is never rewritten.

## Where it runs

Windowing happens in `NativeAgentAdapter`, above the runtime boundary:

1. Resolve the execution (runtime, model profile, binding, provider).
2. Validate execution compatibility.
3. Read the selected model's context window.
4. Window the effective sequence: the durable context when the run has one,
   otherwise the request's single prompt.
5. Resolve the workspace, acquire the model lease, and call
   `runtime.execute` with the bounded context.

Both runtimes are dispatched from this one call site, so Native and OpenHands
receive the identical bounded sequence and then apply their own existing
translation. A runtime importing the manager is an architecture-test failure:
a second trimming site would let the two runtimes send different histories for
the same conversation.

`RunService` is unchanged. Context construction stays upstream of windowing, and
the run lifecycle never learns the size of a context.

### The unlinked prompt path

A legacy `POST /runs` with only a prompt still works exactly as before. The
prompt is measured against the budget — an impossible prompt fails the same way —
but `None` is passed to the runtime so its prompt-only fallback is untouched. A
linked run keeps its conversation id, source message id, and per-message ids.

## Failures

`ContextWindowExceededError` is a distinct typed failure, not a configuration
error: a model can be perfectly configured and still be unable to accept a
particular request. The error carries only safe size metadata — estimated size,
available budget, and the model id — never message content, so it is safe to log.

`NativeAgentAdapter` catches it and returns a failed run with
`"Request exceeds the selected model's context window"`, alongside the existing
execution-unavailable and incompatible-configuration failures. The window check
therefore happens before workspace resolution, before resource acquisition, and
before any provider call: a request that cannot fit never reaches a vendor.

No new run lifecycle, event, or status semantics are introduced. The run fails
through the existing `run_started` → `run_failed` path.

## Preserved boundaries

- `ContextConstructionService` is untouched. Eligibility is still decided from
  durable records, and it still returns the full eligible context.
- The neutral context vocabulary is unchanged: `ContextMessage` and `RunContext`
  still cross every boundary as data.
- Runtime translation is unchanged. Neither runtime knows about budgets.
- The model configuration surface is unchanged. No client can define a window.
- Persistence is unchanged. Nothing about windowing is stored: the durable
  transcript remains complete, and a run's context can be reconstructed from
  records at any time.
- The agent adapter still imports only contracts and execution policy; the
  manager imports only the neutral context contract and the standard library.

## Deliberate non-goals

- No summarization, condensation, or retrieval to fit more history in. Trimming
  is the whole policy; a future summarization phase would sit downstream of the
  same budget decision.
- No per-message or per-response truncation.
- No tokenizer dependency and no vendor vocabulary.
- No persisted context-window value on a model definition.
- No new configuration, environment variable, or request field.
- No change to the model discovery contract or the frontend.
- No change to cancellation, streaming, or reconnect behavior.

## Tests

`tests/test_context_window.py` (33 tests) pins the policy as a pure function:
estimate determinism and additivity, empty and non-ASCII cost, model-agnostic
behavior, a replaced estimator, unknown and invalid limits, reserve arithmetic and
the cap, no-reserve, exact-fit acceptance, one-token-over trimming the oldest
turn, whole-turn and whole-message removal, source message exactly once, an
answer never orphaned from its question, a kept and billed system prompt,
determinism, no input mutation, regenerate collapsing to one visible answer,
ineligible messages never reintroduced, oversized current/leading/system content
failing with a typed error that carries no content, oversized history dropped
whole, and a context of only a system prompt never dropped.

`tests/test_context_window_integration.py` (10 tests) proves the wiring over the
real path — durable conversation/message/run graph, real `ExecutionSelector`,
real `NativeAgentAdapter`, fake providers, and the controlled OpenHands SDK seam:

- Two configured models with different reported windows bound the same
  conversation differently, which is the proof that the budget is not a global
  constant.
- Omitted and explicit execution produce identical bounded context for the same
  model, so the override changes the budget only by selecting a different model.
- A model reporting no window runs with its full eligible context.
- An impossible request fails with the provider never called and only
  `run_started` → `run_failed` events.
- An oversized old turn is dropped instead of failing.
- Native and OpenHands receive the same bounded sequence and each drops nothing
  further; the dropped turns are absent from the rendered transcript.
- Selecting the OpenHands runtime through a run override still produces a bounded
  prompt, which is only possible because windowing precedes runtime dispatch.
- Regeneration through windowing still shows one visible answer per turn.
- The unlinked prompt path is unchanged.
- The estimate that drove the decision describes the request that was sent, and
  the full eligible context really was larger.

`tests/test_architecture.py` adds four guards: the manager imports only the
neutral context contract and the standard library; the window path reaches no
provider implementation, infrastructure module, or provider registry; no runtime
may import the manager; and the policy lives in `ava.execution`, not in
`ava.services` or the contracts package.

## Validation

- Context-focused suites: 55 passed (33 policy + 10 integration + 12 Phase 5.21
  execution-integration regressions).
- Architecture suite: 109 passed.
- Full backend suite with the repository `.env`: 1772 passed, 2 skipped.
- Full backend suite in a hostile environment (`env -i`, no inherited `.env` or
  AVA variables): 1772 passed, 2 skipped — the isolation boundary still holds.
- `ruff check .`: clean. `mypy src/ava`: clean (176 source files).
  `git diff --check`: clean.
- Frontend, unchanged but re-verified: `tsc --noEmit` and vitest clean in
  `@ava/contracts` (23 tests) and `@ava/agent-ui` (174 tests).
- No network calls: the Native path uses a fake provider and the OpenHands path
  uses the controlled SDK seam.

## Follow-ups this phase deliberately leaves

- Configure `context_limit` on production providers so windowing is active rather
  than permissive in real deployments. This is configuration work in
  `ModelProviderFactory`, not policy work.
- If one provider adapter must serve several models, add a per-model capacity
  source and change only what `_context_limit` reads.
- If `/models` should report context windows to clients, that is a discovery
  contract change with a frontend consumer, and it belongs to its own phase.
- A model-aware estimator can be added by implementing `TokenEstimator`; no
  policy change is required.
