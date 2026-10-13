# 43 — Desktop Acceptance

Date: 2026-10-12
Environment: Local AVA workspace; GitHub Actions execution unavailable.

## Result

**#43 Desktop Acceptance — PARTIAL (CI not run).** The Tauri/WebdriverIO harness and Linux/Xvfb workflow are present in the local working tree, and the E2E-specific native build succeeded in prior local validation. The GUI suite has not executed under a display, so this is not Desktop acceptance evidence.

## CI trigger status

Workflow: `.github/workflows/desktop-e2e.yml` (`Desktop E2E`). It defines `pull_request`, `push`, and `workflow_dispatch` triggers. The workflow runs on Ubuntu, installs Node/pnpm, Rust, Python, backend dependencies, Tauri/WebKit libraries and Xvfb, then invokes `xvfb-run --auto-servernum pnpm test:e2e:desktop`.

No GitHub Actions run could be triggered from this checkout:

- The workflow file is untracked and exists only in the local workspace. The connected GitHub repository `cliski1978-hub/AVA` returned 404 for `.github/workflows/desktop-e2e.yml` on its remote default branch.
- This checkout has no Git remote configured, and its working tree contains unrelated uncommitted changes. Publishing the worktree to create a push/PR run would expose and include changes beyond this E2E request, so it was not done.
- `gh` is unavailable. The connected GitHub tool supports repository reads and other actions, but does not expose workflow dispatch.

There is no workflow run URL, job result, Xvfb result, backend fixture result, native startup result from CI, or CI test count to report.

## Local evidence

Previously verified locally:

- Frozen dependency install: **PASS**.
- JavaScript syntax checks and WDIO configuration load: **PASS**.
- E2E-specific Tauri binary build: **PASS**.
- Native startup reached WebDriver initialization, but GTK could not initialize because no usable X display was available. `xvfb-run` is not installed in this environment.
- The backend fixture and actual GUI tests were not executed in CI; the runner is configured to create a temporary SQLite database and delete it after the run.

The ordinary Desktop typecheck still has existing `context_window_tokens` contract errors in `frontend/packages/settings-core/src/models/ModelConfigurationEditor.tsx`. The E2E Tauri config builds the frontend through Vite without removing or masking those source errors.

## Suite coverage review

The expanded suite now defines ten native UI scenarios covering Conversation A → B → A (including draft and attachment isolation and rapid switching), Folder A/B navigation, Project A → B → A (conversations, files, and instructions), Settings section switching, Run Inspector Run A → B → A (prompts, request, response, metadata, events, and attachments), Light/Dark/System surfaces, narrow/default/wide native window sizes, archive/restore, permanent deletion of the exact disposable title `R43 Desktop Delete Test`, and Folder → Project → Folder → Ungrouped relocation. These are test definitions only: the native GUI suite did not run, so pass/fail/skip counts are unavailable.

The runner starts an isolated relational SQLite backend with temporary attachment and Project-file roots and seeds uniquely named E2E data. A test-only mock adapter captures the run context needed by Inspector assertions; production backend behavior is unchanged. The native E2E execution remains unverified because neither a usable display nor `xvfb-run` is available in this environment.

## Security and data isolation

Normal Tauri configuration selects only the `default` capability. The embedded WebDriver plugin is optional behind Cargo feature `wdio`, and only the dedicated E2E config adds the `e2e` capability. The E2E runner allocates a temporary backend port, SQLite database, attachment root, and Project-file root under a temporary directory and removes that directory on exit. The workflow does not point at the normal AVA SQLite database.

## Related acceptance status

- **#43 Desktop Acceptance — PARTIAL.** Required navigation/resize scenarios are now defined, but no GUI or CI result exists.
- **#44 Navigation Acceptance — PARTIAL.** See [44-navigation-acceptance.md](44-navigation-acceptance.md); Tauri navigation remains unverified.
- **#45 Theme Acceptance — PASS (Web), Desktop unverified.** See [45-theme-acceptance.md](45-theme-acceptance.md).

To run the requested CI gate, the E2E changes must be published to the connected repository without including unrelated working-tree changes, or run from a repository checkout that already contains the workflow and harness. After that, trigger `Desktop E2E` via `workflow_dispatch` and record the actual job and test results here.
