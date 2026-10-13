# AVA Phase 6.9 — Approval Management UI

## Scope and architecture verified

Implemented the shared approval review surface described in the Phase 6.9 brief. The owner-locked canonical plan was read and left unchanged. The checked-in Phase 6 outline still has historical numbering that calls the approval UI 6.8 and tool dispatch 6.9; this implementation follows the owner-approved sequence documented in the Phase 6.8 handoff and the supplied 6.9 brief.

Phase 6.8 provides the durable approval contracts, policy-revalidating lifecycle service, repository adapters, and terminal status model. Its production composition has no trusted human identity adapter, execution-authority issuer, current-invocation resolver, or approval HTTP routes. Reads and decisions therefore cannot be safely connected to production today. Run and conversation associations are optional stable references; run lifecycle remains independent, and the Run Inspector has no approval lifecycle event source to inspect.

## Components and navigation

- Added the shared `@ava/approvals-core` package with `ApprovalsWorkspace`, pending and history lists, safe detail presentation, terminal status labels, and confirmation UI.
- Added the Approvals destination at `/approvals` to shared primary navigation. `@ava/workspace` composes the same surface for Web and Desktop and keeps it mounted after first visit using the existing shared-pane convention.
- The production route has no configured data source and clearly reports that the approval service is unavailable. It creates no local, demo, or persistent approval records.
- Presentation is responsive and uses shared semantic theme tokens/classes. Pending and historical items remain separate; run, conversation, and workspace context is displayed only when supplied in the authorized projection.

## Presentation and API boundary

The package defines minimal presentation projections for list items, detail, history, status, and decision availability. They do not mirror backend authority revisions, principal references, Workspace roots, raw arguments, credentials, or repository records. A future `ApprovalDataSource` seam is injectable for tests and secure backend integration.

No approval routes, API-client wrappers, authentication system, or backend capability were added. An adapter must provide backend-scoped and disclosure-safe records and backend-derived decision availability. Without it, the interface is unavailable or read-only. Unauthorized responses are rendered separately from an empty queue.

## Decision controls and state handling

Pending items show Approve and Deny controls, disabled unless the projection says the authenticated principal may decide. The UI also checks expiry locally and fails closed for missing or malformed expiration timestamps; the backend remains authoritative and must revalidate every decision. Consequential approvals use AVA's shared modal confirmation. A decision is reported as successful only after the backend returns the matching terminal approval record. Duplicate submissions are guarded; conflicts and expiry refresh the queue without a success state. Denial is presented as an approval outcome, not as failed tool execution. The UI has no tool execution or run-continuation method.

Loading, unavailable, unauthorized, empty, and generic error states are distinct. Retry uses the current data source. Superseded loads and post-decision refreshes are ignored when their source generation is stale. History has no actionable controls.

## Security and disclosure

The UI consumes display projections only. It never accepts client role flags or constructs approval identities, persists frontend approval records, executes tools, or exposes the raw Phase 6.8 record. Sensitive or unauthorized fields are not rendered, including extra fields present on an object at runtime. The default production route cannot enumerate approval records because it performs no request to an approval endpoint.

## Tests and validation

Added focused tests for unavailable/no-record behavior, pending/details, history, decision authority, expiration, safe disclosure, loading/error/unauthorized/empty states, stale responses, duplicate submissions, confirmed decisions, rejected decisions, and shared Web/Desktop composition. Navigation tests now include Approvals.

Validation status:

- `pnpm install --lockfile-only --offline`: passed; workspace lockfile includes the new package.
- `git diff --check`: passed.
- Frontend tests, TypeScript validation, lint, and Web/Desktop builds: **not run**. The local workspace package links point to a missing root `.pnpm` installation; invoking pnpm attempted to fetch the dependency graph, but registry DNS/network access is unavailable. The attempt was stopped without changing source or dependency state beyond the lockfile-only workspace metadata update.
- No backend route or contract changed, so backend security suites were not applicable to this implementation.

## Limitations and Phase 6.10 readiness

