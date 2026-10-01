# AVA Phase 5 reopened P1 remediation

Phase 5 was reopened for two frontend ownership defects. Phase 6 has not started.

## Defect A: stale cancellation

`cancelActiveRun` could apply a late cancellation result from Run A after Run B
became current. The cancellation path now receives Run A's existing `runEpoch`
and checks ownership after every awaited cancellation/event boundary before
changing state, messages, errors, or applying events.

Regression coverage uses deferred cancellation promises for both a late success
and a late error. Before the guard, both tests changed Run B from `running` to
the old result; with the guard, Run B's identity, epoch, phase, message id, and
error remain unchanged. Removing the ownership guard makes those tests fail.

## Defect B: fresh-mount recovery

This is a test-seam and ownership-model gap, not a backend, API-contract, or
persistence gap. Hydration preserves an assistant message's durable
`source_run_id`, status, content, and message id; recovery derives the run
identity from that message and reads the run snapshot. A hydrated run identity
does not prove that a new provider session owns an observer. Recovery now
suppresses duplicate work only when this provider has an in-memory stream
controller.

`conversation-selection.test.tsx` mounts the public workspace/provider tree
from backend-shaped conversation, message, and active-run responses. It proves
that partial durable content remains visible, no POST run or placeholder is
created, and recovery observes the existing `source_run_id`.

## Validation

Focused validation passes: agent-ui has 207 passing tests and workspace has 57
passing tests with 4 skipped integration tests. The active/terminal recovery
matrix, duplicate-observer proof, targeted mutation evidence, and canonical
re-certification remain required before Phase 5 can be re-certified.

## Defect B mutation proof and re-certification

The permanent guard suppresses recovery only when this provider owns an
in-memory `streamController`. The public fresh-mount workspace regression
passes with that guard. For mutation, the guard was temporarily expanded to
treat `visibleRecoveryCandidate(activeConversation)` — durable assistant/run
identity — as observer ownership. The targeted public test then failed because
`getRun(client, "run-existing")` received zero calls: a fresh provider skipped
recovery. The guard was restored and the public recovery and duplicate-observer
cases passed again.

Defect A has corresponding mutation evidence: removing its post-cancellation
ownership guard made the late-success regression change Run B to `cancelled`.
After restoration, its 207-test Agent UI suite passed.

The public recovery matrix covers pending, running, waiting-for-approval,
completed, failed, and cancelled snapshots. It preserves hydrated partial
content, avoids new runs/placeholders, and suppresses a second observer after
the same provider rerenders. Workspace finished at 63 passed and 4 skipped;
Agent UI finished at 207 passed. `pnpm lint` and `git diff --check` passed.
The user-reported canonical `./scripts/test_all.sh` run passed after the
production fixes. Phase 5 is re-certified; Phase 6 has not started.

## Defect C: non-latest regenerate visibility

A regenerate of an earlier assistant response appends its new assistant row at
the end of durable message history. The frontend transcript projection had
collapsed adjacent assistant rows, which only works when a regenerated turn is
the latest turn. For `U1/A1/U2/B1/A2`, it retained A1 and replaced B1 with A2.

The durable backend lineage was correct: A2's run reused Run A's source user
message and Run B remained unchanged. The correction projects assistant
versions by their durable source user-message identity and returns that identity
on message reads. Hydration therefore uses the run-derived source identity
instead of inferring A2's turn from the user message immediately before its
append position.

`conversation-selection.test.tsx` covers the public two-turn workspace path,
including refresh: regenerating A leaves only A2 visible for the first turn and
preserves B unchanged for the second. `test_run_attempts.py` verifies A2, B,
and their source relationships over relational persistence. A mutation that
restored positional/latest replacement made the workspace regression fail.
Retry shares this projection, so `transcript.test.ts` also locks the same
non-latest replacement invariant independently of the completed-run regenerate
eligibility rule.

## Defect D: native streaming was final-only

Charter B validation found that the native agent entered the inherited
`execute_streaming` fallback. That fallback discarded its callback and called
one-shot generation, so local OpenAI-compatible models could never publish a
durable partial response.

`ModelProviderPort.stream` now carries provider-originated text deltas. The
OpenAI-compatible adapter consumes SSE `data:` frames and NativeRuntime
accumulates those deltas into full-content snapshots for the existing run-event
and durable-message path. No new message is created per chunk; the final
runtime result equals the final persisted snapshot. A gated live Ollama run
received nine chunks before completion for `qwen2.5-coder:7b`.

The first streaming implementation exposed a compatibility regression in six
bootstrap/persisted-execution tests: callback presence alone selected SSE for
models declared final-only. NativeAgent now uses the selected model profile's
`capabilities.streaming` as the execution boundary. Final-only models retain
`generate()`; explicitly streaming models use provider SSE.

