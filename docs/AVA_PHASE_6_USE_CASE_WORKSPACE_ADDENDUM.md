# AVA — Architectural Addendum: Fixed Use Case Execution Workspace

**Status:** Proposed owner-requested addendum for incorporation into the locked master plan
**Date:** 2026-10-12
**Applies to:** Phase 6 foundations; future configurable use-case implementation phase

## Binding architectural rule

Every configured use case **must** reference an explicitly assigned AVA agent-execution Workspace. The Workspace assignment is fixed for ordinary end users and is not modifiable through their application interface, chat, prompts, tool arguments, or runtime/model selection.

### Requirements

1. **Administrator-defined assignment.** An authorized administrator assigns a Workspace when a use case is provisioned. Only an explicitly authorized administrative change can replace it.
2. **No end-user override.** Regular users may choose business resources (a specification, robot, or document set) exposed by the use case, but may not modify its Workspace identity, root, or authorized filesystem scope.
3. **Backend authority.** The server resolves the assigned Workspace from trusted persisted configuration; it never trusts client-supplied workspace IDs, paths, or agent-suggested locations as an authority grant.
4. **Mandatory validation.** Every resource-accessing tool request must be checked against the assigned Workspace plus tool permissions, capability gates, and approval policy. Unset, unavailable, or invalid assignment fails closed.
5. **Stable across runtimes.** Model, model-provider, and agent-runtime switching cannot broaden Workspace authority.
6. **Per-use-case isolation.** Shared filesystem areas are accessible only when explicitly included in each use case's authorized Workspace policy; no implicit cross-use-case access.
7. **Secure path handling.** Filesystem tools enforce real path containment including traversal, symlink, and race-aware controls, using the established Phase 3 security mechanisms.
8. **Revocation and change semantics.** Administrative Workspace changes invalidate pending approvals or authorization decisions based on the former assignment. New actions are checked against the current effective assignment; active actions are cancelled or contained when technically feasible.
9. **Historical truth.** Tool/run records preserve the effective Workspace identity and authorization scope at execution time, without exposing sensitive paths unnecessarily.

## Phase boundaries

**Phase 6:** Preserve agent Workspace security boundaries and build tool-policy/approval contracts so a trusted, fixed Workspace binding can be supplied later. Do **not** define or ship use-case entities in Phase 6.

**Configurable Use Case Application Framework phase:** Add required `workspace_id` binding to the use-case configuration, administrator-only management, regular-user read-only visibility (if helpful), default-deny validation, and end-to-end tests.

## Terminology

An **agent execution Workspace** is a resource/security boundary. A **use case** is an application configuration. A **Project** and **Folder** organize application content. They must remain distinct.

## Governance

This addendum does not silently rewrite the owner-locked canonical master document. Incorporate it only through the master's owner-authorized amendment procedure; thereafter coding agents must not alter it without explicit owner permission.
