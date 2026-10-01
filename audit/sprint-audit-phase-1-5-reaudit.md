# Sprint audit: Phase 1–5 post-remediation

## 1. Verdict: PASS WITH CONDITIONS

The current Phase 1–5 source snapshot passed the full deterministic validation harness: 2,151 backend tests passed (2 intentional opt-in skips), 694 frontend tests passed (4 intentional live-backend skips), and 10 Python-client tests passed. Backend/frontend static checks, web/desktop asset builds, Python package builds, and the native desktop `cargo check` also passed.

The two defects from the first audit are remediated with focused regression tests: stale cancellation now checks the initiating epoch after every awaited boundary, and a freshly mounted provider restores observation of a durable active run.

This is not an unconditional production-security sign-off. The desktop application still explicitly disables CSP, and two Phase 5 documentation entry points contradict the closure record. Those conditions should be resolved before treating the audit as a release-security approval.

## 2. Verification results table

| Step | Command | Exit code | Result | Evidence log path |
| --- | --- | ---: | --- | --- |
| Isolated source snapshot | `git ls-files -c -o --exclude-standard -z` then copy source files | 0 | 821 files copied; ignored caches/build output and untracked local attachment state excluded | `audit/phase1-5-reaudit/evidence/phase1-01-snapshot.log` |
| Dependency install | isolated `uv pip install` and `pnpm install --frozen-lockfile` | 0 | Passed after registry-enabled retry | `audit/phase1-5-reaudit/evidence/phase1-05-python-install-retry.log`, `phase1-06-node-install-retry.log` |
| Full backend suite | `./scripts/test_all.sh` | 0 | 2,151 passed, 2 skipped, 4 warnings | `audit/phase1-5-reaudit/evidence/phase1-23-canonical-harness-retry.log` |
| Full frontend suite | `pnpm test` | 0 | 694 passed, 4 skipped | `audit/phase1-5-reaudit/evidence/phase1-15-frontend-tests.log` |
| Backend/frontend lint and type checks | `pnpm lint; ruff check src tests; mypy src` | 0 | Passed; mypy checked 181 source files | `audit/phase1-5-reaudit/evidence/phase1-16-static.log` |
| Python client checks | `pytest; ruff check src tests; mypy src` | 0 | 10 passed; static checks passed | `audit/phase1-5-reaudit/evidence/phase1-22-client-validation.log` |
| Builds | `pnpm build`; Python `build --no-isolation` | 0 | Web/desktop assets and both Python distributions built | `audit/phase1-5-reaudit/evidence/phase1-08-frontend-build.log`, `phase1-11-python-build-retry.log` |
| Native desktop compile | `cargo check --locked --offline` | 0 | Passed | `audit/phase1-5-reaudit/evidence/phase1-26-native-desktop-check.log` |
| Baseline test counts | Phase-1 archive backend/frontend suites | 0 | Backend: 40 passed. Frontend: 16 passed. No decrease in current test totals. | `audit/phase1-5-reaudit/evidence/phase1-24-baseline-backend-retry.log`, `phase1-21-baseline-frontend.log` |
| Test-integrity review | diff history plus skip/xfail/coverage-marker scan | 0 | No new unexplained skip, xfail, weakened assertion, or coverage-threshold change found | `audit/phase1-5-reaudit/evidence/phase2-01-test-history-diff.log`, `phase2-02-integrity-markers.log` |
| Dependency audit | `pnpm audit --prod; pip_audit` | 0 | No known vulnerabilities. Local `ava-backend` package is not on PyPI and was not audited. | `audit/phase1-5-reaudit/evidence/phase4-03-dependency-audit.log` |
| Secret-pattern scan | `rg` private-key/token patterns | 1 | Matches are explicit test fixtures only; no production credential found | `audit/phase1-5-reaudit/evidence/phase4-02-secret-scan.log` |

The first sandboxed backend run stalled while entering Starlette `TestClient`; the bounded reproduction records its thread dump. The same three tests and the complete harness passed outside that sandbox, so the audit treats this as an environment restriction, not an application failure. See `phase1-17-hang-diagnostic.log`, `phase1-19-hang-diagnostic-unrestricted.log`, and `phase1-23-canonical-harness-retry.log`.

## 3. Findings