## Native streaming final certification attempt (2026-09-30)

The fresh canonical harness passed after the capability-aware dispatch fix:
2,154 backend tests passed, 2 opt-in OpenHands live tests skipped, and the only
four warnings were the existing OpenHands SDK deprecation warnings. Backend
Ruff and mypy passed. All frontend package tests and lint/type checks passed;
the workspace package retained its four intentional live-backend skips. The
Python client passed 10 tests plus Ruff and mypy. Web and Desktop builds passed
with the existing Vite chunk-size advisory, and `git diff --check` passed.

The real web UI confirmed the expected persisted stack before testing:
`ollama-local` at `http://localhost:11434/v1`, model
`qwen25-coder-7b` mapped to `qwen2.5-coder:7b`, Native Runtime, and declared
streaming capability. A new deliberately long request entered the active
"AVA is responding…" state, then failed before any partial assistant content
was displayed. Consequently no refresh was performed while a partial response
was active, and the same-run/message recovery, prefix de-duplication, final
durable-content comparison, and post-completion refresh criteria were not
exercised.

**Charter B end-to-end: FAIL.** The live native/Ollama request fails before its
first streamed partial, despite the configured streaming-capable stack and
green automated coverage. **Phase 5 remains reopened. Phase 6 has not
started.**

## Defect E: partial execution selection collapsed to bootstrap defaults

### Observed behavior

With the composer on `Profile: Application default` the run resolved the
persisted application defaults. With `Profile: Custom / Runtime: OpenHands /
Model: Legacy default` the run appeared to behave like the default local/native
Qwen path, which suggested the explicit runtime had been dropped.

### What the composer values actually were

`Profile: Custom` is not a user choice. `ExecutionControls.tsx` renders
`<option value="custom" disabled>`, so it is a display-only grouping state that
`AppWorkspace.tsx` sets programmatically whenever a runtime or a model is
chosen. `Model: Legacy default` is the label of the empty-value option, shown
whenever the profile is no longer `application-default`; it means "this axis is
unset", and the model axis is a *provider* selector keyed by `provider_id`, so it
sends `model_provider_id` and never `model_id`. The request the UI actually
sent was therefore exactly `{"runtime_id": "openhands"}` — a correct, partial,
explicit selection. Nothing was dropped in the frontend or lost in the API
request.

### Root cause

`ExecutionSelector.resolve` validated persisted defaults but then discarded the
whole resolved configuration whenever any override was present, rebuilding every
axis from the bootstrap catalogs. The runtime axis was re-resolved by registry
adapter key and happened to survive, so the explicit runtime was honored — but
the model axis fell to the bootstrap default profile. The run executed the same
underlying model while recording a *different model identity*, a null
`provider_connection_id`, and `source=bootstrap`.

Live evidence against the persisted configuration (native / `qwen25-coder-7b` /
`ollama-local`), from `GET /runs/{run_id}`:

| `POST /runs` execution | recorded `model_id` before | recorded `model_id` after |
| --- | --- | --- |
| omitted | `qwen25-coder-7b` | `qwen25-coder-7b` |
| `{"runtime_id":"openhands"}` | `local-qwen2.5-coder:7b` | `qwen25-coder-7b` |
| `{"model_provider_id":"local"}` | `local-qwen2.5-coder:7b` | `local-qwen2.5-coder:7b` |

The durable audit record was wrong: a run that used the operator's configured
model was attributed to a bootstrap model, and the configured provider connection
was dropped from the selection.

### Fix

`ExecutionSelector` now treats an override as partial and decides each axis
independently: an axis the override names keeps resolving exactly as before (a
named model or provider is an explicit legacy selection from the bootstrap
catalogs, a named runtime is a registry adapter key), and an axis it leaves unset
keeps the persisted application default. When a named runtime is the same adapter
the persisted configuration already uses, that configured instance is retained so
the run stays attributed to it; otherwise the run records no configured runtime
instance, because none backs the choice.

Deliberately unchanged: an explicit `model_id` or `model_provider_id` still
selects from the bootstrap catalogs. `RunExecutionOverride.model_id` is a
bootstrap-catalog identity, and mapping legacy override fields onto configured
model-configuration ids remains deferred to Phase 5.17, as
`test_legacy_override_is_explicit_not_a_persisted_default` already requires.
Consequently `{"model_id":"qwen25-coder-7b"}` still fails rather than resolving,
and the UI never sends it.

### Regression coverage

