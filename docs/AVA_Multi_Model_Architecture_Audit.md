# AVA Multi-Model Architecture Seam Audit

Status: **AUDIT ONLY — no multi-model subsystem implemented.**
Scope: Phase 3 Step 37.
Baseline: Steps 32–36 (runtime / tool security hardening) and the verified
`498 passed, 2 skipped` backend state.

## 1. Purpose

Determine, before any Model Registry is built, which seams of the planned
multi-model foundation already exist in the codebase, which are partial, and
which are missing — and confirm that the Step 32–36 security invariants still
hold. This document is a factual map of the current code, not a design proposal.

## 2. Target foundation (the thing being audited toward)

The planned multi-model foundation separates three concerns that must never
collapse into one another:

| Concern | Responsibility | Explicitly NOT responsible for |
| --- | --- | --- |
| **Model Registry** | Descriptive facts: which models exist, nominal capabilities, measured qualifications, hosting location, availability. | Permission grants (`allow_shell`, `allow_write`, `allow_network`, `workspace_permissions`, `sandbox_limits`); selection policy. |
| **Model Orchestrator** | Selection policy: which model/profile an execution uses, fallback/phase-aware routing. | Permission grants; residency/load/unload; being a security authority. |
| **Resource Manager** | Physical residency: GPU/RAM, load/unload, leases, accounting. | Descriptive metadata; security policy. |

Two invariants frame the audit:

- Declared `ModelCapabilities` (e.g. `tool_calling=True`) is a **claim**, distinct
  from a **measured** qualification for a given runtime workflow.
- Model/provider/profile selection can influence *whether* an operation is
  attempted but can never *authorize* it. `runtime capability != permission`,
  `model qualification != permission`, `tool availability != operation
  authorization`.

## 3. Method

Static inspection of the backend runtime/model/execution layers, contracts,
composition, services, API routes, public clients, frontend contracts, and the
training/deployment artifacts. Seams are classified:

- **EXISTS** — real, wired, tested boundary.
- **PARTIAL** — boundary exists but is placeholder, single-valued, or conflated.
- **MISSING** — no code representation.

## 4. Seam inventory

| # | Seam | Status | Primary location |
| --- | --- | --- | --- |
| 1 | Model provider port | EXISTS | `models/contracts.py:25` |
| 2 | Provider registry (container) | EXISTS | `models/registry.py:18` |
| 3 | Provider resolver | EXISTS | `models/resolver.py:46` |
| 4 | Provider adapter (protocol) | EXISTS | `models/providers/openai_compatible/provider.py:144` |
| 5 | Provider↔model cardinality | PARTIAL | one provider instance == one model |
| 6 | Runtime port | EXISTS | `runtimes/contracts.py:31` |
| 7 | Runtime registry / resolver | EXISTS | `runtimes/registry.py`, `runtimes/resolver.py` |
| 8 | Provider→runtime binding | EXISTS | `models/bindings.py:10` |
| 9 | Model metadata / capabilities | EXISTS | `contracts/models.py:56` |
| 10 | Runtime metadata / capabilities | EXISTS | `contracts/runtimes.py:23` |
| 11 | Measured qualification | EXISTS | `runtimes/qualification.py` |
| 12 | Qualification persistence / lookup | MISSING | (live trials only) |
| 13 | Model identity | PARTIAL | provider-scoped `model_id` |
| 14 | Hosting mode | MISSING | docs only (`06-local-model-support-strategy.md`) |
| 15 | Execution profiles | PARTIAL | `services/execution_profile_service.py` |
| 16 | Auto routing | PARTIAL | `execution/routing.py`, `execution/selector.py` |
| 17 | Multi-model configuration | PARTIAL | `configuration/settings.py` |
| 18 | Public API surface | PARTIAL | no `/models`; `/model-providers` only |
| 19 | Frontend execution controls | EXISTS | `frontend/.../ExecutionControls.tsx` |
| 20 | Training / deployment artifacts | EXISTS | `training/deployment/` (not code-linked) |

