# AVA Phase 6.2 — Normalized Tool Contracts

Date: 2026-10-12  
Status: implementation and focused validation complete; wider validation exceptions recorded below.  
Next bounded step: Phase 6.3 registry design/implementation, only with explicit owner authorization.

## Scope and authority

Implemented contract values and their validation only. The [locked master](AVA_MASTER_CANONICAL_DEVELOPMENT_PLAN_LOCKED.md), [Phase 6 outline](AVA_PHASE_6_IMPLEMENTATION_OUTLINE.md), [Workspace addendum](AVA_PHASE_6_USE_CASE_WORKSPACE_ADDENDUM.md), [6.1 audit](AVA_Phase_6_1_Architecture_Audit.md), relevant Phase 3 tool/security records and owner-supplied final Phase 5 handoff informed the design. The master's pending approval record and documentation discrepancies identified in 6.1 remain unchanged.

No dispatcher, registry, executor, policy service, API route, runtime integration, feature configuration, approval workflow, UI, dependency, or migration was added. Existing execution behavior and `RunService -> AgentPort` are unchanged.

## Implemented files

- `backend/src/ava/contracts/tools.py`: AVA-owned Pydantic values, enum vocabulary and validation.
- `backend/tests/test_tool_contracts.py`: focused positive/negative/serialization/security tests.
- `backend/tests/test_architecture.py`: one additive guard for the tool contract module's inward imports and absence of async execution/service classes. Existing pre-Phase-6.2 changes in this working-tree file were preserved.
- This completion document.

Import these contracts directly from `ava.contracts.tools`. They are not wired into an existing HTTP API or re-exported through the root contract barrel. No TypeScript/Python-client wire mirrors were introduced: no existing public API boundary now returns or accepts them. When an endpoint or RunEvent integration ships, its applicable mirrors and clients must be added together. The existing published RunEvent/RunStatus vocabulary was not changed prematurely.

## Contract fields and semantics

All values share current `contract_version = "v1"`; a supplied different version is rejected. Unknown top-level fields are forbidden. Models reject field reassignment with Pydantic frozen configuration; nested JSON dictionaries/lists are still mutable values, so freezing is not an immutable authorization snapshot. Future services must canonicalize/copy validated operation data when binding approvals and revalidate before effects.

Tool identifiers are strict lowercase names such as `file.read`, with dot/underscore/hyphen-separated segments and a 128-character maximum. Reference IDs are nonempty strict ASCII opaque identifiers (letters/digits with subsequent dot/underscore/colon/hyphen), maximum 256 characters; slash paths and whitespace are rejected. This syntax check establishes neither ownership nor existence. `tool_version` is a separate opaque definition revision, not the transport contract version or provider/runtime identity.

| Contract | Fields and meaning |
| --- | --- |
| `ToolDefinition` | Required `tool_id`, `name`, `description`, `tool_version`, `input_schema`, `output_schema`, `risk`, `execution_category`. `required_capabilities` defaults to an empty tuple; duplicate declarations reject. `approval_requirement` defaults to `policy`. Definition metadata grants no permission or enablement. |
| `ToolRequest` | Required `invocation_id`, `tool_id`, `tool_version`, `arguments`, `execution_context_ref`. Optional `run_id` and `correlation_id`; no Conversation requirement. Invocation uniqueness/reference ownership must eventually be enforced by trusted services/storage, not by a DTO. |
| `ToolExecutionContext` | Required `context_id`; optional `workspace_id`, `workspace_authorization_ref`, `tool_policy_ref`, `caller_authority_ref`. An authorization reference requires Workspace identity, while Workspace identity alone supplies no authorization. Missing refs default to None; they must never become unrestricted grants. No roots, credentials, permission booleans, model selection or runtime capabilities. |
| `ToolOperationBinding` | Required invocation/tool/version/context identity, 64-character lowercase SHA-256 `operation_digest`, and `authority_revision_ref`. A minimum future approval binding, not ApprovalRequest, ApprovalDecision or approval validation behavior. |
| `ToolExecutionMetadata` | Required context reference; optional Workspace/runtime/model IDs and finite nonnegative duration. Historical/descriptive metadata cannot select a model/runtime or grant access. |
| `ToolResult` | Required invocation/tool/version and terminal `status`; optional structured `output`, existing normalized `ErrorResponse`, opaque `artifact_refs`, execution metadata. Completed requires an object output (empty is valid) and no error. Other unsuccessful outcomes require error, except cancelled may omit it. Failed/cancelled output may describe partial results; it does not change terminal status. |
| `ToolLifecycleEvent` | Required event/invocation/tool/version/context identity, status and timezone-aware timestamp. Optional run/correlation, operation binding and approval reference. Binding identity must match the event. An approval reference always requires a binding; approval-required/approved/expired require both. A revoked fact can exist without prior approval because authority may be revoked before an approval is requested. |