Backend, in `test_execution_configuration_resolver.py`: partial runtime override
keeps the persisted model/provider and reports no runtime instance; partial
model override keeps the persisted runtime instance; an override naming the
persisted runtime keeps its configured instance; omitted execution still resolves
persisted defaults; and with nothing persisted, bootstrap still answers.

Frontend, in `execution-default-request.test.tsx`: the partial payload contains
only the chosen axis, and no unchosen axis is ever sent as an empty string or a
`"default"` sentinel.

### Mutation proof

Removing the new persisted-override branch — restoring the original precedence
where an override discards persisted defaults — fails 6 of the new backend
assertions across both persistence backends. Restored: 64 passed.

### Validation

`./scripts/test_all.sh` exited 0: 2,165 backend tests passed with 2 opt-in
skips and the 4 pre-existing OpenHands SDK deprecation warnings; 700 frontend
tests passed with the 4 intentional live-backend skips; the Python client passed
10 tests. Backend Ruff and mypy (181 source files) and frontend lint across all
10 packages passed. Web and Desktop builds passed with the unchanged Vite
chunk-size advisory, and `git diff --check` passed.

This closes Defect E only. The Charter B native-streaming failure recorded above
is unrelated and still open, so **Phase 5 remains reopened and Phase 6 has not
started.**


## Defect F: a model added in Settings is absent from the chat composer

### Observed behavior

A model created in Settings saved successfully and appeared under
`GET /settings/models`, but never appeared in the composer's Model control. It
was equally unselectable: nothing sent its id, and the resolver had no path that
could accept one.

### Root cause

Three layers each independently prevented it, so no single fix was enough.

1. **Discovery omission.** `ModelDiscoveryService` enumerated only the bootstrap
   `ModelRegistry`. A persisted `ModelConfiguration` had no route into the
   catalog, so `GET /models` reported `local-qwen2.5-coder:7b` and nothing else.
2. **A provider-keyed control.** `ExecutionControls` rendered the model axis from
   `GET /model-providers`, whose option values are `provider_id`. With one
   connection behind several models, a provider key can only ever address one of
   them; `model_info.model_id` was a single bootstrap identity per provider, not a
   per-model choice.
3. **No request path.** `AppWorkspace` sent `model_provider_id`, and
   `ExecutionConfigurationResolver` only ever resolved a *whole* application
   default. `RunExecutionOverride.model_id` was defined as a bootstrap-catalog
   identity, so a configured id had nowhere to land. This was the deliberate
   deferral recorded under Defect E, now closed.

The model was never invalid and never failed to save. It was invisible.

### Fix

`ModelDiscoveryService` now takes the persisted model-configuration and
provider-connection repositories and merges their records into the catalog,
keyed by the stable AVA `model_id`. A persisted record wins an id collision with
a bootstrap profile, because the configured record is the operator's truth.
Discovery stays read-only and public-safe: `provider_model_name`, endpoint, and
credential never appear, which the existing forbidden-key assertions cover.

`ModelDiscoveryResponse` gained `default_model_id`, mirroring the
`default_runtime_id` and `default_provider_id` that `/runtimes` and
`/model-providers` already publish. The composer can therefore label its
"Application default" option with the concrete model it resolves to without
reading settings configuration.

`ExecutionConfigurationResolver` gained `resolve_model_configuration(model_id)`,
which loads one persisted record, rejects a disabled model or a disabled or
missing connection, evaluates orchestration eligibility, resolves the connection's
credential, and builds a provider through the existing factory. It returns `None`
for an id that names no configured model, which leaves the bootstrap path intact
for bootstrap ids.

`ExecutionSelector` now resolves an explicitly named `model_id` as a configured
model *before* anything else, so the answer never depends on whether application
defaults happen to be saved. The two id spaces are checked against each other
rather than trusted: a `model_id` from the configured catalog and a
`model_provider_id` from the provider catalog describing different providers is a
caller error, never silently resolved in favour of one.

Frontend: the Model control lists configured models keyed by `model_id` and
labelled by `display_name`, falling back to the legacy provider list only when
discovery reports no models. `AppWorkspace` sends `model_id` for a catalog choice
and keeps `model_provider_id` for a provider identity that came from an execution
profile — an execution profile pins a provider, not a model, so that value is
rendered as an explicit "Provider local (from profile)" option rather than
silently blanking the select.

### Deliberate decisions

- **Disabled models stay in the catalog** with `enabled: false`, and the composer
  renders them labelled `(disabled)`. A configured model the user can see but
  cannot run is recoverable; one that silently disappears looks like the
  original bug. Selecting one fails on its own explicit terms.
- **An enabled model that cannot run stays selectable.** Hiding models the
  provider cannot serve would make a transient provider fault look like a
  configuration fault, and would hide the error the user needs to see. The run
  fails and records the model that was actually asked for.
