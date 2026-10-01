# Phase 5.40C — Static / Architecture / Builds (working notes)

Temporary working notes for Substep 5.40C only. Phase 5.40E owns consolidation
into the final Phase 5.40 validation document. This file is not the Phase 5.40
closure document.

## Status

```
5.1–5.39                           COMPLETE
5.40A Backend Full Validation      COMPLETE
5.40B Frontend Full Validation     COMPLETE
5.40C Static / Architecture / Builds COMPLETE
5.40D Canonical Validation Harness NOT STARTED
5.40E Reconciliation / Closure     NOT STARTED
```

## Canonical commands and results

### Backend static

```bash
cd /home/bizon/AvaUi/backend
.venv/bin/ruff check .
.venv/bin/mypy src/ava
```

| Check | Result | Exit |
| --- | --- | --- |
| Ruff | `All checks passed!` | 0 |
| mypy | `Success: no issues found in 181 source files` | 0 |

mypy scope is exactly the expected 181 source files. No new failure.

### Frontend lint / type check

There is **no separate `typecheck` script** anywhere in the repo. Every frontend
package defines `"lint": "tsc --noEmit"`, and the root defines
`"lint": "pnpm -r lint"`. So `pnpm lint` *is* the canonical recursive type
check. Forcing a second type-check matrix would have invented a command, which
§3/§4 forbid.

```bash
cd /home/bizon/AvaUi
pnpm lint
```

| Package | Script | Result |
| --- | --- | --- |
| @ava/contracts | `tsc --noEmit` | Done |
| @ava/api-client | `tsc --noEmit` | Done |
| @ava/ui-core | `tsc --noEmit` | Done |
| @ava/agent-ui | `tsc --noEmit` | Done |
| @ava/settings-core | `tsc --noEmit` | Done |
| @ava/document-core | `tsc --noEmit` | Done |
| @ava/workspace | `tsc --noEmit` | Done |
| @ava/web | `tsc --noEmit` | Done |
| @ava/desktop | `tsc --noEmit` | Done |
| @ava/mobile | `tsc --noEmit` | Done |

Exit code 0, 10/10 packages, no `error TS` line in the log.

### Architecture guards

```bash
cd /home/bizon/AvaUi/backend
.venv/bin/pytest -q tests/test_architecture.py
```

Result: **124 passed in 1.31s**. This is the suite that contains
`test_run_service_does_not_own_security_policy`, the guard that caught the
5.40A regression, and it remains green.

Frontend guards, run explicitly (in addition to their inclusion in 5.40B):

| Guard | Scope | Result |
| --- | --- | --- |
| `workspace/src/step411.architecture.test.ts` | transport/persistence/editor/scope tokens out of UI shells; web+desktop stay on `@ava/workspace` | 2 passed |
| `settings-core/src/settings.architecture.test.ts` | Settings transport, secret, storage, state-lib, and exact-write-set boundaries | 15 passed |

No separate dependency-cruiser / madge / ESLint-boundary tool exists in the repo
(verified by search). Architecture enforcement is these Vitest guards plus the
Python `test_architecture.py` suite.

## ExecutionConfigurationError boundary (5.40A fix)

Verified directly against the imported objects:

```
agents.ExecutionConfigurationError is execution.ExecutionConfigurationError  -> True
owned by module                                                             -> ava.agents.contracts
MRO                                                                         -> [ava.agents.contracts.ExecutionConfigurationError, ValueError, Exception, BaseException, object]
issubclass(..., ValueError)                                                  -> True
concrete subclasses in persisted_execution (all still subclass the base)     -> 9
persisted_execution.__all__ entries / missing                               -> 11 / []
run_service imports from ava.execution                                      -> NONE
run_service imports ExecutionConfigurationError                             -> True (from ava.agents.contracts)
```

The compatibility re-export is the same class object, so every existing
`except` still matches; the architecture suite accepts it. Left in place as §6
requires.

## Dependency / package boundaries

### Backend

| Boundary | Result |
| --- | --- |
| `services/` importing `ava.execution.*` | NONE |
| `RunService` → `AgentPort` / `ExecutionConfigurationError` | from `ava.agents.contracts` |
| `RunService` → `ava.runtimes` / `ava.workspaces` | NONE (architecture tests) |
| `ConversationService` → `RunEventRepository` (port) | yes, `ava.repositories.run_event_repository` |
| `RunRecoveryService` boundaries | covered by 124-test architecture suite, green |
| `services/` → `ava.runtimes.configurations` / `registry` | allowed domain types (settings/registry catalog), not execution/transport implementation; architecture suite accepts |

The only services references to `ava.runtimes` are the configuration *catalog*
types consumed by settings, which the architecture contract permits. No service
reaches a runtime/execution *adapter* implementation layer.

### Frontend

Resolved workspace dependency graph (from `package.json`):

```
@ava/contracts      -> (leaf)
@ava/ui-core        -> (leaf)
@ava/api-client     -> contracts
@ava/agent-ui       -> api-client, contracts, ui-core
@ava/document-core  -> api-client, contracts, ui-core
@ava/settings-core  -> api-client, contracts, ui-core
@ava/workspace      -> agent-ui, api-client, document-core, settings-core, ui-core
@ava/web            -> api-client, workspace
@ava/desktop        -> api-client, workspace
@ava/mobile         -> (none)
```

| Required boundary | Result |
| --- | --- |
| `agent-ui` → `settings-core` implementation | **NONE** (zero references) |
| `services → execution` (backend) | forbidden and absent |
| shells (web/desktop) → shared packages | allowed; both depend only on api-client + workspace |
| `workspace` → `settings-core` | allowed; imports package root only, no deep path |
| `settings-core` → `ui-core` | allowed |
| `agent-ui` → `ui-core` | allowed |
| dependency cycles | none (graph is a DAG) |

