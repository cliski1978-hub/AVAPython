# AVA Phase 6.6 — Tool Security and Authorization

Date: 2026-10-13  
Status: normalized preflight foundation implemented; production authority/command restrictions retained.  
Next bounded step: Phase 6.7, after explicit owner authorization.

## 1. Executive summary

Implemented an AVA-owned policy service that returns ALLOW, DENY or REQUIRES_APPROVAL after registry/version, feature, argument, trusted authority, Workspace, capability and approval checks. The service performs no tool execution, dispatch, approval decision, model call or history persistence.

**ALLOW means preflight eligibility, not an execution token.** Every decision has `execution_authorized: false` and `requires_execution_revalidation: true`. Approval-required is never usable as permission. Executors must enforce current authority and race-resistant access at the actual effect boundary.

Default composition supplies neither an execution-authority issuer nor normalized operation classifications. No allowing production issuer or development bypass was added. Production therefore cannot gain authority from metadata registration, feature enablement, Workspace selection or model/runtime choice. Test fixtures supply trusted records only to exercise policy behavior.

Commands reuse the existing command policy but remain denied even when its preliminary checks pass: that policy cannot classify argument/indirect effects or enforce the runner's final executable restrictions. No approval can bypass that unsupported-policy state.

## 2. Sources and implementation

The owner-locked master plan, Phase 6 outline, Phase 6.1–6.5 documentation and actual contracts/registry/features were inspected along with Phase 3 Workspace, command, file containment and sandbox code/guards. Existing governance and identity limitations remain as documented; no locked plan was edited.

Files:

- `backend/src/ava/contracts/tool_policy.py`: policy request/decision enums and validated values.
- `backend/src/ava/tools/authority.py`: internal authority value/port and trusted operation classification enum.
- `backend/src/ava/services/tool_policy_service.py`: runtime-neutral centralized preflight.
- `backend/src/ava/api/app.py`: constructs the default-denying service over existing registry/features/Workspace resolver and command policy; no new route.
- `backend/src/ava/services/tool_feature_service.py`: one validation-hardening adjustment, suppressing serializer warnings while immediately revalidating corrupted stored values. Invalid configuration still fails closed and is not silently accepted.
- `backend/tests/test_tool_policy.py`: isolated policy/security matrix.
- `backend/tests/test_architecture.py`: policy/authority dependency guard; catalog-only guard remains applied to registry and its export rather than unrelated new authority values.
- This report.

No migration, frontend/API-client contract, existing API response, runtime implementation, AgentPort signature, RunService policy dependency or Workspace management behavior changed. New Python policy DTOs are not exposed on HTTP; TypeScript policy mirrors are deferred until a real wire boundary requires them.

## 3. Contracts and policy flow

`ToolPolicyRequest` wraps the existing ToolRequest and v1 transport version; extra fields reject. Runtime/model selection, caller roles, Workspace roots, authority records and approvals cannot be submitted as granting fields. Requests, including unchecked model copies, are revalidated into a snapshot before evaluation.

`ToolPolicyDecision` carries optional safe invocation/tool identity (absent for malformed requests), decision, normalized `ToolPolicyReason`, safe explanation, pending-approval metadata, configuration version, policy revision, and optional existing `ToolOperationBinding`. Decision/reason/binding combinations are validated. Literal revalidation/authorization fields cannot be set to grant execution through normal deserialization. Python values are not cryptographic authorization proofs.

Evaluation order:

1. Validate request; identify the exact registered tool and definition version.
2. Read Phase 6.4 feature state and use `ToolFeatureService.require_enabled`; deny disabled/unknown/invalid settings.
3. Resolve a trusted operation classification; unsupported classifications deny. Validate arguments against the actual definition's Phase 6.2 schema subset, then the narrow operation shape.
4. Resolve current authority through a server-owned provider, never from arguments or client claims.
5. Check context/run linkage, required non-secret authority references, revision, revocation and narrowing tool allowlist.
6. Intersect explicit allowed capabilities with declared requirements/minimum operation requirements and separately check technical support.
7. Resolve current Workspace using the existing resolver; check permissions, canonical root and pinned scope.
8. Preflight the path or delegate preliminary command checks.
9. Re-read authority/Workspace/features and recheck path resolution before publishing eligible file decisions.
10. Build an exact-operation fingerprint and return read eligibility or pending approval. Never execute.

Reasons distinguish malformed requests/arguments, unknown or mismatched tools, disabled/invalid/changed configuration, unsupported operation, missing/invalid/revoked/changed authority, caller tool/capability denial, technical non-support, Workspace failures/changes, path escape, unsupported resources, network/command restrictions, allowed and approval-required. Explanations are fixed reason-derived text and do not echo arguments, content, credential material or physical paths.

## 4. Registry and feature reuse

