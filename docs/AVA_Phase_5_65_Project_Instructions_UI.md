# Phase 5.65 — Project Instructions UI

**Status: COMPLETE**

## UI and state ownership

The Project workspace's Instructions tab now renders a plain multiline editor
using the shared `Textarea` primitive. The section is the only visible section
panel when selected. Helper text explains that instructions are saved for
future use and do not affect conversations until execution integration is
added.

`ProjectsWorkspace` continues to own the fetched canonical Project detail and
Project list. `ProjectInstructionsEditor` owns only its local draft, the
persisted instructions snapshot used for dirty checking, and save/error state.
The textarea starts with `project.instructions ?? ""`; a separate snapshot
retains whether the server value was `null` or an empty string.

An unchanged null or string is clean and sends no request. Editing a null
value and returning to an empty draft is dirty, so Save sends `""`. Clear is
the explicit action that sends `null`. Saving a string calls the existing
`updateProject` method with the required Project name and only the instruction
field; no dedicated API was added. Success replaces the local persisted
snapshot and draft with the returned canonical Project, clears errors, and
reconciles the detail, workspace list, and AppWorkspace sidebar. A failed save
retains the draft and shows a safe retryable error. Cancel restores the latest
persisted Project instructions without a request.

The editor guards concurrent saves with both pending state and a ref, and
supports Ctrl+Enter / Cmd+Enter to save and Escape to cancel. Archived Projects
remain editable, following the existing behavior that archived Projects can
still be opened. Switching Project ids unmounts the editor and discards its
unsaved draft; the next Project starts from its own persisted instructions.
If a Project instruction value is refreshed while clean, the editor adopts it;
if refreshed while dirty, the draft remains while its persisted snapshot
advances.

## Scope and execution boundary

Only Project metadata changes through the existing Project update API. The
editor does not modify Conversation membership, Folder membership, titles,
messages, or runs. No Project instructions are added to run requests, system
messages, prompts, context construction, or runtime adapters. No backend or
API-client production changes, execution defaults, Project files, or RAG
behavior were added.

## Validation

Project workspace tests cover null and string initialization, multiline and
Unicode display/save, empty-string Save, explicit Clear, no-op Save, Cancel,
safe failure/retry state, duplicate-save protection, Project switching, and
archived Project editing. The empty-string test was mutation-checked by
temporarily converting an empty value to null: exactly one test failed on the
request payload. The correct implementation was restored and the test passed.

The full focused workspace package passed 143 tests with 6 existing
integration tests skipped. The API-client package passed 105 tests. TypeScript
checks passed for workspace, API-client, and contracts packages. Web and
Desktop production builds passed with the existing large-chunk advisory.

Live verification used a disposable SQLite database in `/tmp` and a local
backend. A temporary Project's multiline Unicode instructions were saved,
then remained visible after backend restart and browser reload. Saving an
empty textarea returned `instructions: ""`; Clear returned
`instructions: null`; after reload, the editor was empty and clean. The
temporary data and dev services were removed after verification.
