# Phase 5.40 — Full Validation (Authoritative Record)

This is the authoritative Phase 5.40 validation record. It reconciles the four
certified validation layers into one result. It is not a concatenation of the
per-substep notes: where the four layers agree, the agreement is stated once;
where they differ in scope, the scope difference is stated explicitly.

Per-substep working notes remain in:

* `docs/AVA_Phase_5_40A_Backend_Full_Validation_Notes.md`
* `docs/AVA_Phase_5_40B_Frontend_Full_Validation_Notes.md`
* `docs/AVA_Phase_5_40C_Static_Architecture_Builds_Notes.md`
* `docs/AVA_Phase_5_40D_Canonical_Validation_Harness_Notes.md`

## Verdict

**Phase 5.40 passed.** The final Phase 5 codebase is green on every certified
layer: backend tests, frontend tests, static analysis, type safety, architecture
rules, and both production builds. One real production defect was found and fixed
during validation. No failure, no unexplained skip, no unexplained warning, no
unexplained count drift, and no known flaky test remains.

## Scope of Phase 5.40

| Substep | Layer |
| --- | --- |
| 5.40A | Backend full validation |
| 5.40B | Frontend full validation |
| 5.40C | Static, architecture, and builds |
| 5.40D | Canonical validation harness |
| 5.40E | Reconciliation and closure (this document) |

### Why 5.40 was split

A single monolithic validation run would have produced one opaque pass/fail
signal. Splitting it bought three things that a blob cannot:

* **Failure isolation by layer.** A test failure, a type error, an architecture
  violation, and a build break are different classes of problem with different
  owners. Separating them means a regression is *classified* rather than merely
  reported. This is not theoretical: 5.40A found a real architecture regression
  that the layer split exposed and the aggregate harness would have reported as
  an anonymous "backend failed".
* **Honest classification.** When 5.40A hit the violation, the question "is this
  a stale expectation or a wrong dependency?" was answerable from the layer
  contract rather than guessed at.
* **Cheap re-certification.** Because layers are independent, a change in
  frontend code requires re-certifying 5.40B and possibly 5.40C, not the entire
  matrix.

## Backend baseline

Authoritative result, reproduced twice (5.40A and the 5.40D harness):

```text
2153 collected
2151 passed
0 failed
2 skipped
4 warnings
exit 0
```

Duration is not part of the contract: 76.42s in 5.40A, 75.49s in the harness.

### Growth against the Phase 5.34 baseline

```text
2041 collected / 2039 passed / 2 skipped / 4 warnings
→
2153 collected / 2151 passed / 2 skipped / 4 warnings
```

**+112 collected, +112 passed, skips and warnings unchanged.** The growth is
Phase 5.35–5.39 coverage: configuration-failure integration, restart/durability
integration, and race/concurrency hardening. No test was deleted or weakened to
produce this number; the same 2 skips and 4 warnings are present at both ends of
the range.

### Backend skips

Both are intentional, opt-in, live/local-model qualification tests gated by
`AVA_RUN_LOCAL_MODEL_QUALIFICATION=1`, in
`tests/test_openhands_native_tool_qualification_live.py`. They are excluded by
design, not by a bug or a broken environment. **No unexplained backend skip
remains.**

### Backend warnings

All 4 are the same third-party category:

```text
openhands/sdk/agent/base.py:772
DeprecationWarning: LiteLLM parameter modification is enabled process-wide
```

Same category and same count as the earlier baseline, so **Phase 5 introduced no
new warning category**. Nothing was suppressed or filtered to reach a clean line.

## Frontend baseline

```text
69 test files
685 passed
0 failed
4 skipped
689 collected
8/8 test-bearing packages green
exit 0
```

| Package | Files | Passed | Failed | Skipped |
| --- | --- | --- | --- | --- |
| @ava/contracts | 8 | 23 | 0 | 0 |
| @ava/api-client | 10 | 79 | 0 | 0 |
| @ava/ui-core | 9 | 51 | 0 | 0 |
| @ava/agent-ui | 19 | 205 | 0 | 0 |
| @ava/settings-core | 10 | 191 | 0 | 0 |
| @ava/document-core | 7 | 69 | 0 | 0 |
| @ava/workspace | 5 passed / 1 skipped | 56 | 0 | 4 |
| @ava/desktop | 1 | 11 | 0 | 0 |
| **Total** | **69 passed** | **685** | **0** | **4** |