## 5. Stage 1 — Provider seam

**Status: EXISTS.** The provider layer is a clean, framework-neutral port with a
pure container registry and an exact-id resolver.

- `ModelProviderPort` (`backend/src/ava/models/contracts.py:25`) exposes
  `name()`, `health()`, `get_model_info()`, `get_capabilities()`, `generate()`.
  SDK types never escape adapters.
- `ModelProviderRegistry` (`backend/src/ava/models/registry.py:18`) is a pure
  container: no provider logic, no vendor imports, insertion-ordered.
- `ModelProviderResolver` (`backend/src/ava/models/resolver.py:46`) resolves an
  exact id and raises AVA-owned `UnknownModelProviderError`.
- `OpenAICompatibleModelProvider`
  (`backend/src/ava/models/providers/openai_compatible/provider.py:144`)
  represents a **protocol**, not a deployment: the same class serves local
  Ollama, a corporate gateway, or an external endpoint. It never reads global
  settings or environment; configuration is constructor-supplied. Health
  reporting normalizes transport/HTTP failures into AVA-owned status values.
- Composition wires it (`backend/src/ava/infrastructure/composition.py:93`):
  `create_model_provider_registry` registers `"local"` only when
  `settings.model_provider == "local"`; anything else leaves the registry empty.
- Discovery (`services/model_provider_discovery_service.py`) and the
  `/model-providers` route consume the registry through the port only.

**Gaps:**

- **Provider:model cardinality is 1:1.** The model name is bound at construction
  (`OpenAICompatibleModelProvider.__init__`), and `get_model_info()` returns a
  single `ModelInfo`. There is no provider-side model catalog. A Model Registry
  cannot enumerate models from a provider instance as currently shaped.
- **No provider identity vs hosting-mode distinction.** `provider_name` is a
  free string ("local"); there is no typed local/corporate/external classifier.
- **"corporate"/"external" providers are not constructible yet** — the registry
  is empty unless the configured identity is exactly `"local"`.
- **The binding method sits outside the `# BEGIN/END` class markers**
  (`provider.py:391`) — cosmetic only; behavior is correct.

## 6. Stage 2 — Agent runtime seam

**Status: EXISTS.** Runtime identity/capability and execution are separated from
provider and model selection.

- `AgentRuntimePort` (`backend/src/ava/runtimes/contracts.py:31`) exposes
  `get_runtime_info()`, `execute(run_id, request, model_provider, workspace)`,
  `cancel_run(run_id)`. The runtime neither selects nor owns the provider.
- `RuntimeRegistry` / `RuntimeResolver` mirror the provider registry/resolver
  patterns (pure container, exact-id, AVA-owned error).
- `NativeRuntime` (`runtimes/adapters/native/native_runtime.py`) is a minimal
  port implementation using any supplied provider; not used by production
  composition (production uses OpenHands).
- `OpenHandsRuntime` (`runtimes/adapters/openhands/openhands_runtime.py`)
  normalizes outcomes to AVA `RunStatus` and fails closed on un-bindable
  providers via `bind_model_provider`.
- `RuntimeInfo` / `RuntimeCapabilities` (`contracts/runtimes.py:23`) are
  deliberately independent of `ModelCapabilities`.

**Notes / partial areas:**

- `OpenHandsRuntime.get_runtime_info()` reports `shell` / `code_execution` as
  `True` only when a command policy *and* runner were injected at construction
  (`openhands_runtime.py:73`). This is configuration-derived, conservative, and
  correct — but runtime capabilities describe what *may* be attempted, never an
  authorization. The authorization decision remains in
  `ToolAuthorizationPolicy` (Step 36).
- `NativeRuntime` and `OpenHandsRuntime` share no model/residency state, which
  is the right boundary for a future Resource Manager.

## 7. Inference runtime vs provider

