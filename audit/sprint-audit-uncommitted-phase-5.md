# Sprint audit: uncommitted Phase 5.31–5.40 work

## 1. Verdict: FAIL

The declared frontend lint, build, and test commands pass from the current
working tree; the test command reports 685 passed and 4 skipped tests.
However, the required clean-state checkout could not be created because Git's
worktree metadata is read-only, and the backend full test suite could not run
because the available Python environment has no pytest and uv's cache is
read-only. The audit rules therefore prohibit a passing verdict.

Two high-severity stale-ownership defects were found by source review. Both
can apply a prior run's asynchronous result to a newer run.

## 2. Verification results table

| Step | Command | Exit code | Result | Evidence log path |
| --- | --- | ---: | --- | --- |
| Clean checkout | `git worktree add --detach /tmp/ava-audit-base-acc98f7 acc98f7` | 128 | Could not run: `.git/worktrees` is read-only | `audit/evidence/phase1-clean-worktree.log` |
| Frontend test suite | `pnpm test` | 0 | Pass: 685 passed, 4 skipped | `audit/evidence/phase1-full-test.log` |
| Lint/type check | `pnpm lint` | 0 | Pass | `audit/evidence/phase1-lint.log` |
| Frontend build | `pnpm build` | 0 | Pass; Vite reports existing 500 kB chunk warning | `audit/evidence/phase1-build.log` |
| Backend tests | `uv run --no-sync --directory backend pytest -q` | 2 | Could not run: uv cache path is read-only; `python3 -m pytest` also reports pytest absent | `audit/evidence/phase1-backend-test.log`, `audit/evidence/phase1-python-tooling.log` |
| Test-integrity diff | `git diff HEAD -- *test*` | 0 | Reviewed; no new skip/xfail marker found | `audit/evidence/phase2-test-diff.log`, `audit/evidence/phase2-integrity-markers.log` |
| Full source/config diff | `git diff HEAD` plus untracked non-artifact files | 0 | Reviewed | `audit/evidence/phase3-full-diff.log` |
| Dependency audit | `pnpm audit --prod` | 1 | Could not run: npm registry DNS lookup failed | `audit/evidence/phase4-pnpm-audit.log` |
| Registry/dependency metadata | `pnpm view …` | 1 | Unverified: npm registry metadata request failed | `audit/evidence/phase4-dependency-registry.log` |
| Secret scan | `rg` patterns for common private-key/API-token forms | 1 | No matches | `audit/evidence/phase4-secret-scan.log` |

## 3. Findings

| ID | Severity | Phase | Location | Description | Evidence reference | Recommended action |
| --- | --- | --- | --- | --- | --- | --- |
| AUD-001 | High | 3, 6 | `frontend/packages/agent-ui/src/run/conversationRun.ts:668` | `cancelActiveRun` does not capture the current run epoch or check ownership after either awaited request. A delayed cancellation result or event fetch for R1 can set state or paint messages for a newer R2. | `audit/evidence/phase3-full-diff.log`; Phase 5.32 lines 21–32 require epoch checks for cancellation and prohibit late cancellation results from painting a newer run. | Capture `runEpoch` at cancellation start, check it after both awaits and in both error branches, and pass it to `applyRunEvents`. Add a delayed-R1-cancel/started-R2 regression test. |
| AUD-002 | High | 3, 6 | `frontend/packages/agent-ui/src/run/ConversationRunProvider.tsx:136` | The render path copies every existing `activeEpoch` into `sessionEpoch`; the recovery effect then immediately returns because the values match. A newly mounted provider therefore never calls `recoverRunForConversation` for an active persisted run. | `audit/evidence/phase3-full-diff.log`; Phase 5.36 requires refresh recovery for active runs. | Track ownership established by this provider session only. Add a provider-remount test that proves an active durable run is observed. |
| AUD-003 | Medium | 3, 6 | `backend/.ava/` | 220 untracked attachment artifacts (2.8 MB) are present in the proposed working-tree commit. The validation document claims `backend/.ava/ unchanged` and `new runtime artifacts none`. | `audit/evidence/phase3-full-diff.log`; `docs/AVA_Phase_5_40_Full_Validation.md:246-255`. | Exclude the local state from the commit or explicitly update the validation claim and ownership policy. |
| AUD-004 | Low | 5 | `README.md:53-55` | The README tree names three added Phase 5 documents with spaces, but the added files use underscore names (for example, `AVA_Phase_5_Complete_Documentation.md`). The directory listing is inaccurate. | `audit/evidence/phase3-full-diff.log`. | Match the actual filenames, preferably using links. |