| ID | Severity | Phase | Location | Description | Evidence reference | Recommended action |
| --- | --- | --- | --- | --- | --- | --- |
| AUD-001 | Medium | 1–5 / security | `frontend/apps/desktop/src-tauri/tauri.conf.json:21` | Desktop sets `"csp": null`, disabling the WebView content-security policy. This is present since the Phase 1 baseline, so it is not a remediation regression, but it remains an avoidable desktop XSS-defense gap. | `audit/phase1-5-reaudit/evidence/phase5-03-csp-baseline.log` | Define and test a restrictive CSP appropriate to the app's API and asset origins before a production desktop release. |
| AUD-002 | Medium | 5 / documentation | `docs/AVA_Phase_5_Implementation_Plan.md:5` | The plan still says “Planning Complete — Implementation Not Started,” while the canonical plan and closure record say Phase 5 is complete. This can send future work back through already-completed steps. | `phase5-04-requirement-evidence.log`; `docs/AVA_CANONICAL_DEVELOPMENT_PLAN_CURRENT_TO_COMPLETION.md:197`; `docs/AVA_Phase_5_Complete_Documentation.md:3` | Mark the implementation plan superseded/completed and link to the canonical closure record. |
| AUD-003 | Low | 5 / documentation | `README.md:53` | README lists names containing spaces, but the real closure files use underscores, for example `AVA_Phase_5_Complete_Documentation.md`. | `audit/phase1-5-reaudit/evidence/phase5-03-csp-baseline.log` | Replace the prose tree entries with correct Markdown links. |
| AUD-004 | Low | 4–5 / hygiene | `backend/ava.sqlite3` | A 776 KB local SQLite database is tracked. It is present in Phase 5 commits and is developer/runtime state rather than source. Untracked local attachment state also occupies 2.8 MB, although it is ignored. | `audit/phase1-5-reaudit/evidence/phase5-03-csp-baseline.log` | Decide whether a sanitized fixture is required; otherwise remove the database from version control in a dedicated, reviewed hygiene change and document runtime-state ownership. |

Remediation verification: `cancelActiveRun` now checks epoch ownership after cancellation and event awaits, including both error paths (`conversationRun.ts:668-720`), with late-success and late-error tests. A new provider session now uses controller ownership rather than a persisted epoch to decide whether it must recover (`ConversationRunProvider.tsx:130-150`), with public fresh-mount coverage. Evidence: `audit/phase1-5-reaudit/evidence/phase2-01-test-history-diff.log` and source excerpts in `phase5-04-requirement-evidence.log`.

## 4. Task completion map

| Sprint task | Status | Evidence |
| --- | --- | --- |
| Phase 1 foundation: monorepo, FastAPI modular monolith, contracts, shells, client, validation | Implemented | Earliest archive has the foundation; current full harness, builds, and native desktop check pass. `phase1-24-baseline-backend-retry.log`, `phase1-21-baseline-frontend.log`, `phase1-23-canonical-harness-retry.log`. |
| Phase 2: conversation UI/state, prompt composer, run lifecycle, cancellation, shared workspace/document foundation | Implemented | Current shared-package tests and type checks pass; source/test history is in `phase2-01-test-history-diff.log`. |
| Phase 3: runtime/provider/model abstraction, workspace and execution boundaries, model selection/resource seams | Implemented, with live-model qualification unverified | Deterministic suite passes. The two local-model qualification tests are intentionally gated and skipped; no credentialed/local-model endpoint was used by this audit. |
| Phase 4 steps 4.2–4.16: repository ports, migrations, durable conversations/messages/runs/events/documents/revisions/attachments, restart integration | Implemented | Relational/restart tests are included in the 2,153 collected backend tests; attachment restart tests independently passed outside the sandbox. `phase1-19-hang-diagnostic-unrestricted.log`, `phase1-23-canonical-harness-retry.log`. |
| Phase 5.1–5.17: persisted execution configuration, settings API/UI, credential references, resolver/bootstrap | Implemented | Settings, resolver, bootstrap, persistence, and integration tests are enumerated in `phase5-04-requirement-evidence.log`; full suite passed. |
| Phase 5.18–5.30: normalized conversation/run/message model, context, lifecycle, durable cancellation, SSE/replay, partial output, refresh/restart recovery | Implemented | Current source and full suite; remediation source/test evidence above. |
| Phase 5.31: persisted retry/regenerate | Implemented | Retry lineage contracts, backend tests, and frontend action coverage are present in `phase5-04-requirement-evidence.log`; full suite passed. |
| Phase 5.32: stale-event protection | Implemented | Epoch guards are now also present in cancellation; late cancellation success/error regressions pass. |
| Phase 5.33: one active run per conversation | Implemented | Repository active-run guard and race tests are present; backend suite passed. |
| Phase 5.34–5.35: normalized failure/configuration-remediation UX | Implemented | Failure presentation, typed configuration errors, settings navigation, and tests are present; full suites passed. |
| Phase 5.36–5.37: Web and Desktop acceptance | Implemented for deterministic acceptance; live model/backend acceptance unverified | Shared UI tests, web/desktop builds, and `cargo check` pass. No live external model or configured backend was available. |
| Phase 5.38–5.40: restart durability, race hardening, full validation | Implemented | Restart/race suites passed within the complete harness; static/build validation also passed. |
| Phase 5.41: closure documentation | Partial | Closure exists, but the implementation plan and README are stale (AUD-002, AUD-003). |

