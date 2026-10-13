# AVA Phase 6.3 — Tool Registry

Date: 2026-10-12  
Status: implemented; focused checks passed, broader baseline exception recorded.  
Next: Phase 6.4, only after explicit owner authorization.

## Scope and implementation

Implemented an in-process AVA-owned catalog using the actual Phase 6.2 `ToolDefinition`. No competing definition model or contract change was needed. The [master plan](AVA_MASTER_CANONICAL_DEVELOPMENT_PLAN_LOCKED.md), [Phase 6 outline](AVA_PHASE_6_IMPLEMENTATION_OUTLINE.md), [6.1 audit](AVA_Phase_6_1_Architecture_Audit.md), [6.2 contracts](AVA_Phase_6_2_Normalized_Tool_Contracts.md), and established Workspace/runtime security boundaries govern this bounded step. Locked planning documents were not changed.

Files changed for this step:

- `backend/src/ava/tools/registry.py`: `ToolRegistry`.
- `backend/src/ava/tools/__init__.py`: package export.
- `backend/src/ava/infrastructure/composition.py`: `create_tool_registry()` factory.
- `backend/src/ava/api/app.py`: constructs one registry per application as `app.state.tool_registry`.
- `backend/tests/test_tool_registry.py`: focused validation, copy isolation, concurrency, composition and security tests.
- `backend/tests/test_architecture.py`: one additive catalog/runtime dependency guard.
- This report.

The working tree already contained extensive Phase 5/6.2 changes. Those were preserved; the full Git diff of a touched existing file is not the diff of this step alone.

## Public Python interface

Import `ToolRegistry` from `ava.tools` or `ava.tools.registry`.

| Operation | Behavior |
| --- | --- |
| `ToolRegistry()` | Creates an empty independent catalog and a private synchronization lock. |
| `register(definition: ToolDefinition) -> None` | Requires an AVA definition, revalidates its dumped fields through the existing contract, stores a detached snapshot, and rejects a duplicate tool ID. |
| `get(tool_id: str) -> ToolDefinition \| None` | Returns a deep copy of the registered definition; an unknown ID, including an unregistered path-like string, returns None. Lookup does not interpret paths. |
| `list() -> list[ToolDefinition]` | Returns all metadata as detached snapshots, sorted lexically by stable tool ID. Ordering is independent of insertion/thread scheduling. |
| `discover(*, capabilities=(), category=None) -> list[ToolDefinition]` | Filters definitions that declare **all** requested `ToolCapability` values and match the optional `ToolExecutionCategory`. Filters intersect; empty capabilities means no capability filter. Ordering matches list(). Non-AVA filter values reject with ValueError. |

Discovery is descriptive. A declared capability query is not a runtime compatibility check, permission lookup, enabled-tool list or approval check. Required capabilities describe requirements, not grants.

Every existing definition field is retained: ID, name, description, transport contract version, tool version, input/output schemas, declared capabilities, risk, approval requirement and execution category. Schema compatibility is exactly Phase 6.2's supported subset; no instance-schema validation, remote schema fetching, dynamic imports or plugin loading occurs.

## Registration, duplicates and ownership

Trusted application composition/bootstrap owns registration. The registry does not authenticate Python callers; its ownership boundary is dependency placement and absence of a public registration endpoint. Runtime modules neither import nor receive it. Untrusted requests/configuration must not be passed into a future registration loop.

Production composition currently registers **no definitions** because no normalized handlers exist. Tests and the example below demonstrate explicit registration using fixtures. The empty catalog does not change OpenHands' existing adapter-local tools or Native execution; it does not claim those tools have been normalized.

Only one definition per stable ID is accepted. Re-registering the same value, or a different version under the same ID, raises ValueError. There is no replace/update/unregister/clear API. Changing the catalog currently means rebuilding composition; no persisted registry or dynamic configuration behavior was introduced. Normal application object lifetime owns cleanup.

Malformed contract objects, including instances created with `model_construct`, unchecked `model_copy` edits or mutated nested schemas, are revalidated. Invalid identity/version/schema/capability rejects before insertion, leaving the catalog unchanged. Incorrect argument types reject with TypeError. Serializer warnings are suppressed during the dump because the contract immediately performs actual validation; invalid values are not accepted or silently downgraded.

## Immutability and concurrency guarantees

Phase 6.2 frozen models contain mutable JSON dictionaries/lists. The registry therefore revalidates into newly owned containers at registration and deep-copies every get/list/discover response. Edits to the original definition, a returned nested property/required list, or the returned collection cannot alter registry state. Consumers can mutate their detached snapshots; they are not live catalog objects.

A lock protects catalog insertion, duplicate checks, lookup and snapshot construction. Concurrent readers observe ordered consistent snapshots; racing registrations of the same ID have exactly one winner. Returned objects do not share nested schemas with each other or with stored definitions. Registration validation happens before the insertion lock; callers must not mutate their input concurrently while it is being validated. There is no claim of distributed/multi-process catalog synchronization or defense against malicious Python access to private attributes.