The UI is ready to accept a future authorized data source, but production queue retrieval and decision submission remain unavailable until trusted human identity/scope and protected approval endpoints exist. This phase deliberately does not add those authorities. The shared navigation, presentation types, list/detail/history, confirmation, disabled controls, and error handling are ready for later wiring. Phase 6.10 may continue within its own scope; it must not treat the UI's decision display as execution authority or invoke a tool directly from React.

Phase 6.9 is complete. No Phase 6.10 work was started.

## Frontend Validation and Deferred Integration Acceptance

### Dependency restoration

The environment reports Node.js **v24.21.0** and pnpm **12.4.1**. The prescribed command was run:

```text
pnpm install --offline --frozen-lockfile
```

pnpm verified that the lockfile is up to date and skipped dependency resolution, but installation stopped with `ERR_PNPM_NO_OFFLINE_TARBALL`: `@types/prop-types@15.7.15` is absent from the local store. The frozen install did not change the lockfile or upgrade package versions. A registry fetch is not available: pnpm reports DNS lookup failures for `registry.npmjs.org`. TLS settings and registries were not changed.

### Frontend validation results

The Approval UI suite could not start. The attempted command was `pnpm --offline --filter @ava/approvals-core test`; pnpm tried downloading missing packages and emitted registry DNS failures before Vitest ran, so the attempt was stopped. Therefore no frontend test count, failure count, or skip count is available; the suite did not execute.

The following repository scripts remain **blocked and unexecuted** for the same missing dependency installation:

```text
pnpm --filter @ava/approvals-core test
pnpm --filter @ava/workspace test
pnpm --filter @ava/contracts test
pnpm --filter @ava/api-client test
pnpm --filter @ava/settings-core test
pnpm test
pnpm -r lint
pnpm --filter @ava/web build
pnpm --filter @ava/desktop build
```

Frontend architecture tests are included in those package suites and were not executable either. Source inspection confirmed the new package has no direct `fetch`, browser storage, API call, tool-dispatch call, or execution method; the existing shared shell still composes `@ava/workspace` for both Web and Desktop. `git diff --check` passed. No frontend runtime result is claimed.

Review while preparing validation found two issues before execution: the test fixture's pending approval had an expiration time that could be in the past when the suite ran, and the UI used one generic conflict/expiry message while its expiry regression expected the explicit expired message. The fixture now uses a stable future expiration, and the UI preserves distinct expired and conflict messages. These corrections remain unverified by Vitest because dependencies could not be restored.

### Backend security verification

Executed:

```text
cd backend
PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_approvals.py tests/test_architecture.py
```

Result: **145 passed in 2.22s**.

Source inspection confirms that the production app registers no approval router or approval HTTP endpoint. It composes `ApprovalService` with `execution_authority=None`; absent a supplied decision-authority port, the service uses `DenyApprovalDecisionAuthority`. The frontend has no approval identity generator, human-authority field, or tool-execution call. Phase 6.8 continues to treat an approval as a historical record; `remains_valid` is a boolean revalidation result, not an execution grant. No backend production files were changed in this validation step.

### Acceptance classification

- **Frontend Implementation Acceptance: PARTIAL.** The UI implementation and focused tests are present, but the required test, type, lint, and build checks remain blocked by the unavailable dependency tarball and registry DNS failure. There is no confirmed unresolved frontend regression; runtime validation is pending.
- **End-to-End Approval Acceptance: DEFERRED — Awaiting secure Approval API, trusted authority, normalized dispatch, and runtime integration.** No operational approval workflow was attempted.

Deferred acceptance must cover the complete sequence from agent tool request through policy evaluation, durable approval, authorized retrieval, human decision, exact-operation revalidation, execution or continued blocking, persisted tool result/history, and correct run continuation or termination. Schedule that work for later Phase 6 execution/lifecycle steps, with final security acceptance in Phase 6.15.

### Phase 6.10 readiness

Phase 6.9 remains ready for Phase 6.10 implementation within its own scope: the shared view and typed adapter seam are available, while production approval data and decisions remain unavailable until trusted backend integration exists. This validation step did not implement Phase 6.10 or any deferred authority, API, dispatch, runtime, or continuation component.
