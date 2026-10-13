# AVA Phase 5.77 — Project Files UI

Phase 5.77 activates the existing Project workspace Files tab with Project-scoped list, upload, download, and delete actions. The feature uses the certified typed API client and keeps its transient state inside `ProjectFilesPanel`. It does not change backend behavior or place Project Files in Conversation Attachments, prompts, or execution context.

## Files tab behavior

The Files tab mounts `ProjectFilesPanel` only while active. Its first request uses `listProjectFiles(projectId)` and renders the returned backend order unchanged. The table shows filename, content type (or “Unknown”), binary-formatted byte size, creation date, and actions. Empty, loading, and retryable load-error states are local to the tab. A `project_not_found` response reconciles the workspace back to Projects.

Upload uses the selected browser `File` object with `uploadProjectFile`; its authored Unicode filename is preserved, and the browser MIME type is passed through without extension-based inference. Submission is guarded while pending. A duplicate-name conflict is shown inline, retains the selection, and adds no row. On success, the list is fetched again to use canonical backend ordering; if that reconciliation fails, the returned file is still shown and the user can retry the list refresh. Filenames are unique within a Project; zero-byte files render as `0 B`.

Download calls `downloadProjectFile(projectId, file.id)`, saves the Blob under the public metadata filename, and revokes its temporary object URL. Pending and failure state is per file. Delete opens AVA's accessible confirmation modal and calls `deleteProjectFile(projectId, file.id)` only after confirmation. A successful delete removes only that ID and releases its filename for a later upload. Failure keeps the row and leaves the confirmation available for retry.

Changing Projects resets Files state through the keyed Project panel. Cancelled list requests cannot overwrite a different Project's result. Archived Projects use the same Files controls. Existing Project deletion navigation remains in place; if the Files API reports that the Project no longer exists, the workspace invokes the existing deletion/navigation callbacks.

## Boundaries

The feature imports only typed Project File lifecycle methods. Its public metadata type and UI contain no `content_ref`, storage path, or storage root. The Files state is not in global conversation state and the panel does not import conversation or execution-context features. No attachment actions, file preview/parser, execution inclusion toggle, knowledge status, indexing, embeddings, chunks, or retrieval controls were added. Project Files remain inert Project resources.

## Validation

- `ProjectFilesPanel.test.tsx`: 13 tests cover load order, empty/loading/error/retry, upload success/failure/pending, Unicode filenames and duplicate-name conflicts, zero-byte formatting, download/error/object-URL cleanup, confirmation, deletion, delete failure, and the late Project A response race.
- `ProjectFilesPanel.architecture.test.ts`: 2 tests guard typed client use and public/UI boundaries.
- `ProjectsWorkspace.test.tsx`: 27 tests include Files tab activation, archived Project management controls, and deleted-Project reconciliation.
- Workspace: **179 passed, 6 skipped** (the skips are existing opt-in live integration tests).
- API client: **111 passed**; contracts: **41 passed**. Both packages' TypeScript checks passed.
- Workspace TypeScript check passed. Web and Desktop production builds passed; Vite printed its existing bundle-size advisory.
- Mutation proof: changing deletion to use `target.file_name` made the duplicate-ID regression fail once because the API received `spec.pdf` instead of ID `a`. Restoring `target.id` made that test pass.
- Live UI upload/download/reload was not run: no local browser tab was available to the task, and the prior Phase 5.76A backend listener attempt in this restricted sandbox failed with `PermissionError: [Errno 1] Operation not permitted` while binding a socket. No live Project or user data was changed.
- `git diff --check` passed.

```text
Phase 5.77 Project Files UI: COMPLETE
Project Files remain separate from attachments and execution context.
Project knowledge/RAG is not implemented.
Phase 5.78 is not started.
```