`@ava/web` and `@ava/mobile` define no `test` script and were not forced to.

### Frontend skips

All 4 are in one file,
`frontend/packages/workspace/src/live-workspace-run.integration.test.tsx`: the
live-backend integration suite, guarded by `describe.skipIf(!liveBackendUrl)`
and gated on `AVA_LIVE_BACKEND_URL`. It deliberately does not mock
`@ava/api-client`; it exercises the production UI and client against a real
running backend. **No unexplained frontend skip remains.**

## Stability evidence

### Backend concurrency

The 96 Phase 5.39 race tests (lifecycle, run-event concurrency, run-creation)
passed **5 consecutive clean runs** in reverse and forward file order, and
multiple complete backend suite runs were clean. No known concurrency-test
flakiness remains.

### Frontend concurrency

| Suite | Repetition | Result |
| --- | --- | --- |
| `runStreamResumeRaces.test.ts` + `conversationRun.test.ts` | 5 consecutive runs | 55 passed each time |
| `conversation-selection.test.tsx` | 5 consecutive runs | 16 passed each time |
| full `pnpm test` | 4 clean reruns | 685 passed / 4 skipped each time |

Cross-package ordering pollution was separately ruled out by running all 8
packages in isolation in a different order, which produced identical counts.

**No test entered the final baseline with known flakiness.** This is a statement
about what the repeated runs demonstrated, not a claim of zero risk.

## The defect Phase 5.40 found

5.40 found exactly one production defect.

### What was wrong

`RunService` imported `ExecutionConfigurationError` from
`ava.execution.persisted_execution`. That crossed the documented dependency
direction: services must not import `ava.execution`. The codebase is explicit
that the native agent *adapter* is the integration seam permitted to depend on
execution; the run service is not. The guard went unexercised through 5.35–5.39
because each of those phases ran only focused suites — exactly the blind spot
5.40 exists to close.

### How it was fixed

The error was moved to the contract both sides share, not to wherever the
caller happened to be:

* `ExecutionConfigurationError` is now owned by `ava.agents.contracts`.
* `ava.execution.persisted_execution` re-exports **the same class object** for
  compatibility; all 9 concrete subclasses remain there.
* `RunService` imports it from `ava.agents.contracts`.

Verified: same class identity on both import paths; `issubclass(..., ValueError)`
holds; `__all__` resolves with no missing names; `RunService` has no
`ava.execution` import.

### What was deliberately not done

* The architecture test was not weakened, deleted, or allow-listed. The rule is
  correct; the import was wrong.
* Production behavior is unchanged. No schema, migration, or public contract
  changed.
* The compatibility re-export was kept, so existing `except` clauses still match
  the identical class object. No test was edited, relaxed, or skipped.

## Architecture certification

```text
backend architecture tests: 124 passed
frontend architecture guards: 17 passed
```

(2 from `step411.architecture.test.ts`, 15 from
`settings.architecture.test.ts`.) Both layers are also exercised implicitly
inside the canonical harness.

Final Phase 5 boundaries confirmed clean:

* `RunService` → `AgentPort` (and the shared `ExecutionConfigurationError`
  contract) via `ava.agents.contracts`.
* Services do **not** import `ava.execution` implementation.
* `SettingsSectionId` is owned by `@ava/ui-core`; `@ava/settings-core`
  re-exports it.
* `@ava/agent-ui` does not depend on `@ava/settings-core` implementation.
* `@ava/workspace` owns Settings navigation.
* Web and Desktop remain thin shells over the shared workspace composition.
* The frontend workspace dependency graph is a DAG with no cycles.

## Static and type baseline

| Check | Result |
| --- | --- |
| Backend Ruff | PASS |
| Backend mypy | PASS — 181 source files |
| Frontend lint/typecheck | PASS — 10/10 packages (`tsc --noEmit`) |
| Python client pytest | 10 passed |
| Python client Ruff | PASS |
| Python client mypy | PASS — 3 source files |

## Build baseline

