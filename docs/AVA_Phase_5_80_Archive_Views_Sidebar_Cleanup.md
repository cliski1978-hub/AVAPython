# Phase 5.80 — Archive Views + Sidebar Cleanup

## Outcome

Phase 5.80 adds a dedicated **Archived** view to the Chat sidebar and presents
the existing canonical archive flag consistently across conversation lists.
The view is a filtered projection of `ConversationProvider` state; it adds no
second store, API, migration, or backend write semantics.

## Sidebar behavior

- The Chat sidebar has keyboard-accessible **Active** and **Archived** view
  controls. The usual Chat sidebar hierarchy remains New Chat and search,
  followed by Projects, Folder sections, Ungrouped conversations, and the
  separate Archived view.
- Active conversations and archived conversations are derived centrally from
  the canonical conversation collection by `selectActiveConversations` and
  `selectArchivedConversations`.
- Folder sections and Ungrouped render active conversations only. A Folder
  containing only archived conversations remains present and empty.
- If an active conversation has both a Project and Folder, the Chat sidebar
  renders its single row under its Folder. The Project section omits that
  Folder-assigned row, avoiding duplicate actions and duplicate dnd-kit IDs.
  Project-only conversations remain in the Project section. Project detail
  conversation lists also omit archived conversations.
- Archived view aggregates all archived conversations regardless of Folder or
  Project membership. It disables drag sources and Folder move actions; users
  Restore before organizing again.
- The existing Project/Folder expansion and Folder-collapse state stays in the
  mounted sidebar component while switching views.

## Archive, restore, and conversation behavior

Archive and Restore reuse the existing typed `setConversationArchived` call.
The provider serializes pending archive mutations per conversation: if another
target state arrives while the write is pending, it writes the latest target
after the first response and does not publish the stale intermediate state.
Mutations for different conversations remain independent. Errors leave the
canonical previous state in place, retain the action menu for retry, and show a
localized alert. Successful operations provide a screen-reader status message.

Only `is_archived` changes. Conversation ID, transcript, current run state,
pin, Folder ID, and Project ID are preserved. The backend archive service is
metadata-only in memory and SQLite; no production backend or API-client change
was needed. Its existing canonical conversation order determines Archived
ordering (pinned, then updated time, created time, and ID); Phase 5.80 adds no
archive timestamp or ordering field.

The selected conversation is not cleared on archive. The sidebar switches to
Archived after a successful archive of the selected conversation, keeping the
same selected row and main transcript reachable. Restoring that selected
conversation switches back to Active and keeps the same ID selected. Focus
moves to that conversation's row after either operation; when the row is no
longer present (for example, a non-selected archive), focus moves to the
selected row or view control. The `role=status` announcement reports the
completed action.

Archived conversations remain openable, readable, and sendable under the
existing composer/run policy; Phase 5.80 adds no read-only or execution rule.
Run state and event observation are not changed by archive state. Search
semantics remain title search across all conversations, including archived
ones. Mixed search results show a subtle **Archived** label; searching while
in the Archived view narrows those results to archived matches. Search results
are flat rows rather than a second Folder/Project grouping path.

Menu terminology remains **Archive**, **Restore**, **Archived**, and **Delete**.
The existing hard-delete confirmation/action remains distinct from Restore.
No drag-to-archive, drag-to-restore, Folder archive, Project archive change,
or archive-specific table was introduced.

## Validation

- `@ava/agent-ui`: 21 files, 293 tests passed. `@ava/workspace`: 14 files,
  202 tests passed and 6 skipped. `@ava/api-client`: 14 files/112 tests passed.
  `@ava/contracts`: 13 files/42 tests passed.
- Affected workspace regressions cover Folder drag/drop (pointer and keyboard),
  Folder/Ungrouped active filtering, an empty Folder containing only archived
  conversations, Project+Folder de-duplication, Project detail filtering,
  Archived aggregation, search status, selected and non-selected archive,
  restore to Folder and Ungrouped, archive/restore failure, existing hard
  delete actions, and active-run/message-state preservation.
- Backend focused archive/cleanup tests: 9 passed across memory and SQLite.
  They verify archive/restore preserves IDs, transcript, runs/events, pin,
  Folder, and Project; SQLite close/reopen after archive and restore; deleting
  a Folder clears an archived conversation's Folder reference; deleting a
  Project applies its existing cleanup to an archived conversation while
  retaining the conversation/archive state; and hard delete remains distinct.
- Frontend TypeScript checks passed for `agent-ui`, `workspace`, `api-client`,
  and `contracts`. Ruff passed for the two modified backend test modules.
  `pnpm --filter @ava/web build` and `pnpm --filter @ava/desktop build` passed.
  Both builds reported the existing 784.64 kB main-chunk advisory.
- Mutation proof: temporarily removed the active collection's archive filter.
  `conversation-archive-sidebar.test.tsx` failed exactly 1 test because
  **Archived Folder** leaked into the active Folder list. The filter was
  restored and the complete frontend suites pass.
- `git diff --check` passed. Backend production, API-client production, and
  migration files were not changed.

## Environment limits

- `./scripts/test_all.sh` was attempted with a 90-second bound. It reached
  `backend/tests/test_attachment_restart_recovery.py`, an existing
  TestClient-based integration suite, and timed out (exit 124). An isolated
  existing archive TestClient test independently timed out at 20 seconds.
- A direct Python socket bind/listen on `127.0.0.1` failed with
  `PermissionError: [Errno 1] Operation not permitted`. Opening the local app at
  `http://127.0.0.1:5174/` returned `net::ERR_CONNECTION_REFUSED`; the browser
  inventory contained no existing tabs. Thus live archive/restore/reload and
  live-run checks were unavailable. No user conversation or disposable live
  data was modified.
- The non-HTTP memory/SQLite archive, deletion-interaction, and restart tests
  described above passed independently of TestClient.

Phase 5.80 is complete. Phase 5.81 has not started.
