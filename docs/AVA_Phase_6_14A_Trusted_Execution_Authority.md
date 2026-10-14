# AVA Phase 6.14A — Trusted Execution Authority and Current-Invocation Resolution

## Status

Phase 6.14A establishes the portable identity, ownership, grant, and authority foundation. It does not activate production tool dispatch. The production authentication provider, grant administrator, and conversation ownership adapter are not configured in this repository. API authorization tests could not be completed in the current local environment because the installed synchronous Starlette test client stalls before returning even a `/health` response; the focused contract, service, and migration checks listed below did run.

This report records the implementation against the Phase 6.14A brief and the Phase 6 production execution integration addendum. It does not change the owner-locked canonical plan and does not start Phase 6.14B.

## Trust architecture

The trust path has four distinct responsibilities:

1. **Authentication:** an HTTP infrastructure adapter verifies request evidence and returns an AVA-owned `VerifiedPrincipal`.
2. **Resource authorization:** `RunAccessService`, Workspace grants, and the trusted conversation-access port decide which persisted resources the principal may use.
3. **Execution-authority issuance:** `RunExecutionAuthorityService` rebuilds an operation-scoped authority from current Run, session, grant, Workspace, feature, and policy state.
4. **Current invocation:** the normalized execution and approval services require the authority and exact current invocation facts before an operation can proceed.

An authenticated principal alone grants no tool permission. Runtime and model choices do not issue identity or authority. The API layer owns the FastAPI adapter; Core contracts do not depend on FastAPI or provider SDKs.

## Principal contracts and resolution

`VerifiedPrincipal` carries a stable issuer/subject identity, optional tenant, trusted actor type, safe authentication-context identifier, opaque authentication-context reference, and aware authentication/expiry timestamps. It rejects unexpected fields, unsafe provider namespaces, malformed timestamps, and authentication-context labels that resemble credential names. Its stable principal reference is a SHA-256 digest of issuer namespace and subject; raw credentials and SDK objects are not part of the contract.

`HttpPrincipalResolverPort` is the HTTP-specific adapter seam. `require_verified_principal` distinguishes unavailable authentication (503) from missing/invalid identity (401), checks absolute session expiry, and calls `PrincipalValidityPort`. Provider errors fail closed without logging the request or exception. Client headers and request-body identity fields are not consulted as evidence. `UnavailableHttpPrincipalResolver` and `DenyPrincipalValidity` are the production factory defaults; no concrete identity provider is present.

The principal-validity port is also rechecked during authority resolution and while an SSE stream is active. A deployment adapter must bind the opaque authentication-context reference to the exact verified session and return false for expiry, revocation, lookup errors, or unknown sessions.

## Run ownership and authorization

Migration `0029_trusted_execution_authority` adds nullable owner principal, tenant, authentication-context reference, absolute authentication expiry, and execution Workspace fields to Runs. Nullability preserves old rows without asserting an owner. An owner index supports scoped access. New API-created Runs take their owner only from the trusted resolver; the client cannot set it. Retry paths preserve the authorized caller as the new Run owner instead of inheriting authority from the parent.

`RunAccessService` permits reads and mutations only when both principal reference and tenant match the durable owner. Ownerless legacy Runs and foreign Runs are hidden with the same not-found response. This applies to Run snapshots, event reads, SSE, inspection, cancellation, and conversation Run listing. SSE rechecks session validity and Run ownership as it polls. Cross-tenant access is denied, including when the subject is otherwise the same.

Historical ownerless Runs remain in storage and continue to be available to internal recovery and data-management code. They are not assigned to the first authenticated user and are not exposed through protected Run APIs. A later owner migration needs separately verified provenance or an explicitly authorized administrative process.

Conversations do not yet carry trusted owner metadata. `ConversationAccessPort` therefore defaults to deny; linked Run creation and linked context preview return unavailable until a deployment supplies a trusted owner lookup. Standalone Runs do not depend on conversation ownership.

## Workspace grants

Workspace configuration defines the resource boundary and its maximum capabilities. It is separate from a grant, which identifies the principal, tenant, optional Run restriction, permitted capabilities, Workspace configuration revision, status, and grant revision. A grant is separate from the narrow authority snapshot issued for one operation.

Migration 0029 adds durable `workspace_access_grants` storage, active-scope uniqueness, and lookup/revision indexes. The grant repository is composed for memory and relational persistence. Grant creation checks that the Workspace is active, the expected configuration revision matches, the grant tenant matches the authenticated administrator tenant, and grant capabilities are within the Workspace ceiling. Updates use expected revisions; revocation is terminal and increments the revision. Stale configuration revisions invalidate grants at authority resolution.

