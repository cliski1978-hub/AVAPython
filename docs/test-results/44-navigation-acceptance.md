# 44 — Navigation Acceptance

Date: 2026-10-12  
Environment: AVA Web at `http://127.0.0.1:5173/`, backend Connected. `tauri dev` started Vite on port 5174, compiled, and reached `Running target/debug/ava-desktop`; this session's computer-use inventory exposes no native apps/windows (`apps: []`).

## Result

**PARTIAL.** The three confirmed Web defects are fixed and have focused automated coverage. The permanent-delete fallback check passed in Web, including refresh and search verification. The expanded Tauri E2E suite now defines conversation, Folder, Project, Settings, Inspector, archive/delete, relocation, and native resize navigation scenarios. It has not run under a GUI because this environment has no usable display or `xvfb-run`, so this acceptance remains partial.

## Defect fixes

| Defect | Result | Evidence |
|---|---|---|
| Composer draft leakage | Pass | Drafts are retained per conversation (and separately for a new conversation). Manual Web check: entered a draft in `conv 1`, switched to `Test 2 Conv` and saw an empty composer, returned to `conv 1` and saw its draft restored; cleared the draft without sending. The focused workspace test also switches among conversations and verifies isolation/restoration. |
| Archive selected conversation | Pass (automated) | Archiving from Active leaves the view in Active and selects the next non-archived conversation, then the previous one, or clears selection if none remain. Reducer/provider and sidebar tests cover fallback and empty-state behavior. Live archive interaction was not repeated. |
| Move Folder / Project / Ungrouped | Pass (automated) | A single backend move operation updates both membership fields atomically: moving to Folder clears Project, moving to Project clears Folder, and Ungrouped clears both. Frontend state and Project/Folder listings use the canonical response; selection and transcript remain in place. API coverage exercises Folder → Folder, Folder → Project, Project → Project, Project → Ungrouped, Project → Folder, and Folder → Ungrouped using memory and relational repositories. |

## Retained navigation checks

Previously exercised Web checks remain recorded: refresh selection, Project isolation, Project instructions/execution context, Settings navigation, Inspector run switching, responsive sidebar sizing, Back/Forward, Project deep links, missing-Project error state, representative System-dark theme, and no horizontal overflow or console errors. These broader checks were not rerun for this targeted fix.

| Area | Result | Evidence / limitation |
|---|---|---|
| Conversation switching and refresh | Pass (prior browser check); draft isolation Pass (current) | The selected conversation and its messages/attachments/run list followed selection and survived refresh. The manual draft isolation probe passed as recorded above. |
| Folder / Project navigation | Pass (focused automated); prior manual navigation Pass | Existing browser checks verified folder and Project isolation. This follow-up verifies exclusive destination changes with frontend and backend tests; live browser move was not repeated. |
| Archive fallback | Pass (automated) | Active-view selection fallback is covered by focused tests; live backend/browser action not repeated. |
| Permanent-delete fallback | Pass | Created and selected `R44 Delete Fallback Test` in Active while other active conversations existed. Confirmed the irreversible dialog for that exact title. After deletion, it disappeared from Active and AVA selected `Project A instructions check: reply with the required marker.` Its transcript, blank composer, and matching historical run/Inspector data were visible; the fallback had no attachment context. The app remained at `/`, with no stale route. Search returned “No conversations found for ‘R44 Delete Fallback Test’.” |
| Refresh after deletion | Pass | After refresh/loading settled, the same fallback conversation and its selected historical run were restored. The deleted title remained absent from the sidebar and search. A direct backend-list query was not needed; the UI's search result confirmed absence. |
| Last-active deletion edge case | Not tested | Optional edge case deferred; it would require another permanent deletion. |
| Browser Back/Forward and Project links | Pass (prior browser check) | Browser history returned to the expected Settings, Project, and Chat views; Project deep link survived refresh. |
| Layout / console | Pass (prior browser check) | No horizontal overflow or console-breaking errors were observed in the previous acceptance run. Not rerun for this targeted fix. |
| Tauri Desktop navigation | Not verified (session display/tool limitation) | `pnpm --filter @ava/desktop tauri dev` started the Desktop Vite server, compiled successfully, and logged `Running target/debug/ava-desktop`. Native app discovery returned no apps or windows, and this session has native computer controls disabled, so Conversations/Folders/Projects/Settings/Inspector, resizing, and themes could not be observed. No Tauri runtime exception was printed before the dev process was stopped. This is insufficient evidence to classify Desktop navigation as passing or to attribute a UI defect. |
| Web console during deletion/refresh | Pass | Browser console check returned no warnings or errors. |

## Focused validation

- Workspace Vitest, selected navigation cases: **21 passed, 58 skipped** across 4 files (draft isolation, archive behavior, relocation behavior, and related folder/project navigation).
- Workspace Vitest, stale-response/navigation cases: **7 passed, 74 skipped** across 5 files (stale conversation, Project, attachment, Settings, and move responses plus archive fallback).
- API client conversation tests: **18 passed**.
- Backend atomic relocation API test: **2 passed** (memory and relational persistence).
- `@ava/agent-ui` TypeScript lint: **passed**.
- `git diff --check`: **passed**.

The broader workspace test file still has unrelated pre-existing failures when run without the focused test-name filter: a Run Inspector resize expectation and a transport-recovery test that fails only in the full file. Workspace lint also reports existing type errors in Settings and other tests outside this navigation fix. The focused navigation tests and `@ava/agent-ui` lint pass.

## Final status

**#44 Navigation Acceptance — PARTIAL.** The three confirmed defects and permanent-delete fallback/refresh checks pass. Native Tauri navigation scenarios are now automated in `tests/e2e-desktop/specs/desktop-navigation.spec.mjs`, but they have not executed in a GUI. The optional last-active deletion edge case was not tested. Broader browser acceptance was not rerun.
