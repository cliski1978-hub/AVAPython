# Phase 5.40B — Frontend Full Validation (working notes)

Temporary working notes for Substep 5.40B only. Phase 5.40E owns consolidation
into the final Phase 5.40 validation document. This file is not the Phase 5.40
closure document.

## Status

```
5.1–5.39                    COMPLETE
5.40A Backend Full Validation COMPLETE
5.40B Frontend Full Validation COMPLETE
5.40C Static / Architecture / Builds   NOT STARTED
5.40D Canonical Validation Harness    NOT STARTED
5.40E Reconciliation / Closure        NOT STARTED
```

## Canonical command

```bash
cd /home/bizon/AvaUi
pnpm test
```

Root `package.json` defines `"test": "pnpm -r test"`, so the canonical command is
the repository's own recursive script. No new command was invented.

Vitest 2.1.9, run via pnpm 9. All 8 packages that define a `test` script
participate. `@ava/web` and `@ava/mobile` have no `test` script and were not
forced (§5).

## Final canonical frontend baseline

| Metric | Value |
| --- | --- |
| Test files passed | 69 |
| Tests passed | 685 |
| Tests failed | 0 |
| Tests skipped | 4 |
| Total collected | 689 |
| Packages participating | 8 of 8 with a test script |
| Wall-clock duration | ~10s |
| Exit code | 0 |

## Package-by-package results

| Package | Files | Passed | Failed | Skipped | Vitest duration |
| --- | --- | --- | --- | --- | --- |
| @ava/contracts | 8 | 23 | 0 | 0 | 0.58s |
| @ava/api-client | 10 | 79 | 0 | 0 | 0.44s |
| @ava/ui-core | 9 | 51 | 0 | 0 | 1.42s |
| @ava/agent-ui | 19 | 205 | 0 | 0 | 2.19s |
| @ava/settings-core | 10 | 191 | 0 | 0 | 3.05s |
| @ava/document-core | 7 | 69 | 0 | 0 | 4.84s |
| @ava/workspace | 5 passed / 1 skipped | 56 | 0 | 4 | 2.00s |
| @ava/desktop | 1 | 11 | 0 | 0 | 1.24s |
| **Total** | **69 passed** | **685** | **0** | **4** | ~10s wall |

No aggregate total is emitted by pnpm; 685 is the sum of the 8 per-package
Vitest summaries.

## Baseline reconciliation (§2, §16, §17, §18)

Every expected count entering 5.40B was confirmed exactly:

| Expected | Actual | Note |
| --- | --- | --- |
| @ava/agent-ui 205 | 205 | Phase 5.38 `execution_interrupted` presentation and Phase 5.39 race/supersession coverage both included. |
| @ava/workspace 56 passed / 4 skipped | 56 / 4 | Identical. |
| @ava/desktop 11 | 11 | Phase 5.37 Desktop acceptance suite intact. |

Counts for the remaining five packages were not pre-declared and are now
recorded as the new baseline.

## Skipped-test review (§19)

All 4 skips are in one file:
`frontend/packages/workspace/src/live-workspace-run.integration.test.tsx`.

Classification: **intentional opt-in / live integration**. The whole suite is
guarded by `describe.skipIf(!liveBackendUrl)` and runs only when
`AVA_LIVE_BACKEND_URL` is set. It deliberately does not mock `@ava/api-client`,
exercising the production UI and client against a real running backend for the
Step 32 end-to-end path.

No unexpected skip, no environment-gated skip, and no temporary technical debt
skip exists anywhere in the frontend. This is the only skip in the workspace
and the only skip in the repository's frontend tests.

## Failures encountered

**None.** The first canonical run was fully green, so no classification under
§8 (A–F) was required, and no edit was made under §9, §10, or §11.

## Production fixes

**None.** No frontend production code was touched in 5.40B.

## Tests changed

**None.** No test file was added, edited, relaxed, or skipped.

Because no file changed in 5.40B, `git diff --check` was not rerun (§22); it
belongs to 5.40C.

## Race and supersession stability (§7, §12)

The Phase 5.39 mutation-verified suites are load-bearing, so they were
re-stressed before entering the baseline.

| Check | Result |
| --- | --- |
| `agent-ui/src/run/runStreamResumeRaces.test.ts` + `run/conversationRun.test.ts`, 5 consecutive runs | 55 passed every run |
| `workspace/src/conversation-selection.test.tsx`, 5 consecutive runs | 16 passed every run |
| Full `pnpm test`, 4 independent reruns | 685 passed / 4 skipped / exit 0 every time |

No test synchronization changes were needed. Resume-loop deduplication,
sequence handling, `runEpoch`, `ConversationProvider` `loadGenerationRef`, and
same-id stale-content protection all hold deterministically. No flaky test is
admitted into the 5.40 baseline.

## Test-isolation check (§11)

Ordering pollution was ruled out by running every package in isolation via
`pnpm --filter <pkg> test`. All 8 produced byte-identical counts to the
recursive run, and pnpm executed them in a different order, so no global mock,
module-level singleton, fake timer, DOM cleanup, or Vitest module cache
pollution exists between packages.

## Packages with no tests

| Package | Scripts | Reason |
| --- | --- | --- |
| @ava/web | build, dev, lint, preview | No `test` script. Its acceptance was manual in 5.36/5.37. No `*.spec.*` or `*.e2e.*` files exist under `apps/web`. |
| @ava/mobile | lint | No `test` script. |

Not forced (§5). Both are build/lint-only surfaces today; if Web e2e coverage is
wanted later it should be scoped as its own decision, not backfilled here.

## Not run in 5.40B (§13, §20, §21)

No frontend lint, no frontend typecheck, no Web build, no Desktop build, no
Ruff, no mypy, no backend pytest rerun. None was needed, because no production
code changed. All of that belongs to 5.40C.

## Files changed in 5.40B

* `docs/AVA_Phase_5_40B_Frontend_Full_Validation_Notes.md` (this file)

Nothing else. The Phase 5.35–5.39 modifications visible in `git status` were
already present before this substep and were only validated, not edited.