## 4. Task completion map

| Sprint task | Status | Evidence |
| --- | --- | --- |
| Retry/regenerate across persisted runs (Phase 5.31) | Implemented, with unverified backend execution | New request contract, attempt eligibility, UI actions, and focused tests are in the full diff log. |
| Stale-event protection (Phase 5.32) | Partial | Epoch guards were added to start/retry paths, but AUD-001 leaves cancellation unguarded. |
| Conversation-level concurrency (Phase 5.33) | Implemented, unverified backend execution | Repository/service changes and race tests are present; pytest could not run. |
| Failure and error UX (Phase 5.34) | Implemented | Failure-code projection and settings navigation are present; frontend suite passes. |
| Configuration-failure integration (Phase 5.35) | Implemented, unverified backend execution | Typed configuration failure mapping is present; pytest could not run. |
| Web/desktop acceptance (Phases 5.36–5.37) | Partial | Frontend build/tests pass, but AUD-002 breaks active-run refresh recovery. |
| Restart durability and concurrency hardening (Phases 5.38–5.40) | Unverifiable | New backend integration/race tests are present but could not run. |

## 5. Unverified items

- A clean checkout of the sprint head was not possible: Git cannot create
  `.git/worktrees/...` in this environment.
- The full backend suite, backend lint, and backend type check did not run:
  pytest is absent and uv cannot create its cache temporary files.
- Base-versus-sprint test-count comparison is unverified because the clean
  baseline checkout could not be created.
- Registry existence, maintenance, typosquat review, and license data for
  `@testing-library/dom`, `@testing-library/react`, `@types/node`, `jsdom`,
  and `vitest` are unverified because the npm metadata request failed.
- `pnpm audit` is unverified because the npm audit endpoint failed DNS lookup.

## 6. Context-file and documentation updates proposed

- Correct the three Phase 5 filenames in `README.md`.
- Add a repository rule: "Do not stage `backend/.ava/` local attachment state;
  it is runtime data, not source." This is a suggestion until its intended
  ownership is confirmed.
- Record the deliberate distinction between provider-session observer ownership
  and a persisted run epoch before changing the recovery implementation.

## 7. Missing regression tests

- Start cancellation for R1, start R2 before R1's cancellation response and
  event fetch resolve, then prove R1 cannot change R2's state or message.
- Mount the provider with an active persisted run and no provider-owned
  observer, then prove `recoverRunForConversation` starts exactly once.
- Run the new backend race, restart-durability, attempt, and configuration
  failure tests in a provisioned Python environment.

## 8. Retro metrics and observations

- Commits in the selected range: 0. This audit covers uncommitted work against
  `acc98f7`, so commit-level task mapping, reverts, and rework rate are
  unavailable.
- Tracked changed files: 44 (2,285 additions; 320 deletions). Additional
  untracked source, tests, docs, and local artifacts are included in the full
  diff evidence.
- Frontend test result: 685 passed, 4 skipped. Baseline count unavailable.
- Audit defects: 0 Critical, 2 High, 1 Medium, 1 Low.
- The two High findings were caught by source review, not by the passing
  frontend tests, indicating ownership-race test gaps.

## 9. Next-sprint spec stubs

### Cancellation ownership guard

Goal: make cancellation results safe after retry/regenerate supersession.

Acceptance criteria: cancellation captures the initiating epoch; every result,
fallback, event application, and message mutation checks that epoch; a delayed
R1 cancellation cannot alter R2.

Verification: add the delayed-cancellation regression test and run the full
agent-ui suite.

Dependencies: none. Can run in parallel with refresh recovery.

### Refresh recovery ownership

Goal: restore observation of an active persisted run after provider remount.

Acceptance criteria: only an observer started by the current provider session
suppresses recovery; a remount starts one recovery observer; duplicate effects
do not start two observers.

Verification: provider-remount test plus full agent-ui suite.

Dependencies: none. Can run in parallel with cancellation ownership.

### Reproducible backend validation

Goal: provide a writable, pinned Python test environment for the backend
suite.

Acceptance criteria: documented setup runs pytest, Ruff, and mypy without
writing runtime artifacts into the source tree; baseline and sprint counts are
recorded.

Verification: clean-checkout install and full backend validation logs.

Dependencies: environment/write access. Blocked by the current filesystem
restrictions.
