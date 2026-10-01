# Phase 5.40A — Backend Full Validation (working notes)

Temporary working notes for Substep 5.40A only. Final consolidation belongs to
Phase 5.40E; this file is not the Phase 5.40 closure document.

## Status

5.40A Backend Full Validation — **CLOSED**
5.40B Frontend Full Validation — not started
5.40C Builds / Static / Architecture — not started
5.40D Canonical Validation Harness — not started
5.40E Reconciliation / Closure — not started

## Command

```bash
cd /home/bizon/AvaUi/backend
.venv/bin/pytest -q
```

## Final canonical backend baseline

| Metric | Value |
| --- | --- |
| Collected | 2153 |
| Passed | 2151 |
| Failed | 0 |
| Skipped | 2 |
| Warnings | 4 |
| Duration | 76.42s (final run) |
| Exit code | 0 |

The 2 skips are opt-in live local-model qualification, gated on
`AVA_RUN_LOCAL_MODEL_QUALIFICATION=1` (`test_openhands_native_tool_qualification_live.py`).
They are environment-gated by design and are not a regression.

Previous baseline for comparison: 2041 collected / 2039 passed / 2 skipped / 4
warnings / 59.94s, established after Phase 5.34. Growth of +112 collected tests
is attributable to Phases 5.35, 5.38, and 5.39.

## Warning review

All 4 warnings are the single known third-party category, unchanged from the
Phase 5.34 baseline:

```
DeprecationWarning: Deprecated since v1.42.0 and scheduled for removal in
v1.47.0. LiteLLM parameter modification is enabled process-wide; remove this
argument.
  openhands/sdk/agent/base.py:772
  tests/test_openhands_file_tools.py (4 tests)
```

Warning count is identical to the pre-5.35 baseline (4), so **no new warning
category was introduced by Phase 5**. Nothing was suppressed.

## Failure encountered

One failure on the first full run:

```
tests/test_architecture.py::test_run_service_does_not_own_security_policy
AssertionError: assert not ({'agents', 'contracts', 'execution', 'repositories',
'services'} & {'execution', 'runtimes', 'workspaces'})
```

**Classification: A — real regression (architectural), not behavioral.**

Phase 5.35 added `from ava.execution.persisted_execution import
ExecutionConfigurationError` to `RunService` so the service could classify a
configuration failure into a durable AVA error code. That import crosses the
documented dependency direction: the services layer must not import
`ava.execution`. The codebase is explicit that the native agent adapter is the
integration seam permitted to depend on execution
(`test_native_agent_depends_only_on_contracts_and_stdlib` allows
`ava.execution.*`); the run service is not.

The guard was never exercised in Phases 5.35, 5.38, or 5.39, because each of those
phases ran only focused suites. This is precisely the class of regression
5.40A exists to catch.

No user-facing behavior was broken: configuration-failure classification was
working, and the second assertion in the same test (which names the actual
security-policy types) still passed.

## Production fix

Fixed at the smallest responsible layer — the error's *location*, not its
behavior. The failure type crosses the `AgentPort` boundary, so it belongs to
the contract both sides share.

1. `src/ava/agents/contracts.py` — added the `ExecutionConfigurationError`
   definition to the port contract module, with a docstring recording why it
   lives there rather than in `ava.execution`.
2. `src/ava/execution/persisted_execution.py` — removed the local definition and
   re-exported the imported name (plus an explicit `__all__`). All concrete
   subclasses remain in place.
3. `src/ava/services/run_service.py` — one import line now sources the error
   from `ava.agents.contracts`, which the service already imported.

This is the **same class object** on both import paths (verified
`A is B → True`), so every existing `except` clause still matches and no
parallel hierarchy was created. No behavior, schema, migration, or public
contract changed.

Deliberately *not* done: weakening the architecture test, adding an `execution`
exception to its allow-list, or relocating the failure mapping out of the
service. The test encodes a deliberate layering rule; the violation was in the
production import, so the import was corrected.

## Tests changed

None. No test expectation was edited, relaxed, or skipped. The existing guard
was allowed to keep doing its job.

## Validation sequence

| Step | Command | Result |
| --- | --- | --- |
| Failing test, directly | `pytest tests/test_architecture.py::test_run_service_does_not_own_security_policy` | 1 passed |
| Architecture area | `pytest tests/test_architecture.py` | 124 passed |
| Configuration/execution focus | `pytest tests/test_run_service_configuration_failures.py tests/test_persisted_execution_integration.py tests/test_execution_configuration_resolver.py tests/test_execution_defaults.py tests/test_configuration_bootstrap.py tests/test_workspace_execution.py tests/test_run_events.py tests/test_restart_durability_integration.py` | 205 passed |
| Static (code changed) | `ruff check .` | All checks passed |
| Static (code changed) | `mypy src/ava` | Success, 181 source files |
| Full suite, run 1 | `.venv/bin/pytest -q` | 1 failed, 2150 passed, 2 skipped, exit 1 |
| Full suite, run 2 | `.venv/bin/pytest -q` | 2151 passed, 2 skipped, exit 0, 76.42s |
| Full suite, run 3 | `.venv/bin/pytest -q -rs` | 2151 passed, 2 skipped, exit 0, 75.37s |

## Concurrency flakiness

The Phase 5.39 race suites were re-stressed for the 5.40A criterion "no known
flaky race test remains":

| Check | Result |
| --- | --- |
| `test_run_lifecycle_races.py` + `test_run_event_concurrency.py` + `test_run_creation_races.py`, 5 consecutive runs | 96 passed every run, 11.05–11.18s |
| Same three files, declared in reverse order (order-dependence check) | 96 passed |

Plus two clean full-suite runs containing all of them. No synchronization
changes were needed and no test was modified.

## Files changed in 5.40A

* `backend/src/ava/agents/contracts.py`
* `backend/src/ava/execution/persisted_execution.py`
* `backend/src/ava/services/run_service.py`
* `docs/AVA_Phase_5_40A_Backend_Full_Validation_Notes.md` (this file)

## Explicitly not done in 5.40A

No frontend validation, no `pnpm` commands, no Web or Desktop builds, no frontend
lint or type checks, no Phase 5.40B–5.40E work, and no Phase 5.40 closure
document. Ruff and mypy were run only because production code changed, as
section 13 permits; the formal static validation belongs to 5.40C.
