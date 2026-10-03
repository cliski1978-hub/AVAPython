# Phase 5.83A — Shared Loading Regression Recovery

Status: **COMPLETE — shared loading/recovery path hardened.** Phase 5.84 has not started.

## Root cause and evidence

The exact original browser incident was no longer available to inspect. A controlled equivalent was forced on 2026-10-03: keep Web/Vite open, stop the verified AVA Uvicorn backend on port 8000, then initialize the Web app while the backend listener is absent.

**ROOT CAUSE:** initial loads for Conversations, Folders, and Documents settled after a transport failure but did not offer an in-place recovery path. Conversation and Folder showed errors without retry. Conversation also rendered “No active conversations” from its failure-cleared empty array, conflating failure with a successfully empty list. Documents hid its failed list request behind an empty-looking “No document open” view. Restoring the backend did not restart those settled requests, so reload was the only recovery. Projects and Settings already had independent retry behavior. This reproduces a concrete failure that plausibly explains the reported multi-surface incident; it does not prove the timestamp or precise trigger of the original incident.

**TRIGGER:** one backend outage overlapped several independent initial GET requests.

**WHY INTERMITTENT:** a startup with a healthy backend succeeds. A request started during the absent-listener window fails; reopening after recovery issues new requests and often hides the settled-error behavior.

**WHY MULTIPLE SURFACES FAILED:** each feature requested its own data from the same unavailable backend. There was no single global Promise gate, but the shared transport outage caused independent initial failures at the same time. Missing retry and ambiguous empty-state UX made those failures persist and look like a shared loading deadlock.

**WHY A CLEAN RESTART OFTEN HIDES IT:** a reload after backend recovery reissues the initial requests. The original data was durable and intact.

The first failing boundary was transport acquisition: the backend listener was stopped. Browser-visible error states corroborated caught request failures. The available CUA interface did not expose Network-panel entries, so the exact browser request exception/status could not be captured from DevTools. No API payload, message content, prompt, file content, token, or secret was recorded.

## Instrumentation and audit findings

`frontend/packages/workspace/src/loading-recovery.test.tsx` wraps the shared API fetch boundary with test-only trace records: request ID, method, URL, start/end times, HTTP status or error name, and observed provider-consumer state. Deferred promises force StrictMode double-effect startup and out-of-order completion. This instrumentation is test-scoped; no production request logging was added.

The shared loading audit found:

- Conversation, Folder, Project, Document, Settings subsection, and connectivity state are independently owned. A single loader failure does not gate the app shell or unrelated areas.
- Loaders either have a `finally` settlement or reducer success/failure transitions that clear loading. Conversation and Document collection loaders now also expose distinct load errors.
- The API client applies a 10-second timeout to ordinary requests. Collection effects do not abort on cleanup; generation/cancel guards suppress stale results without preventing a remounted provider from starting a fresh request.
- StrictMode invokes collection effects twice in the regression test. A newer successful response remains authoritative when the older request later fails.
- Conversation/Folder/Project deletion tombstones are per-provider/resource sets, not a global load gate. Existing late-list/deletion tests pass; no change was needed.
- Conversation hydration uses `Promise.all` for the individual message lists. A failed child request can reject that Conversation collection hydration, but it now settles into a visible retryable error; this did not explain independent Project, Document, or Settings failures. `Promise.allSettled` is used for independent Folder reconciliation calls.
- The top-level `Promise.all` for runtime/provider/profile discovery only populates execution-choice controls; it does not gate Chat, Projects, Documents, or Settings rendering. Models and workspaces load independently.
- Empty arrays are treated as successfully loaded collections. The live database’s zero-Folder result renders `Ungrouped` without a loading indicator or error.
- Active/Archived filtering and Folder/Project dedup remain derived from canonical data. Existing reducer, selector, folder-state, archive, and project tests pass.
- Documents mounts independently of Conversation state. Settings tabs/subsections remain available independently; a failed provider inventory has a scoped retry.

## Fix

- Conversation collection state distinguishes initial loading from load failure; `reloadConversations` and `reloadFolders` are exposed to the workspace and retry controls are rendered for each error.
- Active, Archived, and search empty labels are rendered only after the corresponding Conversation collection/search state succeeds, so a failed empty-array snapshot is not shown as an empty result.
- Conversation and Folder collection generations suppress stale responses and are invalidated on provider cleanup. A failed request clears loading and a retry starts a new generation.
- Document hydration has explicit start/success/failure reducer actions and `loadError`. `reloadDocuments` uses request generations; the editor shows Loading, a retryable error, or the actual loaded/empty state. Creating a document is disabled until initial hydration is known.
- Web Vite now uses `strictPort: true` on 5173. Previously, starting a second Web dev server silently fell through to 5174, which is the Desktop Vite port and could direct testing to the wrong app. The corrected behavior refuses a duplicate listener instead of silently selecting that port. Desktop already has strict port selection.

No backend, schema, or database changes were made. `scripts/dev_backend.sh` runs Uvicorn and does not silently adopt an existing listener: a second start while port 8000 is occupied reports `Address already in use` and exits. No automatic process kill or ambiguous stale-listener reuse was found. The earlier observed backend and Vite working directories were both `/home/bizon/AvaUi`; there is no evidence that a stale backend caused the incident. Port 5173 is Web; 5174 is Desktop when running.

## Stress and live validation

