# AVA Phase 5.1 — Provider / Model / Runtime Architecture Audit

**Status:** Complete — documentation only.
**Scope:** Current implementation as inspected on 2026-09-24. No Phase 5.2 code, contracts, repositories, or APIs were created.

## A. Current-State Architecture

AVA already has separate provider, model, runtime, and execution seams. Its production composition is still bootstrap/environment driven, rather than AVA-managed or persisted configuration.

| Concern | Current owner | Current state |
| --- | --- | --- |
| Bootstrap configuration | `ava.configuration.settings.Settings` | Environment-backed, cached singleton |
| Provider implementations/connections | `ava.infrastructure.composition.create_model_provider_registry` | One constructed local OpenAI-compatible provider under `local` |
| Model catalog | `ava.models.model_registry.ModelRegistry` | Immutable configured `ModelProfile` catalog; bootstrap creates one profile |
| Model binding | `ava.models.bindings.ModelBindingResolver` | Resolves a stable `model_id` to `ConfiguredModelBinding` |
| Runtime catalog | `ava.runtimes.registry.RuntimeRegistry` | In-memory instances registered as `native` and `openhands` |
| Runtime selection | `ava.execution.selector.ExecutionSelector` | Validates/chooses runtime and provider/model binding per run |
| Run boundary | `ava.services.run_service.RunService` → `ava.agents.contracts.AgentPort` | Preserved; service does not import adapters, registries, or providers |
| Persistence | `ava.infrastructure.persistence.repositories` | Phase 4 persists conversations, messages, runs, events, documents, revisions, and attachments; no execution configuration domain |

`ModelProviderPort` represents a provider execution implementation. The current concrete configured provider is `OpenAICompatibleModelProvider` in `ava.models.providers.openai_compatible.provider`; composition supplies its local endpoint from `Settings.local_model_base_url`. The provider is selected by the bootstrap `model_provider` id, not by a separately stored connection record.

`ModelProfile` is the current configured-model concept. It owns `model_id`, display name, `provider_id`, provider-native model name, hosting mode, capabilities, and enabled state. It deliberately contains no credential, endpoint, runtime, permission, or resource state (`ava.models.model_registry`). `ConfiguredModelBinding` is the execution view derived from that profile (`ava.models.bindings`).

`AgentRuntimePort` is explicitly independent of providers: its `execute` method receives a selected `ModelProviderPort` and optional `ConfiguredModelBinding`; it does not choose either (`ava.runtimes.contracts`). Native and OpenHands are registered independently in composition.

## B. Current Configuration Flow

```text
Environment / .env process environment
  AVA_AGENT_PROVIDER, AVA_AGENT_RUNTIME,
  AVA_MODEL_PROVIDER, AVA_MODEL_NAME, AVA_MODEL_ID,
  AVA_MODEL_HOSTING_MODE, AVA_LOCAL_MODEL_BASE_URL
        ↓
Settings / get_settings()  [ava.configuration.settings]
        ↓
Application composition  [ava.infrastructure.composition]
  ├─ create_model_provider_registry(): local provider + endpoint/credential configuration
  ├─ create_configured_model_profiles(): exactly one bootstrap ModelProfile
  ├─ create_model_registry() / ModelBindingResolver
  ├─ create_model_orchestrator(default_model_id)
  ├─ create_model_resource_manager()
  └─ create_runtime_registry(): native + openhands
        ↓
NativeAgentAdapter / ExecutionSelector
        ↓
per-run selected runtime + provider/model binding
```

`Settings.resolved_model_id` uses `AVA_MODEL_ID` when present; otherwise it derives the legacy id as `<model_provider>-<model_name>`. Hosting mode is strictly parsed as `ModelHostingMode`; persistence and attachment storage configuration are likewise validated. There is no persisted override, settings API, bootstrap migration, or production/development configuration split for models/providers/runtimes beyond environment defaults.

## C. Current Execution Flow