The existing ToolRegistry remains a descriptive immutable-snapshot catalog, not a grant issuer. Trusted constructor mapping associates registered IDs with read/write/edit/delete/command semantics; it is not a second registry or user-supplied plugin/script loader. It supplies no handlers and is empty in production composition.

Feature state remains owned by ToolFeatureService and its repository. The policy reuses its fresh checks rather than reading feature tables directly or maintaining flags. A configuration revision change during evaluation denies and requires a fresh evaluation; feature disabling in a coordinated concurrent test is observed before the result.

Existing Phase 3 `ToolAuthorizationPolicy` remains the legacy SDK-tool activation boundary. No OpenHands/Native integration was changed to pretend it already calls the new normalized operation service. Future runtime integration must route operations through the new common policy and avoid a parallel bypass path.

## 5. Trusted authority model

`ToolExecutionAuthority` is internal server-owned data, not a public request DTO. It contains:

- Existing reference-only ToolExecutionContext, including caller, policy and Workspace authorization references.
- Existing RuntimeWorkspaceBinding pinning an approved canonical root, Workspace kind and permission snapshot.
- An authority revision, allowed registered-tool IDs and explicitly allowed ToolCapability values.
- Separately declared technical capabilities; support is not permission.
- Optional bound run identity and optional narrowing tool-ID set; revocation state.

`ToolExecutionAuthorityPort.resolve(context_ref)` must authenticate/attribute the current caller, check scope/run ownership and expiry/revocation, and return current immutable authority or None. Merely possessing a guessed context ID is not a grant. No real issuing/authentication adapter ships here; missing issuer, invalid records or issuer failures deny. A caller reference string by itself is not authentication.

The issuer must pin the canonical approved root and change/revoke authority when scope changes. Current resolver state is checked against that pin. Reusing a Workspace ID after retargeting its root or changing grants cannot silently extend old authority. No Project, Folder, Project File, selected runtime/model or frontend administrative boolean supplies authority.

Phase 3 Workspace permissions remain necessary, but an independently granted operation capability is also required. For deletion, write scope is necessary but insufficient: explicit FILE_DELETE capability is required. Runtime support can only narrow availability; changing it cannot override a denied caller capability.

## 6. Filesystem preflight and execution-time requirements

The existing WorkspaceResolver is reused. Roots must be existing absolute directories. Preflight uses the same canonical descendant principle as Phase 3, expressed with resolved Paths and `relative_to`, never a string prefix. No SDK containment/execution helper is imported into the neutral policy layer. This is policy path validation, not another Workspace resolver or file executor.

Relative and contained absolute targets are supported. Traversal outside the root, sibling-prefix tricks and symlink escapes deny. Read/edit/delete require a current regular file; directories/root targets, hard-linked files and unsupported resources deny. Write/create may target a not-yet-existing contained path, subject to future executor checks. Invalid permission/root mappings deny; no cwd/home/repository fallback is granted.

The approved canonical root/permission snapshot is pinned by authority. Path resolution and current file metadata are rechecked before the preflight result. This narrows race windows but does **not** eliminate TOCTOU, symlink swaps, resource changes or revocation after return. The fingerprint's stat tuple is an observational revision, not a collision-proof content revision or locked descriptor.

Future executors must revalidate all gates/authority/approval/resource expectations immediately before side effects, use descriptor-anchored or equivalently race-resistant containment where supported, and contain/cancel active work when authority is withdrawn. No executor or claim of race-proof execution was added.

## 7. Commands and network

Command input is structured executable/argument/cwd data; extra environment/credential/permission fields reject. Workspace read/write/shell requirements and network restrictions apply independently of metadata and technical capability.

The existing CommandExecutionPolicy evaluates cwd, permissions, executable syntax and sandbox availability. It never executes. Its current implementation does not validate executable allowlisting (the runner does) or determine arbitrary argument effects; names such as python/bash can cause indirect mutations. Accordingly:

- Missing shell scope, outside cwd and invalid executable preparation deny.
- Network-capability requests and unsupported network policy deny.
- Missing command policy denies.
- A preliminary command-policy allow becomes `command_policy_insufficient`, not ALLOW or REQUIRES_APPROVAL.

All normalized commands, including seemingly harmless pwd, remain conservatively denied until a stronger supported command-effect policy exists. No new allowlist, shell wrapper, host fallback, command handler or sandbox execution was introduced. Existing legacy controlled command behavior is unchanged and is not represented as normalized-policy integration.

## 8. Approval boundary and binding

Validated low-risk read operations can return ALLOW when every independent restriction passes. Mutations, above-low-risk reads and definitions requiring approval return REQUIRES_APPROVAL only after all other checks pass. An earlier denial is never transformed into an approval opportunity.

