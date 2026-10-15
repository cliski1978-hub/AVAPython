# AVA Phase 6.14B — Authenticated Approval API and Conversation Ownership

## Status

**PARTIAL — Phase 6.14B implementation and its backend, frontend-unit, and type-check validations pass.** The broader Linux desktop E2E acceptance remains blocked because its fixture server does not configure trusted authentication, so folder fixture creation receives HTTP 503. This report follows the accepted Phase 6.14A checkpoint `20146e5e9ca5d94312073400825adc27a368a258` and the Phase 6 production integration addendum. The locked canonical development plan was not edited.

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
- Frontend tests and package type checks passed in the existing desktop workflow: Contracts (120 tests), API Client (15 tests), and Approvals Core (14 tests), plus the Contracts, API Client, Approvals Core, Workspace, Web, and Desktop TypeScript checks.
- Local reruns from this worktree were unavailable because its Python and JavaScript dependencies were not installed and this environment could not reach the package registries. The earlier local Linux Phase 6.14B backend run completed with the counts above.

## Native CI certification

The required native Windows run passed, including the shared filesystem/authorization contracts, NTFS capability check, native Windows filesystem security tests, and Ruff. The paired Linux security job also passed, including Linux adversarial filesystem tests, Ruff, and mypy. The first Actions attempt exposed stale architecture assertions, which were corrected; the Windows ordering test was made independent of host clock resolution. The frontend tests and affected-package type checks passed. The subsequent Linux desktop acceptance E2E failed before its scenarios could run because its fixture POST to `/conversation-folders` received `503 {"detail":"Trusted authentication is not configured."}`. That legacy fixture setup remains the exact certification blocker. Runs: [Windows and Linux filesystem security](https://github.com/cliski1978-hub/AVAPython/actions/runs/38748682393); [frontend checks and desktop acceptance](https://github.com/cliski1978-hub/AVAPython/actions/runs/38749293379).

## Acceptance boundary

Phase 6.14B remains PARTIAL pending a trusted-auth test fixture for the broader Linux desktop E2E acceptance. The B-specific backend and frontend checks passed on Linux and Windows as reported above. Keep production tool dispatch disabled. Do not begin 6.14C in this handoff.
