# Phase 5.40D — Canonical Validation Harness (working notes)

Temporary working notes for Substep 5.40D only. Phase 5.40E owns consolidation
into the final Phase 5.40 validation document. This file is not the Phase 5.40
closure document.

## Status

```
5.1–5.39                           COMPLETE
5.40A Backend Full Validation      COMPLETE
5.40B Frontend Full Validation     COMPLETE
5.40C Static / Architecture / Builds COMPLETE
5.40D Canonical Validation Harness COMPLETE
5.40E Reconciliation / Closure     NOT STARTED
```

## Harness identification

* Path: `scripts/test_all.sh`
* Established since Phase 3/4, referenced throughout
  `docs/AVA_Phase_4_Implementation_Log.md` and the canonical plan.
* Invocation: `./scripts/test_all.sh` from repo root.
* No `Makefile`, no `pnpm validate`, no second aggregate script exists.

## Command

```bash
cd /home/bizon/AvaUi
./scripts/test_all.sh
```

## Harness contents (read before running)

`set -euo pipefail`, so any stage failure aborts the run with a non-zero exit.
`ROOT` is derived from the script location, so it is cwd-independent.

Stages, in order:

| # | Stage | Command (from `ROOT`) |
| --- | --- | --- |
| 1 | Backend tests | `(cd backend && <backend python> -m pytest)` |
| 2 | Backend lint | `(cd backend && python -m ruff check src tests)` |
| 3 | Backend typecheck | `(cd backend && python -m mypy src)` |
| 4 | Frontend tests | `(cd frontend && pnpm -r --if-present test)` |
| 5 | Frontend lint | `(cd frontend && pnpm -r --if-present lint)` |
| 6 | Python client checks | `(cd clients/python && python -m pytest)` then `ruff check src tests` then `mypy src` |

`detect_python()` prefers `backend/.venv/bin/python`, falling back to
`python3`/`python`. The script hard-requires `clients/python/.venv/bin/python`
and exits 1 if absent; the venv is present.

## Environment overrides

The harness itself exports nothing. Environment isolation is provided by
`backend/conftest.py`, which sets every `AVA_*` variable at conftest import time:

* `AVA_PERSISTENCE=memory`
* `AVA_PERSISTENCE_DATABASE_URL=<tmpdir>/ava-backend-tests/ava-test.sqlite3`
* `AVA_ATTACHMENT_STORAGE=memory`
* `AVA_ATTACHMENT_STORAGE_ROOT=<tmpdir>/ava-backend-tests/attachments`

This is the established Phase 5 isolation: the tracked `backend/ava.sqlite3` and
`backend/.ava/` cannot be touched by the suite. No manual `export` was used and
none was needed; adding one would have masked contamination rather than fixing
it (§15). No harness env override was introduced.

## Results

Wall-clock: **95.3s** (1m35.299s real). Exit code: **0**.

| Stage | Result |
| --- | --- |
| Backend tests | `2151 passed, 2 skipped, 4 warnings in 75.49s` |
| Backend lint (ruff `src tests`) | `All checks passed!` |
| Backend typecheck (mypy `src`) | `Success: no issues found in 181 source files` |
| Frontend tests | 8 packages / 69 test files / **685 passed, 4 skipped** |
| Frontend lint | 10/10 packages `Done` |
| Python client pytest | `10 passed in 0.09s` |
| Python client ruff | `All checks passed!` |
| Python client mypy | `Success: no issues found in 3 source files` |

### Backend reconciliation vs 5.40A

| Metric | 5.40A | Harness | Match |
| --- | --- | --- | --- |
| Collected | 2153 | 2153 | yes |
| Passed | 2151 | 2151 | yes |
| Failed | 0 | 0 | yes |
| Skipped | 2 | 2 | yes |
| Warnings | 4 | 4 | yes |

The only difference is command shape: 5.40A used `.venv/bin/pytest -q`, the
harness uses `<same venv> -m pytest` with default verbosity. Same interpreter,
same `testpaths = ["tests"]`, same collection. Duration differs only by noise
(75.49s vs 76.42s).

### Frontend reconciliation vs 5.40B

| Metric | 5.40B | Harness | Match |
| --- | --- | --- | --- |
| Test files passed | 69 | 69 | yes |
| Passed | 685 | 685 | yes |
| Failed | 0 | 0 | yes |
| Skipped | 4 | 4 | yes |