**Status: EXISTS / PARTIAL.** The provider is a *protocol adapter*; the actual
inference runtime (e.g. Ollama) is addressed only by endpoint URL.

- `RuntimeModelBinding` (`models/bindings.py`) carries the stable
  `model_id`, `provider_id`, and provider-native `provider_model_name` alongside
  `protocol`, `endpoint`, `api_key` — the minimal description OpenHands/LiteLLM
  needs. `bind_model_provider(provider, binding)` refuses providers that do not
  implement the binding capability.
- The local inference runtime is a placeholder: `models/providers/local/__init__.py`
  contains no implementation; local inference is reached through the generic
  OpenAI-compatible provider pointed at `settings.local_model_base_url`.
- There is **no** representation of model residency, load/unload, or GPU/RAM.
  That belongs to the future Resource Manager and is intentionally absent.

## 8. Model metadata and capabilities

**Status: EXISTS.** `ModelCapabilities` (`contracts/models.py:56`) is a typed,
conservative boolean record: `chat`, `streaming`, `tool_calling`,
`structured_output`, `vision`, `embeddings`, `reasoning`, `code_specialization`.
`ModelInfo` (`contracts/models.py:87`) carries `provider_name`, `model_id`,
`display_name`, `context_limit`, `capabilities`.

- Note on naming: the declared-tools flag is `tool_calling` (not
  `supports_tools`).
- Defaults are all `False`; the OpenAI-compatible adapter reports only
  `chat=True` unless told otherwise (`provider.py:217`). This "claims are
  opt-in, never assumed" stance is exactly what a Registry needs.
- `ModelCapabilities` and `RuntimeCapabilities` remain separate — a runtime may
  support tools even when the model cannot drive them.

## 9. Qualification

**Status: EXISTS (live, opt-in); persistence MISSING.**

- `runtimes/qualification.py` defines `ToolCallQualificationTrial`,
  `ToolCallQualificationResult`, `CodingWorkflowQualificationResult`, plus
  classifiers (`classify_tool_call_trial`, `evaluate_coding_workflow`,
  `classify_workflow_stall`). Qualification is *measured* from observable
  events; assistant prose is never treated as an action.
- The live harness (`runtimes/adapters/openhands/qualification.py`) runs real
  SDK trials and is gated behind `AVA_RUN_LOCAL_MODEL_QUALIFICATION=1`
  (hence the 2 suite skips).
- Qualification results are not persisted or keyed by a stable model identity;
  they live only in test/observability output. A Model Registry would consume
  measured qualification read-only, but that store does not exist yet.
- No security path references a qualification score, model id, provider, or
  profile (`tests/test_architecture.py::test_tool_security_has_no_runtime_model_or_provider_dependency`).

## 10. Model identity

**Status: ADDRESSED (Step 38).** `ModelInfo.model_id` and
`RunExecutionSelection.model_id` identify a model, and the latter now records a
**stable, provider-neutral AVA identity**, not a provider-scoped name.

- `RunExecutionSelection` (`contracts/execution.py:10`) = `runtime_id`,
  `model_provider_id`, `model_id`; stored on `RunRecord` and returned in
  `RunResponse`.
- Step 38 added `ConfiguredModelBinding(model_id, provider_id,
  provider_model_name)` and `ModelBindingResolver` (`models/bindings.py`), plus
  an optional `RunExecutionOverride.model_id`. The stable `model_id` is distinct
  from `provider_id` and from the provider-native `provider_model_name`, so the
  same underlying model reachable through two providers can share one identity.
- This is a foundation, not the Registry: no catalog, qualification, hosting, or
  routing is attached to the identity yet.

## 11. Hosting mode