Grant list/create/update/revoke endpoints require a verified principal. A separate `WorkspaceGrantAdministrationPort` authorizes each action and defaults to deny. No administrator identity, role header, local-origin exception, or universal grant is built in. The API does not expose Workspace root paths in grant projections.

## Scoped authority issuance and current invocation

`RunExecutionAuthorityService` issues an opaque context handle only for a non-terminal, non-cancelled, non-Chat Run whose persisted Workspace matches the requested Workspace. Each later resolution reloads the Run and revalidates session validity, owner metadata, expiry, tenant, active grant and optional Run restriction, grant/configuration revision, Workspace resolution, feature configuration, and effective framework gate. Any lookup or validation error denies authority. The handle map is bounded and is a process-local lookup mechanism, not a durable authority token.

The resulting `ToolExecutionAuthority` is scoped to the Run, principal, tenant, Workspace, grant and revision, Workspace configuration revision, feature configuration version, capabilities, permitted tool IDs, and authority revision fingerprint. Tool IDs are derived from current registry definitions, feature state, capability requirements, and policy. Command operations are excluded; Plan mode is limited to read operations; Chat mode cannot resolve execution authority.

The runtime bridge receives the issuer only when a non-default trusted principal resolver and principal-validity adapter are explicitly composed. Tool execution rechecks the persisted Run mode, ownership, Workspace, cancellation state, grant references, current authority, and scoped tool/capability values. Runtime selection cannot supply an authority issuer.

Approval matching uses the current normalized `ToolRequest`, Run, tool identity/version, invocation identity, and operation fingerprint. Raw arguments are not written to durable approval projections. The exact current request snapshot remains process-local today. After restart, the approval service cannot reconstruct the invocation and pending approval is invalidated; there is no encrypted, restart-safe invocation snapshot store in this phase. This is a remaining requirement for durable approval resumption, not a reason to accept a caller-supplied invocation.

## Persistence and migration

Migration 0029 is additive and registered after version 28. It retains nullable ownership for legacy Runs and creates the grant table and indexes. Run repositories, serialization, lifecycle services, and both memory/relational persistence compositions carry the ownership fields. The migration certification tests exercise the version-28-to-29 path and historical migration progression.

The opaque authority handle and exact in-flight invocation are process-local. Durable facts required to re-authorize—Run owner, tenant, auth-context reference/expiry, Workspace assignment, Workspace grant, configuration revisions, feature configuration, and reservations—are read from their owning repositories. Issuance is not a substitute for rechecking those stores.

## API authorization behavior

Run endpoints require trusted identity. An unconfigured authentication provider reports 503; an absent, invalid, expired, or revoked principal reports 401. Once authenticated, missing, ownerless, or foreign Runs return 404 so resource existence is not disclosed. Workspace grant changes return 403 unless a trusted grant administrator is installed. Linked conversation context fails closed without trusted conversation ownership. Ordinary Workspace configuration endpoints retain their existing separate Workspace administration boundary.

The new tests cover the default-deny resolver, spoofed identity headers, expired sessions, cross-tenant and foreign Run denial, ownerless history, Run owner persistence, grant administration and revision behavior, grant revocation, capability ceilings, linked conversation denial, and authority revalidation. HTTP-path assertions exist in the suite but were not executable in this environment because the installed TestClient stalled before response dispatch, including for `/health`; this is reported as an environment validation limitation rather than a passing result.

## Cloud and local deployment

No deployment is automatically trusted because it is local or uses loopback. A production deployment must inject a server-side verifier that validates its configured identity protocol, an exact-session validity adapter, a tenant mapping, an explicit grant-administration adapter, and (for linked conversations) a conversation-owner adapter. Provider secrets and session credentials must remain in the authentication adapter and must not be put in principal fields, logs, API responses, model context, or Run events.

The same AVA-owned contracts are provider-independent for personal installations, OIDC/Entra, AWS-aligned, and approved Databricks authentication. This phase implements no provider SDK, credential exchange, enterprise administration UI, or cloud resource adapter.

## Readiness levels

| Readiness level | Phase 6.14A result |
| --- | --- |
| Provider-independent contracts | Implemented: principal, validity, conversation access, grant, and authority contracts |
| Test-only trusted authority | Implemented in isolated tests and test-only suite adapter |
| Configured production authentication | Not configured; factory defaults return unavailable/deny |
| Operational execution authority | Issuer and revalidation path implemented, but requires trusted deployment adapters, active grants, Workspace configuration, and enabled features |
| Production tool dispatch | Disabled: app composition supplies no executors; memory reservations are not durable |

