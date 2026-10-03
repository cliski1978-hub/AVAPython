# Phase 5.73 — Project Execution Default Resolution

## Scope

Project runtime and model preferences now participate in backend run selection.
This phase changes the execution-selection path only. It adds no Project
settings UI, API/client surface, prompt-selection policy, capability policy, or
permission behavior.

## Selection audit and boundary

The existing flow is:

```text
RunRequest
→ RunExecutionOverride
→ NativeAgentAdapter
→ ExecutionSelector
→ RuntimeResolver / configured model resolver / bootstrap model catalog
→ ExecutionCompatibilityValidator
→ selected runtime and model provider
```

`RunRequest` contains the canonical `conversation_id` and no Project ID. The
adapter passes that conversation identity to `ExecutionSelector`, which uses
`ProjectExecutionDefaultsResolver` to read the Conversation's current
`project_id` and then the linked Project's preferences. ProjectService and API
routes do not participate in selection.

## Effective precedence

Runtime and model are resolved independently:

```text
Explicit Run Override → Project Default → Application Default → Bootstrap
```

An explicit runtime can coexist with a Project model, and an explicit model can
coexist with a Project runtime. Partial Project preferences fall through only
for the unset or unusable axis. The AVA-owned `ResolvedExecutionSelection`
records effective runtime/model identities, each source (`explicit`, `project`,
`application`, or `bootstrap`), and the Project identity when membership exists.
No source-provenance schema was added. Existing run metadata continues to
persist the effective runtime/model/provider identities actually selected.

## Validation and fallback policy

Project runtime keys are resolved against the current runtime registry on every
run. An unavailable Project runtime is skipped and resolution continues to the
application runtime or bootstrap runtime. A selected application runtime keeps
the existing strict persisted-reference validation.

Project model references are read from the configured model repository on each
run. A missing, disabled, or provider-connection-unavailable Project model is
skipped in favor of the application model or bootstrap model. A selected
application model remains strict: its configured model must exist, be enabled,
and belong to the configured application provider connection. The chosen model
always supplies its own configured provider connection; Project records have
no provider preference.

Runtime and model are not paired or silently substituted by Project selection.
The selected pair proceeds to the existing `ExecutionCompatibilityValidator`,
which reports incompatibility. Model qualification checks continue to receive
the resolved runtime key through the existing model-orchestrator seam.

## Freshness and downstream behavior

Selection is resolved once at the start of each execution. Changes to Project
settings or conversation membership do not mutate an active request; later
runs, including retry/regenerate, resolve current persistence. Moving a
Conversation changes the Project defaults considered by its next run; removing
or deleting the Project clears membership and therefore removes its future
effect. Archived Projects remain linked and continue to supply preferences.

The selected runtime key continues downstream to `ExecutionPromptContextService`
for Runtime-scoped CORE prompt resolution. Project preferences do not select
CORE prompts directly. Runtime capabilities, tool permissions, and approval
policy remain unchanged.

## Validation record

Focused tests cover canonical Conversation membership with memory and SQLite
repositories, explicit-versus-Project axis independence, both partial Project
preference cases, stale runtime fallback, missing Project model fallback, and
configured model/provider identity preservation. A load-bearing mutation that
forced application runtime precedence produced 4 targeted failures; restoring
Project-before-application precedence returned the suite to green.

The final canonical `./scripts/test_all.sh` run passed: 2,451 backend tests, 6
skips, backend Ruff and mypy, frontend tests and TypeScript checks, and Python
client tests/lint/typecheck. Four pre-existing OpenHands SDK deprecation
warnings were emitted. Live Project-default execution was unavailable because
no backend was listening on `127.0.0.1:8000`; no local provider/model process
was running for an end-to-end live run.