**Status: ADDRESSED (foundation, Step 39).** `ModelHostingMode` (closed enum:
`local` / `company_hosted` / `external`) in `contracts/models.py` now represents
placement; `ConfiguredModelBinding.hosting_mode` carries the server-owned
classification, `Settings.model_hosting_mode` / `AVA_MODEL_HOSTING_MODE` supplies
it at composition, and a runtime-neutral `ModelHostingRequirement` seam
(`execution/hosting.py`) plus `ExecutionCompatibilityValidator` can reject a
non-local binding before provider invocation. The mode is never inferred from a
provider id, protocol, or endpoint, and it grants no authority. A Model Registry
that *enumerates* hosting modes across a catalog remains future work.

## 12. Profiles

**Status: PARTIAL / conflated.** `ExecutionProfileService`
(`backend/src/ava/services/execution_profile_service.py`) returns two hardcoded
profiles (`local-default`, `openhands-local`) built from `runtime_id` +
`model_provider_id`. The `ExecutionProfile` contract
(`contracts/responses.py:100`) carries no `model_id`, capabilities,
qualification, or hosting metadata. This is an execution shortcut, not a
Model Profile, and it has no orchestration or resource semantics.

## 13. Auto routing

**Status: PARTIAL / placeholder.** Do not mistake this for a Model Orchestrator.

- `AutomaticExecutionRoutingPolicy.select` (`execution/routing.py:19`) walks
  `(default pair) + all (runtime, provider) pairs`, skipping pairs where
  `r == "openhands"`, and returns the first pair the validator accepts.
- `ExecutionSelector.resolve` (`execution/selector.py:42`) calls the policy with
  a synthetic `RunRequest(prompt="auto")` — the real request/task is discarded,
  so routing is not task- or phase-aware.
- `ExecutionCompatibilityValidator` (`execution/compatibility.py:14`) checks
  only `model_info.capabilities.chat`; it ignores runtime capabilities, tool
  support, context limits, and qualification.
- Composition limits auto routing to `eligible_runtime_ids=frozenset({"native"})`
  (`infrastructure/composition.py:84`).
- There are no fallback chains, scoring, resource awareness, or phase awareness.

The `r != "openhands"` hardcode is a placeholder smell worth removing whenever
the routing policy is revisited — but removing it is Step 38+ work, not this
audit.

## 14. Configuration

**Status: PARTIAL.** `Settings` (`backend/src/ava/configuration/settings.py:39`)
is single-valued: one `model_provider`, one `model_name`, one
`local_model_base_url`, plus `agent_provider` / `agent_runtime`. There is no
multi-model catalog, per-model endpoint map, hosting-mode setting, or profile
definition. Adding multiple models today means adding code, not configuration —
the opposite of the stated "provider change is a configuration change" principle.

## 15. Public API surface

**Status: PARTIAL.** Existing endpoints: `/health`, `/capabilities`, `/runs`,
`/model-providers`, `/runtimes`, `/workspaces`, `/execution-profiles`.

- `/model-providers` (`api/routes/model_providers.py`) returns one
  `ModelProviderDiscoveryItem` per provider, each with exactly one
  `ModelInfo` and a health report. There is no `/models` endpoint and no
  per-model capability/qualification endpoint.
- `RunResponse` exposes `execution_selection` (runtime/provider/model ids) —
  identity only, no permissions.
- Python client (`clients/python/src/ava_client/models.py`) mirrors these
  contracts; no model-catalog type exists.

## 16. Frontend

**Status: EXISTS.** `ExecutionControls`
(`frontend/packages/agent-ui/src/components/ExecutionControls.tsx`) renders
Profile / Runtime / Model / Workspace selectors plus an Auto/Custom profile
choice. The Model selector is keyed by `provider_id` and displays
`model_info.model_id`. There is no display of model capabilities,
qualification, or hosting mode, and no multi-model list.

## 17. Training and deployment artifacts