The presence of an authority issuer or grant does not itself execute a tool. No production executors are installed, no production dispatch is enabled, and no new file or shell operation is activated.

## Validation results

Completed locally:

- Ruff: `backend/.venv/bin/ruff check --no-cache src tests` — passed.
- Strict mypy target: `backend/.venv/bin/mypy --cache-dir=/tmp/ava-mypy-cache src/ava` — passed, 301 source files.
- Identity/grant/authority focused unit tests — 5 passed across targeted selections.
- Migration and Phase 5.83 migration certification tests — 39 passed.

Not completed:

- The complete Phase 6.14A/API lifecycle and inspection suite: synchronous `TestClient` hung before any response, even on `/health`; focused API test totals are therefore unavailable.
- Full Phase 6.6/6.8/6.10/6.12/6.13 regression suite and architecture guards: not rerun in this turn.
- Frontend/API-client checks and Web/Desktop builds: no frontend contract changed.
- Windows/Linux GitHub Actions: workflow paths were extended for the new portable security test, but Actions was not triggered and no native runner results are available.

The backend virtual environment also could not acquire its default uv/cache lock under the current worktree permissions. Direct tools ran with cache output redirected to `/tmp` where supported.

## Known limitations and deployment prerequisites

- No concrete production authentication provider or session revocation store is configured.
- No trusted Workspace grant administrator is configured; grant administration is unavailable by default.
- Existing conversation ownership is not represented in the current model, so linked conversation Runs fail closed until a trusted adapter or durable ownership model exists.
- Ownerless historical Runs remain inaccessible through protected APIs pending provenance-based migration.
- Current invocation arguments are not stored in an encrypted durable snapshot; pending approval cannot safely resume across process restart.
- The authority context-handle map is process-local and bounded; it is intentionally not treated as a durable token.
- Production tool executors are absent and dispatch remains disabled. Durable reservations alone would not make execution safe or operational.
- HTTP route behavior needs a rerun in a compatible test environment, followed by the full security regression matrix and native Windows/Linux workflow.

## Phase 6.14B readiness

The contract and fail-closed authorization foundation is ready for Phase 6.14B implementation work, subject to the validation limitation above. Phase 6.14B must add the durable, protected current-invocation snapshot and reconstruction path required by the phase plan, then prove exact invocation matching after restart. Production authentication, administrator provisioning, linked conversation ownership, remaining security acceptance, and dispatch remain gated; this report does not authorize or activate production execution.

## Certification review — 2026-10-14

### HTTP test stall investigation

The original stall was reproduced with explicit timeouts and isolated from AVA. It occurs in the installed local AnyIO/Starlette test stack:

- `TestClient` blocks during lifespan startup for a minimal FastAPI app, before route execution.
- An async ASGI client against a minimal app succeeds for an async endpoint, but hangs for a synchronous endpoint when FastAPI dispatches through AnyIO's worker pool.
- A standalone `anyio.to_thread.run_sync()` call also hangs. Its worker thread waits on the AnyIO queue while the event-loop thread remains in the selector; plain `threading.Thread` and `asyncio.to_thread()` complete.
- The same `/health` stall reproduces against the clean `main` checkout at `32b2a27`, whose endpoint and composition predate Phase 6.14A. The app factory completes before the request stalls.

This evidence points to the local AnyIO worker/test-client environment, not AVA startup, SQLite migration/locking, authentication dependency construction, or the Phase 6.14A API routes. The native Windows and Linux Actions runs subsequently executed the HTTP cases successfully, including health, capabilities, protected Run routes, and the Phase 6.14A authorization matrix. No production bypass or application workaround was added.

### Security and specification review

The review confirmed the intended separation among verified identity, Run/Workspace authorization, authority issuance, and invocation resolution. New Run owners are set by the authenticated API dependency, persisted in migration 0029, and checked on Run reads, lists, events/SSE, inspection, cancellation, and retry. Historical ownerless Runs remain inaccessible through protected APIs. Workspace grants are revisioned and tenant-scoped, capability ceilings are checked against the Workspace configuration, administrative changes default to deny, and revocation/stale revisions invalidate authority. Root paths are omitted from non-administrator Workspace projections.

Authority resolution reloads the current Run, session validity, grant, Workspace configuration/resolver, and feature state. Tool execution checks authority and policy again before reservation and refuses missing executors or non-durable reservations. No model, runtime, client field, or frontend setting can issue the authority. No production provider, grant administrator, or executor is configured, so production dispatch remains disabled.