- **No silent substitution.** An unknown or unusable configured id never falls
  back to a same-looking bootstrap model.
- **The model catalog is fetched in isolation.** A `/models` failure degrades the
  Model control to the legacy provider list instead of taking runtimes,
  providers, and profiles down with it, matching how `/workspaces` is already
  isolated.

### Live evidence

Against the live backend and Ollama, using only the operator's own records:

| `POST /runs` execution | recorded `model_id` | outcome |
| --- | --- | --- |
| `{"model_id":"qwen35-9b"}` | `qwen35-9b` | completed |
| `{"model_id":"qwen25-coder-7b"}` | `qwen25-coder-7b` | completed |
| `{"model_id":"local-qwen2.5-coder:7b"}` | `local-qwen2.5-coder:7b` | completed |
| `{"model_id":"Bad-model"}` | `Bad-model` | failed at the provider |
| `{"model_id":"disabled-model"}` | none | failed before any provider call |
| `{"runtime_id":"openhands","model_id":"qwen35-9b"}` | `qwen35-9b` | completed |

`GET /models` now reports both configured models with their display names, plus
`default_model_id`. Three models sharing the `local` provider are three distinct
options. The disabled record produced no outbound provider request.

A separate data problem is now visible rather than hidden: the saved application
default is `Bad-model`, whose `provider_model_name` is `Badmodelid`, which Ollama
does not have. That run fails honestly. The record itself is valid and now
selectable; its provider-native name is the thing to correct.

### Regression coverage

Backend, in `test_model_discovery.py`: configured models appear alongside
bootstrap profiles; several models behind one provider stay distinct; a
configured display name is never the provider-native name and no forbidden key
leaks; a disabled configured model is discovered and flagged; a persisted record
wins an id collision with a registry profile; `default_model_id` is reported, is
`null` without defaults, and is still reported when it dangles.

In `test_execution_configuration_resolver.py`, across both persistence backends:
an explicitly chosen configured model runs that exact record; it is chosen
independently of the application default; several models behind one connection
are each selectable and resolve to their own provider-native name; one is
selectable *before* any defaults are saved; a disabled model and a model on a
disabled connection both raise rather than falling back; an unknown id still
resolves through the legacy catalog; an explicit runtime is kept and a
conflicting provider is rejected.

In `test_persisted_execution_integration.py`: Settings → `GET /models` →
`POST /runs` for a newly added model, with the provider-native name asserted
absent from the catalog and a disabled model asserted discoverable but not
runnable.

Frontend, in `execution-default-request.test.tsx`: options are keyed by
`model_id`, labelled by display name, and two models on one provider remain
separate choices; a chosen model is sent as `model_id` and never as
`model_provider_id`; disabled and invalid-but-enabled models stay offered; the
Application default option names the model it resolves to and falls back to a
plain label when none is configured; a profile's provider stays visible; an
explicit runtime and an explicit model combine; and a `/models` failure leaves
runtimes and profiles selectable.

### Mutation proof

Reverting the resolver to never treat an explicit `model_id` as a configured
model — the pre-fix behavior — fails 14 assertions across both persistence
backends, including the end-to-end Settings → `/models` → `/runs` test.
Restored: 96 passed.

Reverting the composer to list provider identities instead of configured models
fails 9 frontend assertions. Restored: 81 passed with the 4 intentional
live-backend skips.

### Validation

`./scripts/test_all.sh` exited 0: 2,192 backend tests passed with 2 opt-in skips
and the 4 pre-existing OpenHands SDK deprecation warnings; 713 frontend tests
passed across all packages with the 4 intentional live-backend skips; the Python
client passed 10 tests. Backend Ruff and mypy (181 source files) and frontend lint
across all 10 packages passed. Web and Desktop builds passed with the unchanged
Vite chunk-size advisory, and `git diff --check` passed.

This closes Defect F only. The Charter B native-streaming failure recorded above
is unrelated and still open, so **Phase 5 remains reopened and Phase 6 has not
started.**

## Defect G: every failure is the same failure

### Observed behavior

A provider that does not exist, a model the provider does not serve, a timeout,
a rate limit, a rejected credential, and an unexpected internal crash all reached
the user as one indistinguishable message: *"Failed to generate response — AVA is
unavailable. Please try again."*

The three live cases that exposed it, against the operator's own records:

| `POST /runs` execution | actual cause | what the user was told |
| --- | --- | --- |
| `{"model_id":"Bad-model"}` | provider serves no such model | unavailable, try again |
| endpoint on a closed port | TCP connection refused | unavailable, try again |
| `{"model_id":"qwen25-coder-7b"}` | completed | completed |

