# AVA Phase 6.14B — Authenticated Approval API and Conversation Ownership

## Status

**PARTIAL — implementation and focused local checks are complete; native Windows/Linux and frontend CI are pending.** This report follows the accepted Phase 6.14A checkpoint `20146e5e9ca5d94312073400825adc27a368a258` and the Phase 6 production integration addendum. The locked canonical development plan was not edited.

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

- Phase 6.14B API, ownership, folder, migration, relational repository, prompt-domain/API, approval, and Project CRUD tests: **137 passed**.
- The unrelated Project execution-defaults API test was deselected because it stalls during TestClient app startup locally; it also stalls on the accepted 6.14A baseline.
- Ruff: **passed**.
- Mypy: **passed across 305 backend source files**.
- `git diff --check`: **passed**.
- The full local backend suite could not be certified in this environment: TestClient-based API tests stall during app startup, including `tests/test_project_api.py::test_project_execution_defaults_api_preserves_omitted_fields_and_clears_explicit_null`; that Project test also stalls on the accepted 6.14A baseline. Focused Phase 6.14B tests use the existing `/home/bizon/AvaUi/backend/.venv` and complete successfully.
- Frontend tests and type checks were not run locally because this worktree has no installed JavaScript dependencies and network access prevents fetching them. The existing GitHub Actions workflow now runs them.

## Native CI certification

Pending. Update this section with the actual GitHub Actions run URL and the Linux, Windows, frontend test, and type-check results before changing the phase status from PARTIAL.

## Acceptance boundary

Phase 6.14B is not certified until the Windows and Linux security jobs and frontend checks pass. Keep production tool dispatch disabled. Do not begin 6.14C in this handoff.