| Build | Result |
| --- | --- |
| Web (`@ava/web`) | PASS — 199 modules |
| Desktop (`@ava/desktop`) | PASS — 199 modules |

Both produced the same shared output bundle: JS ~664.99 kB (gzip ~205.06 kB),
CSS ~3.63 kB. Exact build timings are not part of the contract.

### Build warning

One warning, on both builds: the **Vite chunk-size advisory** (a chunk exceeds
500 kB after minification, because no `manualChunks` is configured). It is
**pre-existing, unchanged** (identical hashes and sizes to the Phase 5.37
record), **not suppressed**, and **not a Phase 5 regression**.

## Repository integrity

```text
git diff --check                              PASS
working tree unchanged by validation           yes
backend/ava.sqlite3 unchanged (sha256/mtime/size verified)   yes
backend/.ava/ unchanged (220 files)            yes
new runtime artifacts                          none
tracked build output                           none
lockfile rewritten                             no
```

### Known repository-hygiene observation (not a validation blocker)

`backend/ava.sqlite3` is **tracked** in the repository. It is currently
unmodified and was not changed by Phase 5 validation (the backend test suite
redirects it away via `conftest.py`). Tracking a local database is a
pre-existing hygiene concern, but it is **out of scope for Phase 5.40** and is
recorded here for future repository-hygiene work, not as a validation failure.

## Canonical harness

```text
./scripts/test_all.sh  →  exit 0 in 95.3s
```

It reproduced the 5.40A backend counts, the 5.40B frontend counts, and the
5.40C static results, and additionally certified the Python client (10 tests,
Ruff, mypy). It did **not** touch the tracked developer DB.

### Harness scope decision

`test_all.sh` remains unchanged. For Phase 5:

```text
test_all.sh  = canonical aggregate test + static harness
5.40C        = supplemental build + repository-integrity certification
```

This is deliberate and should be recorded as the standing decision:

* the harness is long-standing and internally coherent, and it completed cleanly;
* 5.40C explicitly covers the omitted layers (Web build, Desktop build,
  `git diff --check`);
* widening the harness now would introduce new validation-script code and
  require yet another full certification cycle, for no correctness gain.

### Harness completeness matrix

| Validation area | Canonical harness | Supplemental evidence |
| --- | --- | --- |
| Backend full tests | Included | 5.40A |
| Backend Ruff | Included | 5.40C broader scope (`ruff check .`) |
| Backend mypy | Included | 5.40C |
| Backend architecture | Included via pytest | 5.40C explicit (124 passed) |
| Frontend full tests | Included | 5.40B |
| Frontend lint/typecheck | Included | 5.40C |
| Frontend architecture | Included via `pnpm test` | 5.40C explicit (17 passed) |
| Python client | Included | — |
| Web build | Not included | 5.40C |
| Desktop build | Not included | 5.40C |
| `git diff --check` | Not included | 5.40C |

The combined 5.40 evidence is **canonical-complete** even though `test_all.sh`
alone is not build-complete.

## Reconciliation of warning categories

Accepted warnings across all of Phase 5.40, and no others:

| Layer | Warning | Category |
| --- | --- | --- |
| Backend tests | 4× OpenHands/LiteLLM `DeprecationWarning` | third-party, pre-existing, unsuppressed |
| Frontend builds | Vite chunk-size advisory | pre-existing, unchanged, unsuppressed |

No other warning category appeared in any layer. Nothing was suppressed for
aesthetics.

## Reconciliation of skips

Accepted skips across all of Phase 5.40, and no others:

| Layer | Count | Gate | Category |
| --- | --- | --- | --- |
| Backend | 2 | `AVA_RUN_LOCAL_MODEL_QUALIFICATION=1` | intentional opt-in live/local-model qualification |
| Frontend | 4 | `AVA_LIVE_BACKEND_URL` | intentional opt-in live-backend integration |

No other skip appeared in any layer.

## Reconciliation of changes introduced by 5.40

| Kind | Change |
| --- | --- |
| Production code | One: the `ExecutionConfigurationError` ownership/import-boundary fix (5.40A). |
| Tests | None changed for that fix. |
| Harness (`test_all.sh`) | None changed. |
| 5.40E | Documentation only (this record). |