A user told to retry a rate limit, a wrong model name, and an unreachable host
does the one thing that cannot help any of them. The honest causes already
existed somewhere below the UI — as a provider exception type and an HTTP status
— but nothing promoted them to a public vocabulary, so they were discarded at the
boundary.

### Root cause

There was no failure taxonomy to promote into. The public boundary had exactly
one code, and the layers that knew better had no way to say so.

1. **One code, no owner.** `ModelProviderError` carried a message string. Every
   provider failure therefore arrived at `RunService` as an unlabelled exception,
   and the single `_fail_transition` body could not distinguish them.
2. **Classification below the public boundary, in the wrong place.** The
   OpenAI-compatible adapter detected every one of these conditions and then
   raised them with the same type, so the type carried no information.
3. **A generic catch discarded the one typed error that did exist.**
   `NativeAgent` wrapped `ExecutionSelector.resolve()` in a bare
   `except Exception`, returning an unclassified `AgentRunResult`. Every
   `ExecutionConfigurationError` — missing defaults, a disabled runtime, an
   unregistered adapter, a credential failure — was therefore already collapsed
   to `agent_failed` *before* `RunService` ever saw it. The specific mapping in
   `RunService` was unreachable code.
4. **The frontend had nothing to key on.** `AssistantMessage` rendered the
   message text it was handed and always offered Retry.

The layering itself was sound — the boundary was in the right place. What was
missing was a vocabulary and the wiring to carry a classification to it.

### Fix

A closed, architecture-owned vocabulary in
`ava.contracts.failures.FailureCode`, with each code carrying its own safe public
message and recoverability default. The set is deliberately small: every code
must correspond to a *different user action*.

- Configuration: `configuration_missing`, `configuration_invalid`,
  `provider_connection_unavailable`, `model_unavailable`, `runtime_unavailable`,
  `credential_unavailable`
- Execution: `provider_request_failed`, `provider_timeout`,
  `provider_rate_limited`, `provider_authentication_failed`,
  `provider_response_invalid`, `runtime_failed`, `context_window_exceeded`
- Interruption and generic: `cancelled`, `execution_interrupted`, `agent_failed`

Ownership follows the existing layering rather than adding a new one. The
provider adapter is the only layer that reads an HTTP status or a provider error
body, so it is the only layer that classifies `provider_*` codes. The runtime
normalizes outcomes and preserves whatever code it was given, inventing nothing —
`test_native_runtime.py` asserts an unclassifiable exception yields *no* code
rather than borrowing one. The agent classifies only what it can see, and now
re-raises `ExecutionConfigurationError` instead of swallowing it. `RunService`
builds every durable `run_failed` payload through a single `failure_payload()`
call, so a code outside the public taxonomy cannot reach storage.

`ModelProviderError` gained `safe_code` (defaulting to
`provider_request_failed`) and `status_code`. `models/providers/errors.py`
became a re-export of the canonical class so existing importers keep one type.

The adapter classifies: 401/403 → `provider_authentication_failed`; 404 with
model-not-found semantics → `model_unavailable`; 408/504 and transport timeouts →
`provider_timeout`; 429 → `provider_rate_limited`; refused/DNS/broken transport →
`provider_connection_unavailable`; an invalid base URL → `configuration_invalid`;
5xx and other statuses → `provider_request_failed`; malformed JSON, or a success
body with unusable choices/content, → `provider_response_invalid`.

Frontend `errorPresentation.ts` maps each code to a title, a description written
in AVA's voice, a Settings section to open, and whether Retry can help.
`AssistantMessage` renders that title and honors the retry decision while
keeping streamed partial content. Cancellation remains its own non-error state.

### Deliberate decisions

- **`tool_or_runtime_incompatible` was not added.** A compatibility failure is a
  configuration error to the person reading it, and a second code for "this
  selection cannot run" would send them to two different places for one repair.
- **`provider_authentication_failed` is not recoverable**, matching
  `credential_unavailable`. Both are repaired by changing a credential; an
  identical retry fails identically. `provider_timeout`, `provider_rate_limited`,
  and the connection failures stay recoverable.
- **A 404 is a model failure only with model semantics.** A 404 from a wrong base
  URL is `provider_request_failed`, not `model_unavailable`. Status alone is not
  sufficient; the structured `error.code` and then the message shape decide.
- **`cancelled` is in the taxonomy but is not rendered as a failure.** It is a
  state, and the frontend asserts a cancelled message never shows "Failed to
  generate response". The presentation entry is defensive.
- **Retry availability is a UI decision, not a mirror of `recoverable`.** The
  generic `agent_failed` stays retryable so the existing affordance is not
  regressed by an incomplete classification, even though the run is not marked
  recoverable.
