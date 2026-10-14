# AVA Phase 6.14 — Run Inspector and Tool Activity

## Status

Phase 6.14 implementation is complete and committed separately from Phase 6.13. The existing shared Run Inspector now includes a read-only Tool Activity tab. Production tool dispatch remains disabled. No work from Phase 6.14A was started.

The Phase 6.13 implementation was checkpointed at `9f167b32eae1dfede8016933ad4c8c9c4b8c18f5`; Windows test corrections were committed separately at `3520d0eae89224b563afca17c011fa0bbf45f8f1`; the completed CI result was recorded at `d09189bb1d8b896ee24e94fa2f730f35666b18ef`. The Phase 6.14 implementation and this report are included in dedicated checkpoint `c920ba8522cf08a276a39d7c226855a7b3c9a3ee`.

## Scope and implementation

The backend adds a safe `ToolActivityHistory` projection to the existing `GET /runs/{run_id}/inspection` response. It combines sanitized Run lifecycle events with durable invocation reservations. A durable reservation is authoritative when its state differs from a Run event. The service returns at most the latest 100 invocation summaries and indicates whether more exist. Reservation-store failures produce an explicit unavailable history state.

Each item contains only invocation/tool identity, optional current display name, tool version, persisted execution mode, lifecycle timestamps and status, a normalized reason code, approval-required state, and recovery status. It excludes operation arguments, raw executor output, workspace paths, credentials, fingerprints, and authority objects. Conflicting event records that reuse one invocation ID for different tools are omitted from the projection.

The frontend adds Tool Activity to the existing shared `@ava/workspace` Run Inspector used by Web and Desktop. It presents requested, rejected, awaiting-approval, reserved, executing, completed, failed, cancelled, and indeterminate states, including safe timestamps and recovery facts. It distinguishes approval waiting from execution, identifies the bounded-history limit, and explains unavailable or unauthorized responses. Existing request-generation handling continues to reject stale inspection responses when the selected Run or conversation changes. The API client continues using the existing inspection endpoint; there is no new route or dispatch path.

The legacy Phase 6 outline links to the owner-approved [Production Execution Integration Addendum](AVA_Phase_6_Production_Execution_Integration_Addendum.md), which records the later numbering and the planned 6.14A–6.14D gates. The locked canonical master plan was not edited.

## Access and security boundary

The current application has no authenticated user principal to bind to a Run. This work preserves the existing Run-ID access boundary and adds no new endpoint or access route; it does not claim per-user Run authorization. The UI handles HTTP 401/403 responses, but authorization must be enforced by an authenticated backend principal when that capability exists. This is an explicit prerequisite for the trusted-authority work planned in 6.14A.

The activity projection is observational. It neither authorizes nor invokes a tool, resumes a Run, or decides an approval. Existing production normalized-tool dispatch remains default-deny. In particular, an approval-required event is shown as waiting and does not imply executor entry.

## Phase 6.13 cross-platform validation

GitHub Actions run [38587156271](https://github.com/cliski1978-hub/AVAPython/actions/runs/38587156271), commit `3520d0eae89224b563afca17c011fa0bbf45f8f1` on `phase-6.13-windows-validation`, completed successfully. The `ubuntu-22.04` job passed shared filesystem and authorization contracts, Linux adversarial filesystem tests, Ruff, and strict mypy. The `windows-2025` job passed shared filesystem and authorization contracts, native Windows filesystem security tests, and Ruff. Platform-specific checks were skipped on the opposite runner by design. The prior Windows failure and test-only corrections are documented in the Phase 6.13 report.

## Phase 6.14 validation

- Backend focused Run activity, Run inspection, tool execution, and recovery suites: **37 passed**.
- Backend Ruff: passed.
- Backend strict mypy: passed across **291 source files**.
- Workspace frontend suite: **278 passed, 6 skipped**; Run Inspector activity coverage is included.
- Workspace and API-client TypeScript checks: passed.
- API-client tests: **120 passed**; contracts tests: **45 passed**.
- Web and Desktop production builds: passed. The bundler emitted its existing large-chunk advisory.
- `git diff --check`: passed.

Two broader regression commands expose existing failures outside the Phase 6.14 change. `test_run_lifecycle_integration.py` has 13 failures and 7 passes because the unchanged `ControllableAgent.start_run` test double does not accept the `resolved_execution` keyword required by the already-committed AgentPort contract. The full frontend test run also fails in `approvals-core` tests whose year-2099 fixtures trigger Node timeout overflow; the workspace and changed API/client contract suites pass independently. A full frontend lint run reports an unrelated `approvals-core` mock return-type error. These are recorded as open regression-suite issues, not as passing checks.

## Handoff

Phase 6.14 delivers the shared Run Inspector activity view and bounded safe projection. It does not begin 6.14A. The next planned work is the separately scoped 6.14A trusted execution authority and current-invocation resolution. The authenticated Run ownership boundary, durable shared persistence for multi-instance deployments, authenticated approval decisions, approval-driven Run continuation, and production executor registration remain future prerequisites listed in the addendum. Phase 6.15 must not accept an enabled production execution path until its applicable prerequisites have implementation and validation evidence.