Reuse `JsonValue`, `ErrorResponse`, `ErrorCategory`, `CONTRACT_VERSION` and existing Pydantic conventions. Errors must have nonblank code/message and finite JSON details; public message/details content still requires safe producer redaction. No validator can establish that arbitrary authored text contains no secrets. Artifact refs do not expose physical paths or raw vendor objects.

Arguments/output reject SDK objects, bytes, tuples, non-string JSON keys and NaN/infinity instead of silently coercing them. JSON nesting is bounded to 32 levels. Arguments and output are object-shaped JSON, with nested arrays/primitives allowed. ToolRequest is **validation-ready**: it does not select a definition or validate an instance against that definition's schema in this step.

## Schema declarations

Input and output use an explicitly bounded JSON Schema subset represented as JSON dictionaries. Root schemas must have `type: object`; each nested node declares one type. Supported types: object, array, string, integer, number, boolean, null.

Supported keywords: `type`, `title`, `description`, `properties`, `required`, `additionalProperties` (boolean or supported schema), `items`, `enum`, `minLength`, `maxLength`, `minItems`, `maxItems`, `minimum`, `maximum`.

Validation rejects unknown keywords/types; malformed nested schemas; non-string/duplicate/undeclared required names; arrays without items; constraints on incompatible types; invalid bound types, negative length/item bounds and reversed bounds; empty/non-list enum declarations; and non-JSON/non-finite schema values. `enum` values must be JSON but this phase does not prove schema satisfiability or validate instances against enum/type constraints.

References, remote schemas, `$schema`, composition keywords, patterns and custom/executable validators are unsupported and rejected, not silently ignored. No full JSON Schema conformance claim or external validator dependency is made. A future justified schema expansion must explicitly revise validation/tests/compatibility; the registry should not assume arbitrary Draft 2020-12 schemas are accepted.

## Enum vocabulary and lifecycle

- `ToolCapability`: file_read, file_write, file_delete, command_execution, network_access. These are required technical capabilities, not authorization grants or proof of an implementation.
- `ToolRisk`: low, medium, high, critical. Metadata does not replace action/argument-sensitive risk assessment, especially command-mediated mutation.
- `ToolApprovalRequirement`: policy or required. There is deliberately no `never`/approval-disable grant. Policy may impose stricter approvals; required describes a minimum, not a completed approval.
- `ToolExecutionCategory`: deterministic, agentic, hybrid. Independent from runtime and model identities and from Plan/Work authority.

`ToolStatus` covers requested, approval_required, approved, denied, started, completed, failed, cancelled, expired, revoked, interrupted, indeterminate. `TERMINAL_TOOL_STATUSES` is one shared set for results: completed/failed/denied/cancelled/expired/revoked/interrupted/indeterminate.

Interpretation for future lifecycle services:

