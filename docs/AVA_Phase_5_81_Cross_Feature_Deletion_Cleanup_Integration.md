# AVA Phase 5.81 — Cross-Feature Deletion / Cleanup Integration

Phase 5.81 certifies the existing synchronous deletion ownership rules across
conversations, folders, projects, CORE prompts, and Project Files. It does not
add a generic cleanup worker or change archive behavior.

## Ownership and lifecycle matrix

| Resource | Hard delete | Archive | Relationships and owned children | External content / UI |
| --- | --- | --- | --- | --- |
| Conversation | Conversation hard-delete coordinator transaction removes the Conversation, owned messages, eligible Conversation-owned runs/events, and Conversation-scoped CORE assignments. Active runs reject deletion before mutation. | Reversible metadata flag only; transcript, runs, assignments, Folder and Project identity remain. | Folder and Project are references; neither owner is deleted. Deleting a Conversation removes the references with the row. | Owned attachment metadata is removed transactionally; attachment bytes are removed after commit by exact storage key. UI removes active/search/archive rows, chooses the next existing selection or empty state, clears projection, and aborts that Conversation's run observer. |
| Conversation Folder | Folder repository clears `folder_id` on surviving conversations and removes Folder-scoped assignments in the same repository transaction (SQLite) or guarded memory operation. | No archive lifecycle. | Conversations survive; Project membership and archive state are unchanged. | Sidebar removes the Folder/drop target and reconciles search metadata and pending moves. A late Folder list is filtered against locally accepted deletions. |
| Project | Project repository clears `project_id`, deletes Project-scoped assignments and Project File metadata transactionally, then the Project File service removes the exact content refs after commit. | Project archive changes Project metadata only. | Conversations survive; their Folder IDs and archive state are preserved. Project-owned instructions/defaults disappear with the Project row. | Project Files UI is unmounted with the deleted workspace; navigation/cache and Project detail state reconcile. Late list/detail results are ignored or filtered by deleted Project IDs. |
| CORE System Prompt | Prompt repository/service deletes the definition and every assignment for its opaque prompt ID, including disabled and non-durable runtime/capability scopes. | Disabled is not deleted; assignments remain until an owner/delete path removes them. | Scope owner lifecycle separately removes Project, Folder, and Conversation assignments. Runtime/Capability are external identifiers and have no delete lifecycle here. | Resolver reads current repositories; no deletion cache exists. Settings removes the definition/assignment editor selection after successful deletion. |
| CORE Prompt Assignment | Removed with its prompt or durable scoped owner. | No archive behavior. | Global/runtime/capability assignments are removed with their prompt. Durable scopes are also cleaned by the owner lifecycle. | No separate content. |
| Project File metadata | Single delete removes one file ID's metadata before deleting its exact content ref. Project delete collects and removes all Project-owned metadata in the Project transaction. | No archive lifecycle of its own. | Exactly one owning Project; normalized filenames are unique within that Project and may repeat in a different Project. | Content removal follows metadata commit. Failures raise `ProjectFileStorageError`; committed metadata is not rolled back or reported as intact. |
| Project File content | Deleted only through the corresponding Project File metadata record/content ref. | No archive behavior. | Never deleted by filename; no sharing is modeled by the Project File contract. | Content store restart keeps the absence of deleted opaque refs. |
| Messages / Runs / Run Events | Conversation hard-delete service cleans the conversation-owned graph using source-run and ownership rules; shared/ambiguous references are detached or preserved according to the coordinator. | Preserved. | They are Conversation lifecycle children, subject to the coordinator's shared-reference safeguards. | Late stream events are ignored after the observer is aborted and reducer updates for missing Conversation IDs remain no-ops. |

## Transaction and schema audit

The hard-delete coordinator removes Conversation-owned SQL rows in one
transaction; attachment bytes are post-commit. Folder deletion updates
`conversations.folder_id` and removes Folder assignments before deleting the
Folder in one SQL transaction. Project deletion collects Project File refs,
clears Project assignments and Conversation memberships, then deletes the
Project in one SQL transaction; content cleanup is post-commit. CORE prompt
deletion removes assignments and definition in one transaction. Project File
single deletion removes metadata before content. Existing tests inject SQL
failure to confirm rollback and inject content failures to confirm honest
post-commit errors.