- **Nothing provider-shaped is public.** Status codes, provider messages, error
  bodies, endpoints, and credential references are read server-side and discarded;
  only the resulting AVA code reaches the payload. The classifier's own messages
  are AVA's wording and never quote the provider.

### Live evidence

Against the live backend, using the operator's own records and a temporary local
fixture endpoint exercising real HTTP responses. All temporary records and runs
were removed afterwards and the application defaults were restored.

| scenario | `error_code` | `recoverable` | outbound request |
| --- | --- | --- | --- |
| `Bad-model`, `Badmodelid` not served by Ollama | `model_unavailable` | true | yes |
| endpoint on a closed port | `provider_connection_unavailable` | true | attempted |
| non-routable address, 10s connect timeout | `provider_timeout` | true | attempted |
| fixture returns HTTP 401 | `provider_authentication_failed` | **false** | yes |
| fixture returns HTTP 429 | `provider_rate_limited` | true | yes |
| fixture returns malformed JSON | `provider_response_invalid` | true | yes |
| fixture returns HTTP 503 | `provider_request_failed` | true | yes |
| persisted default runtime disabled | `runtime_unavailable` | true | **none** |
| persisted default model disabled | `configuration_invalid` | false | **none** |
| persisted default provider connection disabled | `configuration_invalid` | false | **none** |

The last three rows are the fix to Defect G's third root cause, observed live: a
disabled runtime previously produced `agent_failed` and is now
`runtime_unavailable` without any outbound request.

An early pass of this matrix produced four identical `provider_request_failed`
results, which was a defect in the *harness*, not the product: the fixture routes
were written under `/v1/...` while the adapter appends `/chat/completions`
directly to the configured endpoint, so all four were 404s from an unknown route
— and, correctly, were not reported as model failures. The routes were corrected
and the matrix re-run.

### Regression coverage

`test_provider_failure_classification.py` (29 tests) covers the adapter as the
sole owner of HTTP interpretation: each status and transport class, model-not-found
by structured code and by prose, a 404 *without* model semantics, malformed
success bodies in both `generate` and `stream`, and an assertion that no public
message contains a status code, URL, or credential.

`test_conversation_failure_taxonomy.py` (13 tests) covers the durable path end to
end through `POST /runs` → `run_failed`: every provider code round-trips with its
message and recoverability, a disabled model, connection, and runtime each fail
before any outbound request, an unexpected exception stays `agent_failed`, no
payload leaks an endpoint or credential, cancellation and interruption are not
failures, and a successful run carries no payload.

`test_native_runtime.py` gained a matrix asserting the runtime preserves each
classified code in both the buffered and streaming paths and invents none.

Frontend `failureTaxonomy.test.ts` asserts every backend code has its own
presentation, that no code is left on the generic one, that descriptions leak no
endpoint or status, and that unknown, empty, and non-string codes degrade to the
generic presentation. `assistant-message.test.tsx` asserts the rendered title, the
Settings action named for its destination ("Open Model Settings"), Retry shown or
hidden per code, partial content surviving the failure, and that a cancelled
message shows none of it. `conversationReducer.test.ts` asserts eleven codes
survive a reload, alongside partial content.

### Mutation proof

Removing `provider_authentication_failed` from the non-recoverable set fails the
durable auth test. Remapping a 404 model-not-found to
`provider_connection_unavailable` fails 5 assertions across the taxonomy and
adapter suites, including the streamed path. Renaming the frontend
`model_unavailable` title to the provider's fails 2 frontend assertions, so the
model and provider presentations cannot collapse into one another unnoticed. All
restored.

### Validation

`./scripts/test_all.sh` exited 0: 2,240 backend tests passed with 2 opt-in skips
and the 4 pre-existing OpenHands SDK deprecation warnings; 788 frontend tests
passed across all packages with the 4 intentional live-backend skips; the Python
client passed 10 tests. Backend Ruff and mypy (182 source files) and frontend lint
across all 10 packages passed. Web and Desktop builds passed with the unchanged
Vite chunk-size advisory, and `git diff --check` passed.

This closes Defect G only. The Charter B native-streaming failure recorded above
is unrelated and still open, so **Phase 5 remains reopened and Phase 6 has not
started.**

## Defect H: a declared streaming model was completed in one shot

### Observed behavior

With the native runtime and the local Ollama model configured as
streaming-capable, a reply appeared in the UI only once, in full, at the
moment the run completed. The provider itself was demonstrably incremental, so
the loss happened somewhere between the provider and the browser.

### Signal trace

Each stage was observed separately rather than inferred, and the first stage
that lost incrementality is the defect.