| State | Meaning / limitation |
| --- | --- |
| requested | Intent received, not authorization. |
| approval_required | Specific bound operation requires a decision; no execution permission yet. |
| approved | Descriptive decision fact with matching approval/binding references; current policy still needs rechecking. |
| denied | Policy or human denial; may precede any approval record. |
| started | Execution began; construction of this event does not execute or authorize it. |
| completed / failed / cancelled | Terminal action outcome. Cancellation is not proof that a prior side effect was undone. |
| expired | Bound approval lifetime ended; requires approval identity/binding. |
| revoked | Authority/approval was withdrawn; can occur without a previous approval. |
| interrupted | Execution ownership was lost; producers must not use it to assert a known outcome where effects are uncertain. |
| indeterminate | Effects/outcome cannot be established after interruption; must not be automatically replayed. |

There is no transition table, sequence allocator, timestamp/ID generator, event emission, persistence or startup reconciliation. Lifecycle events are standalone typed values, not new emitted RunEvents. Run pause/resume and pending approvals remain future decisions: the existing running->waiting restriction and startup failure policy were not altered.

## Approval and security design decisions

1. **Reference identity is not authority.** ToolRequest supplies a context reference, never permission fields. Context describes references only. Future services must resolve trusted server records, verify caller ownership/provenance/revocation and deny missing authorization. Objects reconstructed from clients remain untrusted.
2. **Bind the exact validated operation.** The future digest must cover canonical validated arguments, resource identities/expected revisions, invocation/tool/version/context, and authority revision state. `authority_revision_ref` denotes the combined immutable authority snapshot (including relevant Workspace assignment, tool policy/gates and caller scope). Canonicalization, snapshot storage and digest generation/matching are deferred; accepting a syntactically valid digest is not approval proof.
3. **No permissive approval fallback.** Definitions declare policy/required metadata. Approval-related event consistency is validated, but administrative identity, decision authentication, expiry and revalidation are not implemented. A fabricated approved event cannot be used as an executable grant.
4. **Recovery needs uncertainty.** Interrupted and indeterminate preserve the distinction between lost execution and unknown effects. Services must not promise exactly-once external mutation from these values or retry indeterminate actions automatically.
5. **No runtime-security coupling.** Contracts import only stdlib, Pydantic and inward AVA contracts. Existing WorkspacePermissions, ToolAuthorizationPolicy, command/sandbox ports, SDK types and RunService remain independent. Context authority references prepare fixed administrator-assigned Workspace scope and narrowing allowlists without use-case entities.
6. **Standalone operations are possible.** Run identity is optional; future structured UI actions can carry the same normalized request without a chat conversation. This introduces no action endpoint.

Unresolved beyond 6.2: concrete schema-instance validation engine; canonical digest encoding and trusted authority snapshot schema; local administrator authentication before enterprise identity; Workspace provisioning/revocation; descriptor/race-safe filesystem access; command-risk policy; approval continuation/restart semantics per runtime; durable action claims/side-effect reconciliation; retention/redaction and output limits/budgeting. These remain deny-first future implementation decisions, not implicit capability grants.

## Example — values only, no execution

```python
from ava.contracts.tools import ToolDefinition, ToolRequest, ToolResult

definition = ToolDefinition(
    tool_id="file.read",
    name="Read file",
    description="Read an authorized resource through AVA.",
    tool_version="1.0.0",
    input_schema={
        "type": "object",
        "properties": {"resource_id": {"type": "string"}},
        "required": ["resource_id"],
        "additionalProperties": False,
    },
    output_schema={"type": "object", "properties": {"text": {"type": "string"}}},
    required_capabilities=("file_read",),
    risk="low",
    execution_category="deterministic",
)
request = ToolRequest(
    invocation_id="inv-1", tool_id=definition.tool_id, tool_version=definition.tool_version,
    arguments={"resource_id": "resource-1"}, execution_context_ref="ctx-1",
)
result = ToolResult(
    invocation_id=request.invocation_id, tool_id=request.tool_id, tool_version=request.tool_version,
    status="completed", output={"text": "Example content only"},
)
# These are example records. No file read, permission check or execution occurred.
```