Current relevant FK policy is intentionally mixed: `project_files.project_id`
references `projects.id ON DELETE CASCADE`; `core_prompt_assignments.core_prompt_id`
references `core_prompts.id ON DELETE CASCADE`; Project default
`default_model_id` references model configuration with `ON DELETE SET NULL`.
Conversation Folder and Project IDs are nullable application-managed
relationships without FKs; repository delete paths clear them explicitly. Run
events and message/source-run links use service/repository cleanup and integrity
checks rather than relying on a broad cascading delete. No migrations were
needed.

Memory repositories explicitly perform Folder/Project/prompt assignment and
Conversation-reference cleanup; Project File metadata/content cleanup uses
the same service boundary as SQLite. Runtime and Capability assignment IDs
remain exempt from durable-owner FK checks because those are canonical external
identities.

## Integration certification

`backend/tests/test_deletion_cleanup_integration.py` exercises a disposable
Project/Folder/two-Conversation/CORE-prompt/assignment/two-same-name-Project-
File graph against memory and SQLite. It deletes one Conversation, deletes one
same-name file by ID, deletes the Project, deletes the Folder, deletes the
disabled prompt and its remaining assignments, and finally hard-deletes an
archived Conversation. It checks relationship survival at each step, exact
content refs, file/assignment orphan queries, SQLite foreign-key and integrity
checks, and durable deletion after reopening the database.

Existing rollback tests in `test_project_files.py`,
`test_project_persistence.py`, and `test_core_prompt_assignments.py` cover
pre-commit failure. Existing conversation hard-delete tests cover active-run
rejection, transactional rollback, owned messages/runs/events/attachments,
restart durability, and FK integrity. Frontend regressions cover selected
Conversation deletion, search result removal and late search responses, late
run events, Folder deletion during a pending move, and late initial Folder
listing. Folder and Project membership, archive state, and Project content are
not conflated.

Project File content cleanup after a successful metadata commit is synchronous.
If the content store fails, the service reports `ProjectFileStorageError` and
logs the file ID; the committed database deletion is not rolled back. A retry
queue/garbage collector is outside this phase. Future Knowledge/RAG work must
remove Knowledge representations derived from a deleted Project File; no such
implementation exists yet.

## Validation and limitations

Validation completed for Phase 5.81:

- Backend focused lifecycle/persistence/resolver/selector suite: **87 passed,
  4 skipped**; the standalone resolver suite reports **13 passed, 1 skipped**.
- Full workspace suite: **205 passed, 6 skipped**, plus the archived-delete
  regression: **10 passed**. It includes selection,
  search/run events, Folder state and DnD, archive sidebar, Project workspace,
  Project Files, and background navigation.
- `@ava/agent-ui`: **293 passed**; API client: **112 passed**; contracts:
  **42 passed**.
- Ruff passed; full backend mypy passed (236 source files).
- TypeScript lint/type checks passed for agent-ui, workspace, API client, and
  contracts. Web and Desktop production builds passed.
- Mutation proof: removing SQLite Folder `folder_id` cleanup made exactly the
  relational integration-matrix test fail; restoring the update returned the
  matrix to **2 passed**.
- No migration was added. The two stale migration tests that expected schema
  version 17 were corrected to expect the existing latest version 18.
- `./scripts/test_all.sh` was attempted and stalled at
  `test_attachment_restart_recovery.py`; it was interrupted after no progress.
  Independent socket bind/listen reproduction fails with
  `PermissionError: [Errno 1] Operation not permitted`, and the local browser
  URL `http://127.0.0.1:5174/` returned `ERR_CONNECTION_REFUSED`. The canonical
  harness/live app are therefore environment-blocked, not reported as passing.
- Existing Project File tests cover local content-store restart, project-delete
  rollback preservation, and honest post-commit cleanup failure. The new
  integration matrix checks memory/SQLite graph parity and durable SQLite
  deletion after repository restart.

Live destructive browser tests were not run because the local application was
not listening. No non-disposable resources were created or deleted.
