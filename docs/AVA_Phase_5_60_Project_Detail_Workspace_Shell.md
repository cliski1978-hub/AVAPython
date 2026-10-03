# Phase 5.60 — Project Detail / Workspace Shell

Phase 5.60 replaces the Phase 5.59 Project detail placeholder with a stable,
read-only Project workspace frame. The change was reconciled against the
repository state before implementation.

## Scope audit and reconciliation

The initial repository audit found the Phase 5.59 Project list, Project CRUD
actions, `/projects/{project_id}` placeholder, direct `getProject` loading,
safe not-found state, return-to-Projects navigation, and mounted workspace
providers. It found no existing Phase 5.60 implementation, no Phase 5.60
documentation, and no accidental Project conversation linkage, Project file
implementation, execution-default behavior, or instruction execution wiring.

The existing list, navigation, direct-load, and not-found behavior was kept.
The placeholder detail body was replaced with Project identity/context,
section navigation, and the five scoped section bodies. The existing Project
delete action on the detail route remains available. No existing work was
removed or deferred in this reconciliation.

## Project workspace

`ProjectsWorkspace` owns Project list/detail state and the selected Project
section. It calls the existing `getProject` API for `/projects/{project_id}`;
Project detail state is not copied from the list. The Project header shows the
name, non-empty description, active/archived state, and the existing metadata
delete action. Archived Projects continue to open normally.

The workspace uses AVA's existing local tab pattern rather than adding a second
router. Section selection is local React state and defaults to Overview on a
direct route or refresh. The existing browser route remains
`/projects/{project_id}`; the Projects list and back action remain
`/projects`.

Sections are:

| Section | Phase 5.60 behavior |
| --- | --- |
| Overview | Read-only name, description, archive state, creation time, and update time |
| Conversations | Placeholder; no Project conversations are connected |
| Files | Placeholder; Project file management is not enabled |
| Instructions | Placeholder; persisted instructions remain inert metadata |
| Settings | Placeholder; Project execution settings are not configured |

Directly loading a Project route requests its Project from the backend and
shows Overview after load. A `project_not_found` response retains the safe
not-found state and a path back to Projects. Other load errors remain safe and
retryable.

## State ownership and boundaries

Project view state stays in the Project workspace layer. Conversation,
conversation-run, search, folder, and run state remain owned by their existing
providers. The Project detail and section panels are rendered inside the
existing workspace shell, so visiting or switching Project sections does not
unmount the conversation providers or stop background run observation.

This phase adds no `Conversation.project_id`, Project conversation query or
assignment behavior, ProjectFile domain, upload/download/delete file flow,
instruction execution wiring, execution defaults, RAG, or knowledge indexing.
No backend production code or API-client production code changed.

## Validation

Focused Project workspace tests cover Project identity and metadata, all five
sections, direct-route loading, archived Project access, not-found handling,
back navigation, and background-run/conversation preservation through Project
navigation. The focused workspace run passed 84 tests across four files; the
Project API-client regression passed 2 tests. The workspace TypeScript check
and Web and Desktop production builds passed. Both builds retain the existing
large-chunk advisory.

The load-bearing mutation changed every Project section tab to select Overview.
The section-navigation regression failed exactly **1 test** (14 tests skipped
by the focused name filter). After restoring the tab handler, the focused
workspace suite passed again: **84 passed, 0 failed**.
