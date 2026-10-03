# Phase 5.59 — Project List Page and Navigation Shell

Phase 5.59 adds Projects as a primary workspace destination and implements the
initial Project list and metadata actions. The page uses the typed Project API
client and owns Project view state independently of conversation and run state.

## Navigation and refresh

The existing workspace tab shell now includes **Projects**. Selecting it
navigates to `/projects`; opening a Project navigates to
`/projects/{project_id}`. Browser back/forward updates the selected workspace,
and refreshing either route loads current Project data from the backend. The
conversation and run providers remain mounted while Projects is visible, so
switching destinations does not cancel a background run or clear chat state.

## List and metadata actions

The page requests `listProjects` when opened and preserves the returned order.
Active and archived Projects appear in separate sections; archived Projects
remain visible. The page distinguishes an empty Project collection from a
collection with only archived Projects and shows a retryable safe error when
loading fails.

**New Project** opens AVA's shared modal with name, optional description, and
optional instructions. A blank name is rejected before the API call. Create
failures leave the dialog and entered values intact; successful creation
closes the dialog and reloads the backend-ordered list. Duplicate names remain
allowed. Instructions are persisted as metadata only.

Archive and restore use the typed archive mutation. The row action is disabled
while its request is pending. A failed request keeps the previous list state
and reports a safe error; success reloads the canonical list.

Delete requires confirmation and states that only Project metadata is removed.
Success removes the Project from the list and returns to `/projects` if its
placeholder route was open. A `project_not_found` response reconciles the
stale row and uses the same safe navigation. Other failures leave the Project
visible and keep the current route.

## Project placeholder and scope

The `/projects/{project_id}` placeholder loads the Project directly, displays
its name and description, and provides a safe not-found view with a return
action. It explains that the Project workspace is not available yet. It has no
conversation list, files, instructions editor, execution defaults, or
knowledge/RAG behavior.

Conversation folders remain organizational groups in the conversation
sidebar. Projects remain separate workspace/context boundaries; no
conversation linkage or execution behavior was added.