`SettingsSectionId` ownership confirmed:

* Defined in `ui-core/src/state/settingsSection.ts`.
* Re-exported from `settings-core/src/settings/SettingsSectionNav.tsx` and
  `settings-core/src/index.ts` (`export type { SettingsSectionId } from "@ava/ui-core"`).
* Consumed by `SettingsWorkspace.tsx` and `settingsSectionPanelId`.

## Builds

Only `@ava/web` and `@ava/desktop` define a `build` script; root `build` is
`pnpm -r build`, which therefore covers exactly those two. No library builds were
invented (§10).

### Web

```bash
cd /home/bizon/AvaUi
pnpm --filter @ava/web build
```

* Exit code 0, built in 1.74s
* 199 modules transformed
* `dist/index.html` 0.40 kB
* `dist/assets/index-DuWeGZp6.css` 3.63 kB (gzip 1.13 kB)
* `dist/assets/index-CBixrr7W.js` 664.99 kB (gzip 205.06 kB)
* One warning: Vite chunk-size advisory (see below)

### Desktop

```bash
cd /home/bizon/AvaUi
pnpm --filter @ava/desktop build
```

* Exit code 0, built in 1.76s
* 199 modules transformed
* Byte-identical output to Web: `index-DuWeGZp6.css` 3.63 kB,
  `index-CBixrr7W.js` 664.99 kB (gzip 205.06 kB)
* One warning: the same Vite chunk-size advisory

Both builds run `tsc --noEmit && vite build`, so the shell type check is part of
the build already.

### Other build-bearing packages

None. `@ava/document-core`, `@ava/settings-core`, `@ava/ui-core`,
`@ava/contracts`, `@ava/api-client`, `@ava/agent-ui`, `@ava/workspace` have no
build script and are consumed as TypeScript source via `workspace:*`.

### Mobile

`@ava/mobile` has only `lint` (`tsc --noEmit`), covered by `pnpm lint`, and it
passed. No test script, no build script. No mobile build requirement was
created (§11).

## Warnings

| Source | Warning | Classification |
| --- | --- | --- |
| Ruff | none | — |
| mypy | none | — |
| `pnpm lint` (tsc) | none | — |
| architecture tests | none | — |
| Web build | Vite `(#!) Some chunks are larger than 500 kB after minification` | pre-existing, accepted |
| Desktop build | same Vite advisory | pre-existing, accepted |
| `git diff --check` | none | — |

The Vite advisory is **unchanged**: both builds emit exactly the same hashes and
sizes recorded in `docs/AVA_Phase_5_37_Desktop_Acceptance.md`
(`index-DuWeGZp6.css` 3.63 kB, `index-CBixrr7W.js` 664.99 kB, gzip 205.06 kB).
No `manualChunks` is configured in either `vite.config.ts`, which is why the
single shared chunk exceeds 500 kB. Nothing was suppressed.

## git diff --check

```bash
cd /home/bizon/AvaUi
git diff --check
```

Passed, exit code 0, no output. Important because the tree carries uncommitted
Phase 5.30–5.39 work across Python, TS, and docs.

## Working tree review

Captured **before** any build, and the post-build status is byte-identical, so
5.40C introduced no new tracked or untracked change.

* **41 modified tracked files** — Phase 5.30–5.39 backend source/tests, frontend
  source/tests, `docs/AVA_Phase_5_30...md`, and `pnpm-lock.yaml` (updated when
  the Desktop package gained its test harness). All pre-existing.
* **27 untracked entries** — all new Phase 5 source/tests/docs except one:
  * `backend/.ava/` — local attachment store directory.
  * `backend/src/ava/contracts/attempts.py`, 6 new backend test files.
  * 9 Phase 5.31–5.39 docs + 5.40A/5.40B working notes.
  * Desktop test harness (`src/App.test.tsx`, `src/test/`, `vitest.config.ts`).
  * `agent-ui/src/lib/errorPresentation.{ts,test.ts}`, `runActions.ts`,
    `runStreamResumeRaces.test.ts`, `ui-core/src/state/settingsSection.ts`.

### Local artifacts

| Artifact | Status | Action |
| --- | --- | --- |
| `backend/.ava/` | untracked, contains `attachments/` | expected local state; not deleted |
| `backend/ava.sqlite3` | **tracked, unmodified** (790 KB) | note: a local SQLite DB is committed in the repo, but this phase did not change it; no action taken in 5.40C |

`backend/ava.sqlite3` being tracked is a pre-existing repo hygiene observation,
not a build side effect. It is unchanged and outside 5.40C's mandate to alter.

## Build artifact pollution

`dist/` output is gitignored (`.gitignore:26`), which cover both
`frontend/apps/web/dist/` and `frontend/apps/desktop/dist/`. `git status --short`
before and after the builds is identical; no `*.tsbuildinfo` was produced. No
tracked source or generated artifact changed. Nothing to fix.

## Test suites

No backend or frontend full suite was rerun (§1, §17). No production code
changed, so no focused tests were required. The explicit architecture runs above
(`tests/test_architecture.py`, `step411.architecture.test.ts`,
`settings.architecture.test.ts`) are architecture guards, not the canonical
suites certified in 5.40A/5.40B.

## Files changed in 5.40C

* `docs/AVA_Phase_5_40C_Static_Architecture_Builds_Notes.md` (this file)

No production, test, or config file was edited.
