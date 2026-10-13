# AVA Phase 6.7 — Workspace Access Management

**Date:** 2026-10-13  
**Scope:** Persistent AVA-owned execution Workspace configuration, restricted administration, and Phase 6.6 preflight integration.  
**Status:** Implemented within the supplied Phase 6.7 brief. No tool execution, human approval flow, runtime integration, or use-case application was added.

## Existing architecture reused

Phase 3 already separates `WorkspaceRegistry`, `WorkspaceResolver`, `ResolvedWorkspace`, `WorkspacePermissions`, and `RuntimeWorkspaceBinding`. The registry used by the existing NativeAgent/OpenHands selection path remains process-local and contains only explicitly server-provisioned entries. Workspace discovery continues to publish safe identity metadata and does not disclose host paths.

Phase 6.6's `ToolPolicyService` already performs runtime-independent preflight and requires a separately resolved `ToolExecutionAuthority`. The service now uses the same `WorkspaceResolver` with a narrow durable-configuration lookup port. Durable records are resolved only for normalized-tool preflight; they are not added to the older client-selectable Workspace registry. This prevents a Workspace settings record from widening the Phase 3 OpenHands path.

`RunService → AgentPort`, the existing command policy and sandbox boundaries, the tool registry, feature gates, and shared Settings package remain the owning seams for their respective responsibilities. Projects and Conversation Folders remain distinct from execution Workspaces.

The root `CONTEXT.md` glossary does not yet define execution Workspace separately from Project. This report keeps those terms distinct; the glossary gap is noted for future domain-modeling work.

## Configuration contracts

`WorkspaceAccessConfiguration` stores a stable validated ID, optional descriptive name, existing Workspace kind, canonical absolute root, allowed `ToolCapability` restrictions, active/revoked state, positive configuration revision, timestamps, and contract version. It contains no credentials, scripts, SDK objects, or client authority grants.

The existing `WorkspaceResolver` receives a `WorkspaceAccessLookupPort` at composition. The persistence adapter validates that the root still resolves to the same canonical existing directory, then projects the current Workspace permissions and capability ceiling. `ResolvedWorkspace` and its runtime binding carry the configuration revision and optional configured-capability ceiling. Phase 6.6 compares the full binding against the trusted authority snapshot and rejects stale revisions, changed roots, changed permissions, and capabilities outside the configured ceiling.

The authority provider still owns caller, run, and tool scope. Workspace configuration does not issue authority. Tool registration, feature enablement, model/runtime selection, and Workspace selection remain insufficient to create a grant.

## Persistence and migration

The new repository port supports list/get/create and revision-checked compare-and-set. Tests use a lock-protected in-memory implementation. SQLite persistence uses migration **v0025**, which adds `workspace_access_configurations` with a stable primary-key identity, constrained kind/status/revision/version columns, JSON capability storage, and timestamps. Creation is insert-only; updates compare the expected revision in one transaction. Revoked identities cannot be reactivated or reused. A root change therefore requires a trusted administrative update and advances the revision.

Repository decoding validates every stored record. Invalid capability JSON, malformed contracts, missing/non-directory roots, and roots whose canonical target changed fail closed. Corrupt configuration is reported as invalid by Settings and cannot be resolved for preflight.

The owner-locked canonical plan was not edited. Historical test ceilings were advanced to schema 25; no historical migration was rewritten.

## Trusted administrative boundary

Workspace mutation routes require the injected `WorkspaceAdministrationPort`. The default `DenyWorkspaceAdministration` denies creation and updates. It is not controlled by a request header, client role, environment flag, or frontend state. The request contracts reject extra fields such as `isAdmin`. Root paths are returned only when the trusted administration port reports access; ordinary Settings responses omit them.

No authenticated identity source or deployment-restricted administration provider currently exists in AVA. As composed by default, the Workspace Access screen is read-only and both mutation routes return 403. A future deployment integration must back the port with authenticated request-scoped authority or a deployment boundary that excludes untrusted callers. This phase does not add enterprise identity or make privileged administration available by default.

## Revocation, roots, and authority

Revocation is durable and terminal for a Workspace identity. Each preflight lookup reads current configuration. The authority binding includes its configuration revision and configured capability ceiling, so root and permission changes invalidate previously issued bindings. A missing or invalid Workspace, revoked Workspace, inaccessible root, symlink-retargeted root, or stale binding is denied.

Overlapping roots remain separate configuration records with separate capability ceilings. The lookup never merges their permissions; authority continues to name one Workspace identity and caller scope. Existing Phase 6.6 path containment checks remain in force. Validation to later filesystem use or sandbox mounting still has a time-of-check/time-of-use window; preflight does not eliminate that race.

## Settings implementation

The shared `@ava/settings-core` surface now has a Workspace Access section used by Web and Desktop. It shows stable ID, name, kind, capability restrictions, active/revoked status, revision, and administrative status. Root paths are hidden unless the backend explicitly permits disclosure.

When the backend reports trusted administrative access, the section exposes create/edit/revoke forms with a review checkbox and explicit security text. Roots are entered as administrator-supplied absolute paths; there is no filesystem browser or ordinary-user root picker. The existing generation guard drops stale loads, and saves use the expected revision. With default administration denied, these controls are absent or disabled and no mutation call is made.

## Validation

- Workspace access, Phase 6.6 policy, feature gates, registry, persistence migrations, and migration certification: **126 passed**.
- Existing Workspace authorization/security matrix, Workspace execution, and command policy: **91 passed, 2 failed**. The two failures are existing OpenHands test stubs whose `_Agent` constructor does not accept `agent_context`; the Phase 6.6 handoff records the same stale SDK-stub incompatibility in its broader baseline.
- Workspace discovery service checks excluding HTTP endpoint tests: **7 passed**.
- Relevant architecture guards: **7 passed** in the focused run; the Workspace registry/resolver dependency boundary remains intact.
- Backend Ruff: **passed**. Strict mypy over backend source and the new Workspace tests: **273 files passed**.
- Shared Settings suite: **230 passed**. Settings, API client, and contract TypeScript checks: **passed**.
- Web production build: **passed**. Desktop frontend production build: **passed**. Both emit the existing large-chunk warning.
- No tool handler, command, sandbox process, or Workspace file mutation was invoked by the new tests.
- Native desktop interaction was not manually exercised; the shared Settings UI is covered by frontend tests and both application builds.

## Limitations and next phase

There is no production `ToolExecutionAuthorityPort` issuer, authenticated Workspace administrator, or atomic execution lease. The default policy service therefore continues to fail closed for normalized-tool requests. The persisted Workspace registry is configuration only, not an execution grant. Path checks remain subject to the previously documented TOCTOU gap, which must be addressed at the eventual effect boundary.

The supplied Phase 6.7 brief identifies Workspace Access Management and asks for readiness for Phase 6.8. The checked-in [Phase 6 implementation outline](AVA_PHASE_6_IMPLEMENTATION_OUTLINE.md) still labels 6.7 as the durable approval framework and 6.8 as Approval UI. This numbering conflict is recorded without changing the owner-locked plan or outline. Workspace Access is ready for its follow-on review. If Phase 6.8 means Approval UI per the outline, its stated prerequisite—the durable approval framework in outline step 6.7—has not been implemented in this Workspace Access scope, so that UI is not yet ready to build.
