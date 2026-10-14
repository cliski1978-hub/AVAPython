# AVA Phase 6.12A — Power User Execution Mode Selector

**Status:** Complete for the scoped shared-composer and Run-request integration.
**Implementation workspace:** `phase-6-12-agent-runtime` managed worktree.

## Objective and scope

Phase 6.12A adds a Power User choice among Chat, Plan, and Agent to the existing shared conversation composer. It sends the selected value through the established Run creation request and displays the mode persisted on a Run in the existing Run Inspector. It does not add an execution endpoint or make normalized tool dispatch operational.

## Selector and state ownership

The `@ava/agent-ui` `PromptComposer` now presents a compact, keyboard-operable execution-mode select in its lower action row. Chat is the default; the current selection remains visible, and focus styling and colors use the shared theme tokens. A short accessible description explains the selected mode. The control stays available while a Run is active so the user can choose a mode for a future Run.

`AppWorkspace` owns this as transient composer state. It starts in Chat, returns to Chat when the user changes conversations, and does not persist a preference in browser storage or backend settings. When the first prompt creates a conversation, the selected mode is retained for that Run and the new conversation. The authoritative mode for an existing Run remains the backend-persisted Run value.

## Run creation, retry, and immutable history

The existing `submitPrompt` / `startRunForPrompt` path now carries `execution_mode` to the existing `startRun` API call. The composer supplies an explicit value, including Chat. Programmatic callers that omit the optional mode retain the backend's Chat default. Retry and regenerate create a new Run using the current explicit selection; they do not mutate or escalate the prior Run. Model/runtime execution overrides remain independent of execution mode. A synchronous submission guard blocks rapid duplicate sends and releases when the provider reports that a Run has started, allowing another conversation to submit while the original streams in the background.

The Run Inspector displays `execution_mode` from its existing inspection response when present. Changing the composer selection only affects future Run requests; it does not rewrite active or historical Run records.

## Availability feedback and security boundaries

For Plan and Agent, the composer reports model tool-calling capability only when the selected configured model has that catalog field. It separately states that normalized tool execution is unavailable in this deployment and that the backend does not report end-to-end readiness. It does not imply that selecting a mode authorizes execution or that a model capability alone makes a tool operational.

When OpenHands is selected, the UI notes that legacy Workspace tools may remain available under their separate security controls and are outside normalized approval-managed dispatch. It does not block or relabel that established legacy path.

The control appears in the full shared Power User conversation interface used by Web and Desktop. No frontend role flag or security authority was introduced. Trusted Power User/standard-user role visibility remains dependent on future trusted identity integration. Execution mode remains a policy ceiling, not an authority grant.

## Tests and validation

Frontend dependencies were installed with the existing frozen lockfile. No lockfile change was needed. Validation completed:

- Full `@ava/agent-ui` suite: 21 files, 320 tests passed.
- Full `@ava/workspace` suite: 20 files passed; 274 tests passed and 6 integration tests skipped by their existing test setup.
- Full `@ava/api-client` suite: 15 files, 119 tests passed.
- Full `@ava/contracts` suite: 13 files, 45 tests passed.
- TypeScript checks passed for agent-ui, workspace, api-client, and contracts.
- Web and Desktop production frontend builds passed. Vite emitted its existing large-chunk advisory for the roughly 1.09 MB application bundle.
- Backend execution-mode, native tool loop, runtime bridge, OpenHands mode, tool-execution, and approval regression suites: 43 tests passed with the locked OpenHands optional dependency installed.
- Ruff passed on the changed backend files; strict mypy passed for all 287 backend source files.
- `git diff --check` passed.

No browser or native Desktop visual review was performed, and no screenshot is claimed. The full Workspace suite reports six existing skipped integration tests; these were not counted as passing.

## Known limitations and production status

The UI conveys mode selection and the data AVA currently knows about model tool calling; it cannot show whether runtime support, tool registration, feature enablement, trusted authority, durable reservation, or approval continuation are all operational. Production normalized tool dispatch remains unavailable as documented in Phase 6.12. The selector does not add an authority resolver, reservation storage, approval API, identity integration, handlers, or OpenHands migration. No standard-user use-case application behavior was added.

## Phase 6.13 readiness

The Power User mode-selection experience is integrated and validated through the existing Run contracts. Phase 6.12A is accepted within its frontend scope. Production agentic execution is still disabled; any later phase that exposes or enables it must independently establish the trusted authority and durable execution/approval infrastructure identified by the Phase 6.12 handoff. This document does not authorize or start Phase 6.13.