Defects found and closed in earlier Phase 5 steps (5.30–5.39) are not
re-listed here; they belong to their own phase records.

## Count-drift reconciliation

| Layer | Result |
| --- | --- |
| 5.40D backend counts vs 5.40A | identical (2153/2151/0/2/4) |
| 5.40D frontend counts vs 5.40B | identical (69 files, 685/0/4) |
| 5.40D static checks vs 5.40C | agree (Ruff, mypy 181, frontend lint 10/10) |

No count drift. The aggregate harness run introduced no order or environment
interaction that changed any result.

## Final closure statement

Unresolved failures, by category:

```text
Backend failures          0
Frontend failures         0
Static/type failures      0
Architecture failures     0
Build failures            0
Harness failures          0
```

Known flaky tests: **none**, on the repeated race-validation evidence.

Unexplained warning categories, unexplained skips, and unexplained count drift:
**none.**

**Phase 5.40 is fully closed.**

## Post-Re-Certification Native Streaming Remediation

Phase 5 reopened when Charter B exposed the inherited native streaming fallback:
it discarded callback updates and delegated to final-only generation. The
provider contract now supports streaming, the OpenAI-compatible adapter parses
SSE deltas, and NativeRuntime publishes accumulated snapshots through the
existing durable message/event model. Focused provider, runtime, agent, run
streaming, recovery, and frontend suites pass; canonical validation is recorded
with this remediation before final re-certification.

Compatibility follow-up: six legacy/bootstrap fixtures declared
`streaming=false` but were initially routed to SSE because a callback existed.
NativeAgent now dispatches from the selected model profile capability, restoring
final-only generation while preserving real SSE for declared streaming models.

## Post-5.40 re-certification: non-latest regenerate visibility

Phase 5 was reopened after live testing exposed a non-latest regenerate bug.
For durable history `U1/A1/U2/B1/A2`, the frontend previously collapsed A2 into
the latest assistant slot because it used adjacency. The backend had already
created A2 from Run A and User A correctly; the defect was projection and
hydration identity loss, not run lineage.

The repaired message read contract exposes each run-created assistant's durable
`source_user_message_id`, and the transcript projection replaces only the
assistant response for that source identity. The public workspace regression
covers the live action and a full rehydration. Its deliberate positional
replacement mutation fails, and the restored implementation passes.

Validation for this re-certification is recorded with the remediation: focused
backend, Agent UI, workspace, repository lint, diff check, and the canonical
test harness all pass. Phase 5 is re-certified; Phase 6 has not started.

## Native Streaming Final Re-Certification Attempt (2026-09-30)

The native-streaming remediation added real OpenAI-compatible SSE consumption,
accumulated Native Runtime snapshots, and capability-aware dispatch so
final-only profiles retain one-shot generation. A fresh canonical run passed:
2,154 backend tests passed, 2 opt-in OpenHands tests skipped, and 4 pre-existing
OpenHands SDK deprecation warnings were reported. Backend Ruff/mypy, all
frontend tests and type checks, and the Python client (10 tests, Ruff, mypy)
passed. The Web and Desktop builds passed with the unchanged Vite chunk-size
advisory; `git diff --check` passed.

Manual Charter B did not pass. Settings confirmed Ollama Local
(`http://localhost:11434/v1`), `qwen25-coder-7b` / `qwen2.5-coder:7b`, Native
Runtime, and streaming capability. A new long request showed the active
response state but failed before its first partial was rendered. Therefore a
refresh during a live partial response was not performed and no same-run,
same-message, de-duplication, final durable-content, or completed-refresh
claim is made.

**Charter B end-to-end: FAIL. Phase 5 remains reopened. Phase 6 has not
started.**

## Charter B Final Re-Certification (2026-10-01)

### Canonical validation

`./scripts/test_all.sh` exited 0.

- Backend: **2,252 passed, 2 skipped**, plus the 4 pre-existing OpenHands SDK
  deprecation warnings. Ruff and mypy clean across 182 source files.
- Frontend: **781 passed, 4 skipped** (the intentional live-backend skips):
  contracts 23, ui-core 51, api-client 81, agent-ui 286, settings-core 191,
  document-core 69, workspace 69, desktop 11. Lint/tsc clean in all 10 packages.
