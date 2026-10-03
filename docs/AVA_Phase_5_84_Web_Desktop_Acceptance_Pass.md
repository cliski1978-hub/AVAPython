# Phase 5.84 — Web + Desktop Acceptance Pass

**Status: COMPLETE — Web + Desktop acceptance passed. Phase 5.85 was not started.**

The Web application and Desktop package's Vite frontend passed the shared-backend workflows recorded below. Phase 5.84A subsequently closed the remaining native Tauri gates using the actual native window, an outage/retry cycle, repeated native restarts, and the built release artifact. The native acceptance evidence, icon packaging fix, limits, and cleanup are in [AVA_Phase_5_84A_Native_Tauri_Acceptance_Closure.md](AVA_Phase_5_84A_Native_Tauri_Acceptance_Closure.md). Project File upload was verified through the local API because the earlier browser file chooser was inaccessible; no Project File existed for the native release smoke. No acceptance fixture remains.

## Environment and data safety

- Repository: `/home/bizon/AvaUi`.
- Backend: canonical `./scripts/dev_backend.sh`, local API at `http://127.0.0.1:8000`; `/health` returned `healthy` and `/capabilities` returned contract version `v1`.
- Web: canonical `pnpm --filter @ava/web dev`, Vite at `http://127.0.0.1:5173/`. Strict port behavior was retained; it did not fall through to 5174.
- Desktop: canonical `pnpm --filter @ava/desktop tauri dev`; the Tauri build completed and `target/debug/ava-desktop` remained running. Its Vite frontend served at `http://localhost:5174/` and was inspected in the in-app browser. The app inventory contained no native apps/windows, and the CUA environment did not provide native-window interaction. This browser page is evidence for the Desktop package frontend only.
- Live migration registry remained at version 18. No migration, schema, or database reset was performed.
- Before creating fixtures, the live database contained 11 conversations, 0 folders, 1 Project, and 2 Documents. Acceptance records used only disposable test IDs and `ACCEPTANCE-584-*` names.
- At cleanup, the named Folder, Project, three acceptance conversations (including the two Folder/Project-created `New Conversation` records), four Project Files, CORE definition, and its assignment were removed through AVA's local API. The original Project and Documents were not deleted. Final counts returned to 11 conversations, 0 folders, 1 Project, and 2 Documents; migration version remained 18 and `PRAGMA integrity_check` returned `ok`.

## Web acceptance matrix

