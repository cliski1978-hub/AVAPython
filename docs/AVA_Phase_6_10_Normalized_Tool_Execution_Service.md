# AVA Phase 6.10 — Normalized Tool Execution Service

## Outcome

Phase 6.10 adds an AVA-owned execution-mode contract, persists the mode on each
Run, and introduces one runtime-neutral `ToolExecutionService` boundary. It
connects the existing registry, feature service, policy service, trusted
execution authority port, approval service, executor port, and an invocation
reservation repository contract.

This establishes a secure foundation. It does not make tools operational in
production: the production composition supplies no trusted execution-authority
issuer, executor, or durable reservation adapter, so every dispatch remains
unavailable. No file or command handler, agent tool loop, or approval API was
added.

## Execution-mode contract

`ExecutionMode` is an AVA-owned enum with `chat`, `plan`, and `agent` values. A
new Run request that omits the field receives `chat`. The mode is stored in the
Run record at creation and returned in Run responses, Run summaries, inspection
responses, and the `run_started` event payload. There is no repository update
operation for changing a Run's mode. A retry creates another Run and captures
that new request's mode; it does not mutate the prior Run.

`chat` rejects every normalized tool request. `plan` accepts only operations
whose trusted structured operation classification is `READ` and whose declared
capabilities contain no effects beyond `FILE_READ`. Unknown classifications,
mutating or mixed capabilities, and command effects are denied. `agent` allows
the existing policy to evaluate classified reads and mutations, but does not
skip policy or approval. Normalized command execution remains denied under the
conservative Phase 6.6 policy.

The mode is independent of model, provider, runtime, Project, Folder, and
Workspace selection. It does not enable a feature, widen Workspace permissions,
or create an authority grant. The frontend contracts carry the optional field
for future clients; no composer selector was added.

## Persistence and compatibility

Migration `0027_run_execution_mode` adds a non-null constrained column to
`runs`, defaulting to `chat`. Existing rows receive that safe interpretation.
The row mapper also interprets rows from pre-migration query shapes as `chat`.
Both in-memory and SQLite run repositories capture the mode passed at creation.
The schema registry remains additive and forward-only; the owner-locked
canonical development plan was not changed.

Run lifecycle events now include the persisted mode when the Run enters
`running`. Inspection and list projections read the mode from the Run record;
they do not infer it from current runtime or model configuration.

## Execution service and security sequence

`ToolExecutionService` is in AVA Core and depends only on contracts and ports.
It receives a normalized `ToolRequest` with a Run identity, reads the
persisted Run mode, discovers the current definition, checks feature enablement
and trusted effect classification, and applies the mode ceiling. It then
resolves current server-side execution authority and delegates Workspace and
tool-policy checks to the existing `ToolPolicyService`.

The service distinguishes a policy preflight decision from dispatch
authorization. A policy `ALLOW` is recorded as preflight eligibility only; it
does not create an authorized invocation or dispatch. Before dispatch, the
service re-evaluates policy, compares the current authority and operation
binding with the earlier evaluation, re-reads the Run and cancellation intent,
and requires a registered executor and a durable reservation adapter.
Authority, Workspace, feature, operation, or Run changes close the boundary.

`REQUIRES_APPROVAL` returns an awaiting-approval outcome unless the injected
`ApprovalService` confirms a current approved record for the same request. The
new dispatch-time approval check requires the trusted invocation resolver,
checks the persisted record is `APPROVED`, compares the resolver's current
request, and reuses the approval service's exact-operation and policy
revalidation. Pending, expired, denied, cancelled, invalidated, mismatched, or
unresolvable approvals cannot dispatch. A `DENY` result cannot be upgraded by
an approval reference. Approval records remain historical decision evidence,
not bearer tokens.

The executor receives only an `AuthorizedToolInvocation` built inside the
service after its checks. Its constructor guard prevents a caller-created
object from being accepted as proof by the service. Executor results are
revalidated against invocation, tool, and version identities. Exceptions return
a generic normalized failure without exposing exception text. Cancellation
updates the reservation state best-effort and propagates cancellation. The
service does not retry execution. If a side effect returns but reservation
finalization fails, the service reports an indeterminate outcome that must not
be retried automatically.

## Reservation and executor contracts

`ToolExecutorPort` accepts only `AuthorizedToolInvocation` and returns the
existing normalized `ToolResult`. It receives no model/runtime selector and
cannot extend its own grants. Executor registration is an explicit tool-ID
mapping; an absent mapping denies dispatch.

`InvocationReservationRepository` defines atomic reservation and lifecycle
states: not started, reserved, executing, completed, failed, and cancelled.
The service requires an adapter marked durable before it can dispatch. No
production adapter exists in this phase. The test suite uses an isolated fake
reservation provider. Neither that fake nor an in-memory lock/status implies
exactly-once external effects; Phase 6.13 remains the expected owner for durable
reservation infrastructure.

Future filesystem executors must use descriptor-relative operations and
no-follow semantics, validate the opened object and expected identity/revision,
and keep the opened handle through the effect. A canonical path check alone
does not close symlink or retargeting races. Future command execution needs a
separately reviewed executable/argument allowlist and bounded runner controls.
This phase makes no claim that these effect-safety requirements are already
implemented.

## Composition and existing boundaries

The FastAPI composition constructs the service with no authority issuer, an
empty executor map, and no reservation adapter. The existing approval service
also has no trusted human identity adapter or invocation resolver. Thus
production composition cannot dispatch, including in `agent` mode. Workspace
configuration remains a policy input rather than an authority issuer.

`RunService → AgentPort` is unchanged apart from capturing and returning the
Run's mode. The execution service does not import a concrete runtime, and no
agentic tool-calling loop, approval-driven Run continuation, or execution-mode
selector was added. Frontend role flags, model output, runtime choice, tool
feature enablement, and Workspace configuration cannot independently authorize
execution.

## Validation

- Focused execution, policy, approvals, feature-gate, Workspace-access, Run
  lifecycle, migration, and Phase 5 migration-certification tests: **207 passed**.
- Architecture guards: **131 passed**.
- Strict mypy: passed for all 279 `src/ava` files.
- Ruff: passed for the changed backend source and focused tests.
- Frontend `@ava/contracts` test and typecheck were attempted with pnpm but
  could not start because package tarballs at `registry.npmjs.org` failed DNS
  resolution. The dependency check was stopped after the retry also failed; the
  lockfile was preserved.
- The separate legacy `tests/test_run_service.py` suite has two failures in its
  stub AgentPort compatibility: its `start_run` override omits the current
  `resolved_execution` parameter. That mismatch is outside this phase's edits;
  Run persistence, lifecycle, and mode capture were validated through focused
  tests.

## Remaining prerequisites and Phase 6.11 readiness

Before production tool execution can be enabled, AVA still needs a trusted
server-side execution-authority issuer bound to the authenticated caller,
Run, Workspace, and current revisions; a trusted current-invocation resolver
and human identity/scope adapter for approval decisions; a durable atomic
invocation-reservation implementation; and reviewed effect-safe executor
adapters with cancellation and outcome reconciliation. The approval API and
approval-driven Run continuation also remain absent.

The normalized boundary and mode contracts are ready for the next planned
integration phase to consume. `agent` mode must remain non-operational until
those prerequisites are implemented and validated. Phase 6.10 work stops here;
the locked canonical plan remains unchanged.