- Python client: 10 passed; Ruff and mypy clean.
- Web and Desktop builds passed with the unchanged Vite chunk-size advisory.
- `git diff --check` passed.

### Live Charter B evidence

Recorded against the running backend, the real `@ava/api-client` SSE parser and
the real local Ollama model, on a 30-line prompt:

| Signal | Result |
| --- | --- |
| `message_content` events | 620 |
| Delivered **before** `run_completed` | **619** |
| First / last partial | +0.10s / +12.68s |
| Durable message growth while running | 49 samples, 30 → 2,365 chars |
| Replay from cursor 0 | 620 snapshots, identical order |
| Prefixes strictly growing | yes |

### Signal-boundary conclusion

The first non-incremental boundary was the capability handoff at
`ConfiguredModelProviderFactory`: the operator's declared `streaming: true` never
reached the adapter, so `NativeRuntime.execute_streaming` deliberately degraded
to the buffered path. The provider, the SSE route, the browser parser and the
snapshot projection were each confirmed correct by direct observation, not
inference.

A second defect was masked behind the first: enabling real provider streaming
exposed `_classify_status_failure` reading an unread streamed response body,
which raised `httpx.ResponseNotRead` instead of an AVA-owned failure code.

### Mutation proof

| Mutation | Caught by |
| --- | --- |
| Drop `capabilities=model.capabilities` in the resolver | resolver test, both backends |
| Force `capabilities=None` in the factory | factory test + resolver test |
| Remove `await response.aread()` | streamed-error test (`ResponseNotRead`) |
| Emit accumulated content instead of the snapshot | frontend snapshot test |

### Repair note

`git checkout` on `frontend/packages/workspace/src/conversation-selection.test.tsx`
while removing a scratch test also reverted that file's earlier
failure-presentation expectations, which asserted raw transport text such as
`"backend down"` in the UI. Those assertions contradict the Defect G sanitization
work. The two affected tests were rewritten to assert the intended behavior: the
conversation error uses AVA-owned wording (`Unable to rename conversation.`), raw
transport text never reaches the DOM, and a rejected run creation leaves the
prior transcript intact rather than fabricating a failed assistant message. This
is a reconstruction of intent, not a recovered original.

### Not claimed

The Charter B browser pass was executed as real UI + real client + real model in
jsdom against the live backend, and as live HTTP evidence. It was **not**
performed as a manual pixel inspection in an interactive browser session, and the
earlier Settings browser pass remains unperformed. **Phase 5 therefore remains
reopened. Phase 6 has not started.**

## Background Conversation Reconciliation After Navigation (2026-10-01)

### Canonical validation

`./scripts/test_all.sh` exited 0 with the navigation fix applied.

- Backend: **2,252 passed, 2 skipped** (plus the 4 pre-existing OpenHands SDK
  deprecation warnings); Ruff and mypy clean.
- Frontend: **783 passed, 4 skipped** — api-client 81, agent-ui 286,
  settings-core 191, document-core 69, contracts 23, ui-core 51, workspace 77
  (was 69: +8 navigation regressions), desktop 11. Lint/tsc clean.
- Python client: 10 passed; Ruff and mypy clean.
- Web and Desktop builds passed. `git diff --check` passed.

### Live scenario (real backend, real local Ollama, real client)

| Step | Result |
| --- | --- |
| Start long run in A, wait for real partial | partial rendered |
| Navigate to B mid-stream | A keeps observing; no cancel issued |
| A completes while hidden | A's cached projection reaches `completed`, content grows as a strict prefix extension |
| Return to A | `probeContent()` already final **before** any wait — no refetch, no refresh |
| Bubble identity | exactly one assistant bubble, `data-message-state="complete"` |
| Return while still streaming | latest partial visible immediately |

### Mutation proof (live)

Reintroducing selection-scoped observer ownership fails both live scenarios; the
hidden conversation stays `running` and never reaches its final content.

### Known environmental gap (pre-existing, not caused by this work)

`live-workspace-run.integration.test.tsx` fails 4/4 because the backend database
has no seeded workspace named `Validation Ephemeral (live)`. This predates the
navigation fix and is unrelated to it.

**Phase 5 remains reopened. Phase 6 has not started.**