| Surface / workflow | Result | Evidence and limits |
| --- | --- | --- |
| Shell, navigation, initial loading | PASS | Fresh Web shell rendered, Connected state appeared, and Chat, Projects, Documents, and Settings opened. Existing 11 conversations loaded. |
| Existing conversation | PASS | Opened existing `Test 1` read-only; title, long transcript/history, composer, and message actions rendered. Existing `Test 2` Document was also opened without edits. |
| New Chat, streaming, transcript | PASS | Created global `ACCEPTANCE-584-CHAT` with null Folder/Project; sent a harmless prompt; backend logged successful conversation/message/run/SSE requests; exact response appeared once. Hard reload preserved the transcript. |
| Retry/regenerate | PASS | Regenerated an acceptance response; progress appeared and settled without changing the conversation identity. A configured CORE marker was returned exactly by the live execution. |
| Search | PASS | Searching `ACCEPTANCE-584` found the named conversation and selected the correct row (earlier live check in this pass). |
| Archive/restore | PASS | Archived conversation left Active, remained readable in Archived, then restored with history and metadata intact. |
| Pin/unpin | PASS | Pin/unpin and repin worked; canonical pinned ordering changed. No manual ordering was introduced. |
| Folder creation, menu move, New Chat | PASS | Created the Folder, moved the acceptance conversation via menu, and created a Folder New Chat with null Project membership and immediate Folder placement. |
| dnd-kit pointer / Ungrouped / same-Folder | PASS | Pointer drag moved Folder→Ungrouped and back; accessibility state showed the intended drop targets and no duplicate rows. Same-Folder no-op produced no visible change. |
| dnd-kit keyboard | PASS (automated) | Live keyboard drag was not performed. Existing keyboard drag/cancel tests ran as part of the passing Workspace suite. |
| Folder rename and persistence | PASS | Renamed Folder; membership followed the stable Folder ID and survived reload. |
| Folder delete semantics | PASS (API + reload) | Deleting the disposable Folder returned 204. All three conversations survived with `folder_id = null`; the Project conversation retained its Project ID at that point. Web and Desktop-package frontend reloads observed the shared post-delete state. UI confirmation dialog for Folder deletion was not exercised. |
| Projects / workspace | PASS | Existing Project and acceptance Project loaded. Acceptance workspace Overview, Conversations, Files, Instructions, and Settings tabs rendered. Project+Folder conversation was listed once while SQLite retained both links before Folder deletion. |
| Project New Chat and Folder coexistence | PASS | Project-created chat had Project membership; assigning a Folder retained both IDs and the UI did not duplicate it. Folder deletion then cleared only Folder membership. |
| Project Instructions and CORE execution | PASS | Saved exact acceptance instruction and verified it on revisit. Resolver preview showed the enabled global CORE prompt and expected provenance; live execution returned the configured marker exactly. |
| Project execution defaults | PASS | Saved OpenHands as Project runtime, refreshed to verify persistence, then cleared it back to application inheritance. Both save and null/inherit behavior worked. |
| Project Files tab / metadata | PASS | Empty state had loaded before files existed. Four resources later rendered, including Unicode and two distinct same-name rows. File list remained visible after reload in both Web and Desktop-package frontends. |
| Project File upload / download | PARTIAL | Four byte-known files were uploaded through the local API because the legacy CUA browser driver could not control a file chooser. Rows appeared in the Files UI. Download returned HTTP 200 with the expected encoded filename and byte-for-byte matching content/hash. Unicode filename preserved. |
| Duplicate-name deletion | PASS (API + UI refetch) | Deleted one duplicate by its ID through the local API. Web Files refetch showed one remaining duplicate row plus the other files. The row's Delete button was not used. |
| Project deletion | PASS (API + both reloads) | Project UI showed a confirmation stating deletion is permanent; the dialog was cancelled. Local API deletion returned 204, removed all Project File metadata/content and Project-scoped assignments, and cleared Project membership while preserving conversations. Reloads in both frontends showed `Project not found`; surviving conversations had null Project IDs. |
| CORE definitions/assignment | PASS (partial UI) | Created and enabled a harmless global CORE prompt; assignment list and resolver API showed the enabled global scope. Exact execution marker was observed. The UI delete-confirm flow was not exercised; the named prompt and assignment were removed through the local API at cleanup. |
| Documents | PASS | Documents workspace loaded and both existing documents could be opened read-only with content visible. Documents-specific retry during the outage was not separately repeated in this turn. |
| Settings | PASS | Providers, Models, Runtimes, Defaults, and System Prompts sections rendered. Existing Ollama Local connection and model/runtime/default rows were inspected; no real credential or application default was changed. |
| Retry after backend outage | PASS (selected loaders) | With frontend open, backend outage showed explicit error/retry states for Conversations and Folders and an unavailable Projects state, rather than false empty results. Conversation and Folder retries recovered without refreshing; Projects recovered on navigation without refreshing. Documents and Settings outage retries were not separately exercised. |
| Web hard reload / backend restart / frontend restart | PASS | Chat, Project routes, Documents and Files were loaded after reload. Backend was restarted canonically; Vite was restarted canonically while backend remained available. Transcript, Folder before its intentional deletion, Project settings/files before cleanup, and shared data recovered. Full-stack restart/reload was observed. |
| Background-run navigation | NOT RUN | No separate navigate-away-during-generation scenario was performed. |
| Responsive resize / live keyboard/focus audit | NOT RUN | The legacy computer-use surface did not provide viewport resizing. Keyboard and focus checks were limited to automated dnd-kit coverage and normal keyboard-operable UI contracts. |
| Browser console | NOT AVAILABLE | The computer-use surface used for this live pass exposed no browser console-log API. |

## Desktop acceptance matrix