| Scenario | Result |
| --- | --- |
| Web starts before backend; initial requests fail | Reproduced before the fix: Conversation/Folder lacked retry and Documents looked empty after failure. After the fix, the same outage settles into explicit retryable states. |
| Backend starts before Web | Passed: Web was restarted with Uvicorn healthy and loaded the current persisted data. |
| Backend restart with Web left open | Passed across three clean backend restart cycles. During the forced outage, the UI showed unavailable/retry states; restoring the backend and using retries recovered without page reload. |
| Frontend restart with backend healthy | Passed: Vite restarted on 5173; the existing browser tab reloaded and hydrated data. |
| Full-stack restart | Passed: stopped both dev servers, started backend first, then Web, and reloaded the browser. |
| Hard reload during/after bootstrap | Passed after backend recovery. Chat and collection loading settled; no permanent spinner remained. |
| Rapid Chat / Projects / Documents / Settings navigation | Passed; sections returned to usable views. |
| Active / Archived switching | Passed. Current database has no archived conversations, so Archived showed its valid empty state and Active restored the 11 active rows. |
| Direct Project workspace reload | Passed for `/projects/8156f164-7311-4aeb-b084-72c327ed7a14`; the Project overview loaded. Its Conversations tab completed its request and showed the current empty state. |
| HMR update and restoration | Passed. A temporary comment in Web `App.tsx` triggered Vite HMR; loaded conversation rows remained present. The comment was removed and the app remained stable. |
| Delayed and out-of-order API completion | Passed in deferred StrictMode test. Newer success is retained after older failure. |
| One/all initial request failures and retry | Passed for Conversations, Folders, and Documents in StrictMode AppWorkspace tests; retry succeeded without reconstruction. Settings subsection and Project list failures have existing isolated retry coverage. |
| Empty-state versus failed-load distinction | Passed live and in regression test: failed Chat shows retryable errors without “No active conversations”; failed Documents shows a load error instead of “No document open.” Archived/search empty labels are also gated on settled state. |
| Empty Folders | Passed: 0 folders is a settled loaded state, distinct from loading or failure. |
| Stale listener/version mismatch | No controlled stale-revision backend was created; live listener inspection found current checkout working directories. No evidence justified adding version protocol or changing backend startup behavior. |
| Web port collision | Previously reproduced 5173 fallback to 5174; `strictPort` now makes the duplicate invocation fail clearly. |

No browser error overlay or uncaught failure was visible during the live outage/recovery. A console warn/error query from the initial baseline returned no entries because request failures were caught. The CUA surface did not expose a reliable Network panel or pending-request inspector, so current console/network verification is limited to the visible UI and backend access logs. During successful recovery the backend logged HTTP 200 GETs for `/conversations`, `/conversation-folders`, each conversation’s `/messages`, `/documents`, `/projects`, `/projects/{id}/conversations`, and `/settings/providers`; bootstrap also returned 200 for health, models, runtimes, execution profiles, workspaces, and model providers. All observable UI loading states settled after those responses.

## Mutation proof and tests

Mutation proof: temporarily removed the rendered Conversation retry button while leaving the recovery test unchanged. `recovers failed Conversations and Folder startup loads through in-place retry` failed because `Retry loading conversations` could not be found. Restored the control; the same test passed. A separate new test for not rendering “No active conversations” after a failed load also failed before the render guard, then passed after the guard.

| Suite | Result |
| --- | --- |
| `@ava/agent-ui` | 21 files, 294 tests passed (dnd-kit, Archive, tombstones/reducer, Conversation UI included). |
| `@ava/workspace` | 15 files passed, 2 integration files skipped; 209 passed, 6 skipped (loading recovery, Projects retry, archive, folders, project files, settings navigation included). |
| `@ava/api-client` | 14 files, 112 passed. |
| `@ava/contracts` | 13 files, 42 passed. |
| `@ava/document-core` | 7 files, 70 passed. |
| `@ava/settings-core` | 11 files, 209 passed. |
| Phase 5.82/5.83 backend durability and migration certification | 11 passed. |
| Frontend TypeScript checks | agent-ui, workspace, api-client, contracts, document-core, settings-core passed. |
| Web / Desktop production builds | Both passed; existing chunk-size warning remains. |
| `bash -n scripts/dev_backend.sh` | Passed; script was not changed. |
| Ruff / mypy | Not run; no Python source changed. |
| `./scripts/test_all.sh` | Attempted. It collected 2,521 backend tests, then made no progress at `tests/test_attachment_restart_recovery.py`; interrupted after the known TestClient/loopback stall. The focused loading/recovery and migration suites ran independently. |
| Additional backend API group (cleanup/delete/Project API) | Attempted; also stalled in the sandbox’s TestClient/loopback boundary before reporting a result. |

## Durable state and phase record

Read-only SQLite verification after restart stress found schema version **18**, **11 Conversations**, **0 Conversation Folders**, **1 Project**, and **2 Documents**. No rows were modified, no migration was added, and durable data remained intact.

Production files changed for this recovery are:

- `frontend/apps/web/vite.config.ts`
- `frontend/packages/agent-ui/src/components/ConversationList.tsx`
- `frontend/packages/agent-ui/src/state/ConversationProvider.tsx`
- `frontend/packages/agent-ui/src/state/conversationReducer.ts`
- `frontend/packages/document-core/src/editor/DocumentWorkspace.tsx`
- `frontend/packages/document-core/src/state/DocumentProvider.tsx`
- `frontend/packages/document-core/src/state/documentReducer.ts`
- `frontend/packages/workspace/src/AppWorkspace.tsx`

Regression coverage is in `frontend/packages/workspace/src/AppWorkspace.test.tsx`, `frontend/packages/workspace/src/loading-recovery.test.tsx`, and `frontend/packages/document-core/src/state/DocumentProvider.test.tsx`.

Phase 5.83A is complete. Shared loading/recovery is hardened. Phase 5.84 is not started.
