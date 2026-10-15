# AVA Phase 6.14B — Authenticated Approval API and Conversation Ownership

## Status

**PARTIAL — implementation and targeted local Linux checks are complete; native Windows and frontend CI are pending.** This report follows the accepted Phase 6.14A checkpoint `20146e5e9ca5d94312073400825adc27a368a258` and the Phase 6 production integration addendum. The locked canonical development plan was not edited.

## Implemented

- Added authenticated approval queue, detail, and decision endpoints. The API derives the human principal from the trusted request resolver, checks tenant/Workspace/action authority, rejects identity fields supplied in the decision body, and returns a safe operation summary without raw arguments or operation bindings.
- Persisted approval request and terminal-decision audit events in the same SQLite transaction as their record changes. Compare-and-set decisions produce one terminal audit event; audit rows are append-only and survive repository reopening.
- Added a default-deny Workspace administration policy configured through `AVA_WORKSPACE_GRANT_ADMIN_POLICY`. Existing Workspace grant administration endpoints use the injected administration boundary; ordinary principals cannot grant themselves authority. No production identity provider or administrator integration is configured.
- Added durable principal and tenant ownership to conversations, folders, and Projects. Conversation, folder, attachment, prompt-resolution, Project metadata/files/defaults, project-conversation, and linked Run access paths are scoped or fail closed. Legacy ownerless records remain inaccessible through these scoped routes. Project creation stores the verified owner, and project-conversation creation requires matching Project and Conversation ownership; deletion also checks all linked conversations before mutating the project graph.
- Protected global CORE prompt reads behind verified identity and prompt-definition/assignment mutations behind the explicit `AVA_CORE_PROMPT_ADMIN_PRINCIPAL_REFS` allowlist. The default is deny.
- Connected the existing shared Approvals experience in Web and Desktop to the authenticated API through a common workspace data source.
- Preserved the legacy OpenHands fail-closed Workspace restriction. This phase does not implement approval continuation, restart-safe invocation reconstruction, or production tool dispatch; those remain assigned to 6.14C/6.14D.
- Extended the existing native security workflow to include Phase 6.14B tests and added frontend unit/type checks to the existing desktop acceptance workflow.

## Local verification

- Phase 6.14B API, ownership, folder, migration, relational repository, prompt-domain/API, approval, Project CRUD, and architecture migration assertions: **139 passed**.
- The unrelated Project execution-defaults API test was deselected because it stalls during TestClient app startup locally; it also stalls on the accepted 6.14A baseline.
- Ruff: **passed**.
- Mypy: **passed across 305 backend source files**.
- `git diff --check`: **passed**.
- The unrelated Project execution-defaults API test was intentionally deselected after it stalled during TestClient startup locally; the same test stalls on the accepted 6.14A baseline. The targeted Phase 6.14B suite completes with the existing `/home/bizon/AvaUi/backend/.venv`.
- Frontend tests and type checks were not run locally because this worktree has no installed JavaScript dependencies and network access prevents fetching them. The existing desktop workflow is checking them.

## Native CI certification

The required Linux validation ran locally and passed. The push also started the existing Actions matrix on Linux and native Windows. Its first Linux attempt found two stale architecture-test expectations for the new Phase 6.14B schema; both assertions now pass locally and the follow-up Actions run is pending. Native Windows and frontend checks remain in progress. Run: [Phase 6.11 filesystem security](https://github.com/cliski1978-hub/AVAPython/actions/runs/38746879685); [Desktop E2E and frontend checks](https://github.com/cliski1978-hub/AVAPython/actions/runs/38746879740).

## Acceptance boundary

Phase 6.14B remains PARTIAL until native Windows compatibility and frontend checks complete. Linux acceptance is covered by the passing local targeted suite; GitHub Linux jobs are informational under the owner-approved validation policy. Keep production tool dispatch disabled. Do not begin 6.14C in this handoff.