## Security and composition boundaries

Registration and discovery provide no enablement, Workspace authority, approval, executor or handler. The future effective tool set remains the intersection of registry metadata, feature gates, allowlist, Workspace/resource authorization and execution policy, computed by later services. This registry implements only the descriptive first component.

Workspace/model/runtime identities, credentials, command runners, permission booleans and execution contexts are not registry inputs. No use-case entities or assigned Workspace behavior were introduced. Existing `RunService -> AgentPort`, independent runtime/model/provider selection and tool capability-versus-permission separation remain intact.

`create_tool_registry()` follows the existing composition pattern and returns a fresh empty registry. `create_app()` stores it on application state without a lifespan task, network call, persistence adapter, registration API or runtime injection. Later AVA-owned services can receive this shared instance through constructor injection, as existing discovery services receive AVA-owned catalogs. No additional consumer/service was invented for this step.

The new architecture guard restricts the tool package to stdlib catalog/synchronization dependencies and AVA tool contracts/registry, rejects async execution and forbids agent/runtime imports of the catalog. Existing architecture guards remain active. Later execution integration must supply a narrow invocation port rather than let an SDK register tools into the authoritative catalog.

## Example — test fixture, no executable tool

```python
from ava.contracts.tools import ToolDefinition
from ava.tools import ToolRegistry

registry = ToolRegistry()
fixture = ToolDefinition(
    tool_id="example.read",
    name="Example read",
    description="Metadata fixture only; no handler exists.",
    tool_version="1.0.0",
    input_schema={"type": "object"},
    output_schema={"type": "object"},
    required_capabilities=("file_read",),
    risk="low",
    execution_category="deterministic",
)
registry.register(fixture)
assert [item.tool_id for item in registry.list()] == ["example.read"]
assert registry.get("example.read") == fixture
assert registry.get("unknown.read") is None
# Registration did not execute or authorize a file read.
```

## Validation

Executed from `backend/` with bytecode and pytest cache writes disabled:

| Check | Actual result |
| --- | --- |
| Registry + Phase 6.2 + full architecture + existing contracts, tool authorization/audit and command policy suites | **346 passed**, final focused run. |
| Broader run adding model/provider/runtime catalogs, runtime resolver and relational composition | **395 passed, 1 failed in 3.19s**. Existing model-profile field assertion described below. |
| `.venv/bin/ruff check src tests --no-cache` | **PASS**, full backend source/tests. |
| `.venv/bin/mypy src tests/test_tool_registry.py --cache-dir /tmp/ava-phase63-mypy` | **PASS**, 255 source/test files. |
| Formatter check for `src/ava/tools` and new registry tests | **PASS**. Existing composition/API/architecture files were not mass-formatted. |
| `git diff --check` | **PASS**. |

Focused command:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_tool_registry.py tests/test_tool_contracts.py tests/test_architecture.py \
  tests/test_contracts.py tests/test_tool_authorization.py tests/test_tool_audit.py \
  tests/test_command_policy.py
```

The broader run adds `test_model_provider_registry.py`, `test_model_registry.py`, `test_runtime_registry.py`, `test_runtime_resolver.py` and `test_relational_composition.py`. Its one failure is `test_model_registry.py::test_profile_carries_no_credential_or_permission_fields`: the exact expected field list omits the pre-existing `context_window_tokens`. This assertion also fails in the temporary pre-registry source baseline created during Phase 6.2, with no `ava.tools` package or Phase 6.3 composition changes (**1 failed in 0.20s**). No unrelated model code/test was changed to hide it.

Tests cover valid registration/all metadata; missing IDs; duplicate/same-ID-new-version rejection; deterministic ordering; capability/category intersection and invalid filters; malformed/unvalidated definitions; nested input and returned-value mutation; independent registries; parallel reads; concurrent duplicate registration; real memory-mode application construction; absence of a public tool route; and proof that catalog registration cannot activate an existing runtime tool without Workspace authority.

No model inference, shell/tool execution, Bubblewrap, TestClient session, developer database, or native GUI was used. Relational tests use temporary fixtures. Full backend/aggregate harness, frontend builds/tests, Python-client suite and GUI acceptance were not rerun; existing TestClient/Bubblewrap/native acceptance limitations and earlier wider-regression exceptions remain tracked. This report does not upgrade them to PASS.

## Deferred work and readiness

No tool dispatcher, handlers, runtime loop/integration, authorization, enabled gates, configuration persistence, approval state/UI, tool history, migrations, use-case configuration, RAG, plugin loading or engineering workflow was implemented.

Phase 6.4 can build persisted false-default feature controls and backend enforcement using this descriptive catalog after owner authorization. Risks carried forward: registration ownership must stay trusted; schemas remain the bounded Phase 6.2 subset; catalog discovery must never become authorization; handler availability must be distinguished from registered metadata; future Workspace/approval policies must revalidate current authority; broader validation is not fully green.

Phase 6.3 is complete within this scope. Phase 6.4 has not started.
