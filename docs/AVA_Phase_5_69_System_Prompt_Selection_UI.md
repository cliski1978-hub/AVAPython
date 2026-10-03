# Phase 5.69 — System Prompt Selection UI

**Status: COMPLETE. Phase 5.70 was not started.**

Phase 5.69 adds the UI for managing reusable CORE prompt definitions and editing
their stored, explicit assignment state. It uses the existing typed client
methods and does not calculate inheritance, preview resolved prompts, or change
run construction/provider prompt assembly.

## Locations

- **Settings → System Prompts** lists definitions in backend order, shows their
  category, description, and enabled state, and provides name/category/status
  filters. Create and edit use labeled text fields and a plain multiline prompt
  editor; prompt text whitespace is passed through unchanged. Definition
  enable/disable is separate from per-scope DISABLE. Delete requires
  confirmation and explains that the definition and its assignments are
  removed, while Projects, Folders, and Conversations remain.
- **Settings → System Prompts → Assignments** includes Global, Runtime, and
  Capability selectors. Global writes use `scope_type=global` and `scope_id=null`.
  Runtime targets come from the runtime registry; Capability targets use the
  canonical capability keys.
- **Project → Settings** contains the Project selector. Project Instructions
  remain in their existing separate section and editor.
- **Folder actions → System Prompts** and **Conversation actions → System
  Prompts** open a labeled modal for the selected scope. Opening these surfaces
  does not select or move a conversation.

Application and Model Compatibility are omitted because their assignment writes
are unsupported. Folder and Conversation custom instructions were not added.

## Assignment behavior

Each prompt uses one accessible three-state selector:

- **INHERIT** means there is no explicit assignment row at this scope.
- **ENABLE** stores an explicit enable at this scope.
- **DISABLE** stores an explicit disable at this scope.

The selector loads the prompt definitions and assignments for that exact
scope. It does not read another scope to fill in an INHERIT value and does not
show inheritance-source or effective-state labels. One prompt mutation is
pending at a time within a scope selector. State changes after the typed write
succeeds; a failure retains the previous value and displays a retryable safe
error. Definition-disabled status remains separately visible while stored
assignment state is preserved.

## Boundaries

- Project instructions and Project conversation membership are unchanged.
- Folder membership is unchanged by opening or editing prompt assignments.
- Conversation selection, transcript hydration, and active-run observation are
  unchanged by opening or editing prompt assignments.
- No backend production or API-client production changes were needed.
- CORE assignment metadata remains inert for execution. Phase 5.70 resolution
  and later execution integration were not started.

## Verification

- `@ava/settings-core`: 209 tests passed.
- `@ava/workspace`: 150 tests passed; 6 existing integration tests skipped.
- `@ava/agent-ui`: 292 tests passed.
- `@ava/api-client`: 108 tests passed.
- `@ava/contracts`: 36 tests passed.
- TypeScript checks passed for Settings, Workspace, Agent UI, API Client, and
  Contracts.
- Live UI verification created **Software Engineering**, **Architecture
  Guardian**, and **Research Assistant**; stored Global ENABLE, Project
  ENABLE/DISABLE plus Project INHERIT, Folder DISABLE, and Conversation ENABLE.
  All states were visible after a browser reload. A Project remained INHERIT
  while the same prompt was Global ENABLE. A post-assignment run returned the
  ordinary requested response without CORE prompt injection.
- Mutation proof: changing the missing-row fallback from `inherit` to `enable`
  made the targeted Project selector test fail (1 failure, expected `inherit`,
  received `enable`); the correct implementation was restored and the full
  focused suite passed.