**Status: EXISTS (not code-linked).** `training/deployment/` holds base-control
and SFT-v1 GGUF artifacts, `Modelfile`s, a manifest, merged model files, and
reports; `docs/AVA_Agent_Model_Training_Guide.md` covers SFT/merge/quantize and
declares larger SFT and registry integration out of scope for now. No backend
code references these artifacts, and no Model Registry consumes them. This is
the raw material a Registry would eventually describe; linking it is future work.

## 18. Security invariant assessment (Steps 32–36)

The audit found **no weakening** of the established invariants:

- **Descriptive ≠ authoritative.** `RunRequest` and `RunExecutionOverride`
  carry only prompt, opaque `workspace_id`, and execution *identity* selection;
  there are no permission/sandbox fields
  (`test_public_request_has_no_permission_or_sandbox_grants`,
  `test_public_run_request_has_no_shell_escalation_fields`).
- **Qualification ≠ permission.** `ToolAuthorizationPolicy` has no dependency on
  models, providers, runtimes, or profiles, and names no `model_id` / `provider`
  / `runtime_id` / `profile` / `prompt`
  (`test_tool_security_has_no_runtime_model_or_provider_dependency`).
- **Runtime capability ≠ permission.** `RuntimeCapabilities` never feeds an
  authorization decision; Step 36's fail-closed `ToolAuthorizationPolicy.evaluate`
  remains the sole gate, with operation-time revocation.
- **`RunService` stays thin.** It depends only on `AgentPort` and does not import
  execution, workspaces, runtimes, or security policy
  (`test_run_service_does_not_own_security_policy`,
  `test_run_service_remains_model_provider_free`,
  `test_run_service_does_not_depend_on_runtime_contracts`).

New in this step: the guard tests
`test_model_and_runtime_metadata_contracts_carry_no_permission_grants` and
`test_runtime_model_binding_carries_no_permission_grants` lock in the boundary
that model/runtime metadata and the provider binding transport identity, never
authority.

## 19. Gaps and risks for the Model Registry

| ID | Gap | Impact if unaddressed |
| --- | --- | --- |
| G1 | Provider instance is 1:1 with a model; no model catalog. | Registry cannot enumerate models per provider. |
| G2 | No hosting-mode representation or local-only enforcement. | Cannot express or enforce hosting policy. |
| G3 | No provider-independent model identity. | Same model via two providers is two identities. |
| G4 | Auto routing discards the request; hardcoded `openhands` exclusion; trivial validator. | Orchestrator would inherit a placeholder. |
| G5 | No persisted, identity-keyed measured qualification. | Registry cannot report measured capability truthfully. |
| G6 | Execution profiles conflate runtime+provider; hardcoded. | Model Profile concept is absent. |
| G7 | Single-model configuration. | Multi-model requires code changes, violating the config principle. |
| G8 | `RuntimeModelBinding` includes `api_key`. | Must never be serialized to public contracts (currently internal only — keep it that way). |
| G9 | Routing/selector style (`# ruff: noqa`, inline statements) reads as placeholder. | Low; cosmetic/maintainability. |

### Post-Step-38 status

- **G1 — addressed (foundation).** `ConfiguredModelBinding` + `ModelBindingResolver`
  let one provider serve many models, and the OpenHands runtime targets an
  explicit `provider_model_name`. A model *catalog* still does not exist.
- **G3 — addressed (foundation).** Stable, provider-neutral `model_id` is
  decoupled from `provider_id` and `provider_model_name`, and is retained in run
  metadata. Persistence of identities and the same-model-across-providers
  catalog remain future work.
- G2, G4–G9 unchanged.

### Post-Step-39 status

- **G2 — addressed (foundation).** Explicit `ModelHostingMode` classification
  attached to configured bindings, strict `AVA_MODEL_HOSTING_MODE` config, and a
  runtime-neutral local-only enforcement seam evaluated before provider
  invocation. No routing policy, and no catalog-level hosting enumeration yet.
- G1/G3 remain addressed (foundation); G4–G9 unchanged.

### Post-Step-40 status