```text
POST /runs  [ava.api.routes.runs]
        ↓
RunService  [ava.services.run_service]
  creates/persists AVA run and delegates only to AgentPort
        ↓
NativeAgentAdapter (or configured MockAgentAdapter)
        ↓
ExecutionSelector  [ava.execution.selector]
  resolves runtime id and provider/model request choices
        ├─ RuntimeResolver → RuntimeRegistry → AgentRuntimePort
        └─ ModelProviderResolver + ModelBindingResolver
                ↓
          ConfiguredModelBinding
                ↓
          ModelOrchestrator / ModelSelectionDecision
                ↓
          ModelRegistry / ModelProfile + qualification metadata
                ↓
          ModelResourceManager lease (hosting-aware)
                ↓
          AgentRuntimePort.execute(..., ModelProviderPort, model_binding)
                ↓
          provider execution / provider-native model name
```

`RunService` remains at the stable `AgentPort` boundary. Selection, provider construction, resource management, workspace resolution, and runtime adapter details are composed outside it. `ModelOrchestrator` owns deterministic model-selection policy; `ModelRegistry` is descriptive and owns no selection. `ModelBindingResolver` owns exact binding/default failure semantics, not provider construction. `ModelResourceManager` leases configured model descriptors and does not preload or infer resources from provider identity.

## D. Existing Concepts We Must Reuse

- `Settings` for bootstrap/fallback and strict operational validation, not as the eventual authoritative persisted catalog.
- `ModelProfile`, `ModelRegistry`, `ModelBindingResolver`, `ConfiguredModelBinding`, and the stable `model_id` as the existing model identity chain.
- `ModelProviderPort`, `ModelProviderRegistry`, and `ModelProviderResolver` as provider implementation/lookup seams.
- `AgentRuntimePort`, `RuntimeRegistry`, and `RuntimeResolver` as runtime seams.
- `ExecutionSelector` and `ModelOrchestrator` as configuration consumers, not stores.
- Phase 4 repository interfaces and SQLite/in-memory paired adapters as the model for future durable configuration storage.
- Existing discovery contracts/endpoints and `@ava/api-client` methods as read-only catalog surfaces to evolve rather than duplicate.

## E. Architectural Gaps

| Proposed concept | Classification | Evidence / implication |
| --- | --- | --- |
| ProviderConnection | Missing | Provider id and local endpoint are composed from environment; no connection identity, enablement, or credential reference exists. |
| PersistedModelConfiguration | Partially exists | `ModelProfile` is the correct in-memory configuration shape, but it is immutable/bootstrap-derived and not persisted. |
| PersistedRuntimeConfiguration | Partially exists | Runtime ids/metadata and registry exist, but configured enablement/settings are not durable records. |
| ApplicationExecutionDefaults | Partially exists | Composition passes bootstrap defaults to resolvers; there is no persisted, validated defaults aggregate. |
| CredentialReference | Missing | Credentials/endpoints are provider construction inputs; no neutral secret-reference abstraction exists. |
| ExecutionConfigurationResolver | Partially exists | `ExecutionSelector` plus resolvers consume request/default configuration, but no authoritative persisted-configuration resolver exists. |

No listed concept should be discarded. The first five are genuine Phase 5 configuration gaps; the last should be introduced only as a thin resolver over persisted records and existing selection seams, never as a replacement execution stack.

## F. Provider vs Provider Connection Analysis

Today, a provider means an AVA `ModelProviderPort` implementation registered under an opaque provider id. `create_model_provider_registry()` constructs the local OpenAI-compatible implementation when `Settings.model_provider == "local"`; `Settings.local_model_base_url` supplies its endpoint. This conflates adapter type, configured deployment, endpoint, and default identity in bootstrap composition.

A first-class `ProviderConnection` fits cleanly because it can move endpoint, enablement, display name, and credential reference out of adapter selection while preserving `ModelProviderPort` as the execution implementation. One adapter can then support Local Ollama, vLLM, or a company gateway as different connection records. It must not replace `provider_id` as the adapter/type identifier until exact existing resolver semantics are mapped in 5.2.

## G. Model Identity Analysis

`model_id` is the stable AVA key and is unique in `ModelRegistry`. `provider_id` references the provider registry identity, while `provider_model_name` is the provider-native deployment/model target. `hosting_mode` is server-owned, explicit, and never inferred from provider id or endpoint. The profile-to-binding conversion preserves all four for execution.

The registry permits many model profiles for one provider id; `provider_model_name` need not be globally unique. Bootstrap composition currently creates only one profile, so the existing frontend discovery selector incorrectly presents `ModelProviderDiscoveryItem` as a “Model” choice while submitting `model_provider_id` (`frontend/packages/agent-ui/src/components/ExecutionControls.tsx`). This is a current UI limitation, not a backend identity rule.