5.40B ran `pnpm test` (root `pnpm -r test`); the harness runs
`pnpm -r --if-present test` from `frontend/`. `--if-present` only suppresses the
error for packages lacking a `test` script; the same 8 packages participate and
the counts are identical.

### Static reconciliation vs 5.40C

| Check | 5.40C | Harness | Note |
| --- | --- | --- | --- |
| Ruff | PASS (`ruff check .`) | PASS (`ruff check src tests`) | harness scope is a subset; it omits repo-root files such as `conftest.py`, all of which 5.40C checked |
| mypy | PASS (181 files) | PASS (181 files) | identical |
| Frontend lint/typecheck | PASS (10/10) | PASS (10/10) | identical |
| Backend architecture | 124 passed | implicitly included | full `pytest` runs `tests/test_architecture.py` |
| Frontend architecture | 17 passed | implicitly included | harness output shows `settings.architecture.test.ts (15)` and `step411.architecture.test.ts (2)` |
| Web build | PASS (199 modules) | not included | certified in 5.40C |
| Desktop build | PASS (199 modules) | not included | certified in 5.40C |
| `git diff --check` | PASS | not included | certified in 5.40C |

No disagreement with 5.40C. The two omitted categories are intentional harness
scope, not failures (§22).

## Architecture coverage confirmation

* Backend: full `pytest` includes `tests/test_architecture.py` (124 tests). It is
  not separately named, but no `--ignore`/`-k` filter exists and `testpaths`
  covers the whole `tests/` tree, so it runs.
* Frontend: `pnpm -r test` includes both guards, visible in the harness log:
  `settings.architecture.test.ts (15 tests)` and
  `step411.architecture.test.ts (2 tests)`.

## Warning reconciliation

| Source | Warning | Change |
| --- | --- | --- |
| Backend pytest | 4× OpenHands/LiteLLM `DeprecationWarning` at `openhands/sdk/agent/base.py:772` | unchanged |
| Ruff (backend + client) | none | — |
| mypy (backend + client) | none | — |
| Frontend `tsc` lint | none | — |
| Builds | not run by harness | Vite advisory certified unchanged in 5.40C |

No new warning category.

## Skip reconciliation

| Skip | Count | Reason | State |
| --- | --- | --- | --- |
| Backend `test_openhands_native_tool_qualification_live.py` | 2 | opt-in live local-model qualification (`AVA_RUN_LOCAL_MODEL_QUALIFICATION=1`) | unchanged, not enabled by harness |
| Frontend `live-workspace-run.integration.test.tsx` | 4 | opt-in live backend (`AVA_LIVE_BACKEND_URL`) | unchanged, not enabled by harness |

The harness sets neither variable, so the same 2 + 4 skips remain gated exactly
as certified. No unexplained skip drift.

## Working-tree integrity

Captured before and after the run and diffed:

* `git status --short`: **byte-identical** before and after (69 entries pre,
  69 post; the only 5.40C/5.40D additions are the notes documents).
* `git diff --check`: clean before and after.
* `backend/ava.sqlite3`: `sha256 18588fa3…cd697`, mtime `1790426228`, size
  `790528` — **unchanged** (checksum verified post-run).
* `backend/.ava/`: **220 files** before and after — unchanged.
* No new untracked runtime artifact, no rewritten lockfile, no tracked build
  artifact.

## Harness completeness matrix

| Check | Coverage |
| --- | --- |
| Backend full tests | directly included |
| Backend Ruff | directly included (scope `src tests`) |
| Backend mypy | directly included |
| Backend architecture guards | implicitly included (full pytest) |
| Frontend full tests | directly included |
| Frontend lint/typecheck | directly included |
| Frontend architecture guards | implicitly included (`pnpm -r test`) |
| Web build | not included |
| Desktop build | not included |
| `git diff --check` | not included |
| Python client tests/lint/typecheck | directly included (extra stage beyond 5.40A–C) |

## Failures and fixes

None. The harness completed with exit 0 on the first run. No production code, no
test, and no harness line was changed. The harness is not broken or incomplete
relative to its own scope: it stops on error, propagates exit codes, uses the
correct working directories, and does not touch the developer DB (conftest
isolation). Its omission of builds and `git diff --check` is long-standing scope,
and §17/§22 say to document that rather than expand it here.

## Files changed in 5.40D

* `docs/AVA_Phase_5_40D_Canonical_Validation_Harness_Notes.md` (this file)

No other file was created or modified.
