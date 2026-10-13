# 46 — Backend Validation

Date: 2026-10-12  
Environment: `/home/bizon/AvaUi/backend`, Python 3.12.14, pytest 9.1.1, Linux; Starlette 1.7.0, AnyIO 4.15.1.

## Result

**#46 Backend Validation — PARTIAL.** The Native Agent compaction dependency violation is fixed, both architecture guards pass, and focused compaction/attachment tests, Ruff, mypy, and migration checks pass. The full suite still cannot complete because Starlette `TestClient` hangs while starting its AnyIO blocking portal in this environment. The same hang reproduces with a minimal FastAPI app before AVA startup or SQLite code runs, so this is classified as a test-infrastructure/environment issue rather than an attachment regression.

## Architecture correction

`NativeAgentAdapter` no longer imports or invokes `ContextCompactionService`. The AVA-owned `RunContextPreparationService` now resolves prompt layers and performs summary/history compaction before `RunService` calls `AgentPort`. Composition shares one `ExecutionSelector`; the prepared context and that exact resolved execution are handed to the adapter together, avoiding a second resolution after summary generation. Run inspection compaction accounting travels with the prepared `RunContext`. Runtime adapters receive the same normalized AVA context regardless of runtime selection.

The focused capturing-AgentPort test verifies that `RunService` supplies prompt layers and compaction accounting before dispatch and passes through the exact selected execution object. The Native adapter integration test verifies a compacted context reaches runtime input and its inspection snapshot.

**Remaining architecture scope:** model-window fitting/budgeting (`_bound_context` and `_context_limit`) still runs in `NativeAgentAdapter`, as it did before this correction. The context-compaction service dependency and prompt/summary preparation now sit upstream, but the broader requirement that *all* context-window orchestration be moved upstream is not complete. The existing architecture guards do not currently detect this. This is recorded as unfinished architecture work rather than claimed as a completed boundary correction.

Files changed for this correction:

- `backend/src/ava/services/run_context_preparation_service.py` (new AVA-owned upstream preparation service)
- `backend/src/ava/services/run_service.py`
- `backend/src/ava/contracts/conversations.py`
- `backend/src/ava/agents/contracts.py`
- `backend/src/ava/agents/adapters/native/native_agent.py`
- `backend/src/ava/agents/adapters/mock/mock_agent.py`
- `backend/src/ava/infrastructure/composition.py`
- `backend/src/ava/api/app.py`
- `backend/tests/test_context_compaction_service.py`
- `backend/tests/test_attachment_run_context.py`

## Commands and results

| Command | Result |
| --- | --- |
| `timeout 45s .venv/bin/python -m pytest` | Collected **2,657** tests. Progress reached `tests/test_attachment_restart_recovery.py` at 10%; command timed out after 45 seconds. No final passed/failed/skipped totals are available. |
| `.venv/bin/ruff check .` | **PASS** — All checks passed. |
| `.venv/bin/mypy src` | **PASS** — no issues in 251 source files. |
| `.venv/bin/python -m pytest -q tests/test_architecture.py tests/test_context_compaction_service.py tests/test_attachment_run_context.py` | **166 passed** in 5.32 seconds. This includes both formerly failing architecture guards and the new AgentPort handoff coverage. |
| `.venv/bin/python -m pytest -q tests/test_persistence_migrations.py` | **31 passed** in 2.17 seconds. |
| `.venv/bin/python -c 'from ava.api.app import create_app; ...'` | **PASS** — imports and `create_app()` construction succeed. |
| `git diff --check` | **PASS**. |

The focused combined result is 127 architecture tests, 9 compaction-service tests, and 30 attachment/run-context tests. The earlier Phase 5 focused run recorded 142 passed / 3 skipped before this boundary correction; the current 166-test focused run supersedes its architecture, compaction, and attachment/run-context coverage.

## Failure classification and stall investigation

- **Native Agent architecture regression — fixed:** `native_agent.py` had imported the service-layer compaction implementation and performed summary preparation there. The service dependency was moved upstream. `test_native_agent_depends_only_on_contracts_and_stdlib` and `test_runtimes_and_adapters_must_not_read_persistence_or_services` now pass; the full architecture module is **127 passed**.
- **Full-suite stall — environment/test infrastructure:** the exact first stalled test is `tests/test_attachment_restart_recovery.py::test_api_end_to_end_restart_smoke_relational_metadata_local_content`. An isolated verbose run also stalled before reporting the first test result and was stopped by a 25-second command timeout. A minimal FastAPI app with an empty lifespan reproduces the hang at `TestClient.__enter__`; a bare AnyIO blocking portal likewise fails to schedule its coroutine, leaving its event-loop thread idle. The observed failure occurs before AVA lifespan recovery, attachment routes, temporary storage, or SQLite are entered. The full-suite run was stopped by the 45-second timeout (exit 124), not by an assertion failure or a manual interrupt.
- The restart-recovery test itself retains its relational metadata/local content restart and byte-exact read assertions. No attachment test was weakened.
- No new Phase 5 data-loss, migration, attachment, or compaction regression was identified in the passing focused checks.

## Persistence and migration sanity

- Backend imports and `create_app()` construction: **PASS**.
- Migration registry/current schema: version **23**, recognized by the passing migration suite.
- Migration tests: **31 passed**.
- The current development database was previously opened read-only during this validation pass; SQLite integrity returned `ok` at schema version 23. No active DB or backup DB was modified.

## Final status

**#46 Backend Validation — PARTIAL.** The direct compaction-service dependency is resolved and all completed quality/focused gates pass. The full-suite result is unavailable because of the Starlette/AnyIO TestClient portal hang, and runtime-neutral context-window fitting remains unfinished. Therefore the backend cannot be recorded as fully validated yet.
