# AVA Phase 6.13 — Durable Tool Lifecycle and Persistence

## Status

Phase 6.13 adds durable lifecycle infrastructure for normalized tool invocations. Production agent dispatch remains unavailable: application composition still has no trusted execution-authority issuer, context resolver, or production executor registration. The SQLite reservation adapter is wired into relational composition; the memory composition receives an explicitly non-durable test adapter that cannot satisfy the dispatch gate.

Implementation status: reviewed, checkpointed, and validated on native Windows and Linux GitHub Actions runners. The Phase 6.14 handoff records the implementation and CI-correction commit SHAs.

Implementation branch: `codex/phase-6.13-durable-tool-lifecycle`
Baseline: `646121e9792d066db83805727f0e5b3b3120ec93` (`codex/phase-6.12-12a-reviewed`)
Implementation commit: committed on the implementation branch; see `AVA_Phase_6_14_Run_Inspector_and_Tool_Activity.md` for the SHA and validation run link.

## Phase 6.13 specification and standards review

The implementation was reviewed against the Phase 6.13 request, the Phase 6.10 execution contract, Phase 6.12 Run/event behavior, migration conventions, and repository architecture guards. Atomic reservations, immutable invocation binding, revision-checked transitions, non-replay recovery, indeterminate outcomes, event reconciliation, and default-deny composition match the reviewed requirements. Migration 28 is additive and leaves historical migrations unchanged.

Two specification defects were corrected before checkpoint. First, incomplete-invocation recovery and per-Run history reads previously had no query bound. Both repository adapters now accept a validated limit, reads have deterministic ordering, and recovery processes at most 100 records per call so later calls can continue safely. Second, a normalized executor result of `CANCELLED` or `INDETERMINATE` was persisted as `FAILED`; durable state and runtime disposition now preserve the confirmed terminal status.

No remaining actual ports-and-adapters, import-direction, type-safety, SQLite-boundary, cross-platform import, or secret-persistence violation was identified in the reviewed change. Non-blocking observations are recorded in the production prerequisite register: trusted identity/authority, authenticated human decisions, approval-driven resumption, and production executor registration remain unavailable, so normalized production dispatch remains disabled.

## Architecture and repository contract

The AVA-owned port and immutable lifecycle record live in `ava.repositories.invocation_reservation_repository`. They contain no SQLite or runtime SDK types. The record binds invocation ID, Run ID, tool ID/version, operation fingerprint, Workspace ID, execution context reference, authority revision, tool-feature configuration revision, persisted Run execution mode, state/revision, timestamps, normalized result status/error code, and reconciliation status.

`RelationalInvocationReservationRepository` stores these values in `tool_invocation_reservations`. Invocation ID is the primary key, Run ID has a foreign key to `runs`, indexes support Run history and incomplete recovery, and all transitions use a database transaction plus a state-and-revision conditional update. SQLite's `BEGIN IMMEDIATE` serializes competing writers across independent connections to the same database file. A duplicate ID always conflicts, so an invocation cannot be rebound to another fingerprint or Workspace.

Migration 28 creates the new table and indexes. Existing migrations were not modified. The in-memory adapter uses a lock for isolated contract tests and reports `durable = False`.

## Lifecycle and dispatch integration

The lifecycle is `RESERVED → EXECUTING → COMPLETED | FAILED | CANCELLED | INDETERMINATE`. `NOT_STARTED` remains a conceptual state and is never persisted. Transitions are forward-only, revision checked, and terminal states cannot be reopened. Identity columns are immutable after reservation.

`ToolExecutionService` preserves the existing order: load the persisted Run and mode, enforce registry and feature gates, resolve trusted authority and Workspace, evaluate policy, validate approval where required, re-evaluate policy and authority, re-read Run state, reserve the exact operation, mark it executing, then enter the executor. Reservation storage is not treated as authorization. Missing or non-durable storage denies dispatch.

The reservation includes the exact operation digest already produced by `ToolPolicyService`, the current authority revision reference, and the persisted tool-feature configuration version. It stores no arguments, credentials, file contents, output payloads, or unrestricted authority object. It records only normalized status and an error code.

Tool lifecycle events remain safe summaries. Executor failures produce a started event followed by a failed outcome, without an additional pre-dispatch rejection. Pre-dispatch denials and approval waits remain distinct from dispatched invocations. Safe historical records are available through `ToolExecutionService.list_invocations_for_run`; no Run Inspector UI or new API was added.

## Recovery and cancellation

`ToolExecutionService.reconcile_interrupted_invocations()` is an explicit, bounded recovery operation; no background worker was added. A reserved record becomes `FAILED` with `execution_not_started`, or `CANCELLED` if its Run has a persisted cancellation request. An executing record becomes `INDETERMINATE` with `interrupted_execution_outcome_unknown`. Recovery never calls an executor and a second invocation of recovery leaves terminal records untouched. Reconciled outcomes are appended only when no outcome event for that invocation is already present; event IDs are deterministic for the lifecycle revision.

Cancellation before reservation prevents dispatch through existing Run checks. A reserved operation can be safely finalized as cancelled before executor entry. Cancellation while awaiting an executor is recorded as indeterminate because Python task cancellation cannot prove that an external side effect was undone. Completed outcomes are immutable; indeterminate outcomes are not rewritten as known failures.

The recovery method is not called automatically during application startup. The application owner must invoke it at a controlled startup point after repositories and Run state are available. Corrupt rows fail closed with `PersistenceError`; missing Run IDs are prevented for new records by the database foreign key.