1. **Provider transport — incremental.** Ollama's chat-completions stream
   delivered 474 deltas over 2,828 characters, first delta at +0.118s and last
   at +9.760s. Nothing upstream buffered.
2. **Capability handoff — lost.** The configured model profile declared
   `streaming: true`, but the adapter built by
   `ConfiguredModelProviderFactory` reported `streaming: false`. The resolver
   built the adapter without forwarding the operator's declared capabilities,
   so the adapter answered "chat only" for a model that can stream.
3. **Runtime gate — the first non-incremental boundary.**
   `NativeRuntime.execute_streaming` branches on
   `model_provider.get_capabilities().streaming`. Observing the live run showed
   the profile reporting `streaming=True` and the adapter reporting
   `streaming=False`, so the runtime deliberately degraded to the buffered
   `execute` path: one generation, one `on_content` call, at the end.
4. **Durable message — final only.** Consequently the assistant row received a
   single `message_content` snapshot at completion, and a refresh during the
   run had nothing partial to show.
5. **SSE — correct.** The run-event stream polls the repository every 100ms and
   yields events as they are persisted, so it was never the cause. Once real
   partials existed it emitted them progressively.
6. **Browser — correct.** The client's `streamRun` reads
   `response.body.getReader()` and splits frames on the live buffer, and the
   event processor maps `message_content` to `setMessageContent`, which
   *replaces* the message content. The user-visible symptom was fully explained
   by stage 3; no frontend defect was involved.

A second, separate defect was masked by the first: with streaming disabled the
runtime never called the provider's `stream`, so the provider's own non-200
handling was never exercised. Enabling real streaming revealed that
`_classify_status_failure` read `response.content` on a response that had not
been read, raising `httpx.ResponseNotRead` instead of an AVA-owned code. A
misconfigured streaming model surfaced as an opaque `agent_failed`.

### Fix

- `ModelProviderFactory.create` accepts an optional `capabilities` value, and
  `construct_compatible_provider` and `ConfiguredModelProviderFactory.create`
  forward it to the adapter. Omitting it keeps the conservative chat-only
  default, so a model that declares nothing still completes in one shot.
- `ExecutionConfigurationResolver` passes `model.capabilities` when it builds
  the adapter, which is what makes the adapter's answer truthful.
- `NativeRuntime.execute_streaming` now genuinely iterates the provider's
  stream. It was a stub that built an empty response and never iterated, so no
  delta could ever reach `on_content`. It now accumulates deltas and publishes
  the growing **snapshot** per delta, never the delta itself: appending
  downstream would duplicate the prefix on every update.
- The OpenAI-compatible adapter reads a streamed error body before classifying
  it, so a streamed 404/401 yields `model_unavailable` /
  `provider_authentication_failed` instead of `ResponseNotRead`.

Final-only compatibility is deliberately intact: a model that reports
`streaming=False` still takes the buffered `execute` path and persists exactly
one snapshot.

### Live evidence

Against the real backend, the real `@ava/api-client` SSE parser and the real
model, a 30-line prompt produced:

- 620 `message_content` events, **619 delivered before** `run_completed`
  (first at +0.10s, last at +12.68s);
- the durable assistant message growing across 49 samples from 30 to 2,365
  characters, every non-empty sample taken while the run was still active;
- replay from cursor 0 reproducing the identical 620 snapshots in the same
  order, with strictly growing prefixes.

### Regression coverage

- `test_run_streaming.py` drives the real `NativeAgent` + `NativeRuntime` path
  with a provider that gates every delta on an explicit release, and asserts
  that each snapshot reaches an SSE consumer **while the provider still had
  deltas pending** (`[2, 1, 0]`), that content replaces rather than appends,
  that the durable event log grows before completion with dense monotonic
  sequences, that a non-streaming model still yields one snapshot, and that a
  mid-stream provider failure keeps the partial content and its specific code.
- `test_execution_configuration_resolver.py` asserts a configured streaming
  model reaches the adapter as streaming, and that a model without the
  declaration stays chat-only, across both persistence backends.
- `test_openai_compatible_model_provider.py` asserts a streamed non-200 is
  classified instead of crashing, using a stream-backed body that is genuinely
  unread — an eagerly built `json=` body hides the defect.
- Frontend: `runs.test.ts` asserts the parser delivers each partial before the
  stream closes and reassembles an event split across two network reads;
  `conversationRun.test.ts` asserts snapshots replace rather than append, that
  each is projected while the run is open, and that every content update lands
  on the one backend assistant message.

### Mutation proof