## Validation and limitations

Executed from `backend/`, with pytest bytecode/cache writes disabled:

| Gate | Actual result |
| --- | --- |
| New contracts + full architecture + existing contracts/tool authorization/audit/command policy: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_tool_contracts.py tests/test_architecture.py tests/test_contracts.py tests/test_tool_authorization.py tests/test_tool_audit.py tests/test_command_policy.py` | **326 passed in 2.41s**, no warnings. Covers valid/invalid definitions/schemas/arguments/results, all lifecycle states, JSON round trips/generated schemas, extra-field grant rejection, references, timestamps, approval-binding identity, finite JSON/limits, and existing boundaries. |
| `.venv/bin/ruff check src tests --no-cache` | **PASS** across backend source/tests. |
| `.venv/bin/ruff format --check src/ava/contracts/tools.py tests/test_tool_contracts.py` | **PASS**, both new files formatted. Existing architecture file was not mass-formatted. |
| `.venv/bin/mypy src tests/test_tool_contracts.py --cache-dir /tmp/ava-phase62-mypy` | **PASS**, 253 source/test files checked. |
| Existing execution-selection/run-service/run-events/run-lifecycle regression subset | **109 passed, 3 failed in 0.99s**. Failure classification below; no unrelated test or production fix made. |
| Temporary baseline, same regression subset, new tools.py absent and no new guard/test added | **109 passed, same 3 failed in 1.10s**. Confirms those failures pre-exist Phase 6.2. |
| Wider combined run including Native agent HTTP tests | Incomplete; showed the three failures and was interrupted after progress stopped, exit 130. No final totals claimed. |
| Isolated `timeout 25s ... pytest -x -q ... tests/test_native_agent.py` | Incomplete, exit 124 after five displayed passes before the HTTP TestClient cases. Consistent with the known TestClient environment limitation; no new stack-level portal diagnosis or full Native pass is claimed. |
| `git diff --check` | **PASS**. |

The three reproducible unrelated failures are:

- `test_execution_selection.py::test_existing_project_conversation_uses_current_default_and_persists_each_run`
- `test_run_service.py::test_start_run_generates_ava_owned_run_id`
- `test_run_service.py::test_cancel_run_delegates_to_agent`

Existing `_SelectionAgent` / `StubAgent` test implementations do not accept `resolved_execution`, which the current AgentPort default streaming implementation forwards. Two fail with TypeError; the cancellation test observes no captured run because the task fails first. Baseline comparison copied unchanged source/tests under `/tmp`, removed the new tool contract module, and retained the original repository layout/frontend status union needed by lifecycle tests. Developer source/data were not reset or changed for comparison.

No Bubblewrap execution was needed or rerun: these contracts do not dispatch commands. Full backend aggregate/`test_all.sh`, frontend suites/builds, Python-client suite and native GUI acceptance were not rerun. No existing frontend/client/API payload changed; the Native HTTP timeout and independent regression failures prevent claiming full-stack green certification. Earlier Phase 5 evidence remains documentary evidence.

The audit's scope-sensitive architecture protections remain in force, including no approvals/migrations in the Phase 5 schema and no direct runtime imports of services/repositories. The new guard adds protection rather than relaxing those restrictions.

## Completion and Phase 6.3 readiness

Phase 6.2's contracts and focused validation are complete. Phase 6.3 can begin with trusted registry/discovery work against these definitions after owner authorization. Registry acceptance must treat registration/schema metadata as declarations, not enablement or permission; unsupported schema features must reject explicitly.

Existing wider-suite failures, TestClient/native acceptance gaps and 6.1 security/design debt remain visible. No claim is made that AVA can execute a normalized tool or approve a privileged operation yet. Phase 6.3 has not started.