## Hosting and limits

The adapter provides atomic uniqueness and compare-and-set transitions only among processes using the same SQLite database. Separate application instances with separate database files do not coordinate. SQLite does not provide global exactly-once side effects: a crash after an external effect but before outcome persistence leaves an indeterminate record, and this phase never retries it. Multi-instance Windows/Linux cloud hosting and Databricks Apps require externally managed shared durable persistence with equivalent transactional guarantees. Executor host/resource selection remains independent from the repository.

Durable model-loop resumption, automatic retry, distributed leases, approval-driven Run resumption, and full inspection UI remain deferred. The Phase 6.11 native Windows workflow was run against the dedicated validation branch; see the Validation section for the run and results.

## Validation

The earlier handoff's Linux evidence included 72 focused tests, 131 architecture tests, Ruff, and strict mypy across 290 source files. These are prior results, not substitutes for this checkpoint's validation.

The Phase 6.13 implementation and a separate Windows-test correction were pushed to `phase-6.13-windows-validation`. GitHub Actions run [38587156271](https://github.com/cliski1978-hub/AVAPython/actions/runs/38587156271) completed successfully for commit `3520d0eae89224b563afca17c011fa0bbf45f8f1`. Linux (`ubuntu-22.04`) passed shared filesystem/authorization contracts, Linux adversarial filesystem tests, Ruff, and strict mypy. Windows (`windows-2025`) passed shared filesystem/authorization contracts, Windows-native filesystem security tests, and Ruff. Platform-specific steps were skipped on the opposite runner by design. The earlier run `38585897194` exposed Windows test assumptions (SQLite connection handles, timestamp resolution, and tied ordering); the corrections are in the separate CI-fix commit and the rerun is green.

Local Phase 6.13 checkpoint validation also passed 58 reservation, execution-service, runtime-bridge, and migration tests; 131 architecture tests; Ruff; strict mypy across 290 backend files; and `git diff --check`. The workspace Run Inspector suite passed 274 tests with 6 skipped before Phase 6.14 edits.

The current `test_run_recovery.py` run passed (16 tests). `test_run_lifecycle_integration.py` reported 13 failures and 7 passes: the failing cases raise `TypeError` because the unchanged `ControllableAgent.start_run` test double does not accept the `resolved_execution` keyword that the already-committed `AgentPort` contract passes. The failing fixture and contract are unchanged from the Phase 6.12 baseline, so this is a pre-existing test-fixture compatibility failure rather than a Phase 6.13 regression; it remains an open regression-suite issue. No Phase 6.14 frontend change existed during the checkpoint test. The 13 failures are outside the Phase 6.13 CI workflow's selected acceptance suites and are not represented as CI passes.

The focused tests cover atomic duplicate reservation across two independent SQLite connections, CAS and stale-revision rejection, terminal immutability, file-backed restart retrieval, immutable identity on duplicate reuse, corrupt-row fail-closed behavior, interrupted reserved/executing recovery, recovery idempotence and Run-mode mismatch, execution gating, executor failure/event behavior, finalization failure to indeterminate, migration certification, and native workspace read regressions. No file mutation or shell execution was used to validate tool dispatch.

## Remaining Production Agent Execution Prerequisites

| Prerequisite | Status | Proposed owner | Acceptance criteria |
|---|---|---|---|
| Trusted per-Run execution authority issuer | Not implemented | Dedicated bounded security integration before Phase 6.15 | Authenticated principal and active Run are bound to a narrow, revocable server-issued grant. |
| Trusted current-invocation/context resolver | Not implemented | Same trusted security integration | Resolves the current invocation and Workspace from trusted server state; client/model data cannot grant authority. |
| Authenticated human approval authority | Not implemented | Dedicated approval integration before Phase 6.15 | Decision attribution is authenticated, durable, scoped, and auditable. |
| Authorized Approval API | Not implemented | Same approval integration | Approval decisions require authenticated authority and exact operation binding. |
| Approval-driven Run suspension/resumption | Not implemented | Dedicated Run continuation integration | Run suspension, approval wakeup, cancellation, and resume are durable and race-safe. |
| Production executor registration | Unavailable; no executors registered | Phase 6.13 composition review or dedicated activation step | Each executor is registered only after its host, capability, workspace, cancellation, and audit boundaries are reviewed. |
| Durable reservation storage | Implemented for relational SQLite composition; memory adapter is test-only | Phase 6.13 | Shared-database atomic uniqueness/CAS and restart retrieval pass platform CI; deployment limits are documented. |
| OpenHands legacy normalized-tool mediation | Not implemented | Dedicated runtime migration step | Legacy OpenHands tool calls cross the same AVA policy, approval, authority, reservation, and event boundary. |
| Full end-to-end approval/execution validation | Not implemented | Phase 6.15 | Authenticated approval through runtime dispatch and durable outcome is validated end-to-end on supported hosts. |

The owner-approved additive roadmap companion, `AVA_Phase_6_Production_Execution_Integration_Addendum.md`, assigns these dependencies to 6.14A–6.14D before the existing Phase 6.15 security/integration testing. This is a plan addition only; none of those prerequisites is implemented by the assignment or this checkpoint. The owner-locked canonical plan remains unchanged.

## Phase 6.14 readiness

Phase 6.13 establishes safe durable lifecycle primitives and explicitly bounded reconciliation, while production dispatch remains disabled. Native Windows and Linux workflow acceptance passed on the dedicated validation branch. Phase 6.13 does not grant production agent authority.