The review also found that a trusted HTTP principal could request a globally configured Workspace through the legacy OpenHands tool factory, which does not yet apply this principal's grant or narrow global Workspace permissions. Run creation and context preview now reject all Workspace-bound requests with 503 until the runtime path enforces principal-scoped authority. This deliberately keeps the legacy path unavailable to authenticated Runs without migrating OpenHands tools in Phase 6.14A. Revoked grants are now terminal at the service boundary; restoring access requires a new grant rather than reactivating a revoked record.

The review found one credential-handling hardening gap: `authentication_context_ref` accepted arbitrary strings even though Run persistence retains that value for exact-session revalidation. It now requires a 64-character lowercase hexadecimal opaque digest; a regression test rejects a raw session-shaped string. Production authentication adapters must derive that reference with a keyed digest/HMAC of the provider session identifier and keep the original credential out of AVA contracts and persistence.

The exact invocation remains process-local. Approval validation rejects a missing or mismatched current invocation, and pending requests cannot safely resume after restart. No raw arguments are present in routine approval projections. Durable protected snapshots remain assigned to Phase 6.14C in the production prerequisite register.

### Corrective changes and regression findings

The persisted grant adapter and migration 0029 were added to architecture guard expectations. The guards now permit the adapter's Pydantic validation import, assert the grant table and indexes, include the grant repository in composed persistence ports, and expect migration version 29. Existing lifecycle test doubles and API expectations were updated for owner propagation and indistinguishable 404 handling. The review found and closed the conditional legacy OpenHands Workspace bypass described above; no normalized executor or production dispatch was enabled.

The first local core regression run reported 208 passes and four architecture-guard failures; those failures were stale pre-6.14A expectations and were corrected. The first native matrix exposed twelve stale persistence/runtime fixtures plus the missing conversation-list authorization check. A later Linux run exposed seven filesystem fixtures that lacked the new trusted Run owner and Workspace binding; those fixtures were corrected without weakening the authority checks.

### Standards and platform validation

Ruff and strict mypy passed locally after the credential-reference and grant-lifecycle fixes. Local focused results: 39 migration and Phase 5.83 certification tests passed; 131 architecture guards passed; 39 tool-policy tests passed; 14 ToolExecutionService tests passed; 6 runtime bridge tests passed; and 5 direct identity/grant/authority tests passed. The grant-revocation terminal test was rerun after the fix and passed. These are 234 passing unique test cases across those selections. Bounded Run-attempt/lifecycle batches and HTTP tests did not complete locally; runs stalled without progress and were terminated at their timeout. The HTTP stall reproduces on a minimal app and the clean main checkout as described above.

Native GitHub Actions run [38603365540](https://github.com/cliski1978-hub/AVAPython/actions/runs/38603365540) passed on commit `2ed4ea657fc8f05632ca50f868a14b90e161a4c1`. The `ubuntu-22.04` job passed 517 shared tests, 13 Linux adversarial filesystem tests, Ruff, and strict mypy. The `windows-2025` job passed the native NTFS fixture-capability check, 517 shared tests, 3 Windows filesystem security tests, and Ruff. The shared tests include HTTP health/capabilities and authorization cases. No test failures remain in this certification run. The workflow uses `contents: read`, pins checkout/setup-python actions by commit, and does not request secrets or write permissions. The repository is public as previously authorized; the owner may change its visibility separately.

The standards review found no ADR conflict. It recorded two judgment-call smells: owner snapshot fields are passed individually through lifecycle/persistence layers, and similar grant-route exception mappings are repeated. The domain guide also requires new domain vocabulary to be added to `CONTEXT.md` or the gap noted for domain-modeling; this certification records that vocabulary follow-up rather than changing the locked canonical plan. Neither smell is a tooling violation or a confirmed acceptance/security defect.

### Prerequisite assignments and readiness

The editable production integration addendum now assigns production identity validation to Phase 6.14D; trusted grant administration to Phase 6.14B or a preparatory integration step before 6.14D; conversation ownership to Phase 6.14B before 6.14D; and protected durable exact-operation snapshots to Phase 6.14C. Each remains explicitly incomplete and blocks the corresponding production activation path.

Phase 6.14A certification is **ACCEPTED** for this checkpoint: the HTTP authorization tests executed, both native operating-system jobs passed, identified defects were corrected, the four future prerequisites have explicit assignments, and the worktree is committed. Phase 6.14B may begin as a separate task. Its runtime integration must preserve the fail-closed Workspace boundary before any Workspace-bound execution is enabled. No Phase 6.14B implementation was started here. Production tool dispatch remains disabled, and the four production prerequisites continue to block activation.