The SHA-256 fingerprint covers the revalidated request, definition metadata/schema/version, operation classification, effective configuration/policy revisions, Workspace identity/canonical scope, authority references/revision, allowed/narrowing tool sets, permitted/technical capabilities, Workspace permissions and observed target metadata. Root/path values participate privately in the digest, not in the public explanation/binding fields. Changed arguments, context/definition/scope/revisions/capabilities alter the fingerprint or deny revalidation.

The binding is an exact-operation reference for future approval comparison, not a signature or accepted approval. Phase 6.7 must authenticate decisions, bind immutable records, enforce expiry/revocation and revalidate before continuation. Configuration-enable dialogs, model text and a fabricated approved DTO do not count as human execution approval. No approval records, service, routes, decisions or resume/restart logic were implemented.

## 9. Future use cases and invariants

The authority's optional narrowing tool set intersects the base allowed set; it cannot widen it. A future use-case provider can bind administrator-assigned Workspace authority through the same trusted interface without importing use-case entities into policy. Standard/Power User presentation and deterministic/agentic/hybrid metadata are not permission axes.

RunService still depends on AgentPort and not this policy service. Runtime, provider, model, inference runtime, Workspace and resource ownership remain separate. No model-routing/resource-manager behavior or Phase 5 execution precedence changed. Public policy values import only AVA contracts, stdlib and Pydantic; internal authority uses neutral AVA Workspace values, not SDK objects.

## 10. Executed evidence

| Gate | Actual result |
| --- | --- |
| Policy/feature/registry/architecture/command authorization/audit/Phase 6.2 contracts subset | **356 passed in 3.98s**, final run, no warnings. |
| Existing SDK tool security matrix using isolated files/stub command runner | **15 passed in 4.02s**; no Bubblewrap/model command execution. |
| Broader run including existing Workspace execution tests | **385 passed, 3 failed in 3.62s**. Failure baseline below. |
| Pre-policy temporary source baseline, Workspace execution suite | **29 passed, same 3 failed in 0.29s**. |
| Backend Ruff, `src tests --no-cache` | **PASS**. |
| Strict mypy, source plus new policy tests | **PASS**, 265 source/test files. |
| New contract/authority/service/test formatter check | **PASS**. |
| Settings-core frontend regression | **226 passed**. |
| API-client frontend regression | **118 passed**. |
| `git diff --check` | **PASS**. |

Focused command from backend:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_tool_policy.py tests/test_tool_features.py tests/test_tool_registry.py \
  tests/test_architecture.py tests/test_command_policy.py tests/test_tool_authorization.py \
  tests/test_tool_audit.py tests/test_tool_contracts.py
```

The security matrix covers all requested denial boundaries: registry/version, master/individual gates, enabled-but-not-authorized, missing/malformed/revoked authority, invalid/pinned Workspace, traversal/absolute/symlink/sibling escapes, contained paths, write/delete distinctions, shell/cwd/network and indirect commands, pending approval without execution, technical capability changes, narrowing, malformed request/configuration, normalized reasons, concurrent disable/revocation, immutable decision flags and no file side effects. Fixtures issue no production identity; they model trusted server records. No developer files or destructive commands were used.

The three broader failures are in `test_workspace_execution.py`: approved-binding SDK fixture, no-Workspace SDK fallback fixture, and missing-file-tools fixture. Their stub SDK does not satisfy the current controlled OpenHands runtime initialization and returns runtime-unavailable rather than the expected result. The same assertions fail in an isolated temporary baseline with the new policy/authority/contracts/wiring removed and the feature-warning adjustment reverted. They were not fixed or hidden by changing runtime code.

Architecture guards verify registry remains catalog-only; authority values remain inward/SDK-free; policy has no runtime/provider/infrastructure/transport dependency; feature evaluation stays separate; RunService never imports the policy service; and runtime adapters do not acquire catalog/authority registration paths. Restricting the catalog guard to catalog files permits the separately guarded neutral authority module without relaxing catalog security.

Full backend/TestClient/aggregate harness and native acceptance remain unverified here; earlier AnyIO/Bubblewrap limitations remain. No sandbox was launched or model inference performed. No frontend API/schema boundary changed, so no new TypeScript policy mirror or Web/Desktop build was required/repeated in this backend-only step. Existing frontend feature/API behavior was rerun as above.

## 11. Limitations and Phase 6.7 readiness

Ready for bounded approval-foundation work after explicit authorization, not operational privileged-tool rollout. Still absent: production authenticated authority issuer, durable grant revocation/provisioning, approval identity/persistence/continuation, descriptor-safe executors, command-effect classification, normalized runtime dispatch and effect recovery. The stat fingerprint is not a content-lock guarantee; no preflight result prevents changes after return. Secret-bearing Workspace provisioning and content disclosure policy remain trusted issuer/executor responsibilities.

No new capability was activated, no migration/UI/history/use-case/RAG work was done, and no locked planning document was modified. Phase 6.7 has not started.