- **Model Registry — implemented v1 / PASS.** `ModelProfile` and the immutable
  `ModelRegistry` establish the configured catalog keyed by stable `model_id`.
  `ModelBindingResolver` is registry-backed and derives execution bindings; it
  no longer owns an independent configured-model list. The read-only `/models`
  endpoint exposes safe, deterministically ordered descriptive metadata without
  provider-native names, endpoints, credentials, paths, or permission grants.
- **G1/G3 — implemented for the configured catalog.** One provider can serve
  multiple registered model identities, while `model_id`, `provider_id`, and
  `provider_model_name` remain separate. Hosting classification is retained per
  profile and Step 39's local-only enforcement remains before provider use.
- **G7 — partially reduced.** Composition and registry seams accept an explicit
  ordered profile inventory, but environment configuration remains deliberately
  single-model; a multi-model configuration format is future work.
- **G4, G5, G6, G8, and G9 remain unresolved.** No automatic model selection,
  persisted qualification metadata, execution-profile redesign, credential
  transport redesign, or routing cleanup was introduced.

### Post-Step-41 status

- **G5 — PARTIAL.** The configured-model catalog now has a read-only,
  in-memory qualification store keyed by `model_id`, with optional `runtime_id`
  and a closed measured-status vocabulary. `GET /models` returns only safe,
  deterministic qualification summaries. The store is deliberately separate
  from the live runtime harness, does not affect capability declarations,
  routing, or execution, and has no persistence. Production starts empty
  because no historical artifact maps deterministically to the bootstrap model
  identity.

### Post-Step-42 status

- **G4 — PARTIAL.** `ModelOrchestrator` now deterministically selects a
  configured model using hard catalog filters (enabled, hosting, fixed
  provider, declared capability, and explicitly requested measured
  qualification), followed by configured-default then stable-model-id
  preference. It is wired into `ExecutionSelector`; explicit model overrides
  fail closed and auto selection has no runtime/provider execution fallback.
  Runtime routing itself remains separate and still requires later redesign.
- **G5 — PARTIAL.** Qualification evidence can now be a strict model-selection
  requirement without changing declared capabilities or any security authority.
  Persistence remains deferred.

### Post-Step-43 status

- **Resource Manager — implemented v1 / PASS.** `ModelResourceManager` keeps
  model-id-keyed operational descriptors, validated residency transitions,
  capacity admission, and leases separate from the descriptive registry and
  deterministic selector. It serializes lifecycle operations and refuses to
  unload models with active leases. Production currently uses a provider-managed
  pass-through adapter with unknown resource estimates; this deliberately does
  not claim GPU telemetry or control remote/provider memory. Concrete local
  provider lifecycle integration, telemetry, and persistence remain future
  operational work.

## 20. Sequencing implication (advisory only — not implemented here)

The existing seams are sufficient to start building toward a Model Registry, but
in this order to avoid collapsing concerns:

1. Provider↔model cardinality and a stable, provider-independent model identity.
   *(Step 38 delivered the foundation: `ConfiguredModelBinding`,
   `ModelBindingResolver`, stable `model_id`, explicit `provider_model_name`.)*
2. Hosting-mode classification (typed local / corporate / external).
   *(Step 39 delivered the foundation: `ModelHostingMode`,
   `ConfiguredModelBinding.hosting_mode`, `AVA_MODEL_HOSTING_MODE`, and a
   runtime-neutral local-only enforcement seam. No routing policy.)*
3. Read-only consumption of measured qualification keyed by model identity.
4. A Model Orchestrator that consumes the Registry for selection; permissions
   stay server/workspace-owned.
5. A separate Resource Manager for residency/leases.

No step above is authorized by this audit. Each requires its own approval and
security review.

## 21. Explicit non-goals of this audit