| Surface / workflow | Result | Evidence and limits |
| --- | --- | --- |
| Tauri/Desktop shell launch | PASS (closed by 5.84A) | Actual native window, WebView, process, routes, interactions, outage/retry, and release artifact are verified in the linked 5.84A record. |
| Desktop Chat, existing history, shared state | PASS (Desktop Vite frontend) | `AVA — Desktop` page connected to the same backend and showed the acceptance conversation, exact assistant transcript/CORE marker, Folder and Project groupings, and existing conversations. |
| Desktop Projects and workspace | PASS (Desktop Vite frontend) | Project list and workspace opened. Overview and Files were inspected; Files showed the same metadata as Web. Instructions and Settings tabs existed and were exercised earlier in the shared frontend pass. |
| Desktop Documents and Settings | PASS (Desktop Vite frontend) | Shared package views were opened during the pass; all Settings major sections loaded. Native window rendering and controls were inaccessible. |
| Desktop search/archive/restore/Folder drag | PARTIAL | These shared workflows passed on Web. Desktop Vite showed the same list/state, but a separate full Desktop interaction cycle was not repeated. |
| Desktop restart | PASS (closed by 5.84A) | Normal close and two subsequent native development relaunches reconstructed durable data; the built release also closed/reopened after cleanup. |
| Web/Desktop shared backend state | PASS (browser frontends) | Resources created in Web were visible in Desktop Vite frontend after reload; Folder and Project deletion cleanup propagated to both frontends. This does not certify the native Tauri webview. |
| Desktop runtime errors | PASS with observability limit (5.84A) | Native stdout and backend request logs showed no acceptance-blocking runtime errors. Native WebView console capture is unavailable in this environment. |

## Recovery, API, and cross-shell notes

Live backend logs showed successful 200 responses for health, capabilities, conversations/messages, folders, Projects, Documents, settings providers/models/runtimes, CORE prompts/assignments, resolver, and Project File operations. The focused UI outage proved no-refresh recovery for conversation and Folder loaders and later Projects navigation. Full restart and Vite restart evidence passed for the browser frontends. Existing resources remained available; after cleanup, the live database returned to its pre-acceptance top-level counts and integrity check passed.

No stale Folder/Project/File/CORE resource returned after deletion and reload. The deleted Project deep link rendered the explicit `Project not found` state in Web and Desktop Vite. All acceptance fixture IDs were absent from SQLite at the end. The user-owned Project and both Documents remained present.

## Defects and implementation changes

Phase 5.84A found one native packaging defect: AppImage bundling had no configured square icon. Tauri already had a 512×512 icon asset, so the bundle config now explicitly uses it; all configured native bundles then built. No runtime product defect or regression test gap remains for native acceptance. The native console, pointer drag, native Project File download, and Documents/Settings-specific outage clicks remain unverified as detailed in the closure report; the Project had no files to download. The earlier Project File upload chooser and several less central live checks remain partial as listed above, with no BLOCKER or MAJOR acceptance defect.

## Automated validation

| Check | Result |
| --- | --- |
| `@ava/agent-ui` | PASS — 294 passed |
| `@ava/workspace` | PASS — 209 passed, 6 skipped; 2 integration tests skipped |
| `@ava/api-client` | PASS — 112 passed |
| `@ava/contracts` | PASS — 42 passed |
| `@ava/document-core` | PASS — 70 passed |
| `@ava/settings-core` | PASS — 209 passed |
| Focused backend domains | PASS — 136 collected, 133 passed, 3 skipped; included Folder, Project, execution defaults, Project Files, CORE, hard delete, restart durability and migration coverage |
| Project API focused test | BLOCKED — the third parameterized API test stalled. A minimal `TestClient` context with a temporary database also hung during lifespan entry, before the test request; this is a harness/environment issue. Live Project API behavior succeeded. |
| Canonical `./scripts/test_all.sh` | BLOCKED — collected 2,521 tests, passed through `tests/test_attachment_repository.py` (8%), then stalled at `tests/test_attachment_restart_recovery.py`, specifically the end-to-end restart/recovery harness; interrupted after no progress. This matches the known TestClient/loopback harness limitation. |
| TypeScript checks | PASS — both production builds ran TypeScript before Vite. |
| Web build | PASS — `pnpm --filter @ava/web build`; Vite emitted the existing large-chunk warning. |
| Desktop build | PASS — `pnpm --filter @ava/desktop build`; same non-failing chunk warning. |
| Ruff / mypy | NOT REQUIRED — no Python code changed. |
| Phase 5.79 keyboard/dnd coverage | PASS — included in full Workspace suite. |
| Phases 5.80–5.83A, CORE, Project defaults, Project Files backend regressions | PASS — included in the focused backend and frontend suites listed above. |

## Remaining acceptance gates

Phase 5.84 is **COMPLETE** after the native closure in [AVA_Phase_5_84A_Native_Tauri_Acceptance_Closure.md](AVA_Phase_5_84A_Native_Tauri_Acceptance_Closure.md). The known canonical backend TestClient/loopback harness stall and the focused Project API lifespan stall remain recorded as environment limitations, with the earlier focused backend suite passing. Project File upload-chooser and other non-native items marked partial above are not BLOCKER or MAJOR acceptance defects. No Phase 5.85 work was started.