## H. Runtime Independence Analysis

Runtime and provider/model selection are structurally independent: `AgentRuntimePort.execute` receives its provider/binding, and `RuntimeRegistry` only stores runtime instances. `ExecutionControls` exposes separate runtime and model/provider selectors; execution profiles carry both ids. `ExecutionSelector` is the explicit point where compatible selections are validated.

The UI's `ExecutionProfile` can intentionally select both a runtime and a provider, but that is a profile convenience—not a declaration that either owns the other. The provider-labelled-as-model control and bootstrap defaults are the main accidental coupling risks Phase 5 must remove by adding true model selection, provider-connection selection, and validation through AVA-owned contracts.

## I. Persistence Recommendation

Follow the Phase 4 pattern: AVA-owned repository protocol in `ava.repositories`, an in-memory implementation for tests/development, a relational SQLite implementation in `ava.infrastructure.persistence.repositories`, serialization, and an additive migration registered through the existing migration runner.

The minimal likely durable entities are: provider connection, configured model, configured runtime, and one execution-defaults record. Credentials should be references only. Do not persist adapter implementations, provider SDK objects, resource leases, workspace grants, or raw secrets. Existing run/conversation/document repositories should remain unchanged initially.

## J. API Recommendation

`GET /models`, `/model-providers`, `/runtimes`, and `/execution-profiles` already return AVA-owned discovery contracts through corresponding API-client methods. They should evolve to read authoritative configuration once it exists. `/model-providers` currently describes provider-backed model entries and should be reviewed before any new “provider connections” discovery endpoint is named.

Phase 5 will likely need a coherent Settings/configuration API for provider connections, models, runtimes, and defaults, with redacted credential-reference presentation. It should not create overlapping ad-hoc management endpoints or make `POST /runs` configure application defaults.

## K. Frontend Impact

The shared frontend already has reusable API-client discovery methods, contracts, `ExecutionControls`, and `AppWorkspace` default-selection state. Web and Desktop are thin consumers of shared packages. No Settings UI exists.

Future UI work must distinguish the model id sent in execution requests from provider/connection identity. It can reuse the existing selectors and execution-profile flow after contracts become explicit, but must not introduce a new state library or let a runtime selector silently choose a provider/model.

## L. Secret Handling Recommendation

The current bootstrap endpoint and any provider credential are composition inputs; `RuntimeModelBinding` explicitly marks `api_key` internal and states it must never be serialized. There is no credential-reference domain. Settings APIs must return only redacted metadata plus a credential reference/status (never a value), frontend state must not retain raw credentials, logs must not include them, and ordinary model metadata must not store them. Phase 5.2 should define the neutral reference boundary; actual secret backend selection can remain environment-backed initially.

## M. Phase 5.2 Recommendation

**Exact scope:** define the AVA-owned Provider Connection domain only. Do not persist it, add an API, migrate data, or build UI in 5.2.

Likely affected areas: `backend/src/ava/contracts/`, `backend/src/ava/models/` (only where provider identity contracts must reference connection identity), architecture documentation, and focused contract tests. The domain should define opaque connection identity, provider implementation id, display metadata, enabled state, endpoint/configuration metadata, credential-reference shape, and timestamps—without raw secrets or SDK types.

Repository/migration/API/frontend impact in 5.2: none beyond forward-compatible contract design. Persistence belongs in 5.3, settings endpoints in 5.10, and UI in 5.11–5.15. Required 5.2 tests: invariant/validation tests for nonblank opaque ids, adapter-vs-connection separation, redaction/no-secret fields, and no runtime/model ownership coupling.

## Validation

- Inspected the primary source modules named throughout this document, including composition, settings, contracts, registries, bindings, selectors, discovery API clients, and shared frontend selectors.
- Relevant architecture guard test areas include backend tests for model registry, model bindings, model selection/orchestration, runtime registry/resolution, provider ports/resolvers, and execution-profile/model-resource behavior. They were identified for Phase 5.2 regression selection; no production code was changed in this audit.
- `git diff --check` must be run after this document is added.

## Stop Condition

This completes Step 5.1. The next permitted action is review/approval of this audit; Phase 5.2 has not been started.
