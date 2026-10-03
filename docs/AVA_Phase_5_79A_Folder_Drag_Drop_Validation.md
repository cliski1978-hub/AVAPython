# Phase 5.79A — Folder Drag/Drop Validation and Certification

## Result

Phase 5.79 implementation and Phase 5.79A automated certification are complete.
No Phase 5.80 work was started. dnd-kit is AVA's shared drag/drop
infrastructure.

Live browser checks could not run because the in-app browser had no tabs and no
AVA server was listening. The canonical full test harness could not finish
because its backend test stage stalls in this sandbox; a minimal FastAPI
`TestClient` reproduction independently reached construction and then stalled
on the first request. Loopback binding is also blocked by sandbox
`PermissionError`. Focused repository, ASGI-transport, interaction, type,
lint, and build checks provide the available certification evidence below.

## Infrastructure and implementation audit

- `@dnd-kit/core` `^6.3.1` and `@dnd-kit/sortable` `^10.0.0` are declared in
  the shared `frontend/packages/agent-ui/package.json`, with matching locked
  versions 6.3.1 and 10.0.0. Web, Desktop, workspace, API-client, and
  contracts do not declare independent copies.
- `ConversationList` uses dnd-kit `DndContext`, `useDraggable`, `useDroppable`,
  PointerSensor, KeyboardSensor, and `onDragEnd`. Conversations use canonical
  conversation IDs, Folder targets use Folder IDs, and Ungrouped uses a stable
  sentinel. The keyboard coordinate getter navigates Folder targets. There is
  no sortable-list behavior, drag overlay, nested Folder target, or persisted
  ordering field.
- A production-code search found no competing HTML drag/drop handlers or
  `draggable` attributes. The accessible Move-to-Folder and Move-to-Ungrouped
  menu actions remain available.
- Folder move code updates only the Folder assignment. Provider state keeps
  the conversation identity, Project, pin/archive fields, messages, selected
  ID, and run state. Move requests serialize per conversation, retain only the
  latest pending destination, and update from the final canonical response.
  Separate conversations use separate in-flight entries. A destination Folder
  deleted during a move is reconciled from canonical server state.
- Folder New Chat makes one create request with `folder_id`; the provider adds
  the returned canonical conversation only after success. The response's
  `project_id` remains null. Global New Chat still calls the global create
  method without a Folder ID; Project New Chat uses the Project-specific
  endpoint. No shared pending Folder context is stored.

## Automated evidence

The dnd-kit interaction tests exercise a real pointer-sensor sequence and a
keyboard-sensor sequence. Pointer coverage includes Folder X-to-Y targeting by
ID even when Folder names are duplicates, Ungrouped, same-Folder no-op,
pointer cancellation, and dropping outside a valid target. Keyboard coverage
includes moving to a Folder and Escape cancellation. Accessible menu tests
cover moving to a Folder and Ungrouped; failed moves preserve canonical
location and expose a retryable error.

Provider tests verify selected conversation, transcript, pin/archive metadata,
and active run state survive movement; a message update still applies to that
canonical conversation after its Folder changes; rapid moves serialize and a
late earlier response cannot win; separate conversations move concurrently; deleted
destinations and deleted Folders reconcile safely; and Folder creation sends
one request and yields a Folder-assigned, Project-unassigned conversation.
Global and Project creation behavior is also covered by the existing
`AppWorkspace` tests. Search continues to use canonical conversation IDs and
Folder membership updates do not create or remove conversations. Existing
resolver tests cover Project and Folder scopes together; a new resolver test
verifies that moving X→Y→Ungrouped changes Folder prompt participation while
preserving Project scope. Existing execution-default/selection tests passed.

Backend tests verify omitted and explicit-null Folder IDs create ungrouped
conversations, a valid ID is assigned atomically, and an unknown ID returns
`conversation_folder_not_found`. These checks run through ASGI transport for
memory and SQLite providers. SQLite restart coverage now creates in X, reopens,
moves X→Y, reopens, moves Y→Ungrouped, and reopens again. Backend movement
checks preserve conversation fields and identity, messages, run status, and
run events; Project preservation is tested for both X→Y and Y→Ungrouped on
memory and SQLite.

Validation results:

| Check | Result |
| --- | --- |
| `@ava/agent-ui` tests | 292 passed |
| `@ava/workspace` tests | 191 passed, 6 skipped; 13 files passed, 2 skipped |
| `@ava/api-client` tests | 112 passed |
| `@ava/contracts` tests | 42 passed |
| Folder persistence and Project relationship backend tests | 20 passed |
| CORE resolver tests | 11 passed, 1 skipped |
| CORE resolver, execution context/selection, and Project execution defaults | 34 passed, 1 skipped |
| TypeScript checks: agent-ui, workspace, API-client, contracts | passed |
| Backend Ruff (`src tests`) | passed |
| Backend mypy (`src`) | passed; 236 source files |
| Web production build | passed |
| Desktop production build | passed |
| `git diff --check` | passed |

The Vite builds emitted the existing advisory that the minified JavaScript
chunk exceeds 500 kB; both builds completed successfully.

## Environment blockers and mutation proof

`./scripts/test_all.sh` was attempted with a 90-second limit. It entered the
backend test stage and timed out before reaching later harness stages. The
focused TestClient test also stalls in this environment; independently,
`TestClient(FastAPI())` printed that construction completed but its first
request did not return before a 5-second timeout. ASGITransport API tests and
direct service/repository tests pass, so the stall is classified as a
sandbox-level TestClient limitation, not a Folder feature failure.

The loopback bind probe failed with `PermissionError: [Errno 1] Operation not
permitted`. CUA reported no open browser tabs and no application server was
listening, so live pointer/keyboard/reload checks were unavailable. No
disposable user data was created and no cleanup was needed.

Mutation proof temporarily changed the Folder reducer to clear `projectId`.
The rapid move test failed with the expected mismatch (`projectId: null`,
expected `project-a`). The mutation was restored and the complete workspace
suite passed afterward.

The certification therefore records all available automated checks as passed
and the canonical-harness/live-browser checks as independently evidenced
environment blockers. Phase 5.79A is complete; Phase 5.80 remains unstarted.