The original audit did **not** implement a Model Registry, ModelProfile, or
`/models` endpoint. Steps 40 and 41 subsequently implemented catalog discovery
and read-only qualification summaries. They did
not implement a Model Orchestrator, Resource Manager, automatic model routing,
fallback chains, phase-aware multi-model behavior, a new inference runtime,
training or SFT-v2, auth/RBAC, persistence, a production repository workspace,
Git tooling, or qualification integration. No model inference was run.

## 22. Validation

- Architecture guard tests (including the two new boundary tests): see the
  Step 37 section of `docs/AVA_Phase_3_Implementation_Log.md`.
- Ruff and strict mypy results are recorded there as well.
- Security invariants from Steps 32–36 re-confirmed by the existing plus new
  architecture tests; no security code was changed.

## 23. Post-audit update — Step 38 implementation

Step 38 implemented the first sequencing item (G1 + G3 foundation) without
touching the Registry/Orchestrator/Resource-Manager concerns. Added:

- `ConfiguredModelBinding` and `ModelBindingResolver` (with `UnknownModelError`
  and `NoModelConfiguredForProviderError`) in `models/bindings.py`.
- Stable, provider-neutral `model_id` on `RuntimeModelBinding`,
  `RunExecutionSelection`, and an optional `RunExecutionOverride.model_id`;
  `RuntimeModelBinding` also carries `provider_id` / `provider_model_name`.
- `RuntimeModelBindingPort.create_runtime_model_binding(*, model_id,
  provider_id, provider_model_name)` and `bind_model_provider(provider, binding)`.
- `ModelProviderPort.generate(request, *, model_name=None)` (additive) and
  `AgentRuntimePort.execute(..., model_binding=None)` (additive).
- `Settings.model_id` / `AVA_MODEL_ID` plus `create_configured_model_bindings`
  composition; legacy single-model config derives an identical identity.
- OpenHands targets `openai/<provider_model_name>`; native passes
  `provider_model_name` to `generate`.

Security posture unchanged: `ConfiguredModelBinding` has no credential or
connection fields, `RuntimeModelBinding.api_key` remains internal-only, and the
extended guard over both bindings confirms no permission/sandbox fields.
Validation is recorded in the Step 38 section of the implementation log
(backend 514 passed / 2 skipped, Ruff clean, mypy 86 files, contracts tests
passing).

## 24. Post-audit update — Step 39 implementation

Step 39 implemented the second sequencing item (G2 foundation) without touching
the Registry/Orchestrator/Resource-Manager concerns. Added:

- `ModelHostingMode` (closed StrEnum: `local`, `company_hosted`, `external`) in
  `contracts/models.py`; server-owned placement metadata, never inferred.
- `ConfiguredModelBinding.hosting_mode` (default `local` for back-compat) and
  composition propagation via `Settings.model_hosting_mode` /
  `AVA_MODEL_HOSTING_MODE` (strict parse; unknown values are configuration errors).
- `RunExecutionSelection.hosting_mode` (additive, mirrored in `@ava/contracts`
  and the Python client). `RunExecutionOverride` deliberately has **no** hosting
  override, so clients cannot dictate placement.
- `execution/hosting.py`: `ModelHostingRequirement` (+ `local_only()`) and stable
  internal `HostingReason` codes.
- `ExecutionCompatibilityValidator.validate(..., hosting_mode=None,
  hosting_requirement=None)`: rejects non-permitted/missing classification before
  provider invocation; providers never enforce placement. An optional
  server-owned `hosting_requirement` threads through `NativeAgentAdapter` /
  `create_agent_adapter` / `create_app` (default `None` = unconstrained).

Deliberate exclusions: `RuntimeModelBinding` and `ModelInfo` do not carry hosting
mode. Security posture unchanged: hosting mode is descriptive, not authority;
`ToolAuthorizationPolicy` remains the sole tool authority gate; `api_key` stays
internal-only. Validation is recorded in the Step 39 section of the implementation
log (backend 533 passed / 2 skipped, Ruff clean, mypy 87 files, contracts tests
10 passing, Python client 7 passing).