## 5. Unverified items

- A true Git worktree could not be created because Git worktree metadata is read-only in this environment. The audit instead used an isolated 821-file snapshot with a SHA-256 manifest. This preserves the current uncommitted remediation state but is not a committed revision.
- Real local-model and live-backend integration are intentionally gated and were not run: they require a user-controlled endpoint and credentials.
- Dependency registry existence, maintenance status, typosquat analysis, and licenses for every transitive dependency were not independently verified. The lockfile install succeeded and vulnerability audits were clean.
- The audit does not establish a packaged desktop application works on every supported OS; it verified the Rust target compiles on this Linux host.

## 6. Context-file and documentation updates proposed

- Update `docs/AVA_Phase_5_Implementation_Plan.md` status to completed/superseded and link to `AVA_Phase_5_Complete_Documentation.md` and `AVA_Phase_5_40_Full_Validation.md`.
- Replace the three stale Phase 5 names in `README.md` with exact linked filenames.
- Add a short repository rule: “`backend/ava.sqlite3` and `backend/.ava/` are local runtime state; do not commit them unless a reviewed fixture policy explicitly requires it.”
- Record the desktop CSP decision in an ADR or security note: required directives, allowed API origin, and the test that prevents it reverting to `null`.

## 7. Missing regression tests

- A desktop configuration test should fail if `app.security.csp` is `null` or excludes required production API/asset origins.
- A packaged desktop smoke test should start the application and exercise the shared workspace with the production CSP enabled.
- A live-backend acceptance job, gated on a disposable local backend, should run the currently skipped workspace suite in CI or a release environment.

## 8. Retro metrics and observations

- Committed range: 3 commits after the earliest Phase 1 commit; the current remediation is uncommitted. There are no `revert` commits in the visible history.
- Committed Phase 1–5 delta: 716 files, 139,936 insertions, 309 deletions. This includes substantial training/skill artifacts beyond application code; their inclusion makes the phase-level change volume a poor proxy for product work alone.
- Uncommitted remediation delta: 44 tracked files, 2,383 insertions, 323 deletions, plus new tests/docs. The two P1 ownership defects from the first audit are covered by new regression tests and pass in the full suite.
- Test growth: backend 40 → 2,151 passed; frontend 16 → 694 passed; Python client 0 → 10 passed. Current skips are 2 backend opt-in local-model tests and 4 frontend live-backend tests.
- Findings: 0 Critical, 0 High, 2 Medium, 2 Low.

## 9. Next-sprint spec stubs

### Desktop CSP hardening

Goal: ship the desktop shell with an explicit least-privilege CSP.

Acceptance criteria: CSP is non-null; it permits only bundled assets and documented AVA API origins; the workspace loads and API requests succeed; automated configuration test rejects a null CSP.

Verification: desktop asset build, `cargo check`, CSP configuration test, and a packaged-shell smoke test.

Dependencies: frontend/API-origin decision. This can run independently of documentation cleanup.

### Phase 5 documentation reconciliation

Goal: make Phase 5 entry points describe the same completed state.

Acceptance criteria: implementation plan says completed or superseded; README links resolve to real files; closure links remain accurate.

Verification: markdown-link check and review of the canonical plan, implementation plan, README, and closure record.

Dependencies: none. Can run in parallel with CSP hardening.

### Runtime-state ownership policy

Goal: prevent developer databases and attachment content from being committed accidentally.

Acceptance criteria: approved policy documents whether a fixture is needed; runtime paths are ignored or replaced with a sanctioned fixture; tests do not write runtime state into the repository.

Verification: clean checkout, full backend suite, and `git status --ignored` review.

Dependencies: decision on whether `backend/ava.sqlite3` is intentionally a fixture.