Dropping `capabilities=model.capabilities` from the resolver fails the resolver
test on both persistence backends. Forcing `capabilities=None` in the factory
fails the factory test and the resolver test. Removing the `await
response.aread()` fails the streamed-error test with `ResponseNotRead`. Making
`setMessageContent` emit the accumulated content instead of the snapshot fails
the frontend snapshot test. All restored.

### Validation

See `AVA_Phase_5_40_Full_Validation.md` for the full record.

**Charter B is closed.** Phase 5 remains reopened only because the earlier
browser Settings pixel pass was never performed, and Phase 6 has not started.

## Defect I — Background conversation run reconciliation after navigation (2026-10-01)

### Reported symptom

Starting a streaming response in conversation A and navigating to B before A
finished left A's projection stale. The backend run continued and durable state
kept progressing; returning to A did not always show the latest partial or final
content, and a refresh or a second navigation cycle made the full response
appear.

### Root cause: observer ownership was scoped to the selection, not the run

`AgentRunProvider` held a **single** `streamController` ref and aborted it
whenever the selected conversation changed:

```ts
useEffect(() => {
  if (activeConversationId.current !== conversation.activeConversation?.id) {
    streamController.current?.abort();   // observer for run A is destroyed
    streamController.current = null;
    recoveryKey.current = null;
    activeConversationId.current = conversation.activeConversation?.id ?? null;
  }
}, [conversation.activeConversation?.id]);
```

So A → B did three things at once: it destroyed Run A's only SSE observer,
cleared the recovery key, and reset the owned-conversation marker. The backend
run was untouched (an aborted client fetch is not a cancellation), which is why
generation kept going while the UI froze at the last partial it had received.
Nothing was left observing, so no completion could reach conversation A.

### What was already correct

- **Message routing was never selection-based.** `applyRunEvents` targets the
  durable `conversationId` captured when the run started, keyed by
  `runEpoch` + `assistant_message_id`, and `conversation:updateMessage` resolves
  by `action.conversationId`. A late event cannot be misrouted to the visible
  conversation.
- **Provider scope was already stable.** `ConversationProvider` and
  `AgentRunProvider` are mounted at the workspace root, not beneath the selected
  conversation, so no route-level remount was involved.
- **Recovery/observer separation was preserved.** The persisted epoch still only
  identifies the current run; ownership is still proven by this session.

The defect was therefore one layer above routing: the observer that would have
performed that routing was being cancelled by the selection.

### Chosen architecture: Option A, background observation, owned per conversation

Runs are observed even when their conversation is not selected. Ownership moved
from one global controller to `Map<conversationId, AbortController>`, so:

- selecting B never touches Run A's observer;
- a conversation still has at most one observer, preserving
  one-active-run-per-conversation;
- ownership is released when that run's observation loop settles, so a later run
  can always claim it;
- recovery stays selected-conversation-scoped (unchanged fresh-mount
  semantics), and is now guarded by real per-conversation ownership instead of a
  single global slot.

`AbortSignal` plumbing became an explicit acquisition contract
(`AcquireRunStream → RunStreamHandle { signal, release }`) taken inside
`startRunForPrompt` / `recoverRunForConversation`, which is the first place the
owning conversation id is known.

### Preserved protections

`runEpoch` staleness, late-cancel protection, late-event rejection, exclusive
cursor replay, source-user-message lineage for retry/regenerate, and
bootstrap-content ordering are all unchanged; navigation is no longer an event
that can supersede or invalidate them.

### Regression coverage

`frontend/packages/workspace/src/background-run-navigation.test.tsx`
(mocks at the api-client boundary with a durable store that persists each event,
so "stale cache" and "lost run" stay distinguishable):

- background observation continues after deselection;
- latest content on return, one bubble, no duplicated prefix;
- completed-while-hidden shows the final response immediately;
- a hidden completed run leaves no stale `running` phase;
- failed-while-hidden reaches the terminal failed state;
- navigation alone issues no cancel and does not drop the run id;
- cancelled-while-hidden shows the cancelled state;
- refresh recovery still re-owns and continues the same run.

### Live verification

`live-background-navigation.integration.test.tsx` (no api-client mock; real
providers, real HTTP, real local Ollama model) passes. Under the reintroduced
mutation it fails with the hidden conversation stuck at `running`, confirming
the reported scenario reproduces and is fixed.

### Mutation proof

Reintroducing selection-scoped ownership (abort every observer whose
conversation is not selected) fails 4 deterministic regressions and both live
scenarios. A second mutation that routed `updateMessage`/`setRunState` only to
the selected conversation was **not** caught — the in-flight run captured a
`commands` closure created while its own conversation was still selected — which
documents that layer as already identity-routed rather than load-bearing.

**Phase 5 remains reopened. Phase 6 has not started.**
