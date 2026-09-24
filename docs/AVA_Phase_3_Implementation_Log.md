# AVA Phase 3 Implementation Log

Step-by-step record of the Phase 3 implementation. Each entry documents what
was built, the contracts introduced, and the validation results. Entries for
later steps are added only when those steps are actually implemented.

---

## Step 2 — Model Capability Contract

**Status: COMPLETE**

### Goal

Define an AVA-owned, provider-neutral vocabulary for *model capabilities* so
AVA can ask "what can this model do?" without knowing which provider (Ollama,
OpenAI, AWS, Databricks, Stellantis gateways, ...) hosts the model.

### Contracts created

`ModelCapabilities` in `backend/src/ava/contracts/models.py`:

- Pydantic `BaseModel` DTO (AVA's established contract convention, Pydantic v2).
- Typed boolean record (not a set of vendor feature names):
  `chat`, `streaming`, `tool_calling`, `structured_output`, `vision`,
  `embeddings`, `reasoning`, `code_specialization`.
- All defaults are `False` — deterministic and conservative. A capability is
  only `True` when a provider's adapter confirms the model supports it.
- Carries `contract_version` (`v1`), matching every other AVA contract.
- No provider-SDK objects, no HTTP/API response objects, no provider enums.
- Serializes to JSON via `model_dump()` / `model_dump(mode="json")`.

### Contract extended

`ModelInfo` (existing AVA model metadata, reused — not duplicated):

- Added `capabilities: ModelCapabilities` with `default_factory` so every
  existing construction site stays valid (defaults to all-`False`).
- `context_window` was **not** added: the existing `ModelInfo.context_limit`
  (`int | None`) already represents numeric context size. Context size remains
  numeric metadata; the capability booleans live in `ModelCapabilities`.

`ModelCapabilities` is available through the package boundary via
`ava.contracts` (`ava.contracts.ModelCapabilities`).

### Scope boundaries honored

- `ModelProviderPort` API was **not** changed. `get_capabilities()` still
  returns `set[CapabilityName]`. The new typed capability contract is the
  Step 2 vocabulary; reconciling the port's return type is Step 4 work.
- No provider, registry, resolver, runtime, or run-path wiring was added.
- `ModelProviderPort` remains disconnected from `RunService`.
- The Mock Agent was not modified.

### Tests

Added to `backend/tests/test_contracts.py` (Model Contract Tests section):

- `test_model_capabilities_default_to_conservative_false` — all-`False`
  deterministic defaults; an unsupported capability never defaults to enabled.
- `test_model_capabilities_can_enable_capabilities_independently` — multiple
  capabilities can be set without enabling the rest.
- `test_model_capabilities_are_independent_of_each_other` — enabling one
  capability (e.g. `tool_calling`) does not enable unrelated ones
  (`structured_output`, `reasoning`, `vision`, ...).
- `test_model_capabilities_serialize_to_json` — JSON-safe, provider-neutral
  serialization with `contract_version`.
- `test_model_info_includes_capabilities` — model identity, context window,
  and capabilities survive construction and serialization through `ModelInfo`.
- `test_model_info_context_window_is_numeric_metadata` — context window is a
  numeric property of `ModelInfo`, not a boolean capability.

### Validation

- Targeted: `pytest tests/test_contracts.py` — 29 passed.
- Backend model/port guardrails: `pytest tests/test_architecture.py` — passed.
- `ruff check src tests`, `mypy src` — clean.
- Full gate: `./scripts/test_all.sh` — green (see note).

### Files changed

- `backend/src/ava/contracts/models.py` — added `ModelCapabilities`; extended
  `ModelInfo` with `capabilities`.
- `backend/src/ava/contracts/__init__.py` — export `ModelCapabilities`.
- `backend/tests/test_contracts.py` — added Step 2 tests.
- `docs/AVA_Phase_3_Architecture_Audit.md` — added pre-Phase-3 baseline note.
- `docs/AVA_Phase_3_Implementation_Log.md` — this file.

---

## Step 3 — Runtime Capability Contract

**Status: COMPLETE**

### Goal

Define an AVA-owned, provider-neutral vocabulary for *agent runtime
capabilities* so AVA can ask "what can this runtime do?" without binding
AVA to OpenHands, LangGraph, AWS AgentCore, or any specific framework.

Step 3 creates the runtime parallel to Step 2's `ModelCapabilities`.

### Contracts created

`RuntimeCapabilities` in `backend/src/ava/contracts/runtimes.py`:

- Pydantic `BaseModel` DTO, following AVA's established contract convention.
- Typed boolean record (not a set of framework feature names):
  `tools`, `multi_agent`, `shell`, `filesystem`, `browser`,
  `code_execution`, `checkpointing`, `persistence`, `human_approval`,
  `parallel_execution`.
- All defaults are `False` — deterministic and conservative. A capability is
  only `True` when a runtime adapter declares it.
- Carries `contract_version` (`v1`), matching every other AVA contract.
- No framework-specific SDK objects or enums appear.
- Serializes to JSON via `model_dump()` / `model_dump(mode="json")`.

`RuntimeInfo` (also in `ava.contracts.runtimes`):

- Metadata contract associating a runtime identity with its capabilities.
- `runtime_id: str` (required), `display_name: str | None` (optional),
  `capabilities: RuntimeCapabilities`, `contract_version: str`.
- Parallels `ModelInfo` in structure; `RuntimeInfo` is the runtime-side
  analog of `ModelInfo`.

### Design decisions

- **Naming: `RuntimeInfo` not `RuntimeDescriptor`** — `ModelInfo` is the
  repository's established metadata contract; `RuntimeInfo` maintains parallel
  naming. The Step 1 audit referenced `RuntimeDescriptor` conceptually, but
  `RuntimeInfo` is more consistent with the existing convention.
- **Capability defaults — conservative:** all ten booleans default to `False`.
- **Runtime/Model separation:** `RuntimeCapabilities` and `ModelCapabilities`
  are completely separate types. A runtime can support `tools` while the
  selected model does not support `tool_calling`; future compatibility
  validation will detect such mismatches. That logic is explicitly out of
  scope for this step.
- **No reuse of `CapabilityName`:** `CapabilityName` (in
  `ava.contracts.capabilities`) is a StrEnum used by the app-level
  `/capabilities` endpoint and `AgentPort.get_capabilities() -> set[CapabilityName]`.
  It names AVA application capabilities (health, runs, streaming, etc.), not
  per-runtime boolean capabilities. They are orthogonal. Documented below as
  an overlap to be reconciled in a later step.

### Scope boundaries honored

- `AgentPort` was not redesigned; `get_capabilities()` still returns
  `set[CapabilityName]`.
- No `AgentRuntimePort` was created.
- No runtime registry, resolver, or real runtime adapter was added.
- No provider architecture was changed.
- No `ModelProviderPort` changes were made.
- No run lifecycle or MockAgent behavior was changed.

### Tests

Added to `backend/tests/test_contracts.py` (Runtime Contract Tests section):

- `test_runtime_capabilities_default_to_conservative_false` — all-`False`
  deterministic defaults; an unsupported capability never defaults to enabled.
- `test_runtime_capabilities_can_enable_capabilities_independently` — multiple
  capabilities set independently.
- `test_runtime_capabilities_are_independent_of_each_other` — enabling
  `tools` does not imply `shell`/`filesystem`/`code_execution`; enabling
  `multi_agent` does not imply `parallel_execution`.
- `test_runtime_capabilities_serialize_to_json` — JSON-safe, framework-neutral
  serialization with `contract_version`.
- `test_runtime_info_includes_capabilities` — runtime identity and
  capabilities survive construction and serialization.
- `test_runtime_info_requires_runtime_id` — `RuntimeInfo` enforces the
  required `runtime_id` field.
- `test_runtime_info_display_name_is_optional` — `display_name` defaults to
  `None` and is not required.
- `test_runtime_and_model_capabilities_are_independent` — `RuntimeCapabilities`
  and `ModelCapabilities` are separate contracts; each carries different field
  names and one does not alter or imply values in the other.

### Validation

- Targeted: `pytest tests/test_contracts.py` — 37 passed.
- Full gate: `./scripts/test_all.sh` — green (backend 122 passed, all
  lint/typecheck clean, frontend all green, Python client green).

### Files changed

- `backend/src/ava/contracts/runtimes.py` — created; `RuntimeCapabilities`
  and `RuntimeInfo`.
- `backend/src/ava/contracts/__init__.py` — export `RuntimeCapabilities` and
  `RuntimeInfo`.
- `backend/tests/test_contracts.py` — added Step 3 tests.
- `docs/AVA_Phase_3_Implementation_Log.md` — this entry.

---

## Step 4 — Harden ModelProviderPort

**Status: COMPLETE**

### Goal

Make the existing `ModelProviderPort` boundary ready for future real provider
implementations while preserving AVA ownership of all contracts. The port
existed but reported capabilities as `set[CapabilityName]`, which predates
the Step 2 `ModelCapabilities` contract. This step reconciles that mismatch.

### Final port contract

`backend/src/ava/models/contracts.py`:

```python
class ModelProviderPort(ABC):
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    async def health(self) -> ModelProviderHealth: ...

    @abstractmethod
    def get_model_info(self) -> ModelInfo: ...

    @abstractmethod
    def get_capabilities(self) -> ModelCapabilities: ...

    @abstractmethod
    async def generate(self, request: ModelRequest) -> ModelResponse: ...
```

### Contract reconciliation

- **`get_capabilities()`** now returns `ModelCapabilities` (the Step 2
  normalized model capability contract) instead of `set[CapabilityName]`.
  `CapabilityName` is **not** removed: it remains the application-level
  vocabulary used by `AgentPort.get_capabilities()`, `/capabilities`
  (`CapabilitiesResponse`), and `CapabilityService`. The two concepts are
  orthogonal — `ModelCapabilities` describes a model's capabilities (chat,
  streaming, tool calling, ...); `CapabilityName` names AVA application
  capabilities (health, runs, cancellation, ...).
- **`get_model_info()`** continues to return the canonical AVA-owned
  `ModelInfo` (provider identity + `context_limit` + `ModelCapabilities`).
  `ModelInfo.capabilities` and `get_capabilities()` are consistent by contract
  (a provider must report the same capability structure through both).
- **`generate(request)`** continues to use only AVA-owned contracts:
  `ModelRequest` → `ModelResponse`. No provider SDK type crosses the port.
- **`health()`** remains the AVA-owned, provider-neutral `ModelProviderHealth`
  contract; no health redesign was performed.
- **Streaming** was **not** added. A `ModelCapabilities.streaming` field
  describes future support only; the port gains no streaming method yet.

### Test fake

No production provider exists. Added a minimal test-only
`FakeModelProvider` in `backend/tests/test_model_provider_port.py` that
implements the full port with deterministic AVA-owned values. No production
provider, registry, or resolver was created.

### Architecture

Dependency direction preserved:

```text
AVA application/domain
        ↓
ModelProviderPort
        ↓
future provider adapter
        ↓
provider SDK / HTTP API
```

Added two architecture guardrail tests: the models port must not import
forbidden vendor/transport modules, and the models port must depend only on
`ava.contracts`.

### Tests

New `backend/tests/test_model_provider_port.py` (8 tests) plus 2 architecture
tests in `backend/tests/test_architecture.py`:

- `test_get_capabilities_returns_model_capabilities` — port capability method
  returns `ModelCapabilities`.
- `test_get_capabilities_no_longer_returns_capability_name_set` — the old
  `set[CapabilityName]` boundary no longer defines the port; `CapabilityName`
  itself remains an AVA capability-name vocabulary.
- `test_get_model_info_returns_ava_owned_model_info` — identity, context
  limit, and capabilities via `ModelInfo`.
- `test_get_model_info_capabilities_match_get_capabilities` — internal
  consistency between `ModelInfo.capabilities` and `get_capabilities()`.
- `test_generate_uses_ava_owned_contracts` — `generate()` accepts
  `ModelRequest`, returns `ModelResponse`; JSON-safe.
- `test_health_returns_ava_owned_health` — `health()` returns
  `ModelProviderHealth`, JSON-safe.
- `test_conservative_capability_reporting` — default `ModelCapabilities()`
  reports every optional capability as unsupported.
- `test_explicit_capability_reporting` — a provider can declare
  `chat`/`streaming` without altering unrelated fields.
- `test_model_port_must_not_import_forbidden_modules` / `..._depends_only_on_contracts`
  — port-layer boundary guardrails.

### Validation

- Targeted: `pytest tests/test_model_provider_port.py tests/test_architecture.py tests/test_contracts.py` — 56 passed.
- Backend suite: 132 passed; `ruff check src tests` and `mypy src` clean.
- Full gate: `./scripts/test_all.sh` — green.

### Files changed

- `backend/src/ava/models/contracts.py` — `get_capabilities()` now returns
  `ModelCapabilities`.
- `backend/tests/test_model_provider_port.py` — created; port hardening tests
  with a minimal test-only `FakeModelProvider`.
- `backend/tests/test_architecture.py` — added model-port boundary guardrails.
- `docs/Model Provider.md` — updated port signature and `ModelInfo`/capability
  documentation to the actual Step 4 architecture.
- `docs/Contract Standards.md` — updated `ModelInfo`, added
  `ModelCapabilities` and runtime contract documentation.
- `docs/AVA_Phase_3_Implementation_Log.md` — this entry.

### Future concerns (not implemented)

- `ModelProviderPort` is still **not connected** to `RunService`; wiring is a
  later step.
- No provider registry/resolver exists yet; the hardened port is a
  prerequisite, not the registry itself.
- The `local` provider placeholder (`ava.models.providers.local`) remains
  docstring-only; a real adapter is a later step.

---

## Step 5 — Create Model Provider Registry

**Status: COMPLETE**

### Goal

Create a central backend registry for available model providers, ready for the
later resolver step to select providers from configuration.

### What was added

`backend/src/ava/models/registry.py`:

```python
class ModelProviderRegistry:
    def register(self, provider_id: str, provider: ModelProviderPort) -> None
    def get(self, provider_id: str) -> ModelProviderPort | None
    def contains(self, provider_id: str) -> bool
    def list(self) -> list[str]
```

- Providers register under an AVA provider identity — example ids `mock`,
  `local`, `corporate`, `external`. These are AVA identities, not framework
  classes.
- `register()` rejects blank ids and duplicate registrations with
  `ValueError` (matching the existing `RunStore`/`composition.py` conventions).
- `get()` returns `None` for an unknown id (no registry-level exception),
  parallel to `RunStore.get()`; `contains()` is available for explicit checks.
- `list()` returns registered ids in insertion order.
- The registry is a pure container over the `ModelProviderPort` abstraction:
  it holds no provider logic and imports no vendor SDK. It lives in the
  `ava.models` layer, exactly where the architecture audit placed it (sibling
  to `_AGENT_ADAPTER_FACTORIES`, in the `model_provider →
  ModelProviderRegistry → ModelProviderPort` chain).

### Architectural decisions

- Registry treats providers as **instances of `ModelProviderPort`**, not
  frameworks — matching the port abstraction from Step 4.
- State is per-instance (no shared/global registry), matching the rest of the
  backend's composition style.
- No provider was concretely implemented yet: tests register a minimal
  test-only `RegistryProvider` stub. The `local` placeholder stays
  docstring-only.
- `ava.models.__init__.py` now exports `ModelProviderRegistry`.

### Tests

New `backend/tests/test_model_provider_registry.py` (8 tests):
register/get round-trip; unknown id returns `None`; `contains`; insertion-order
`list`; duplicate registration rejected; blank id rejected; per-instance state
independence; retrieved providers satisfy the `ModelProviderPort` boundary
(health + generate exercised through the async port).

Also tightened the Step 4 architecture guardrails: `test_model_port_must_not_import_forbidden_modules`
now scans only the port file `models/contracts.py`, and
`test_model_port_depends_only_on_contracts` was relaxed to also allow the
models-layer sibling `models` (so the registry may import the port) while still
forbidding any outward dependency. Both still pass — no weakening of the
original boundary intent.

### Validation

- Targeted: `pytest tests/test_model_provider_registry.py tests/test_architecture.py tests/test_model_provider_port.py` — 27 passed.
- Backend suite + ruff + mypy (`src`): green.
- Full gate: `./scripts/test_all.sh` — green.

### Files changed

- `backend/src/ava/models/registry.py` — created; `ModelProviderRegistry`.
- `backend/src/ava/models/__init__.py` — export `ModelProviderRegistry`.
- `backend/tests/test_model_provider_registry.py` — created; registry tests with
  a minimal `RegistryProvider` stub.
- `backend/tests/test_architecture.py` — scoped model-port guardrails to the
  port file and allowed the models-layer internal sibling.
- `docs/AVA_Phase_3_Implementation_Log.md` — this entry.

### Future concerns (not implemented)

- The registry is **not yet populated or wired** into `app.py`/composition;
  that is the resolver/configuration step (Step 7).
- No real provider exists to register; the `mock`/`local`/`corporate`/
  `external` ids are placeholders for the resolver.
- No frontend, Ollama, or external API implementation was added (per plan
  "Do Not").

---

## Step 6 — Model Provider Configuration

**Status: COMPLETE**

### Goal

Allow AVA configuration to identify the model provider *and* the model
name/id independently of agent configuration. Config-only: no resolution, no
registry wiring, no provider instances.

### Canonical configuration

| Concept | Field | Environment | Default |
| --- | --- | --- | --- |
| Agent provider | `Settings.agent_provider` / `ApplicationConfig.agent_provider` | `AVA_AGENT_PROVIDER` | `mock` |
| Model provider | `Settings.model_provider` / `ApplicationConfig.model_provider` | `AVA_MODEL_PROVIDER` | `local` |
| Model name/id | `Settings.model_name` / `ApplicationConfig.model_name` | `AVA_MODEL_NAME` | `local-model` |

`model_name` is the single canonical model-identifier field. It did not exist
before this step; `model_provider` already existed and was preserved, and the
existing `AVA_*` environment convention was followed (`AVA_MODEL_NAME`). The
default `local-model` is a neutral placeholder consistent with the default
`model_provider = "local"` — it is not a vendor-specific model and does not
imply a live provider. The application starts without any model configured.

### Independence

The three concepts are independent fields with independent environment
variables and independent defaults. Changing any one never changes the other
two. Settings still flow through the environment-driven `Settings` object and
mirror into the framework-neutral `ApplicationConfig` in `app.py`; no provider
instance, registry, or resolution participates.

### Scope discipline

- Configuration answers only *what* provider/model the application is
  configured to use. *Which* provider instance executes a request belongs to
  Step 7.
- No validation of provider existence, model existence, availability, or
  capability compatibility was added. An unknown provider id is a resolution
  problem, not a configuration parsing problem.
- The settings layer does **not** import `ModelProviderRegistry` or any
  concrete model-provider adapter (enforced by a new architecture guard).
- No real provider, resolver, registry population, `RunService` change, or
  runtime work was performed.

### Tests

New `backend/tests/test_settings.py` (7 tests):

- `test_default_settings_construct_successfully` — defaults construct with no
  live provider/model required.
- `test_model_provider_env_override_changes_only_model_provider` — an
  `AVA_MODEL_PROVIDER` override changes only `model_provider`.
- `test_model_name_env_override_changes_only_model_name` — an
  `AVA_MODEL_NAME` override changes only `model_name`.
- `test_agent_and_model_selection_are_independent` — `agent_provider`,
  `model_provider`, `model_name` all survive independently.
- `test_alternate_combinations_are_not_derived` — two unrelated
  agent/provider/model combinations resolve exactly as configured; nothing is
  derived.
- `test_application_config_mirrors_provider_selection` — the core
  `ApplicationConfig` receives the same independent values from `Settings`.
- `test_default_application_config_has_neutral_model_defaults` — default core
  config mirrors the default settings.

`backend/tests/test_architecture.py` — added
`test_configuration_must_not_import_registry_or_providers` proving the
configuration layer does not import `ModelProviderRegistry` or concrete
model-provider adapters.

Environment isolation: the test module clears all `AVA_*` variables before
each test so assertions are explicit rather than ambient.

### Validation

- Targeted: `pytest tests/test_settings.py tests/test_architecture.py` — 19 passed.
- Backend suite: 148 passed; `ruff check src tests` and `mypy src` clean.
- Full gate: `./scripts/test_all.sh` — green.

### Files changed

- `backend/src/ava/configuration/settings.py` — added `model_name` field
  (`AVA_MODEL_NAME`, default `local-model`).
- `backend/src/ava/core/application.py` — added `model_name` to
  `ApplicationConfig` (default `local-model`).
- `backend/src/ava/api/app.py` — threads `model_name` into `ApplicationConfig`.
- `backend/tests/test_settings.py` — created; configuration/independence tests.
- `backend/tests/test_architecture.py` — added configuration-layer guard.
- `docs/Model Provider.md` — document the supported model configuration.
- `docs/Local Development.md` — added `AVA_MODEL_NAME` to the env table.
- `docs/AVA_Phase_3_Implementation_Log.md` — this entry.

### Step 7 concerns (documented, not implemented)

- `model_provider`/`model_name` are not yet resolved against the registry;
  unknown ids are a resolution-time question for Step 7.
- Should resolution validate that the configured model name exists for the
  chosen provider, or defer to provider health/availability checks? Left open
  for Step 7.
- Whether the resolver receives `model_name` from the start, or only resolves
  the provider id, is a Step 7 decision. The configuration to support it now
  exists.

---

## Step 7 — Create the Model Provider Resolver

**Status: COMPLETE**

### Goal

Introduce the AVA-owned service that turns a configured model provider id into
a registered `ModelProviderPort` instance through `ModelProviderRegistry`.

### Resolver

`backend/src/ava/models/resolver.py`:

```python
class ModelProviderResolver:
    def __init__(self, registry: ModelProviderRegistry) -> None: ...
    def resolve(self, provider_id: str) -> ModelProviderPort: ...

class UnknownModelProviderError(ValueError):
    provider_id: str
```

- `resolve(provider_id)` looks up the AVA provider identity in the injected
  registry and returns the registered `ModelProviderPort`.
- The resolver depends on the registry only through composition — no global or
  hidden registry state.
- It knows only AVA provider identities and AVA abstractions: no vendor SDKs,
  no construction of providers, no registration, no health checks, no
  `model_name` validation.

### Unknown/blank provider behavior

- Unknown id: raises `UnknownModelProviderError` (a `ValueError` subclass —
  consistent with the repository's domain-error convention of descriptive
  `ValueError`s) carrying the unresolved `provider_id`. No default provider is
  returned, and `None` is never returned from `resolve`.
- Blank/whitespace ids: raise the same `UnknownModelProviderError`
  deterministically. The resolver never remaps blanks to a default — default
  selection is configuration's job.
- The error exposes only the provider id, never registry contents or
  implementation internals.

### Composition decision

The `ModelProviderRegistry` and `ModelProviderResolver` are **not** constructed
in `app.py` and are **not stored in `app.state`**. There is no consumer yet —
no route, service, or run executes through the resolver — so exposure would
alter no behavior while adding surface. The resolver is fully constructible and
is exercised by tests through composition

```python
registry = ModelProviderRegistry()
resolver = ModelProviderResolver(registry)
```

Production composition wiring is deferred until a real provider exists and a
consumer needs resolution (Step 8+). The registry remains empty and unpopulated
in production.

### Model name responsibility

`model_name` stays entirely outside resolver responsibility. Step 6 kept
`model_provider` and `model_name` independent; the resolver resolves the
provider only. Later provider logic may consume `model_name` when inference
becomes relevant. A test proves changing `model_name` never changes which
provider `resolve()` returns for a fixed `model_provider`.

### Tests

New `backend/tests/test_model_provider_resolver.py` (8 tests) with a minimal
test-only `ResolverProvider`:

- `test_registered_provider_resolves` — a registered id resolves to the same
  instance.
- `test_multiple_providers_resolve_independently` — each id resolves to its own
  object; none is derived.
- `test_unknown_provider_fails_explicitly` — unregistered id raises
  `UnknownModelProviderError` carrying the id; never a default.
- `test_blank_provider_id_fails_explicitly` — `""` and `"   "` fail explicitly.
- `test_resolution_does_not_mutate_registry` — registry contents are identical
  before and after resolution (including failed lookups).
- `test_resolved_provider_is_used_through_port_boundary` — the result is used
  only as `ModelProviderPort` (health + generate driven through the port).
- `test_config_provider_selects_configured_model_provider` —
  `resolver.resolve(config.model_provider)` selects the configured provider.
- `test_model_name_does_not_affect_resolution` — `model_name` changes never
  alter provider resolution.

`backend/tests/test_architecture.py` — added
`test_model_resolver_depends_only_on_models_and_contracts` proving the resolver
imports only the registry/port/contracts layer, never vendor SDKs, agent
ports/adapters, RunService, runtime frameworks, or configuration.

### Validation

- Targeted: `pytest tests/test_model_provider_resolver.py tests/test_model_provider_registry.py tests/test_architecture.py tests/test_settings.py` — 36 passed.
- Backend suite: 156 passed; `ruff check src tests` and `mypy src` clean.
- Full gate: `./scripts/test_all.sh` — green.

### Files changed

- `backend/src/ava/models/resolver.py` — created; `ModelProviderResolver` and
  `UnknownModelProviderError`.
- `backend/src/ava/models/__init__.py` — export `ModelProviderResolver` and
  `UnknownModelProviderError`.
- `backend/tests/test_model_provider_resolver.py` — created; resolver tests.
- `backend/tests/test_architecture.py` — added resolver dependency guard.
- `docs/Model Provider.md` — document the resolver in the architecture.
- `docs/AVA_Phase_3_Implementation_Log.md` — this entry (replacing the Step 6
  forward-look at resolution).

### Step 8 concerns (documented, not implemented)

- The resolver has no registered providers to resolve in production; the first
  real provider (OpenAI-compatible HTTP provider, Step 8) will need to be
  registered in the composition root before resolution becomes meaningful.
- `model_name` remains unresolved; the Step 8 provider will need to consume it
  when inference begins, without relocating it into the resolver.
- Composition wiring of registry/resolver (`app.state` or equivalent) should be
  introduced with the first consumer, not preemptively.

---

## Step 8 — OpenAI-Compatible HTTP Model Provider

**Status: COMPLETE**

### Goal

Implement the first real `ModelProviderPort` adapter: an AVA-owned
`OpenAICompatibleModelProvider` that speaks the OpenAI-compatible
chat-completions HTTP protocol directly. The adapter proves that AVA model
contracts can be translated to and from a compatible HTTP API **without
changing `RunService`, `AgentPort`, application composition, or the runtime
architecture**.

### Provider class / module

- `backend/src/ava/models/providers/openai_compatible/provider.py` —
  `OpenAICompatibleModelProvider(ModelProviderPort)`.
- `backend/src/ava/models/providers/openai_compatible/__init__.py` — exports the
  class.
- `backend/src/ava/models/providers/errors.py` — `ModelProviderError`, the
  narrow AVA-owned provider error shared by provider adapters.

The provider represents a **protocol**, not a deployment. It is not named or
tied to `local`, `ollama`, `openai`, or a gateway: the same class is usable for
a local Ollama `/v1` endpoint, a company OpenAI-compatible gateway, or an
approved external endpoint. It does not register itself and does not know its
AVA registry id.

### Supported protocol endpoint

- Generation: `POST {base_url}/chat/completions`
- Health: `GET {base_url}/models`

`base_url` is normalized by trimming a trailing slash before appending the
path, so `http://localhost:11434/v1` and
`http://localhost:11434/v1/` both produce
`.../v1/chat/completions` (no `//`, no `/v1/v1/`). No generalized URL-routing
framework was added.

### Construction / configuration

```python
OpenAICompatibleModelProvider(
    *,
    base_url: str,                      # required
    model_name: str,                    # required
    provider_name: str = "openai-compatible",
    api_key: str | None = None,
    timeout: float | None = None,
    capabilities: ModelCapabilities | None = None,
    context_limit: int | None = None,
    display_name: str | None = None,
    http_client: httpx.AsyncClient | None = None,   # injection point for tests
)
```

- Configuration is passed in explicitly. The adapter never calls
  `get_settings()`, `os.getenv()`, or reads `ApplicationConfig`.
- `model_name` is consumed operationally here (the correct place). It was not
  moved into the resolver, registry, or `RunService`.
- Construction is tolerant of blank values so misconfiguration is discoverable
  at runtime instead of crashing composition: `health()` reports
  `CONFIGURATION_INVALID` and `generate()` raises `ModelProviderError`.

### Request translation

`ModelRequest` → compatible request JSON, all inside the adapter:

| AVA (`ModelRequest`) | Compatible request JSON |
| --- | --- |
| `messages[].role` / `messages[].content` | `messages[].role` / `messages[].content` |
| `temperature` (if not `None`) | `temperature` |
| `max_output_tokens` (if not `None`) | `max_tokens` |
| — (adapter identity) | `model` = configured `model_name` |

Optional fields are omitted entirely when AVA does not supply them. AVA's
`max_output_tokens` contract field name is unchanged; only the outbound
protocol field is `max_tokens` (the broadly supported chat-completions field).
AVA contracts were not changed to mirror external JSON names.

### Response translation

Compatible response JSON → `ModelResponse`, with no HTTP/JSON types escaping:

- `choices[0].message.content` → `ModelResponse.content`
- response `model` → `ModelResponse.model_id` (falls back to the configured
  `model_name` when the provider omits a model id)
- `httpx.Response`, raw dicts, and provider response objects never leave the
  adapter.

### Health strategy

`health()` issues the lightweight `GET {base_url}/models` probe (broadly
supported by OpenAI-compatible servers) and maps results to AVA-owned
`ModelProviderHealth`:

| Condition | Status | `available` |
| --- | --- | --- |
| 2xx | `HEALTHY` | `True` |
| 401 / 403 | `AUTHENTICATION_FAILED` | `False` |
| connection refused (`httpx.ConnectError`) | `RUNTIME_UNAVAILABLE` | `False` |
| timeout / other transport error | `UNAVAILABLE` | `False` |
| other non-2xx status | `UNAVAILABLE` | `False` |
| blank `base_url` | `CONFIGURATION_INVALID` | `False` |

`health()` never raises and never leaks HTTP-client exception types.
`MODEL_NOT_LOADED` and `DEGRADED` are intentionally unused: an HTTP probe
cannot reliably diagnose those states.

### Capability strategy

- `get_capabilities()` returns the configured `ModelCapabilities`.
- Default is `ModelCapabilities(chat=True)` — the adapter specifically
  implements the chat-completions protocol, so `chat` is enabled by default.
- Every other capability (`streaming`, `tool_calling`, `structured_output`,
  `vision`, `embeddings`, `reasoning`, `code_specialization`) defaults to
  `False`. No capability is inferred merely because an OpenAI-compatible server
  might support it.
- Explicitly supplied capabilities are used unchanged; Step 2's conservative
  principle is preserved.
- `ModelInfo.capabilities` and `get_capabilities()` are consistent by contract.

### Error handling

`ModelProviderError` (in `ava.models.providers.errors`) is the single
provider-layer exception, kept deliberately small (no deep hierarchy). It
optionally carries `status_code`.

| Failure | Representation |
| --- | --- |
| non-success HTTP status during generation | `ModelProviderError(..., status_code=<code>)` |
| timeout | `ModelProviderError` (wraps the client timeout) |
| connection/transport failure | `ModelProviderError` (wraps the client error) |
| invalid JSON body | `ModelProviderError` |
| missing/empty `choices`, missing `message`, missing/null/non-string `content`, non-object body | `ModelProviderError` |

Raw `httpx` exceptions are wrapped (`raise ... from exc`), so they never cross
the port boundary. Error messages contain no API keys or raw URLs; the original
exception remains in the `__cause__` chain for diagnostics. No retries,
backoff, or circuit breakers were added. Errors are not mapped to HTTP API
responses here (this adapter is below the API layer).

### Authentication

An optional `api_key` is sent as `Authorization: Bearer <key>`. When no key is
configured, no `Authorization` header is sent (no fake/empty value). No secret
storage and no environment reads were introduced.

### Dependencies

**No new dependency.** `httpx>=0.28.0` is already a direct backend dependency
in `backend/pyproject.toml`; the adapter uses its async client and
`httpx.MockTransport` for tests. No OpenAI SDK, Ollama SDK, or other vendor SDK
was added.

### Tests

New `backend/tests/test_openai_compatible_model_provider.py` (36 tests). All
HTTP runs through `httpx.MockTransport`; no live provider, network, or
credentials are needed. Highlights:

- Port implementation: adapter is a `ModelProviderPort`; port methods return
  AVA-owned types only; no HTTP-client types escape.
- Generation: emits `{base_url}/chat/completions` with `model` + `messages`;
  response becomes `ModelResponse`; trailing-slash base URL is normalized.
- Messages: order and roles preserved across multiple messages.
- Optional temperature: omitted when `None`; translated when set.
- Optional output limit: `max_output_tokens` → `max_tokens`; AVA field name
  unchanged.
- Model response: response `model` → `model_id`.
- Authentication: `Authorization: Bearer ...` sent with a key; absent without
  one; error messages never contain the key.
- Health: success → `HEALTHY`; 503 → `UNAVAILABLE`; connection refusal →
  `RUNTIME_UNAVAILABLE`; timeout → `UNAVAILABLE`; 401/403 →
  `AUTHENTICATION_FAILED`; blank base URL → `CONFIGURATION_INVALID`.
- Generation failures: non-success status (500, 401) → `ModelProviderError`
  with `status_code`; timeout/connection error wrapped; blank `model_name`
  fails deterministically.
- Malformed responses: missing choices, empty choices, missing message,
  missing/null content, invalid JSON, non-object body → `ModelProviderError`.
- Model info / capabilities: configured metadata returned; default
  capabilities are chat-only; explicit capabilities remain independent.

`backend/tests/test_architecture.py` — two guards added:
`test_openai_compatible_provider_imports_only_contracts_and_http` (the provider
may depend only on AVA contracts plus a generic HTTP client — never the
registry, resolver, configuration, or outward layers) and
`test_runtime_layers_must_not_import_openai_compatible_provider` (API,
services, core, and agents never import the concrete adapter).

### Scope discipline — production composition is NOT wired

- No provider was registered in production; the registry remains empty.
- `app.py` was **not** modified: it does not construct
  `ModelProviderRegistry`, `ModelProviderResolver`, or
  `OpenAICompatibleModelProvider`, and does not store them in `app.state`.
- `create_agent_adapter()` / `_AGENT_ADAPTER_FACTORIES` were **not** modified.
- `RunService` and `AgentPort` are **unchanged**; MockAgent execution is
  unchanged.
- `ModelProviderResolver` is not consumed in production.
- No route makes the provider reachable from the chat UI.
- No Ollama/local runtime configuration was implemented.
- Streaming, tool calling, and embeddings were **not** implemented;

  `ModelCapabilities.streaming` / `tool_calling` / `embeddings` remain metadata
  only. The port still exposes only complete-response `generate()`.
- No Step 9 work was started.

### Validation

- Targeted: `pytest tests/test_openai_compatible_model_provider.py tests/test_architecture.py` — 51 passed.
- Backend suite: 195 passed; `ruff check src tests` and `mypy src` clean.
- Full gate: `./scripts/test_all.sh` — green (backend, frontend, Python client).

### Files changed

- `backend/src/ava/models/providers/errors.py` — created; `ModelProviderError`.
- `backend/src/ava/models/providers/openai_compatible/__init__.py` — created;
  exports `OpenAICompatibleModelProvider`.
- `backend/src/ava/models/providers/openai_compatible/provider.py` — created;
  the adapter.
- `backend/src/ava/models/providers/local/__init__.py` — corrected the
  docstring (placeholder only; no implementation).
- `backend/tests/test_openai_compatible_model_provider.py` — created; adapter
  tests.
- `backend/tests/test_architecture.py` — added provider import guards.
- `docs/Model Provider.md` — documented the OpenAI-compatible adapter.
- `docs/AVA_Phase_3_Implementation_Log.md` — this entry.

### Step 9 concerns (documented, not implemented)

- Ollama runs as a server; the adapter assumes it is already running and
  reachable. Whether AVA should detect/start a local runtime is a Step 9
  question.
- Ollama's OpenAI-compatible endpoint is rooted at `/v1`; `base_url` must
  include `/v1`. Whether to accept a bare host and append `/v1` is a
  configuration question, deliberately not generalized here.
- `GET /models` availability and response shape on Ollama `/v1` should be
  verified against a live local runtime in Step 9.
- Capability defaults for a specific local model (e.g. tool calling) remain an
  explicit configuration decision for Step 9.
- Composition wiring of registry/resolver/provider (with a first consumer)
  remains deferred, as in Step 7.

---

## Step 8A — OpenAI-Compatible Provider Lifecycle/Error Boundary Correction

**Status: COMPLETE**

### Goal

Small corrective pass over the Step 8 adapter, addressing two issues surfaced
by the Step 8 architecture inspection before Step 9 begins:

1. **HTTP client lifecycle.** A provider-created `httpx.AsyncClient` had no
   explicit close path.
2. **Raw `httpx.InvalidURL` leakage.** `httpx.InvalidURL` is *not* a
   `RequestError` subclass, so a malformed `base_url` could cross the
   `ModelProviderPort` boundary uncaught.

### HTTP client ownership

- `__init__` now records `self._owns_http_client = http_client is None`.
- A **caller-injected** `http_client` is the caller's; the provider never
  closes it.
- An **internally created** client is owned by the provider and has an explicit
  close path.
- The client is still created once per provider instance and **reused** across
  `health()` / `generate()` calls — no per-request clients, pools, or factories.

### `aclose()` behavior

Added `OpenAICompatibleModelProvider.aclose()`:

- Provider-created client → `await client.aclose()`.
- Caller-injected client → no-op (never closed by the adapter).
- Idempotent: after the first close, `_owns_http_client` is cleared so repeated
  calls are no-ops (and `httpx.AsyncClient.aclose()` is itself idempotent).

Added a trivial `async with` context manager (`__aenter__`/`__aexit__` delegating
to `aclose()`) so provider-owned client lifecycle can be scoped explicitly.

**`ModelProviderPort` was NOT changed.** `aclose()` is adapter resource
lifecycle, not yet a universal port requirement.

### `httpx.InvalidURL` boundary

- `generate()`: an `httpx.InvalidURL` during request construction/execution is
  wrapped as `ModelProviderError("OpenAI-compatible base_url is invalid")`,
  following the existing Step 8 provider-error strategy. The malformed URL text
  is not included in the message.
- `health()`: an `httpx.InvalidURL` maps to
  `ModelProviderHealthStatus.CONFIGURATION_INVALID` with `available = False`
  (configuration failure, not runtime unavailability). `health()` still never
  raises.

### Blank/whitespace base URL

The existing `.strip()` guards already treated `""` and `"   "` as blank:
`health()` → `CONFIGURATION_INVALID`, `generate()` → `ModelProviderError`
("base_url is not configured"). No generalized configuration validator was
added; `model_name` semantics are unchanged.

### Tests

Added 9 tests to `backend/tests/test_openai_compatible_model_provider.py`:

- `test_provider_owned_client_is_closed_by_aclose` — provider-created client
  reports `is_closed` via `httpx` after `aclose()`.
- `test_aclose_does_not_close_injected_client` — injected client stays open,
  remains usable, and can be closed by the caller afterward.
- `test_aclose_is_safe_to_call_repeatedly` — double `aclose()` never fails and
  leaves the client closed.
- `test_async_context_manager_closes_provider_owned_client` — `async with`
  closes the owned client on exit.
- `test_async_context_manager_does_not_close_injected_client` — `async with`
  leaves injected clients open.
- `test_generate_invalid_base_url_raises_provider_error` — `httpx.InvalidURL`
  is wrapped; no raw `httpx.InvalidURL`/`RequestError` escapes.
- `test_generate_invalid_base_url_error_message_has_no_url` — the wrapped error
  exposes no URL text.
- `test_health_invalid_base_url_returns_configuration_invalid` — malformed URL
  returns `available=False`, `CONFIGURATION_INVALID`, never raises.
- `test_generate_whitespace_only_base_url_fails_deterministically` — `"   "` is
  rejected before any HTTP client work.

No existing Step 8 tests were rewritten; all regression behavior is unchanged.

### Validation

- Targeted: `pytest tests/test_openai_compatible_model_provider.py tests/test_architecture.py` — **60 passed**.
- `ruff check src tests` and `mypy src` — clean (44 files).
- Full gate: `./scripts/test_all.sh` — green.

### Files changed

- `backend/src/ava/models/providers/openai_compatible/provider.py` —
  `_owns_http_client`, `aclose()`, `__aenter__`/`__aexit__`, `httpx.InvalidURL`
  caught in `generate()` and `health()`; docstrings updated.
- `backend/tests/test_openai_compatible_model_provider.py` — 9 lifecycle /
  invalid-URL tests added.
- `docs/Model Provider.md` — documented provider HTTP-client lifecycle.
- `docs/AVA_Phase_3_Implementation_Log.md` — this entry.

### Step 9 concerns (recorded, not implemented)

- A malformed base URL with an **out-of-range numeric port** (e.g.
  `http://localhost:99999/v1`) surfaces as an anyio `ExceptionGroup`, not an
  `httpx.InvalidURL`; that edge is not wrapped by this correction.
- `aclose()` is adapter-specific; promoting a close/lifecycle method onto
  `ModelProviderPort` is a later port decision.
- Trailing whitespace in `base_url` (e.g. `"http://host/v1 "`) is not stripped
  by `rstrip('/')`; the blank-check only uses `strip()`. Left for Step 9
  configuration handling.

---

## Step 8B — Transport Configuration Boundary Hardening

**Status: COMPLETE**

### Goal

Close the final known transport-error leak in `OpenAICompatibleModelProvider`:
an out-of-range port (`http://localhost:99999/v1`) could surface as an anyio
`ExceptionGroup` from the async transport stack — not an `httpx.InvalidURL` or
`RequestError` — and escape the `ModelProviderPort` boundary. Fixed by
validating the configured base URL **before I/O** rather than broadening the
exception handlers.

### Validation/normalization strategy

- Added a provider-local `_base_url_config_valid(base_url)` helper using the
  standard-library `urllib.parse.urlsplit`. It validates only what this adapter
  needs: an `http`/`https` scheme, a hostname, and (when present) an in-range
  numeric port. No generalized URL-validation framework was created.
- `base_url = base_url.strip()` is applied at construction, so harmless outer
  whitespace (`"  http://localhost:11434/v1/  "`) is normalized before URL
  assembly. Path content is untouched and `rstrip('/')` still prevents double
  slashes.
- The helpher is consulted in `health()` and `generate()` **before** any HTTP
  client call, so malformed configuration never reaches the transport stack.
  The Step 8A `httpx.InvalidURL` catches remain as defense in depth. No broad
  `except Exception` was introduced.

### Exact malformed-URL behavior

Rejected structurally (bad scheme, missing host, non-numeric/out-of-range/zero
port):

- `generate()` → `ModelProviderError("OpenAI-compatible base_url is invalid")`
  (static/sanitized message; no URL, no API key, no transport internals).
- `health()` → `ModelProviderHealth(available=False,
  status=CONFIGURATION_INVALID, message="base_url is not a valid URL")`,
  never raising.

`http://localhost:11434/v1` and `http://localhost:11434/v1/` still produce the
same endpoint paths as before (`.../v1/chat/completions`, `.../v1/models`).

### Tests

Added 9 cases to `backend/tests/test_openai_compatible_model_provider.py`:

- `test_generate_out_of_range_port_raises_provider_error` — out-of-range port
  → `ModelProviderError`, never `ExceptionGroup`/`httpx.RequestError`.
- `test_generate_out_of_range_port_is_rejected_before_io` — a mock transport
  handler is never invoked for malformed configuration.
- `test_health_out_of_range_port_returns_configuration_invalid` — `available =
  False`, `CONFIGURATION_INVALID`, no exception.
- `test_base_url_outer_whitespace_is_normalized` — `"  .../v1/  "` produces
  `.../v1/chat/completions` (generation) and `.../v1/models` (health), no
  spaces, no path double slash.
- `test_malformed_base_url_is_contained_for_generate_and_health` (parametrized
  over zero port, missing scheme, missing host, non-numeric port, unsupported
  scheme) — both operations fail deterministically as configuration.

Existing valid-URL and Step 8A lifecycle tests are unchanged and green.

### Validation

- Targeted: `pytest tests/test_openai_compatible_model_provider.py tests/test_architecture.py` — **69 passed**.
- `ruff check src tests` and `mypy src` — clean (44 files).
- Full gate: `./scripts/test_all.sh` — green.

### Files changed

- `backend/src/ava/models/providers/openai_compatible/provider.py` —
  `_base_url_config_valid()` (stdlib `urlsplit`), construction-time
  `base_url.strip()`, pre-I/O configuration checks in `health()` and
  `generate()`; docstrings updated.
- `backend/tests/test_openai_compatible_model_provider.py` — transport
  configuration boundary tests added (45 → 54).
- `docs/Model Provider.md` — documented pre-I/O validation and whitespace
  normalization.
- `docs/AVA_Phase_3_Implementation_Log.md` — this entry.

### Remaining risks (recorded, not implemented)

- A base URL with **embedded** whitespace (e.g. `"http://host/v1 /model"`)
  still reaches the transport and surfaces as a wrapped `RequestError`
  (`ConnectError`) rather than a config-invalid detection; the adapter only
  strips outer whitespace.
- `model_name` remains unvalidated beyond the existing blank check; broader
  provider/model validation is Step 9 territory.

---

## Step 9 — Local Ollama Configuration and Provider Composition

**Status: COMPLETE**

### Goal

Make the configured provider identity `local` (the default) resolve in
production composition to a real, constructed `OpenAICompatibleModelProvider`
targeting a local Ollama `/v1` endpoint — without starting an Ollama process,
without network activity at startup, and without changing the run path
(`POST /runs` still flows through `RunService → AgentPort →
MockAgentAdapter`).

### Summary

```text
Environment → Settings.local_model_base_url
                         ↓ (infrastructure/composition.py)
          OpenAICompatibleModelProvider(base_url=..., model_name=...,
                                        provider_name="local")
                         ↓
          ModelProviderRegistry (register "local")
                         ↓
          ModelProviderResolver → composed in the API factory (app.state)
```

### Configuration

- Added `Settings.local_model_base_url`, read from the new environment
  variable `AVA_LOCAL_MODEL_BASE_URL` with default
  `http://localhost:11434/v1` (Ollama's OpenAI-compatible base). No synonym
  variables exist; `Settings` is the only reader.
- **`ApplicationConfig` decision:** `local_model_base_url` is deliberately
  **not** added to the framework-neutral `ApplicationConfig`. It is a
  transport/endpoint detail; the composition layer consumes it directly from
  `Settings`, so infrastructure-specific configuration stays out of core.
- `AVA_MODEL_NAME` remains the one canonical model-identifier field; the local
  provider sends it as the chat-completions `model` value.

### Provider construction

- Provider construction lives in `backend/src/ava/infrastructure/composition.py`
  (beside `_AGENT_ADAPTER_FACTORIES`, per the architecture audit):
  - `create_model_provider_registry(settings)` — builds a registry and, when
    `model_provider == "local"`, registers a real `local` provider. Unknown
    configured identities register nothing; startup never fails eagerly for an
    unknown identity (resolution reports `UnknownModelProviderError`).
  - `_create_local_model_provider(settings)` — constructs
    `OpenAICompatibleModelProvider(base_url=settings.local_model_base_url,
    model_name=settings.model_name, provider_name="local", api_key=None)`.
    No API key for local; capabilities stay the default conservative
    `chat=True, everything else False`.
  - `close_model_providers(registry)` — adapter-specific lifecycle: awaits
    `aclose()` on every provider exposing it (the provider-owned HTTP client
    is closed; injected test clients are never touched).
- `ModelProviderPort` was **not** changed; `aclose()` remains adapter-specific
  and infrastructure-localized.

### Application wiring

- `create_app()` composes the registry once and stores
  `app.state.model_provider_registry` and `app.state.model_provider_resolver`
  (resolver composed over the same registry instance).
- A FastAPI lifespan handler runs shutdown cleanup:
  `await close_model_providers(app.state.model_provider_registry)`.
- `app.py` never imports the concrete provider — the existing architecture
  guard makes that impossible; it reaches it only through composition.

### Resolver behavior (unchanged)

- Resolution is provider-neutral: no `if provider_id == "local"` anywhere in
  the resolver. `resolve("local")` returns the registered port;
  `resolve("<unknown>")` still raises `UnknownModelProviderError`.

### Network behavior

- No Ollama process management, no `/v1` auto-append, no API-key wiring, no
  startup probe. Composing the application and serving `/health` never contact
  a provider runtime; a configured base URL is only exercised when `health()`
  or `generate()` is actually called.

### Tests

Settings (`tests/test_settings.py`):

- `AVA_LOCAL_MODEL_BASE_URL` added to the `_AVA_VARS` cleared-env set.
- Default endpoint asserted in the default-settings test.
- New: `test_local_model_base_url_default_is_the_local_ollama_endpoint`;
  `test_local_model_base_url_env_override_changes_only_local_base_url`;
  independence assertions added to the `model_provider` override test.

New `tests/test_model_provider_composition.py` (9 tests) — no live network:

- Registry: default settings compose+register `local` (provider-neutral
  `ModelProviderPort` assertions); env-driven base URL flows into the composed
  provider (`_base_url` construction detail used as the only cable without a
  network call); resolver over the populated registry.
- Unknown identity: registers nothing, and resolution raises
  `UnknownModelProviderError` with `.provider_id`.
- Application: `create_app()` + `TestClient` `/health` succeed without any
  provider runtime; registry and resolver are exposed on `app.state` over the
  same instance.
- Lifecycle: `close_model_providers()` closes the provider-owned client;
  FastAPI lifespan shutdown closes it after `TestClient` context exit.

Architecture (`tests/test_architecture.py`):

- New `test_provider_construction_is_localized_to_infrastructure`: the
  concrete provider may be imported only by its own package and by
  `infrastructure/composition.py` across all of `src/ava`.

### Validation

- Backend suite: **225 passed** (213 → 225).
- Targeted: settings, composition, architecture, health, runs, capabilities —
  **69 passed**.
- `ruff check src tests` and `mypy src` — clean (44 files).
- Full gate: `./scripts/test_all.sh` — green.

### Files changed

- `backend/src/ava/configuration/settings.py` — `local_model_base_url` field
  (`AVA_LOCAL_MODEL_BASE_URL`, default `http://localhost:11434/v1`).
- `backend/src/ava/infrastructure/composition.py` — model-provider registry
  construction, local provider factory, `close_model_providers()`.
- `backend/src/ava/api/app.py` — composed registry/resolver on `app.state`,
  FastAPI lifespan shutdown cleanup.
- `backend/tests/test_settings.py`, `backend/tests/test_model_provider_composition.py`,
  `backend/tests/test_architecture.py` — new tests / guard.
- `docs/Model Provider.md`, `docs/Local Development.md`, `.env.example` — docs.
- `docs/AVA_Phase_3_Implementation_Log.md` — this entry.

### Remaining risks / Step 10 questions (recorded, not implemented)

- The run path still ignores the model provider entirely: `RunService` uses
  `AgentPort` (MockAgentAdapter), and no service or route consumes the
  registry/resolver yet. Step 10 decides whether/when the run path begins to
  couple to a model provider.
- A base URL with **embedded** whitespace still reaches the transport and
  surfaces as a wrapped `RequestError`; only outer whitespace is normalized
  (from Step 8B).
- `model_name` remains unvalidated beyond the blank check (recorded from
  Step 8B).
- No Ollama process management: the endpoint is expected to be running already
  (documented in `docs/Local Development.md`).

---

## Step 10 — Model Provider Health and Discovery

**Status: COMPLETE**

### Goal

Answer "what model providers are available, and are they healthy?" with a
read-only discovery endpoint — without touching the run path (`POST /runs`
still flows through `RunService → AgentPort → MockAgentAdapter`), without
startup I/O, and without any concrete provider leaking into services or the
API layer.

### Overview

```text
GET /model-providers
        ↓ app.state.model_provider_discovery_service
ModelProviderDiscoveryService (registry + configured default provider id)
        ↓ registry.list() / registry.get()
ModelProviderPort (health(), get_model_info())
        ↓
ModelProviderDiscoveryResponse (provider items reusing ModelInfo + health)
```

### Discovery contracts

Added to `backend/src/ava/contracts/responses.py` (available through
`ava.contracts`):

- `ModelProviderDiscoveryItem` — `provider_id`, `is_default`, `model_info`
  (`ModelInfo`, reused), `health` (`ModelProviderHealth`, reused),
  `contract_version`. No parallel model vocabulary is introduced: identity,
  capabilities, and health are exactly what the adapter reports through the
  port.
- `ModelProviderDiscoveryResponse` — `contract_version`,
  `default_provider_id`, `providers: list[ModelProviderDiscoveryItem]`.

`default_provider_id` truthfully reports the configured default provider
identity (from `Settings.model_provider`, decided at composition). It may or
may not appear in `providers`: an unknown/unregistered default is represented
as-is and never fabricates an entry.

### Service design

`backend/src/ava/services/model_provider_discovery_service.py`:

- `ModelProviderDiscoveryService(registry=..., default_provider_id=...)`
  depends only on `ModelProviderRegistry` (a pure container), the
  `ModelProviderPort`, and AVA contracts — never adapters, HTTP clients,
  configuration, agent layers, or runtime frameworks.
- Reads the registry through its public surface only (`list()` / `get()`);
  it does not know which provider ids are "special" and does not know the
  word `local`. The resolver is **not** injected (discovery enumerates, it
  does not resolve).
- `discover()` enumerates providers in registry insertion order, calling
  `get_model_info()` and `await provider.health()` per provider (sequential).
- A bare `except Exception` at `_probe` is the isolation boundary: a raising
  port implementation becomes a sanitized
  `ModelProviderHealth(available=False, status=UNAVAILABLE,
  message="Model provider health check failed")`. Other providers are still
  returned; raw exceptions never escape discovery; no exception hierarchy was
  added.

### API endpoint

`backend/src/ava/api/routes/model_providers.py` — `GET /model-providers`
(a dedicated resource endpoint; **not** an extension of `/capabilities`,
which reports application capability names). The route reads the discovery
service from `app.state` and contains no business logic, and it never imports
a concrete provider. The existing `/capabilities` contract is unchanged.

`create_app()` composes the discovery service over the **existing**
`model_provider_registry` (never a second registry) using
`settings.model_provider` as the default id, stores it as
`app.state.model_provider_discovery_service`, and includes the router.

### Health behavior

- The service never performs its own network probes — the adapter's
  `health()` does (`GET /models` inside `OpenAICompatibleModelProvider`).
- One failing provider does not break discovery for the others.
- Adapters normally never raise (`health()` returns a report); a raising
  third-party port implementation is sanitized to `UNAVAILABLE`.
- **No startup health checks**: startup stays network-free with Ollama
  offline. The endpoint is exercised only when called.

### Default provider representation

Unknown configured defaults (e.g. `model_provider="corporate"` with only
`local` registered) yield `default_provider_id="corporate"`, the registered
providers listed normally with `is_default=False`, and no startup failure, no
fake provider, and no silent substitution.

### Tests

- `backend/tests/test_contracts.py` (+3): item serialization; response
  serialization with an empty provider list; response embedding nested
  `ModelInfo` + `ModelProviderHealth` with `contract_version`.
- New `backend/tests/test_model_provider_discovery_service.py` (8 tests, stub
  `DiscoveryProvider`): single healthy provider; only the configured default
  flagged; registry insertion order; unhealthy report passed through;
  raising health isolated (sanitized, other providers still returned, no
  exception text leaks); per-provider model info; empty registry is truthful;
  unknown configured default is truthful and harmless.
- New `backend/tests/test_model_providers.py` (3 tests): the composed local
  provider is exercised **for real** with `httpx.MockTransport` (no live
  localhost, no real network) — reachable → `HEALTHY`; connection refused →
  `RUNTIME_UNAVAILABLE` without raising; and the mock path (never a real
  endpoint) is asserted.
- `backend/tests/test_architecture.py` (+1): new guard
  `test_model_provider_discovery_service_imports_only_contracts_and_model_ports`
  — the service imports only `ava.contracts` / `ava.models`, never concrete
  providers, HTTP clients, configuration, agents, or outward layers. The
  route-side boundary (API layer never imports concrete providers) was
  already enforced.

Frontend (typed-client support only, no UI): `@ava/contracts` gained
`model_providers.ts` (`ModelProviderDiscoveryItem` /
`ModelProviderDiscoveryResponse`), and `@ava/api-client` gained
`getModelProviders()` plus a vitest mirror of the endpoint payloads.

Python client: `ava_client.models` mirrors the discovery models
(`ModelProviderHealthStatus`, `ModelProviderHealth`, `ModelCapabilities`,
`ModelInfo`, `ModelProviderDiscoveryItem`, `ModelProviderDiscoveryResponse`),
`AvaClient.model_providers()` fetches the endpoint, and
`test_models.py` validates the backend-shaped payload.

### Scope boundaries honored

- Run path unchanged; `RunService`, `AgentPort`, and `MockAgentAdapter` are
  untouched.
- No model-backed native agent, no `RunService` integration, no model
  existence validation, no Ollama process management, no model install, no
  auto-selection, no compatibility validation, no runtime abstraction, no
  frontend UI. Streaming / tool calling / embeddings / RAG / persistence
  remain unimplemented.
- `close_model_providers` was not redesigned; the Step 9 architecture
  checkpoint's multi-provider shutdown caveat (a raising `aclose()` aborts
  remaining cleanups) is recorded, not fixed.

### Validation

- Targeted: contracts, discovery service, API route, architecture, settings,
  composition, health/runs/capabilities — **85 passed**.
- Backend suite: **240 passed** (225 → 240); `ruff check src tests` and
  `mypy src` clean (46 files).
- Frontend `pnpm -r test` and `pnpm -r lint` (tsc) — green.
- Python client pytest/ruff/mypy — green.
- Full gate: `./scripts/test_all.sh` — green.

### Files changed

- `backend/src/ava/contracts/responses.py` — discovery response contracts.
- `backend/src/ava/contracts/__init__.py` — exports.
- `backend/src/ava/services/model_provider_discovery_service.py` — new
  service.
- `backend/src/ava/api/routes/model_providers.py` — new `GET /model-providers`
  route.
- `backend/src/ava/api/app.py` — composed + wired the discovery service.
- `backend/tests/test_contracts.py`, `backend/tests/test_model_provider_discovery_service.py`,
  `backend/tests/test_model_providers.py`, `backend/tests/test_architecture.py`.
- `frontend/packages/contracts/src/model_providers.ts` (+ index export).
- `frontend/packages/api-client/src/model_providers.ts`, `model_providers.test.ts`
  (+ index export).
- `clients/python/src/ava_client/models.py`, `client.py`, `__init__.py`,
  `clients/python/tests/test_models.py`.
- `docs/Model Provider.md`, `docs/Contract Standards.md`,
  `docs/AVA_Phase_3_Implementation_Log.md` — this entry.

### Remaining risks / Step 11 questions (recorded, not implemented)

- Discovery is read-only by design; no endpoint here ever selects or starts a
  provider. Wiring the discovered provider into the run path is a later step.
- `is_default` requires the discovery layer to know the configured default;
  the registry and resolver still do not, preserving their neutrality.
- Recording the Step 9 checkpoint caveat: `close_model_providers()` has no
  per-provider error isolation — a raising `aclose()` aborts later cleanups.
  Not addressed in this step.
- The multi-provider shutdown error-isolation caveat above remains open for a
  future lifecycle hardening step.

## Step 11 — Native Model-Backed AVA Agent

Status: COMPLETE

### Architecture and API

`POST /runs → RunService → AgentPort → NativeAgentAdapter → ModelProviderPort`.
The native constructor accepts only `model_provider: ModelProviderPort`.
Its unchanged port methods are `name()`, `get_capabilities()`,
`start_run(run_id, request) -> AgentRunResult`, and
`cancel_run(run_id) -> RunResponse`. Identity is `native`; capabilities are
exactly `RUNS` and `CANCELLATION`. No provider metadata determines application
capabilities or model selection.

`RunRequest.prompt` maps unchanged to
`ModelRequest(messages=[ModelMessage(role="user", content=request.prompt)])`.
No system prompt, history, tools, or generation overrides are added.
`ModelResponse.content` becomes completed `AgentRunResult.content`.
`ModelProviderError` and unexpected ordinary `Exception` values become failed
results with stable content `Model provider request failed`. Unexpected errors
are logged internally; exception text is never returned to clients.
`CancelledError` becomes cancellation, not failure. No `BaseException` catch
is introduced. **RunService remains unchanged and model-provider-free**;
it owns all event construction, including its existing sanitized failure payload.

### Cancellation and ownership

Each adapter tracks active generation tasks by AVA run id, inserts them before
awaiting generation, and removes them in `finally` after success, failure, or
cancellation. Cancel requests target only the selected run. Repeated cancellation
is a no-op; finished runs return their recorded outcome and unknown runs return
cancelled, matching the mock contract. Lightweight terminal statuses are retained
in memory for that behavior, but completed tasks and model responses are not.
Cancellation wins even if a provider suppresses cancellation and returns content
or raises an ordinary error during cleanup. Cancellation of the awaiting start
task also cancels generation and produces the normal cancelled lifecycle.

Task cancellation is cooperative: a provider that suppresses cancellation and
continues indefinitely can delay task cleanup and the original start response.
Cancelling local HTTP work cannot guarantee the remote server stops inference.
No provider close operation is called by the agent; composition/lifespan still
owns provider shutdown.

### Composition and configuration

Settings → ApplicationConfig; Settings → registry → resolver → resolved
ModelProviderPort → NativeAgentAdapter → RunService. Registry/resolver are
created once before agent selection; discovery uses the same registry and
native execution receives the same registered provider instance.

- `AVA_AGENT_PROVIDER=mock` remains the default and never resolves a model,
  including when `AVA_MODEL_PROVIDER=unknown`.
- `AVA_AGENT_PROVIDER=native` resolves `AVA_MODEL_PROVIDER`; unknown identities
  raise `UnknownModelProviderError`, without fallback.
- Composition performs no provider `health()` or `generate()` I/O. Native
  startup works with the local runtime offline; runs can fail normally later.
- Automated tests use test-only deterministic/controllable providers. No live
  Ollama, internet access, API credentials, or local model runtime is required.

### Tests and validation

Native tests verify translation, sanitized expected/unexpected errors, task
cleanup, truthful capabilities, direct and external cancellation, concurrent-run
isolation, and providers suppressing cancellation. HTTP tests traverse production
native composition with a test registry, proving:

- Success: `run_started → message_started → message_content → run_completed`.
- Both failure classes: `run_started → run_failed`, HTTP 200 with failed run
  state, no raw error leakage, and no stranded RUNNING state.
- RunService cancellation: `run_started → run_cancelled`, exactly one terminal
  event, no failure/completion event, and provider task cleanup.

Composition tests verify mock independence, native unknown-provider failure,
shared provider identity, network-free startup, and lifespan-owned shutdown.
An additive native architecture guard permits only stdlib and AVA contracts/
ports, including `ava.models.errors` (the repository's existing AVA error
contract). The mock guard is unchanged. A separate guard keeps RunService free
of model-provider imports.

Validation on 2026-09-14:

- Initial targeted regression suite: 131 passed. Three extra cancellation
  regression cases added afterward also passed in the full gate.
- `./scripts/test_all.sh`: PASS (exit 0).
- Backend: 257 tests passed; Ruff clean; mypy clean (49 source files).
- Frontend: 171 tests passed; all configured TypeScript lint checks passed.
- Python client: 2 tests passed; Ruff and mypy clean.
- Two existing FastAPI/Starlette test-client deprecation warnings remain.
- The sandbox stalled FastAPI TestClient even on an existing mock test;
  approved execution outside the sandbox passed without changing/skipping tests.

### Files changed for Step 11

- `backend/src/ava/agents/adapters/native/__init__.py`
- `backend/src/ava/agents/adapters/native/native_agent.py`
- `backend/src/ava/infrastructure/composition.py`
- `backend/src/ava/api/app.py`
- `backend/tests/test_native_agent.py`
- `backend/tests/test_model_provider_composition.py`
- `backend/tests/test_architecture.py`
- `.env.example`
- `docs/Agent Adapter.md`
- `docs/Model Provider.md`
- `docs/AVA_Phase_3_Implementation_Log.md`

Earlier uncommitted Phase 3 work was preserved.

### Remaining risks and scope

The multi-provider shutdown error-isolation caveat remains: one raising
`aclose()` can prevent subsequent provider cleanups. Terminal run statuses,
like existing service/mock state, remain in memory without eviction. Cooperative
cancellation limitations are documented above. Streaming and tools are absent.
No concrete provider, settings, registry, or resolver is imported by the native
agent. No RunService model dependency, runtime abstraction, AgentRuntimePort,
streaming, tools, RAG, or Step 12 work was introduced. Step 11 stops here.

## Step 12 — Real Local Model Vertical Slice Validation

Status: COMPLETE

Validated 2026-09-14 against the actual local runtime. Overall result: PASS.
No production code changes or new automated tests were necessary.

### Environment and effective configuration

- Ollama client/server version: `0.33.3`.
- Installed model: `qwen2.5-coder:7b`, local ID `dae161e27b0e`, size `4.7 GB`.
- Runtime reachable; `ollama ps` initially showed no loaded model.
- No repository-root or backend `.env` was present. Validation used process-local
  environment variables read by the existing Settings/composition path:

```dotenv
AVA_AGENT_PROVIDER=native
AVA_MODEL_PROVIDER=local
AVA_MODEL_NAME=qwen2.5-coder:7b
AVA_LOCAL_MODEL_BASE_URL=http://localhost:11434/v1
```

The default remains mock. No credentials, installations, downloads, runtime
restarts, or saved configuration changes were made. The execution sandbox
blocked localhost sockets; live checks ran with approved access outside it.

### Method and provider discovery

A temporary manual harness launched the unchanged production `create_app()`
under Uvicorn on an OS-assigned loopback port. An ordinary HTTP client called
AVA routes over TCP. The provider used its real HTTP client and the actual
Ollama endpoint; no test doubles or direct Ollama generation calls were used.
The temporary harness is not part of the repository or default test suite.

Before generation:

- `GET /health`: HTTP 200, application `AVA`, status `healthy`.
- `GET /model-providers`: HTTP 200, `default_provider_id=local`, one provider
  with `provider_id=local`, `is_default=true`, and
  `model_info.model_id=qwen2.5-coder:7b`.
- Provider health: `available=true`, `status=healthy`, `message=null`.

Discovery successfully exercised the adapter's `GET /v1/models` request.
No model-existence validation or discovery parsing changes were introduced.

### Real generation and retrieval evidence

Prompt: `Reply with exactly: AVA LOCAL MODEL OK`.

`POST /runs`: HTTP 200, elapsed approximately **11.460 seconds**, including
initial model loading and response generation (observational, not a benchmark).

```json
{
  "run_id": "46b21ac1-aefb-415c-b275-614823e45fd9",
  "status": "completed",
  "contract_version": "v1"
}
```

Actual assistant content: **AVA LOCAL MODEL OK**.

`GET /runs/46b21ac1-aefb-415c-b275-614823e45fd9` returned the same response.
The events endpoint returned exactly:

```text
run_started      2026-09-14T21:03:16.100806Z
message_started  2026-09-14T21:03:27.555774Z
message_content  2026-09-14T21:03:27.555796Z
run_completed    2026-09-14T21:03:27.555820Z
```

Message role was `assistant`; the started/content events shared an AVA message
id. Content was non-empty and precisely matched the requested text. Public run
and event responses contained AVA contracts, not compatible-provider response
JSON, HTTP types, or model/endpoint fields in run payloads. All active native
run tasks were removed after completion.

### Real transport-failure evidence

After success, a second temporary AVA instance used the same native/local/model
settings with base URL `http://127.0.0.1:44173/v1`. This port was reserved locally
without a listener, guaranteeing a refused connection without touching Ollama
or unrelated processes. No fake provider or mock HTTP transport was involved.

- Application still started and `/health` returned HTTP 200, `healthy`.
- Discovery returned `available=false`, `status=runtime_unavailable`, message
  `Could not connect to the OpenAI-compatible endpoint`.
- `POST /runs`: HTTP 200, approximately **0.006 seconds**, status `failed`.
- Run id: `f78a7ba5-aeb3-47ff-8b3f-2508ab1cb8c1`.
- Retrieval matched the failed response; events were exactly
  `run_started → run_failed`, with no RUNNING state left behind.
- Failure event payload:

```json
{
  "error_code": "agent_failed",
  "message": "The agent failed to complete the run.",
  "recoverable": false
}
```

This is the existing RunService wording. The native adapter internally produces
`Model provider request failed`; RunService normalizes it to the above public
payload. No raw URL, httpx error, stack trace, or provider body was exposed.
Tasks were cleaned up. Temporary AVA servers shut down normally and closed
their owned clients. The temporary endpoint override was restored before the
harness exited; saved configuration and Ollama remained untouched.

### Cancellation and architectural verification

Live cancellation is **not externally testable with the current synchronous
route**: `POST /runs` awaits completion and only then returns its generated
run id. There is no public active-run listing or early id response. Automated
Step 11 cancellation tests remain authoritative; no API behavior was changed.

Startup remains network-free: inspection confirms constructors perform no
`health()` or `generate()` calls, and the real unreachable-endpoint instance
started successfully. Discovery explicitly triggers health I/O; `POST /runs`
triggers generation I/O. Existing deterministic startup guards also passed.

The live harness asserted that the native agent's provider is the exact
registered/resolved provider and discovery holds the same registry. No second
execution provider was constructed. Inspection confirms only the compatible
provider adds its configured model name to the wire request; neither native
agent, RunService, nor route selects it. RunService remains provider-free.

### Automated gate and builds

After live validation:

- `./scripts/test_all.sh`: PASS, exit 0.
- Backend: **257 passed**; Ruff clean; mypy clean (49 source files).
- Frontend: **171 passed**; configured TypeScript lint/typechecks passed.
- Python client: **2 passed**; Ruff and mypy clean (3 source files).
- `./scripts/build_all.sh`: PASS, exit 0 (configured web/desktop frontend
  application builds; not native desktop packaging).
- Existing FastAPI/Starlette deprecation warnings and Vite's bundle-size
  warnings remain informational. No checks were skipped or weakened.

The deterministic suite remains independent of Ollama, installed models,
credentials, and internet. No live test was added to the default harness.

### Documentation and remaining risks

Updated this log and `docs/Local Development.md` with an optional manual
procedure. Production code changes: **None**.

Remote inference cancellation remains cooperative. The multi-provider shutdown
error-isolation caveat remains (one failing close may prevent later closes).
No streaming or tools are supported. This installed model obeyed the short
prompt exactly; other prompts and cold starts can differ. The existing
30-second provider HTTP timeout remains relevant for slower generation.
Run/event storage remains in memory and disappeared when validation servers
stopped; the evidence above records the retrieved results.

No runtime abstraction, framework integration, streaming/tools/RAG, model or
process management, or Step 13 work was performed. Step 12 stops here.

## Step 13 — Agent Runtime Port

Status: COMPLETE

### Purpose and independence

Agent runtime selection and model-provider selection are independent axes.
`AgentRuntimePort` receives the selected `ModelProviderPort` at execution time
rather than owning or resolving a model provider itself.

The new `ava.runtimes` package defines an abstraction only. No production
runtime implementation exists yet, and runtime selection does not work yet.
The validated Step 12 native model execution path remains unchanged:

```text
RunService → AgentPort → NativeAgentAdapter → ModelProviderPort
           → OpenAICompatibleModelProvider → Ollama
```

### Port and internal result

Defined in `backend/src/ava/runtimes/contracts.py`, exported from
`backend/src/ava/runtimes/__init__.py`:

```python
class RuntimeRunResult(BaseModel):
    status: RunStatus
    content: str | None = None

class AgentRuntimePort(ABC):
    @abstractmethod
    def get_runtime_info(self) -> RuntimeInfo: ...

    @abstractmethod
    async def execute(
        self,
        *,
        run_id: str,
        request: RunRequest,
        model_provider: ModelProviderPort,
    ) -> RuntimeRunResult: ...

    @abstractmethod
    async def cancel_run(self, run_id: str) -> RuntimeRunResult: ...
```

`RuntimeRunResult` is an internal Pydantic DTO independent of `AgentRunResult`,
not a wire response. Implementations normalize COMPLETED, FAILED, and CANCELLED
through the existing `RunStatus`. No new enum, terminal-only validator, or
extra fields were added. Content is optional assistant text or sanitized
failure text. Existing `RunRequest` is reused without modification.

The port reuses canonical `RuntimeInfo`, which contains `RuntimeCapabilities`.
Runtime capabilities describe execution framework functionality; they remain
separate from `ModelCapabilities` and application `CapabilityName` values.
There is no duplicated runtime metadata vocabulary.

`model_provider` is a required keyword-only execution input, not constructor
state or a provider/model id. The caller owns provider selection, configuration,
and lifecycle. The same runtime instance can accept different providers on
successive calls without changing its identity.

Cancellation uses the AVA-generated `run_id` supplied to execution. Future
implementations keep task/session/remote identifiers private, normalize effective
cancellation to CANCELLED, report prior terminal outcomes for finished runs,
and treat repeated or unknown-run cancellation as idempotent. Cancellation
remains cooperative; no framework handles appear in this interface.

### Dependencies and guards

Actual imports in the runtime contract module:

- `abc.ABC`, `abc.abstractmethod`
- `pydantic.BaseModel`
- `ava.contracts.requests.RunRequest`
- `ava.contracts.responses.RunStatus`
- `ava.contracts.runtimes.RuntimeInfo`
- `ava.models.contracts.ModelProviderPort`

The dedicated runtime architecture guard permits only stdlib, Pydantic for
internal DTOs, AVA data contracts, and the model port (plus the package's own
contract re-export). It rejects agent-layer dependencies, concrete providers,
registries/resolvers, settings, API/services/core/infrastructure, and external
framework/transport libraries. Relative imports cannot bypass the guard.
Additional tests enforce that model/data contracts do not depend back on the
runtime port, and RunService does not import runtime contracts. Existing
native/mock guards remain intact.

The baseline architecture audit now explicitly labels its obsolete wiring
proposals: neither model providers nor runtime orchestration should be injected
into RunService. Runtime orchestration stays behind AgentPort in future work.

### Tests and validation

`test_runtime_port.py` covers abstractness, omission of each required method,
complete test-only implementation, exact AVA type annotations, asynchronous
operations, keyword-only execution injection, and absence of a port constructor.
One test runtime accepts two distinct test ModelProviderPort instances configured
with different model ids, invokes each provider, and returns AVA results while
keeping the same runtime metadata. Cancellation receives the AVA run id.
Result cases cover completion with content, failure with/without content,
cancellation, minimal fields, defaults, and JSON round trips.

Validation on 2026-09-14:

- Targeted runtime/native/RunService/provider/composition/architecture tests:
  **123 passed**.
- `./scripts/test_all.sh`: PASS, exit 0.
- Backend: **270 passed** (10 new runtime cases, 3 new architecture guards);
  Ruff clean; mypy clean (51 source files).
- Frontend: **171 passed**; configured TypeScript checks passed.
- Python client: **2 passed**; Ruff/mypy clean.
- `./scripts/build_all.sh`: PASS, exit 0, configured web/desktop frontend builds.
- Existing FastAPI/Starlette deprecation and Vite bundle-size warnings remain.
- No Ollama, live-model calls, credentials, or downloads were required. Test
  execution used approved access outside the sandbox for FastAPI TestClient.

### Files changed for Step 13

- `backend/src/ava/runtimes/__init__.py`
- `backend/src/ava/runtimes/contracts.py`
- `backend/tests/test_runtime_port.py`
- `backend/tests/test_architecture.py`
- `docs/AVA_Phase_3_Architecture_Audit.md`
- `docs/AVA_Phase_3_Implementation_Log.md`

### Questions reserved for Step 14

Implementing NativeRuntime will need to decide how to maintain per-run task and
terminal state, preserve cooperative cancellation/cleanup, and normalize provider
and unexpected failures into sanitized RuntimeRunResult values. It must preserve
execution-time provider injection and caller-owned shutdown. These implementation
decisions are recorded only; no NativeRuntime implementation or agent migration
was attempted here.

### Scope confirmation

No NativeRuntime, RuntimeRegistry, RuntimeResolver, runtime configuration,
runtime selection, framework integration, streaming/tools/RAG, or Step 14 work.
AgentPort, NativeAgentAdapter, MockAgentAdapter, RunService, RunRequest,
composition, and the existing production execution path were not changed in
Step 13. Earlier uncommitted Phase 3 work was preserved. Stop here.

## Step 14 — Native Runtime

Status: COMPLETE

### Implementation and API

`backend/src/ava/runtimes/adapters/native/native_runtime.py` now provides
`NativeRuntime(AgentRuntimePort)`. It is not yet wired into production.

```python
NativeRuntime()
get_runtime_info() -> RuntimeInfo
async execute(
    *, run_id: str, request: RunRequest, model_provider: ModelProviderPort,
) -> RuntimeRunResult
async cancel_run(run_id: str) -> RuntimeRunResult
```

The constructor receives no provider or configuration. Runtime selection and
model-provider selection remain independent: every execute call supplies the
selected ModelProviderPort, with provider configuration/lifecycle caller-owned.

Metadata: `runtime_id="native"`, `display_name="AVA Native Runtime"`,
`contract_version="v1"`, and RuntimeCapabilities with all ten flags false:
`tools`, `multi_agent`, `shell`, `filesystem`, `browser`, `code_execution`,
`checkpointing`, `persistence`, `human_approval`, `parallel_execution`.
Cancellation and independently active asyncio tasks do not imply these features.
Metadata is fresh per call and is never inferred from model capabilities.

### Translation and normalized outcomes

RunRequest.prompt maps unchanged to one user ModelMessage inside ModelRequest.
No model id, provider id, system prompt, history, tools, generation limits, or
runtime policy is added. The supplied provider's generate method is called.

- ModelResponse.content → COMPLETED RuntimeRunResult with that content.
- ModelProviderError → FAILED, `Model provider request failed`.
- Unexpected ordinary Exception → internal exception log and the same sanitized
  FAILED result, without raw exception text in returned content.
- Explicit asyncio.CancelledError → CANCELLED, never FAILED.

No BaseException catch, agent-layer result, event emission, or service/store
access is introduced.

### Task ownership, duplicates, and cancellation

Each runtime instance owns `_run_tasks: dict[str, asyncio.Task[ModelResponse]]`
and lightweight `_final_status` entries. Tasks are registered before awaiting
provider work and removed in `finally` for success, either failure class, and
cancellation. Completed task/provider-response objects are not retained.

Duplicate active run ids return FAILED with `Run is already active` before
altering state or invoking the duplicate provider. The first task remains
reachable and cancellable. Reuse after a finished execution clears its old
status, so an earlier cancellation cannot contaminate new execution.

Active cancellation records CANCELLED and cancels the selected task once;
repeated cancellation does not interrupt provider cleanup again. Unknown ids
return a cancelled no-op. Finished ids return their recorded terminal status.
Cancellation while execution is still tracked wins over late provider content
or cleanup failures. Once execution records completion, later cancellation
reports COMPLETED. Cleanup and final status recording contain no intervening
await, avoiding a gap between those operations on the event loop.

Cancellation is cooperative: a provider that ignores it indefinitely can delay
cleanup. Remote inference may continue despite local task cancellation.
Terminal status history remains in memory without eviction, consistent with
existing agent semantics; there is no persistence or generic scheduler.

### Dependencies and ModelProviderError inspection

Actual imports: `asyncio`, `logging`, AVA ModelMessage/ModelRequest/ModelResponse,
RunRequest, RunStatus, RuntimeCapabilities/RuntimeInfo, ModelProviderPort,
ModelProviderError, and AgentRuntimePort/RuntimeRunResult.

The active compatible provider and native agent already import the generic
`ava.models.errors.ModelProviderError`, which NativeRuntime also uses. A separate
legacy definition exists at `ava.models.providers.errors`; it is not imported
by this implementation. No error file was moved or modified. Thus there is no
concrete-provider dependency or architectural blocker. An exception from the
legacy class would still be sanitized by the ordinary Exception boundary.

The Step 13 runtime-port guard now targets the package's top-level contract
modules, retaining their original restrictions. A separate implementation guard
covers runtime adapters and allows only stdlib, AVA contracts, model port/error,
and runtime port. It rejects agent, service, API, core, infrastructure,
configuration, registry/resolver, vendor/framework, and concrete provider imports.
Existing native-agent/mock guards remain unchanged.

### Test evidence and validation

Eleven new NativeRuntime cases cover successful request translation, expected
and unexpected errors (including internal logging), all task cleanup outcomes,
conservative/fresh metadata, active/repeated/unknown/post-completion cancellation,
external cancellation, reuse after cancellation, active duplicate rejection,
independent concurrent runs and instances, and providers suppressing cancellation
to return content or raise a cleanup error.

The same NativeRuntime instance executes against two distinct test provider
implementations: TestProvider yields `Native answer`, then FakeModelProvider
yields `reply to Hello`. Both are used without reconstructing the runtime;
no provider is stored on it.

Validation on 2026-09-14:

- Targeted runtime-port/native-runtime/model-port/architecture/native-agent/
  RunService/composition tests: **81 passed**.
- `./scripts/test_all.sh`: PASS, exit 0.
- Backend: **282 passed**; Ruff clean; mypy clean (54 source files).
- Frontend: **171 passed**; configured TypeScript checks passed.
- Python client: **2 passed**; Ruff/mypy clean.
- `./scripts/build_all.sh`: PASS, exit 0 (configured web/desktop frontend builds).
- Existing FastAPI/Starlette deprecation and Vite bundle-size warnings remain.
- No live Ollama validation was needed; automated tests remain model-independent.
  Tests ran with approved access outside the sandbox for FastAPI TestClient.

### Files changed for Step 14

- `backend/src/ava/runtimes/adapters/__init__.py`
- `backend/src/ava/runtimes/adapters/native/__init__.py`
- `backend/src/ava/runtimes/adapters/native/native_runtime.py`
- `backend/tests/test_native_runtime.py`
- `backend/tests/test_architecture.py`
- `docs/AVA_Phase_3_Architecture_Audit.md`
- `docs/AVA_Phase_3_Implementation_Log.md`

### Production path and scope

Production remains `RunService → NativeAgentAdapter → ModelProviderPort →
OpenAICompatibleModelProvider`. NativeRuntime exists but is not composed or
selectable. No AgentPort, runtime-port, NativeAgentAdapter, RunService, or
composition changes. No registry, resolver, runtime configuration, migration,
framework integration, streaming/tools/RAG, routing, persistence, or Step 15 work.
Earlier uncommitted Phase 3 changes were preserved.

### Questions reserved for Step 15

Registry work should settle duplicate/blank runtime-id registration behavior,
lookup/list semantics, and ownership of registered runtime instances. These
registry decisions are not implemented here. Stop at Step 14.

## Step 15 — Runtime Registry

Status: COMPLETE

### Pure runtime instance storage

`ava.runtimes.registry.RuntimeRegistry`, also exported through `ava.runtimes`,
stores already-created AgentRuntimePort instances. Its exact interface is:

```python
class RuntimeRegistry:
    def __init__(self) -> None: ...
    def register(self, runtime_id: str, runtime: AgentRuntimePort) -> None: ...
    def get(self, runtime_id: str) -> AgentRuntimePort | None: ...
    def contains(self, runtime_id: str) -> bool: ...
    def list(self) -> list[str]: ...
```

Registration rejects empty/whitespace-only ids with ValueError and rejects any
duplicate key, including registration of the same instance twice. The original
reference remains unchanged on failure. Nonblank ids are opaque and preserved
exactly: no trimming, case normalization, aliases, or special native key.
Registration does not call get_runtime_info or enforce a metadata-id match.

`get` returns the exact stored object or None; `contains` uses exact membership;
`list` returns a fresh list in deterministic insertion order. Returned-list
mutation does not affect the registry. Registries hold independent state.
These semantics mirror ModelProviderRegistry without modifying it or introducing
a generic shared abstraction.

The caller owns construction and lifecycle. This registry stores instance
references, not constructors/factories. It performs no execution, cancellation,
health checks, resolution, default selection, compatibility policy, or lifecycle
management. Its sole import is `ava.runtimes.contracts.AgentRuntimePort`.
There are no direct model/provider imports or assumptions: the runtime port's
execution-time model input is unrelated to container storage.

### Tests and architecture

Eleven registry cases use a test-only AgentRuntimePort implementation with no
provider state; its methods raise if invoked. Coverage includes empty state,
registration/identity, three blank inputs, duplicate-preservation with both the
same and different instances, multiple exact keys/insertion ordering, list
snapshot isolation, registry-instance isolation, and unknown lookup without
mutation. No production runtime is needed for these tests.

A dedicated registry guard permits only stdlib and the runtime contract import,
rejecting runtime adapters, models, agents, configuration, services, API, core,
infrastructure, and external libraries. The existing port guard is scoped to
contracts.py and package exports; only the package export gains permission to
re-export RuntimeRegistry. Native runtime and native-agent guards are unchanged.

### Validation

Validation on 2026-09-14:

- Targeted registry/runtime-port/native-runtime/architecture/model-registry/
  native-agent/composition suite: **88 passed**.
- `./scripts/test_all.sh`: PASS, exit 0 after fixing an import-spacing lint issue.
- Backend: **294 passed**; Ruff clean; mypy clean (55 source files).
- Frontend: **171 passed**; configured TypeScript checks passed.
- Python client: **2 passed**; Ruff/mypy clean.
- `./scripts/build_all.sh`: PASS, exit 0 (configured web/desktop frontend builds).
- Existing FastAPI/Starlette deprecation and Vite bundle-size warnings remain.
- No Ollama, credentials, or live model calls were required. Offline tests ran
  with approved access outside the sandbox for FastAPI TestClient compatibility.

### Files changed for Step 15

- `backend/src/ava/runtimes/registry.py`
- `backend/src/ava/runtimes/__init__.py`
- `backend/tests/test_runtime_registry.py`
- `backend/tests/test_architecture.py`
- `docs/AVA_Phase_3_Architecture_Audit.md`
- `docs/AVA_Phase_3_Implementation_Log.md`

### Production path and scope

Production remains `RunService → NativeAgentAdapter → ModelProviderPort`.
No RuntimeRegistry instance is composed, no NativeRuntime is registered, and
runtime selection does not exist yet. No AgentPort, NativeAgentAdapter,
RunService, ModelProviderPort, ModelProviderRegistry, ModelProviderResolver,
Settings, ApplicationConfig, create_app, or create_agent_adapter changes.
No RuntimeResolver, UnknownRuntimeError, runtime configuration, application
wiring, migration, discovery, framework integration, or Step 16 work.
Earlier uncommitted Phase 3 work was preserved.

### Questions reserved for Step 16

Resolver work should define explicit missing-id error semantics and how blank
resolution input is reported, while preserving exact registered instance
identity and avoiding implicit defaults. These resolution policies are not
implemented in the container. Stop at Step 15.

## Step 16 — Runtime Resolver

Status: COMPLETE

### API and resolution semantics

`ava.runtimes.resolver` introduces the following, also exported by `ava.runtimes`:

```python
class UnknownRuntimeError(ValueError):
    def __init__(self, runtime_id: str) -> None:
        self.runtime_id = runtime_id
        super().__init__(f"Unknown runtime: {runtime_id!r}")

class RuntimeResolver:
    def __init__(self, registry: RuntimeRegistry) -> None: ...
    def resolve(self, runtime_id: str) -> AgentRuntimePort: ...
```

RuntimeRegistry is injected; no registry is internally constructed or globally
stored. Registered ids resolve to the exact existing instance. Empty,
whitespace-only, and unknown ids raise UnknownRuntimeError, preserving the
original runtime_id. Nonblank keys are used unchanged; casing and trailing
spaces only resolve if that exact key exists. No defaults or native special
cases are introduced. Error messages contain only the unresolved id, never
registry contents or implementation details.

RuntimeRegistry remains unchanged: get returns an instance or None, while
resolve returns an instance or raises an explicit resolution error. Semantics
parallel ModelProviderResolver without modifying it or adding generic machinery.
The resolver never calls runtime metadata, capability, execution, cancellation,
or lifecycle methods and performs no network I/O.

### Independent axes and dependency direction

RuntimeRegistry/RuntimeResolver and ModelProviderRegistry/ModelProviderResolver
are parallel but independent systems. Future composition may resolve a runtime
and model provider separately, then pass the selected provider to
`runtime.execute(..., model_provider=model_provider)`. Neither resolver selects
the other axis. Default selection and configuration remain outside resolvers.

The exact imports in runtimes/resolver.py are:

- `ava.runtimes.contracts.AgentRuntimePort`
- `ava.runtimes.registry.RuntimeRegistry`

There is no model/provider, configuration, agent, service, core, API,
infrastructure, concrete runtime, or vendor dependency. A dedicated resolver
guard enforces those boundaries, including rejection of relative-import
bypasses. The package export guard permits the new resolver re-export;
registry and implementation guards remain unchanged.

### Tests and validation

Nine resolver test cases cover repeated exact-instance resolution without any
runtime method invocation (a port-spec mock records zero calls), unknown/empty/
whitespace ids, original id retained on errors, absence of fallback when native
is registered, non-normalized case/spacing, multiple distinct runtime objects,
exactly registered spaced/cased keys, unchanged registry contents/order, and
independent injected registries. Tests also demonstrate that a resolver sees
registrations made after its construction, rather than holding a copied registry.

Validation on 2026-09-14:

- Targeted resolver/registry/runtime-port/native-runtime/model-resolver/
  architecture/native-agent/composition tests: **98 passed**.
- `./scripts/test_all.sh`: PASS, exit 0.
- Backend: **304 passed**; Ruff clean; mypy clean (56 source files).
- Frontend: **171 passed**; configured TypeScript checks passed.
- Python client: **2 passed**; Ruff/mypy clean.
- `./scripts/build_all.sh`: PASS, exit 0 (configured web/desktop frontend builds).
- Existing FastAPI/Starlette deprecation and Vite bundle-size warnings remain.
- No Ollama, credentials, model installation, or network model calls required.
  Tests used approved access outside the sandbox for FastAPI TestClient.

### Files changed for Step 16

- `backend/src/ava/runtimes/resolver.py`
- `backend/src/ava/runtimes/__init__.py`
- `backend/tests/test_runtime_resolver.py`
- `backend/tests/test_architecture.py`
- `docs/AVA_Phase_3_Architecture_Audit.md`
- `docs/AVA_Phase_3_Implementation_Log.md`

### Production path and scope

Production remains `RunService → NativeAgentAdapter → ModelProviderPort`.
No runtime registry/resolver is constructed or populated in production, and
NativeRuntime remains unused there. No runtime configuration, defaults,
NativeRuntime registration, NativeAgentAdapter migration, RunService change,
runtime discovery, compatibility validation, framework integration, or Step 17
work was introduced. RuntimeRegistry, NativeRuntime, existing model/provider
classes, AgentPort, settings, and composition remain unchanged. Earlier
uncommitted Phase 3 changes were preserved.

### Questions reserved for subsequent configuration/composition work

Future work must specify the runtime configuration key/default and where
composition constructs and registers runtime instances, while preserving
independent model resolution. Those decisions are recorded only; runtime
selection is not operational in production. Stop at Step 16.

## Step 17 — Runtime Configuration and Production Composition

Status: COMPLETE

Added the canonical `AVA_AGENT_RUNTIME` setting with default `native`, mirrored
as `ApplicationConfig.agent_runtime`. It remains independent from
`AVA_AGENT_PROVIDER` (default `mock`) and the model-provider settings.

Infrastructure composition now constructs one `RuntimeRegistry`, registers one
caller-created `NativeRuntime` under `native`, and constructs one
`RuntimeResolver` over that registry. `create_app()` exposes both as
`app.state.runtime_registry` and `app.state.runtime_resolver`; the resolver
returns the same registered instance. Runtime construction remains in
infrastructure, while registry and resolver remain pure.

The configured runtime id is retained truthfully but is not eagerly resolved,
because runtime execution is not yet consuming it. Unknown runtime ids
therefore do not fail mock or native agent startup in this step. Construction
remains network-free. The model registry/resolver and provider discovery are
unchanged.

## Step 19 — Execution Selection Metadata

Status: COMPLETE

Runs now carry optional `RunExecutionSelection` metadata (`runtime_id`,
`model_provider_id`, `model_id`). NativeAgentAdapter derives identities from
the actual injected runtime and model-provider ports; AgentRunResult carries
the DTO and RunService stores and exposes it through RunResponse and
`GET /runs/{run_id}`. Mock runs leave metadata absent. Events and RunRequest
remain unchanged; selection is still application-configured with no per-run
overrides or compatibility validation. Frontend and Python client models
mirror the optional field. Contract version remains v1 for these optional
backward-compatible additions.

Production execution remains `RunService → AgentPort → NativeAgentAdapter →
ModelProviderPort`; NativeRuntime and its registry/resolver are dormant for run
execution. No run metadata, overrides, discovery endpoint, compatibility
validation, agent migration, streaming/tools/RAG, or next-step work was added.

Tests cover runtime defaults/overrides, independence of agent/runtime/model
settings, native runtime registration, shared app-state identity, and unknown
runtime startup for both mock and native agent providers. Targeted deterministic
tests passed. The full gate was not rerun in this turn because external test
execution was rejected by the account usage limit; prior full gates were green.
The relevant local tests and Ruff checks pass (`41 passed` targeted settings,
registry, resolver, and NativeRuntime tests; Ruff clean after import ordering).

## Step 18 — Native Agent Runtime Migration

Status: COMPLETE (full external gate unavailable in this turn)

`NativeAgentAdapter` now receives two independently resolved ports:

```python
NativeAgentAdapter(
    runtime: AgentRuntimePort,
    model_provider: ModelProviderPort,
)
```

The adapter passes the original `RunRequest` and provider unchanged to
`runtime.execute(...)`, then explicitly maps `RuntimeRunResult` fields to
`AgentRunResult`. It delegates `cancel_run(run_id)` to the runtime and maps
the returned result to the existing `RunResponse`. Direct ModelRequest
construction, provider generation, provider-error handling, and provider task
ownership were removed from the adapter; NativeRuntime is now the sole owner
of those responsibilities. The adapter retains only a small defensive catch
for unexpected runtime exceptions and maps them to sanitized failed results.

Composition resolves `settings.agent_runtime` through RuntimeResolver and
`settings.model_provider` through ModelProviderResolver independently, then
injects the exact registered instances. The mock path still resolves neither
dependency. Native selection now fails explicitly for unknown runtime or model
provider ids. RunService, AgentPort, routes, and per-run contracts remain
unchanged.
## Step 20 — Per-Run Runtime and Model-Provider Overrides

Status: COMPLETE

`RunRequest.execution` carries optional independent runtime and model-provider
ids through `RunExecutionOverride` (with no model-id override). Composition
builds `ExecutionSelector`, which lazily resolves effective ids against the
existing registries while preserving configured defaults. NativeAgentAdapter
executes the resolved registered instances and reports actual Step 19
metadata. Unknown ids produce sanitized terminal failures without fallback.
RunService and events remain unchanged; mock runs do not claim runtime/provider
selection. No compatibility validation or UI selection was added.
## Step 21 — Execution Compatibility Validation

Status: COMPLETE

Added a deterministic, network-free `ExecutionCompatibilityValidator` at the
execution boundary. It validates the current prompt-only requirement that the
resolved model is chat-capable; specialized runtime flags are not required.
Validation runs after per-run selection and before runtime execution, with no
id-based pair tables, fallback, health checks, or model-existence checks.
Incompatible or malformed metadata produces a sanitized terminal failure while
preserving RunService and event behavior.
## Step 22 — Runtime Discovery API

Status: COMPLETE

Added read-only `GET /runtimes` discovery backed by the same production
RuntimeRegistry used for resolution and execution. RuntimeDiscoveryService
enumerates registered runtimes in insertion order, returns their actual
RuntimeInfo and capabilities, and reports the configured default id truthfully
even when unregistered. Discovery performs no health checks, compatibility
validation, provider inspection, or network I/O.
## Step 24 — Execution Profiles

Status: COMPLETE

Execution profiles are now AVA-owned discoverable configuration exposed by
`GET /execution-profiles`. The default `Local Coding` profile maps the
configured runtime and provider; frontend controls consume this discovery
response and no longer define the profile. Selecting a profile updates the
underlying runtime/provider override, while manual changes produce `Custom`.
Profiles contain no model id, are not persisted, and introduce no provider
management or automatic routing.
## Step 26 — External Runtime Model Binding Abstraction

Status: COMPLETE

Added the internal `RuntimeModelBinding` / `RuntimeModelBindingPort` bridge
without changing `ModelProviderPort` or any run lifecycle. The selected
OpenAI-compatible provider can expose protocol, model id, endpoint, and an
internal credential reference for future external runtime adapters; unsupported
providers fail explicitly. Bindings are not public contracts, are never sent
through API or frontend models, and no OpenHands dependency or integration was
added.
## Step 27 — OpenHands Runtime Skeleton

Status: COMPLETE

Added an adapter-local `OpenHandsRuntime` implementing `AgentRuntimePort` with
identity `openhands` and conservative zero capabilities. It accepts the
selected `ModelProviderPort`, validates the Step 26 binding seam, and returns
sanitized disabled-execution results; no OpenHands SDK is imported or invoked,
and the runtime is not registered in production or exposed to Auto/UI
selection. OpenHands is declared as an optional packaging extra only.
## Step 29 — OpenHands Real Local Validation

Status: READY FOR HOST VALIDATION

Added `backend/scripts/smoke_openhands.py`, a developer-only smoke test that
constructs the real OpenAI-compatible local provider and calls the existing
`OpenHandsRuntime` with the exact prompt `Reply with exactly: AVA OPENHANDS OK`.
Run it from `backend` after activating `.venv` with:

```bash
python scripts/smoke_openhands.py
```

The script prints the normalized status/content and exits successfully only
when the final response is exactly `AVA OPENHANDS OK`. It performs no provider
or runtime registration and is not part of the deterministic test suite.
### Step 29 follow-up — OpenHands local credential compatibility

The OpenHands adapter now supplies the fixed non-secret `local-ava` placeholder
only when an OpenAI-compatible binding has no credential, satisfying
LiteLLM's required key field for unauthenticated local endpoints. Real binding
credentials pass through unchanged; AVA binding data, Ollama, and global
environment configuration are untouched.
## Step 30 — Controlled OpenHands Registration

Status: COMPLETE

OpenHands is now registered in production runtime composition and appears in
runtime discovery for explicit selection. Its conservative capability flags
remain false, and model providers are still supplied at execution time. Auto
routing explicitly excludes OpenHands until structured capability requirements
and stronger workspace policy exist. The adapter keeps SDK imports lazy, so
native startup remains safe when the optional dependency is absent.
### Step 30 follow-up — controlled eligibility and profile

Added the backend-owned `OpenHands Local` profile mapped to `openhands` and
the configured provider. Automatic routing now receives a generic eligible
runtime-id set from composition (`native` only), rather than containing an
OpenHands-specific branch. OpenHands remains manually/profile selectable.
## Step 32 — Runtime-Neutral Workspace and Security Boundary

Status: COMPLETE/PASS (contracts + backend execution wiring + discovery API +
frontend workspace-selection path + live end-to-end validation)

The full path is proven over a real running backend and the real Web UI stack:
selector → `selectedWorkspaceId` → `submitPrompt` → `startRunForPrompt` →
`@ava/api-client` → HTTP `POST /runs` → `RunRequest.workspace_id` →
`WorkspaceResolver` → `RuntimeWorkspaceBinding` → `runtime.execute(workspace=...)`.
See the live validation section below. Security boundary holds live: workspace
IDs are opaque, never authorized as real paths, and a selected workspace never
grants tools, shell, filesystem access, or alters runtime Auto routing.

Added AVA-owned workspace identity, kind, permission, resolved-workspace,
registry, and resolver contracts. `RunRequest` accepts only an opaque optional
`workspace_id`; it exposes no raw path or permission escalation fields.
Unknown IDs fail explicitly and the registry performs no filesystem or shell
operations.

### Backend execution wiring (complete)

The adapter layer now resolves a requested workspace before execution:

- `NativeAgentAdapter` gained an optional `workspace_resolver` and converts
  the opaque id to an already-approved `RuntimeWorkspaceBinding` via
  `bind_workspace(resolved)` between compatibility validation and the runtime
  call. `workspace_id is None` preserves the existing no-workspace path; a
  missing resolver or unknown id raises `UnknownWorkspaceError`, and the run
  fails cleanly with "Requested workspace is unavailable" (no fallback to
  cwd, home, repository root, or `/`). Save/cancel paths are unchanged.
- `AgentRuntimePort.execute` accepts optional `workspace`; runtimes receive a
  resolved binding only and never re-derive perms from prompt text, runtime
  type, or client input. OpenHands uses the binding `local_path` when present
  and otherwise keeps its isolated `workspace/project` default; the native
  runtime accepts and ignores it (no tools/shell/filesystem grants).
- Composition constructs an empty `WorkspaceRegistry` (`create_workspace_resolver`)
  and injects it into the API app (`app.state.workspace_resolver`), so
  resolution is live but the registry starts empty and startup stays
  network-free.
- New architecture guards keep `RunService`, `AgentPort`, the resolver, and
  the registry free of runtime/workspace coupling (adapter is the only
  coordinator).

### Workspace discovery API (complete)

Read-only, metadata-only discovery of AVA-approved workspaces:

- `WorkspaceDiscoveryResponse` (`ava.contracts.responses`) reuses the existing
  public-safe `WorkspaceInfo` (workspace_id, display_name, kind) as the
  discovery item and carries `contract_version`. No permission flags, host
  paths, or bindings are exposed.
- `WorkspaceDiscoveryService` (`ava.services.workspace_discovery_service`)
  reads the shared registry through `list()`/`get()`, preserves registration
  order, never constructs a `RuntimeWorkspaceBinding`, never resolves or
  invokes a runtime, and performs no filesystem/shell/network activity. It can
  never create ephemeral directories; provisioning is an execution concern.
- `GET /workspaces` (`ava.api.routes.workspaces`) is a thin typed route
  returning `WorkspaceDiscoveryResponse`; OpenAPI documents the item schema as
  exactly `{workspace_id, display_name, kind}`.
- Composition exposes `create_workspace_registry()` and
  `create_workspace_resolver(registry=...)`; the app wires one shared
  `WorkspaceRegistry` into `app.state.workspace_registry`, the resolver, and
  the discovery service, so discovery and resolution observe the same
  registrations. An empty registry legitimately returns `workspaces: []`.
- Architecture guard added: the discovery service depends only on contracts
  and the workspaces layer.
- Python client: `AvaClient.get_workspaces()` plus client-side
  `WorkspaceKind`, `WorkspaceInfo`, `WorkspaceDiscoveryResponse` mirroring the
  backend shapes; testable via an optional `httpx` transport.

### Frontend workspace-selection path (complete)

Shared workspace discovery and selection across the Web and Desktop apps:

- `@ava/contracts`: new `workspaces.ts` contract (`WorkspaceKind = "local" |
  "ephemeral"`, public-safe `WorkspaceInfo {workspace_id, display_name, kind}`,
  `WorkspaceDiscoveryResponse {contract_version, workspaces}`) mirroring the
  backend `/workspaces` payload exactly; `RunRequest` gains optional
  `workspace_id`. New `workspaces.test.ts` locks the backend-shaped types and
  the omittable-`workspace_id` behavior.
- `@ava/api-client`: `getWorkspaces(client)` performs `GET /workspaces` like
  the other discovery calls; new tests cover path, typed deserialization,
  empty registry, and `ApiError` on non-OK.
- `@ava/agent-ui`: `ExecutionControls` gains a generic Workspace selector —
  options are "None" plus discovered workspaces (label `display_name`, value
  `workspace_id`), `selectedWorkspaceId`/`onWorkspaceChange` are controlled
  props, and a `workspacesUnavailable` state renders the disabled "Workspace
  options unavailable" label instead of degraded options. No paths,
  permissions, folder picker, or polling. New selector tests cover None
  default, discovered options, selected value, empty registry, and failure
  degradation.
- Run serialization: `submitPrompt` / `startRunForPrompt` thread
  `workspaceId`; the run request includes `workspace_id` only when a real id is
  present and omits it when null/undefined. Retry/regenerate intentionally
  follow the existing execution-override behavior (no workspace re-injection).
- `@ava/workspace`: `AppWorkspace` (the shared shell used as-is by `apps/web`
  and `apps/desktop`) loads `getWorkspaces` in a discovery effect that is
  failure-isolated from runtime/provider/profile discovery, keeps
  `selectedWorkspaceId` (default None, never auto-selected), derives
  execution/profile/runtime/model selections from the profile control alone
  (workspace is independent), clears a stale selection back to None after a
  fresh discovery, and guards submission time by resolving the selected id only
  against the current discovered set. `handleComposerSubmit` still builds the
  run request as before, now with the optional `workspace_id`.
- Validation: contracts 9, api-client 22, agent-ui 123 (was 110), workspace 12
  tests pass (plus 4 opt-in live integration tests, see below); only the 2
  pre-existing `PromptComposer` `>Send</span>` assertion failures remain
  (unrelated to this work). `tsc --noEmit` lint passes for every frontend
  package and both apps; `apps/web` and `apps/desktop` build. Backend
  regression: 369 passed (359 prior + 10 new HTTP integration tests).

### Live end-to-end validation (PASS, Step 32 completion gate)

Proof of the real path with an actual running server and the actual application
stack (no mocks on the happy-path HTTP, client, service, agent, resolver,
registry, or binding code).

- **Harness (dev/test wiring only, removed after the gate):** the production
  FastAPI app composed exactly as in production, served with uvicorn on
  127.0.0.1; runtime and model provider were swapped for deterministic offline
  ports (recording runtime + echo provider) and ONE safe ephemeral workspace was
  registered through the production `WorkspaceRegistry`
  (`ephemeral-validation-live`, `WorkspaceKind.EPHEMERAL`, `root_path=None`,
  zero permissions). The repository, home, cwd, and `/` were never registered;
  the production registry stays empty.
- **Backend HTTP integration tests (new, `tests/test_workspace_live_integration.py`,
  10 passed):** over the real transport — `GET /workspaces` empty registry →
  `[]`; registered workspace → exactly `{workspace_id, display_name, kind}`
  with no path/permission keys; `POST /runs {workspace_id}` → completed and the
  runtime received a `RuntimeWorkspaceBinding` (id, kind ephemeral,
  `local_path=None`, all permissions false); no `workspace_id` → binding `None`;
  unknown and path-like ids (`missing-workspace`, `/home/bizon/AvaUi`,
  `../project`, `/tmp/test`) → run `failed`, generic public message, runtime
  never invoked (recording count 0), no message content; explicit runtime
  (`openhands`) + workspace coexist independently; Auto + workspace unchanged.
- **Live uvicorn checks (curl against the running server):** `/workspaces`
  returned only the ephemeral identity; `POST /runs` with the workspace id →
  `completed` (`runtime_id=native`) and the event stream carried
  `...:ephemeral-validation-live/ephemeral` and no path; no-workspace request →
  `completed` with binding `None`; `missing-workspace` and all three path-like
  ids → `failed` with only `run_started`/`run_failed` (generic
  "The agent failed to complete the run.", `error_code=agent_failed`,
  `recoverable=false`) and the runtime-observation endpoint showed those runs
  never reached the runtime; OpenHands Local profile (`runtime_id=openhands`)
  → `execution_selection.runtime_id=openhands` while carrying the same
  workspace id (profile/workspace independence); Auto + workspace →
  `runtime_id=native` (routing unaffected).
- **Frontend live integration (new, opt-in `@ava/workspace`
  `live-workspace-run.integration.test.tsx`, 4 passed against the live server,
  auto-skipped otherwise):** real `ApiClient` (real fetch) + real `AppWorkspace`
  driving the real selector — the ephemeral option is discovered and rendered
  ("None" stays present); selecting it and submitting runs a real `POST /runs`
  whose assistant message contains the opaque `ephemeral-validation-live/ephemeral`
  receipt and leaves the selector on the selected workspace; switching to the
  OpenHands Local profile does not auto-grant a workspace; Auto profile keeps
  the selected workspace out of routing. The backend observation endpoint
  confirmed the UI submissions reached the runtime with the expected bindings.
- **Security confirmations under live traffic:** the four path-like/unknown ids
  failed closed with zero runtime calls; the public surface exposed no absolute
  paths, permission flags, or binding internals at any point (discovery item is
  exactly `{workspace_id, display_name, kind}`); no tools, shell, filesystem,
  or code-execution changes (OpenHands stays explicit-only with 0 tools and
  binary disabled); a recorded binding is never re-derived from prompt text,
  runtime type, or client input; failed runs surfaced only the generic message.
- **Full regression at the gate:** backend 369 passed + ruff clean + mypy
  (`src`) clean (new integration file is strict-mypy clean); python client 7
  passed; frontend contracts 9 / api-client 22 / ui-core 20 / document-core 11 /
  workspace 12 (+4 live) / agent-ui 123 passing with the same 2 pre-existing
  `PromptComposer` failures reported separately; `tsc --noEmit` lint 9/9; web
  and desktop production builds pass. Validation artifacts (harness, logs)
  were removed after the gate.

---

## Step 33 — Controlled OpenHands File Access

**Status: COMPLETE**

OpenHands now receives the AVA-owned contained `file_editor` only when the
resolved workspace has a local root and `read=True`. A read-only workspace
receives that editor with every mutation blocked; a read/write workspace may
create, replace, insert, and undo files inside its approved root. No workspace,
no local root, or no read permission produces an empty tool list.

The editor uses a canonical, existing absolute workspace root. Every operation
performs canonical containment before the SDK accesses the path, rejecting
absolute escapes, `..` traversal, file and directory symlink escapes, hard
links, and special files. Directory listings omit escaped symlink entries.
The installed editor's 10 MiB file limit applies to reads and existing files;
AVA also checks proposed write content before writing. Delete is unavailable.

`OpenHandsRuntime` now uses adapter-local controlled SDK subclasses. They
disable ambient user/project plugins, skills, MCP servers, memory, hooks, and
file-based agent definitions; only the AVA-created `file_editor` can be
resolved. The runtime explicitly disables SDK default tools, so terminal,
browser, task, delegation, patch, shell, and code-execution tools remain
unavailable. OpenHands capability metadata truthfully advertises only
`tools=True` and `filesystem=True`.

The optional dependencies are split and pinned to the validated SDK version:
`openhands` provides the SDK runtime, while `openhands-tools` adds the file
editor implementation. A run requesting file access fails safely when that
optional tools package is unavailable.

Validation completed with 36 deterministic Step 33 tests covering policy,
containment, write/read-only behavior, size limits, delete denial, registry
resolution, SDK initialization, disabled ambient loading, and runtime-level
read-only/read-write behavior. The backend regression passed **404 tests**;
Ruff and strict mypy passed for all 77 backend source files. Python client
checks passed (7 tests, Ruff, mypy). Frontend contracts, API client, UI core,
document-core, and workspace suites passed, as did all frontend TypeScript
checks and Web/Desktop production builds. The existing agent-ui suite still
has two unrelated stale `PromptComposer` assertions expecting a `Send` label
where the component intentionally renders the `↑` icon.

---

## Step 34 — Controlled Terminal / Shell Policy

**Status: COMPLETE — raw TerminalTool remains disabled**

Added the runtime-neutral `CommandExecutionPolicy` seam in
`ava.execution.command_policy`. Its internal `CommandRequest` carries a bare
executable, arguments, and an optional relative working directory; it contains
no public request fields, client environment overrides, or client timeout
override. `CommandDecision` carries AVA-owned effective working directory,
timeout, and environment data for a future runner.

`SandboxedCommandExecutionPolicy` requires an approved local workspace with
`WorkspacePermissions.shell=True`. It canonicalizes the workspace root and a
relative requested subdirectory, rejects absolute paths, `..` traversal,
unavailable roots, and symlink escapes, and rejects executable strings that
contain shell/path syntax. It produces only a static minimal environment:
`PATH=/usr/bin:/bin`, `LANG=C.UTF-8`, and `LC_ALL=C.UTF-8`; it never inherits
the AVA process environment. The backend-owned prospective timeout is 30
seconds.

The policy nevertheless returns `allowed=False, reason_code="sandbox_required"`
for every otherwise valid command. This is deliberate: inspection of the
pinned OpenHands 1.47.0 `TerminalTool` showed that it creates a persistent host
shell (subprocess or tmux) and accepts arbitrary shell strings. It has no AVA
interception point capable of technically preventing reads/writes outside the
workspace, absolute-path access, shell metacharacters, or symlink escapes.
Giving it an approved working directory would undermine Step 33 containment.

Consequently OpenHands receives no terminal tool for no workspace, shell-false,
or shell-true workspaces; a shell-true local workspace still gets only the
existing contained FileEditor when it has read permission. Runtime discovery
continues to report `tools=True`, `filesystem=True`, and `shell=False`.
Auto eligibility, execution profiles, workspace registration, public contracts,
and frontend controls are unchanged.

The deterministic Step 34 policy suite covers permission gating, no-local-root
failure, canonical working-directory containment, absolute/`..`/symlink escape
denial, executable syntax rejection, static environment redaction of fake
process/provider secrets, timeout ownership, and absence of public shell
escalation fields. Architecture guards enforce that the policy imports neither
OpenHands nor process-execution modules, and that the OpenHands adapter still
does not construct terminal, task, browser, delegation, patch, or shell tools.

**Known limits and next security checkpoint:** no terminal commands were run,
so cancellation, process-tree cleanup, network isolation, CPU/memory/process
limits, disk quotas, and host filesystem containment remain unimplemented.
OpenHands' terminal environment helper begins from a sanitized parent
environment, which is insufficient for AVA's credential-isolation requirement;
the AVA policy's static environment is not passed to any host runner. Step 35
must not begin until a sandbox/container/remote execution boundary can enforce
the policy's working-directory, filesystem, process, environment, timeout, and
network guarantees.

---

## Step 34B — Sandboxed Command Execution Boundary

**Status: COMPLETE — validated with qualified Granite model**

Host inspection found Bubblewrap 0.6.1 (`bwrap`), `unshare`, Linux user
namespaces, and cgroup v2. Docker and `systemd-run` executables exist, but the
Docker socket and user systemd bus are inaccessible; cgroup v2 is read-only.
Podman, firejail, and nsjail are unavailable. Bubblewrap was selected because
it provides a usable unprivileged mount, PID, and network namespace boundary
on this host. Its namespace launch requires host execution in this development
environment, but it works there without privileged execution.

`ava.execution.sandbox` now defines the runtime-neutral
`SandboxedCommandRunnerPort`, `SandboxedCommandRequest`,
`SandboxedCommandResult`, and `SandboxResourceLimits`. Composition selects the
infrastructure-only `BubblewrapSandboxedCommandRunner`; neither core policy nor
the OpenHands adapter constructs Bubblewrap directly. Requests accept a bare,
allowlisted executable and literal arguments only—never a shell string. The
initial executable set is `cat`, `env`, `ls`, `pwd`, `python`, `python3`,
`python3.11`, and `sleep`; package-management and arbitrary executable paths
are unavailable. `network=true` is rejected.

Each command runs under `bwrap --unshare-all --die-with-parent --new-session`
with a cleared environment. `/usr` is read-only for runtime libraries;
`/bin`, `/lib`, and `/lib64` are symlinks into it; `/dev`, `/proc`, and `/tmp`
are private. The approved workspace alone is mounted at `/workspace`,
read-only or read/write from AVA workspace permissions. Real `/home`, `/etc`,
`/root`, host `/tmp`, the AVA repository, other workspaces, and the Docker
socket are absent. Effective environment is AVA-owned `PATH`, `LANG`,
`LC_ALL`, `HOME=/tmp/ava-home`, and `TMPDIR=/tmp`; no backend environment is
inherited. `--unshare-all` creates a disconnected network namespace, including
no host-loopback access.

The inner trusted Python launcher enforces CPU (30 seconds), address-space
(128 MiB), and process-count (32) rlimits immediately before `exec`; this
avoids applying an NPROC limit to the Bubblewrap launcher itself. Runner output
is capped at 64 KiB, command timeout defaults to 30 seconds, cancellation is
exposed by command id, and timeout/cancellation terminates the outer process
group. Bubblewrap's PID namespace and `--die-with-parent` provide additional
child-process cleanup.

The Step 34 policy now produces an allowed decision only when composition has
provided an available sandbox runner. It converts that decision to the internal
sandbox request; shell permission remains independent of read/write permission.
The OpenHands adapter supplies a custom `ava_terminal` tool only for an
approved local workspace with `read=true`, `shell=true`, and `network=false`.
Its schema is `executable`, literal `arguments`, and optional relative
`working_directory`; it routes through AVA policy and runner. Runtime-only tool
dependencies are held outside persisted SDK tool specs. The raw OpenHands
`TerminalTool` remains permanently disabled. Tool surfaces are `[]` without
read access, `[file_editor]` for read-only/read-write shell-false workspaces,
and `[file_editor, ava_terminal]` for shell-approved workspaces. With a
composed runner, OpenHands reports `tools=true`, `filesystem=true`,
`shell=true`, and `code_execution=true`; the default uncomposed runtime still
reports shell and code execution as false.

Deterministic validation passed: 88 focused tests plus Ruff and strict mypy
across 82 source files. The suite covers sandbox `/workspace` identity,
inside read/write, read-only enforcement, host sibling and absolute-path
inaccessibility, symlink isolation, HOME and fake backend/provider-secret
absence, loopback network denial, timeout, cancellation, child cleanup,
memory/process/output limits, policy conversion, Step 33 FileEditor behavior,
and OpenHands custom-tool resolution through the real runner.

The existing local Ollama service and `qwen2.5-coder:7b` were available. Two
safe temporary read-only-workspace runs used OpenHands with the custom tool and
a prompt to list/read `sample.txt`; the model returned `ava_terminal` JSON as
plain assistant text rather than an SDK tool call. No sandbox command was
executed by either live run. Therefore the required live controlled-terminal
smoke has not passed and Step 34/34B remain partial despite the passing
deterministic adapter-to-runner tests. No repository was registered and all
temporary workspaces were cleaned up.

Remaining work before declaring these steps complete: use a compatible local
tool-calling model to complete the live smoke. Broader limitations remain
TOCTOU between validation and mount, Bubblewrap/user-namespace availability,
rlimits instead of cgroup-enforced aggregate accounting, no audit log or
persistent sessions, and no dependency installation, Git automation,
production repository access, or enterprise remote sandbox. Step 35 has not
begun; TaskTracker, browser, MCP, LangGraph, and AgentCore remain untouched.

---

## Step 34C — Native Tool-Calling Model Qualification

**Status: COMPLETE — Granite qualified for this OpenHands tool workload**

Added the reusable, internal qualification contract in
`ava.runtimes.qualification`. A passing trial requires an OpenHands SDK
`ActionEvent` for `ava_terminal`, an `ObservationEvent`, a recorded request at
the `SandboxedCommandRunnerPort`, return of the tool result, and a final agent
response. The aggregate gate requires every trial to pass (the live harness
runs three). This is intentionally separate from provider compatibility and
runtime capabilities: runtime capability does not equal model qualification.

The adapter-local live harness observes SDK conversation events rather than
console text. It is environment-gated by
`AVA_RUN_LOCAL_MODEL_QUALIFICATION=1`; `AVA_QUALIFICATION_MODEL` and
`AVA_LOCAL_MODEL_BASE_URL` select a candidate, while
`AVA_QUALIFICATION_REQUIRE_PASS=1` makes a selected candidate a strict test
gate. It uses only a temporary read-only workspace, `ava_terminal`, and `pwd`.

Assistant content that merely contains `ava_terminal` JSON is classified as
`tool_call_emitted_as_text`; it is never parsed, repaired, or sent to the
executor. Deterministic regression tests cover textual pseudo-calls, malformed
arguments, wrong tools, missing execution/result/final-response stages, and a
complete structured loop.

Installed-model inventory found only `qwen2.5-coder:7b`: 4.7 GB on disk,
Qwen2 architecture, 7.6B parameters, Q4_K_M quantization, 32,768 context, and
Ollama-advertised `tools` capability. Three live OpenHands trials against the
local Ollama OpenAI-compatible endpoint produced **0/3** native calls, **3/3**
textual pseudo-tool calls, **0** executions, **0** sandbox receipts, **0**
tool-result consumptions, and **0** final responses after a result. It is not
qualified for this OpenHands native-tool workload despite its advertised tool
capability.

Step 34B's Bubblewrap implementation and deterministic adapter tests remain
passing. A later Model Registry should record measured runtime/tool-protocol
qualification separately from general coding capability. No text-to-tool
fallback, raw TerminalTool, host shell, repository registration, Step 35,
orchestrator, LangGraph, or AgentCore was added.

### Granite 4.2 8B qualification update

The official `ibm/granite4.2:8b` artifact is installed: 5.3 GB, Granite
architecture, 8.8B parameters, Q4_K_M quantization, 131,072 advertised
context, and Ollama `tools`, `thinking`, and `completion` capabilities. It was
not modified or selected as AVA's default model. Its manifest's 131,072
`num_ctx` default was too large for this qualification; the
OpenAI-compatible extra-body request did not change Ollama's loaded context.
The local `ava-granite4.2-qualification:8b-q4km` overlay therefore reuses the
official base layers and changes only `num_ctx` to 8,192. Ollama confirmed the
loaded 8,192 context.

Three strict OpenHands trials with that overlay passed: **3/3** native
`ActionEvent`s for `ava_terminal`, **0** textual pseudo-calls, **3** valid
Bubblewrap receipts/executions, **3** `ObservationEvent`s and tool-result
consumptions, and **3** final responses. The first trial reported the actual
sandbox path `/workspace`. In the second safe task, a temporary read-only
workspace contained `sample.txt` with `granite fixture`; Granite made the
native structured `cat sample.txt` call and reported the exact content. The
combined FileEditor/terminal model smoke was unnecessary to establish terminal
qualification; both tools retain independent deterministic coverage.

At 8,192 context, Ollama reported 94% GPU / 6% CPU placement and approximately
6.7 GiB GPU use on the 8 GiB RTX 4060. The strict three-trial test completed in
about 21 seconds. `qwen2.5-coder:7b` remains installed with its recorded 0/3
baseline failure. The qualification confirms that runtime capability differs
from model qualification, and declared `tools=true` metadata differs from
runtime/transport-specific qualification.

---

## Step 35 — OpenHands Coding Workflow Validation

**Status: PARTIAL — deterministic workflow harness complete; live coding loop did not complete**

Added a reusable `CodingWorkflowQualificationResult` evaluator and deterministic
tests for required coding-workflow facts: an implementation edit, unchanged
tests, a real test execution, native-tool-only activity, and no false claim of
success. The opt-in live workflow test reuses the Granite/OpenHands/Bubblewrap
qualification path and remains gated by `AVA_RUN_LOCAL_MODEL_QUALIFICATION=1`.

The disposable fixture is a Python project with `label_normalizer.py` and a
standard-library `unittest` suite. Its intentional bug drops integer `0` while
normalizing labels; the baseline sandbox command
`python -m unittest discover -s tests` fails deterministically. The model is
given only the task-level prompt, not a file or line hint. The temporary
approved workspace has `read=true`, `write=true`, `shell=true`, and
`network=false`; its tool surface is contained `file_editor` plus
`ava_terminal` only. The terminal test command uses Python's standard library,
so no package installation is needed.

The first live Granite workflow did not finish within a practical qualification
window (more than three minutes). It was cancelled and the local model unloaded
rather than consuming the default longer agent timeout. Therefore there is no
valid completed agent sequence, implementation change, model-run final test
result, or final response to count. This is recorded as an incomplete
long-agent-loop/coding-workflow qualification, not as a sandbox, native tool,
or text-to-tool failure. The fixture was temporary and no workspace, process,
or repository access was retained.

Step 35 remains partial pending a bounded successful coding workflow. Granite
is qualified for native OpenHands tool calls; coding repair, repository
navigation, failure recovery, and completion behavior require separate measured
qualification. No raw TerminalTool, host shell, network, Git workflow,
dependency install, production AVA repository registration, Step 36, Model
Orchestrator, LangGraph, or AgentCore was added.

### Step 35B — Long-Agent-Loop Diagnosis

**Status: COMPLETE — diagnosis harness PASS; Step 35 remains PARTIAL**

The live harness now captures incremental, sanitized callback facts as OpenHands
emits them: event class, controlled tool name, and monotonic elapsed time. It
retains this partial trace after a backend-owned timeout, then asks the SDK to
interrupt the conversation. `OpenHandsWorkflowTrace` separately records final
response presence, completion/cancellation, controlled tool counts, sandbox
receipts, and a stable stall category. No reasoning text, host paths, secrets,
or tool arguments are persisted in the timing trace. Deterministic tests cover
partial-run stall classification and distinguish task facts from completion.

| Scenario | Result | Observable evidence |
| --- | --- | --- |
| A: one-file inspection | PASS | One native `file_editor` action at ~8.9 s, observation ~5 ms later, final response at ~15.4 s correctly described normalization; no edits. |
| B: source + test inspection | PASS | Three native FileEditor actions (~3.4, 5.8, 8.2 s), observations within milliseconds, final response at ~25.2 s correctly identified `if value` dropping zero; no edits. |
| C: guided edit only | PARTIAL | Source read at ~11.7 s and observed immediately. The next FileEditor action arrived only at ~82.4 s; the 60-second qualification bound interrupted it before edit execution. Source and tests remained unchanged. |
| D: test only | PARTIAL | Granite ran native `ls`, then incorrectly supplied `ls -la` as an executable instead of executable `ls` plus argument `-la`; AVA rejected it. Granite then read files and reached the 4/5-iteration limit without running `unittest` or emitting a final response. |

The `ava_terminal` description was generically clarified with the literal
structured-argument example `executable='ls', arguments=['-la']`. The rerun of
Scenario D repeated the same malformed combined-executable behavior, so it is
recorded as model tool-selection behavior rather than a schema ambiguity or a
policy defect. AVA correctly preserved the bare-executable restriction.

The original opaque coding run is now explained by the same observable class of
failure: short FileEditor and terminal observations are not the latency source;
the long waits occur between observations and Granite's next model-generated
action, and bounded runs may reach iteration limits without a final response.
Granite is therefore PASS for native terminal calls, single-file inspection,
and multi-file inspection; PARTIAL for contained editing, test execution,
edit/test sequencing, autonomous bug repair, long-agent-loop behavior, and
completion behavior. Failure recovery was not tested because the prerequisite
guided edit/test mechanics did not pass.

### Qwen3.5 9B qualification

**Status: PARTIAL — native tool and inspection mechanics pass; bounded repair
workflow does not complete. Step 35 remains PARTIAL.**

The official `qwen3.5:9b-q4_K_M` artifact was installed for this experiment.
Ollama reports Qwen35 architecture, 9.7B parameters, Q4_K_M quantization, a
6.6 GB base artifact, 262,144 advertised context, and `completion`, `vision`,
`tools`, and `thinking` capabilities. The parameter-only
`ava-qwen3.5-qualification:9b-q4km` overlay reuses the base model and fixes
`num_ctx=8192`; during the live runs Ollama reported that overlay at 8,192
context. Neither artifact changes AVA defaults or model selection.

The strict native-terminal gate passed **3/3**: three SDK-native
`ava_terminal` ActionEvents, zero textual pseudo-calls, zero malformed calls,
three Bubblewrap receipts/executions, three observations/result consumptions,
and three final responses. The gate completed in 37.2 seconds including setup.
This is OpenHands/LiteLLM/Ollama transport evidence; assistant JSON-looking
text remains non-executable by design.

| Scenario | Result | Observable evidence |
| --- | --- | --- |
| A: one-file inspection | PASS | One native FileEditor action at ~5.0 s, observed ~5 ms later; final response at ~9.6 s; no source or test changes. |
| B: source + test inspection | PASS | Three native FileEditor actions at ~4.8, 6.7, and 8.2 s, each observed within milliseconds; final response at ~26.0 s; no modifications. |
| C: guided edit only | PARTIAL | Four FileEditor actions by ~24.6 s made the required source change and left tests unchanged, but the five-iteration bound ended with no final response. Stall: `completion_not_emitted`. |
| D: test only | PASS | One native `ava_terminal` ActionEvent at ~6.0 s reached Bubblewrap and produced the expected failing-test observation; it consumed that result and emitted a final response without file changes. The attempted test command was recognized as a `unittest` execution through the structured terminal interface. |
| E: guided edit + test | PARTIAL | Four FileEditor actions and one terminal action by ~21.7 s changed only source, then the terminal action failed before a sandbox receipt; tests remained failing and the five-iteration bound ended without a final response. Stall: `completion_not_emitted`. |
| F: autonomous repair | NOT TESTED | Not run because the guided edit-and-test prerequisite did not pass. |

At the post-run observation the 8 GiB RTX 4060 held about 6.9 GiB and Ollama
reported **100% GPU** placement for the 8,192-context overlay. The model was
therefore practical for short interactive tool tasks (first actions near five
seconds and inspection completion in 10–26 seconds), but not yet practical as
a bounded autonomous repair loop because it reached the iteration limit without
completing Stage C or E. No hidden reasoning was captured or stored; traces
contain only event type, controlled tool name, and elapsed timing.

| Capability | Granite 4.2 8B | Qwen3.5 9B |
| --- | --- | --- |
| Native terminal calls | PASS | PASS |
| Single-file inspection | PASS | PASS |
| Multi-file inspection | PASS | PASS |
| Contained edit | PARTIAL | PARTIAL |
| Test execution | PARTIAL | PASS |
| Edit to test sequencing | PARTIAL | PARTIAL |
| Autonomous bug repair | PARTIAL | NOT TESTED |
| Failure recovery | NOT TESTED | NOT TESTED |
| Long loop completion | PARTIAL | PARTIAL |

This confirms that declared model capabilities, measured native-tool protocol
qualification, task-specific workflow qualification, and hardware practicality
are separate facts a future Model Registry must represent separately. Qwen was
unloaded after the experiment; model artifacts remain intentionally installed.

---

## Step 35C — Granite QLoRA Training Feasibility

**Status: COMPLETE — a one-step 4-bit QLoRA smoke is feasible; Step 35 remains PARTIAL.**

Training is isolated under `training/`; AVA runtime imports no ML libraries.
The source is the official Apache-2.0 Hugging Face Safetensors checkpoint
`ibm-granite/granite-4.2-8b` at revision
`7fce579a7fbbad4b1e7703b6850cefd517a4002b`, never the Ollama GGUF.
The isolated Python 3.10.12 environment uses Torch 2.7.1+cu128,
Transformers 4.57.1, PEFT 0.17.1, TRL 0.22.2, bitsandbytes 0.46.1,
Accelerate 1.10.1, and Datasets 3.6.0.

`ava-agent-sft-v0` contains 28 synthetic train and 5 validation trajectories,
with role-preserving native tool calls and results. Its deterministic validator
rejects disabled/unknown tools, textual pseudo-calls, malformed bare executable
rules, unmatched results, false test-success claims, split overlap, and the
Step 35 label-normalizer holdout. The smoke configuration uses NF4 + double
quantization, BF16 compute, 1024 tokens, batch one, gradient checkpointing,
rank-16/all-linear LoRA (alpha 32), and one update at 2e-4.

Standard PEFT k-bit preparation OOMed while trying to allocate 1.53 GiB of
FP32 non-quantized parameters with only 1.48 GiB free. A conservative fallback
kept frozen 4-bit weights resident and enabled input gradients/checkpointing
without that upcast. It completed load, LoRA attachment, forward/backward/update,
adapter save, reload, and inference in 28.2 seconds. Peak allocated VRAM was
6,825,492,480 bytes and reserved VRAM was 7,564,427,264 bytes on the RTX 4060.
The saved experimental adapter is `training/outputs/granite-4.2-8b-ava-agent-smoke`.
This proves pipeline feasibility only, not agent-quality improvement; no adapter
was merged, quantized, or deployed to Ollama.

### Step 35D.1 — Adapter Reload and Serving Feasibility

**Status: COMPLETE — reload PASS; adapter runtime qualification BLOCKED by a
missing compatible serving path. Step 35D and Step 35 remain PARTIAL.**

The saved `granite-4.2-8b-ava-agent-sft-v1` adapter contains its PEFT config
and a 189 MiB Safetensors weight file. Its config identifies
`ibm-granite/granite-4.2-8b`, rank 16, alpha 32, and the seven Q/K/V/O plus
gate/up/down projection target modules. A clean, separate process loaded the
recorded Granite revision `7fce579a7fbbad4b1e7703b6850cefd517a4002b` in NF4,
attached the adapter without merging, applied Granite's chat template, and
generated `AVA ADAPTER RELOAD OK`. It took 12.76 seconds, peaked at 5.73 GiB
allocated / 6.07 GiB reserved VRAM, and returned to the ~392 MiB desktop
baseline after exit.

Serving inspection found only Transformers in the training environment; vLLM,
SGLang, FastAPI, Uvicorn, and llama.cpp server are absent. Installed Ollama
0.33.3 is OpenAI-compatible, but its documented Safetensors-adapter support is
limited to Llama, Mistral, and Gemma; Granite is absent, and its guidance also
warns that QLoRA quantization methods may differ. Its supported import route
would require an Ollama model creation/conversion artifact, which is outside
this step. Therefore no direct local OpenAI-compatible endpoint can currently
serve this Granite PEFT adapter while preserving genuine native tool calls.

| Path | Available | Live LoRA for Granite | OpenAI API | Native tools | 8 GiB fit | Conversion | Decision |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Transformers alone | Yes | Yes in-process | No server | Not exposed | Proven reload | None | Not an OpenHands endpoint |
| Ollama 0.33.3 | Yes | No documented Granite Safetensors support | Yes | Existing base path | Yes for GGUF base | Required | Blocked |
| vLLM / SGLang / llama.cpp server | No | Not inspected as runnable | N/A | N/A | N/A | New framework | Not installed |

No temporary server, merge, GGUF conversion, Ollama model creation, or
OpenHands smoke was performed. A future behavioral comparison must run both
base and adapter through the same serving engine to avoid a transport confound.

### Step 35D.2A — Paired Quantization Forensics

**Status: COMPLETE — paired Q4 artifacts are structurally equivalent.**

Read-only GGUF forensics recorded in
`training/deployment/reports/paired-gguf-forensics.json` resolved the apparent
size discrepancy. Both final F16 artifacts are exactly 17,587,420,736 bytes;
both final Q4_K_M artifacts are exactly 5,347,917,376 bytes. The earlier 4.3
GiB display was observed while adapter quantization was still incomplete.

Base and merged HF configs match for Granite architecture, hidden size 4096,
vocabulary 100352, 40 layers, BF16 dtype, and `tie_word_embeddings=false`.
Their F16 and Q4 GGUF inventories each contain the same 363 tensor names,
shapes, types, and serialized byte sizes. Each preserves independent
`token_embd.weight` and `output.weight` matrices of shape `[4096, 100352]`.
In Q4_K_M, the output head is Q6_K (337,182,720 bytes) and the embedding is
Q4_K (231,211,008 bytes) in both artifacts; type distributions are identical
(41 Q6_K, 241 Q4_K, and matching F32 tensors). The Q4 checksums are recorded
in the report. No model artifact was altered during forensics.

The pair is suitable for a controlled deployment comparison. No custom Ollama
model, OpenHands qualification, coding scenario, retraining, remerge, or
requantization occurred in this forensic substep.

### Step 35D.2 — Controlled LoRA Deployment to Ollama

**Status: COMPLETE — PASS. Step 35D and Step 35 remain PARTIAL.**

The verified base control and merged AVA SFT-v1 Granite artifacts were imported
as `ava-granite4.2-base-control:8b-q4km` and
`ava-granite4.2-agent-sft-v1:8b-q4km`. Their Modelfiles differ only in `FROM`;
both retain the installed official Granite `{{ .Prompt }}` template and set
`num_ctx=8192`, temperature 1, and top-p 0.95. Ollama reports identical
Granite 8.8B Q4_K_M metadata and the `completion`, `thinking`, and `tools`
capabilities for each deployment.

Both models completed the basic import/load/inference check with the expected
deployment response. The control used 6,653 MiB VRAM and the adapter about
6,670 MiB; both ran at a 94% GPU / 6% CPU placement. This check establishes deployment integrity only;
it does not establish coding quality or SFT benefit.

The unchanged strict OpenHands native-tool harness passed 3/3 for the control
and 3/3 for the adapter. Each branch produced three native `ava_terminal`
ActionEvents, zero textual pseudo-calls, zero malformed calls, three sandboxed
Bubblewrap executions, three consumed observations, and three final responses.
The execution boundary therefore remained OpenHands → native ActionEvent →
`ava_terminal` → CommandExecutionPolicy → Bubblewrap → ObservationEvent.

The deployment manifest records base revision, adapter/dataset identity,
checksums, converter commit, Modelfiles, runtime settings, metadata, and gate
results at `training/deployment/manifest.json`. Generated weights, GGUFs,
training outputs, tool checkout, and virtual environment are ignored by Git;
the intentional artifacts remain available for Step 35D.3. No coding scenarios
were run, and no dataset, defaults, training, merge, or quantization operation
was changed in this validation step.

### Step 35D.3 — Frozen Base-vs-Adapter Coding Qualification

**Status: COMPLETE — comparison complete. Step 35D is COMPLETE. Step 35 remains PARTIAL.**

The paired evaluation used the frozen A–F prompts, a fresh intentionally failing
`label_normalizer` holdout for every run, the same contained FileEditor and
`ava_terminal` surface, network-disabled Bubblewrap, 8,192 context,
temperature 1, top-p 0.95, five iterations, and a 60-second run limit. There
is no seeded OpenHands/Ollama evaluation path, so A–D ran once per model and
critical E/F ran twice per model: 16 independent runs total. No SFT dataset was
read or injected during evaluation.

The control passed A (one-file inspection) and B (source-plus-test inspection).
The adapter made native tool calls in both but failed to emit a final response:
A used one FileEditor call plus four terminal calls; B made five file reads.
Both models were PARTIAL for C through F. Neither completed a verified
edit→test loop or autonomous repair. The closest adapter E trial produced a
correct source edit but no successful test, final response, or completed run.
There were no verified passing final tests, false-success claims, test-file
changes, or textual pseudo-tool executions in the returned traces.

An SDK cancellation defect surfaced when a timed-out OpenHands conversation did
not return to the evaluator. The evaluator was generically corrected by running
each model/scenario/trial in a separate process with a 70-second hard boundary.
The pre-correction partial pair was discarded and the entire 16-run comparison
was restarted. Hard-bound trials are explicitly reported as
`evaluator_hard_timeout`, not interpreted as model success.

This evidence shows that the bounded 12-step, 512-token SFT preserved native
tool compatibility but did not demonstrate improved long-loop completion on
this holdout. The local conclusion is limited to these AVA/OpenHands scenarios,
this Ollama transport, and this workstation. The machine-readable report is
`training/deployment/reports/step35d3-base-vs-adapter.json`.

### Step 35 — Final Disposition

**Status: PARTIAL — model-specialization work DEFERRED**

Step 35 remains PARTIAL. The deterministic coding-workflow harness, native-tool
protocol qualification, long-loop diagnosis, QLoRA feasibility, paired
quantization forensics, Ollama deployment, and the frozen base-vs-adapter
comparison are all complete and recorded. No model under test demonstrated
reliable autonomous long coding-agent completion: both the Granite control and
the AVA SFT-v1 adapter remained PARTIAL for guided edit→test sequencing and
autonomous repair, and neither produced a verified passing final test.

Further model specialization (more SFT data, additional training rounds,
larger models, or new adapters) is **DEFERRED**. The measured result is a
model-capability finding, not an AVA platform defect. Non-model platform
architecture is unaffected, and Step 35 does not block Step 36 or later
platform work. Model-selection and model-qualification facts remain separate
from security authorization, which is server/workspace-owned and
model-independent.

---

## Step 36 — Runtime / Tool Security Hardening

**Status: COMPLETE — deterministic full-backend validation green; no model
inference required**

### Goal and trust boundary

Step 36 closes two architecture gaps left by the incremental Step 33/34/34B
guards and adds defense against a known OpenHands SDK cancellation limitation.
Before Step 36 the guards existed but were distributed across the OpenHands
tool factory, the contained FileEditor, `CommandExecutionPolicy`, and the
Bubblewrap runner, with no runtime-neutral authorization contract evaluated
*before* privileged SDK tools were constructed, and with file/terminal failures
that could surface host filesystem paths to the model.

The trust boundary is unchanged and remains server-owned:

```
client/model  →  RunRequest (prompt + opaque workspace_id + execution override)
                 never a permission, tool list, sandbox, or path grant
server         →  workspace resolution, authorization, tool construction,
                 operation policy, sandbox, audit
```

No public contract changed. `RunRequest` still carries only `prompt`, an
optional `execution` override (runtime/model identity only), `workspace_id`,
and `contract_version`. There is no `allow_write`, `allow_shell`, `allow_*`,
`permissions`, tool-list, sandbox, or root-path field, and no client can grant
itself authority. Clients still select a workspace by opaque `workspace_id`
only.

### Runtime-neutral authorization

`ava.execution.tool_security` is a new runtime-neutral module living in the
core/execution layer. It imports only `ava.contracts.runtimes` and
`ava.workspaces.contracts`; it never imports OpenHands, a model provider,
`ava.runtimes`, `ava.models`, configuration, or infrastructure. It contains:

- `ToolAuthorizationPolicy.evaluate(tool_id, capabilities, workspace) ->
  ToolAuthorizationDecision(allowed, reason_code)` — a pure, fail-closed
  activation policy;
- `ToolAuditEvent`, `ToolAuditSink` (protocol), `NoOpToolAuditSink`,
  `InMemoryToolAuditSink`;
- `ToolRunContext` — run-scoped identity, audit sink, and `revoked` event.

The architectural rule is `authorize → construct approved tools → runtime
receives only approved tools`, never `construct all tools → hope the model
does not use them`. `ava.runtimes.adapters.openhands.file_policy.build_openhands_tools`
evaluates the policy for the `file_editor` and `ava_terminal` tool ids and
returns a plain list of approved OpenHands tool *specs*, plus opaque
context-id params. Missing policy, missing runtime capability, missing
workspace, insufficient permissions, unknown tools, and missing terminal
composition dependencies all fail closed.

### Tool ids, decisions, and reason codes

Tool ids: `file_editor`, `ava_terminal`. Decision type:
`ToolAuthorizationDecision(allowed: bool, reason_code: str)`.

Activation reason codes: `allowed`, `tool_not_approved`,
`runtime_capability_missing`, `workspace_required`,
`workspace_read_denied`, `workspace_shell_denied`,
`network_policy_unsupported`, and `tool_disabled` (no policy, or terminal
requested without a composed policy+runner).

Operation reason codes remain distinct from activation: file
`path_outside_workspace`, `delete_not_authorized`, `write_not_authorized`,
`unsafe_file_type`, `file_size_limit`, `file_operation_failed`,
`run_cancelled`; command `read_permission_required`,
`shell_permission_required`, `local_workspace_required`,
`workspace_root_unavailable`, `working_directory_outside_workspace`,
`invalid_executable`, `sandbox_required`, `command_nonzero_exit`,
`sandbox_timeout`, `run_cancelled`; runner `sandbox_unavailable`,
`environment_not_allowed`, `invalid_resource_limits`,
`network_policy_unsupported`, `executable_not_allowed`,
`workspace_unavailable`, `sandbox_start_failed`, `timeout`, `cancelled`,
`sandbox_resource_limit`.

### Tool activation matrix

`RuntimeCapabilities` describe implementations and never grant run permission.
`OpenHands supports shell` is not permission; only the server-approved
workspace permission is.

| Workspace state | FileEditor read | FileEditor write | ava_terminal |
| --- | --- | --- | --- |
| no workspace / no local path | unavailable | unavailable | unavailable |
| read-only (`read=T, write=F`) | allowed | denied (`write_not_authorized`) | unavailable |
| read/write (`read=T, write=T`) | allowed | allowed | unavailable |
| read/write/shell (`read=T, write=T, shell=T, network=F`) | allowed | allowed | available; every request still passes `CommandExecutionPolicy` |
| unknown tool id | denied (`tool_not_approved`) | — | — |
| runtime capability missing | denied (`runtime_capability_missing`) | — | — |
| runtime `network=true` on workspace | — | — | denied (`network_policy_unsupported`) |
| revoked / cancelled run | denied (`run_cancelled`) | denied (`run_cancelled`) | denied (`run_cancelled`) |

No workspace means no cwd, home, repository, or `/` fallback. A read-only
FileEditor may exist while `file.write` is denied: tool availability never
replaces operation policy, and `ava_terminal` availability never authorizes
arbitrary commands.

### Run-level revocation

Revocation is represented by a run-scoped `ToolRunContext` holding a
`threading.Event` named `revoked`. `OpenHandsRuntime` creates exactly one
context per run, stores it under the run id, and `OpenHandsRuntime.cancel_run`
sets that run's event. No global mutable state is used, so parallel runs are
independent and one run's cancellation cannot revoke another's.

Revocation is checked at **operation time**, not only at tool construction:

- `ContainedFileEditorExecutor.__call__` checks `context.revoked.is_set()`
  before dispatching any read or write and records `run_cancelled`;
- `AvaTerminalExecutor._execute` checks it before policy evaluation, and
  `_run_command` polls it while a command runs, calls `runner.cancel`, and
  awaits process-tree cleanup.

A surviving OpenHands SDK worker that obtains an authorized tool object still
cannot begin a new privileged AVA-controlled operation after cancellation
because the per-operation gate denies it. The tool specs the SDK holds are
specs plus opaque context ids; the runtime-only dependencies (workspace,
policy, runner, context) live in adapter-local registries and are discarded in
`OpenHandsRuntime.execute`'s `finally` block.

**OpenHands cancellation limitation (accurate statement).** AVA can and does
hard-stop processes it owns through the Bubblewrap runner. AVA does **not**
claim that OpenHands SDK cancellation forcibly terminates the underlying
worker thread; the SDK can report cancellation while a worker thread survives.
The security guarantee is narrower and precise: a revoked run cannot initiate
additional AVA-controlled privileged tool operations.

### Operation-level policy retained

Authorization activates tools; it never replaces per-operation enforcement.
Contained FileEditor behavior remains: canonical containment against the
approved root, absolute/`..`/symlink-escape denial, hidden-and-outside
directory-listing filtering, hard-link rejection, FIFO/device/socket
rejection, the 10 MiB named file-size limit, read-only write denial, and
deletion disabled (`delete_not_authorized`). The OpenHands SDK delete schema
was **not** broadened to test deletion; the deletion guard is exercised
directly against the contained editor.

Terminal behavior remains: structured `executable` + literal `arguments` +
optional relative `working_directory`; combined executable strings, executable
paths, shell metacharacters, unavailable/absolute/`..`/symlink-escape working
directories, `shell=false`, and unapproved workspaces are denied. A valid
nonzero exit is a normal execution result, not a security failure. Bubblewrap
remains the only executor and the raw OpenHands `TerminalTool` remains
unavailable.

### Audit metadata

`ToolAuditEvent` contains only `run_id`, `runtime_id`, `tool_id`, `action`,
`outcome`, `reason_code`, and a timezone-aware `timestamp`. It deliberately
contains no prompt text, file contents, tool-result bodies, stdout/stderr
bodies, secret values, full command arguments, or file paths. Recorded actions
are `tool.activate`, `file.read`, `file.write`, and `command.execute`;
outcomes are `authorized`, `denied`, `success`, and `failure`. Denial
(`denied`) is kept distinct from an authorized operation that failed
(`failure`). The default sink is `NoOpToolAuditSink`; `InMemoryToolAuditSink`
is for tests and internal consumers and is never a public run event.

Audit observes decisions and operations; it does not control them. Sink
failure is caught, logged without payload or exception text, and never
converts a deny into an allow.

### Error sanitization

Public/client-visible errors no longer expose host paths, workspace roots,
internal stack traces, environment values, or sandbox command lines. Internal
diagnostics still exist at appropriate levels.

- File: `FileSecurityError` carries a fixed reason code and a fixed
  public-safe message; unexpected exceptions are logged internally and the
  observation text is the constant `File operation failed`.
- Terminal: policy denials return a constant message; runner results map to
  `Command execution ended: <reason>`; unexpected exceptions return the
  constant `Command execution failed`.
- Public run boundary: the native agent converts an unexpected runtime failure
  to `Agent runtime failed`, and `RunService` emits
  `The agent failed to complete the run.` A test injects a failure containing
  `/tmp/ava-secret-root-123` and `AVA_FAKE_SECRET_DO_NOT_LEAK` and asserts
  neither the path nor the sentinel appears in the public run response or event
  stream.

### Bubblewrap validation, environment, and process cleanup

The Bubblewrap integration suite validates: fake-secret isolation
(`AVA_FAKE_SECRET_DO_NOT_LEAK` and provider tokens read as `None`), `HOME`
isolation (`HOME=/tmp/ava-home`, never the host home), temporary-directory
isolation (`TMPDIR=/tmp`; an unrelated host temp file is invisible), a
host-loopback TCP listener is unreachable from the sandbox namespace
(`ConnectionRefusedError`; this proves the new network namespace does not reach
the host loopback, not broader egress shaping), process visibility (a synthetic
host PID has no `/proc/<pid>` and `os.kill(pid, 0)` raises `ProcessLookupError`
while the host process stays alive), timeout behavior, cancellation, CPU /
memory / process-count rlimits, a 64 KiB output cap with truncation flag, and
owned-process-tree cleanup. After timeout and after cancellation, the recorded
outer Bubblewrap process, command parent, and command child are all absent from
`/proc`.

Note on execution environment: Bubblewrap namespace/socket creation is
sometimes blocked by an enclosing development sandbox (including the tooling
sandbox used during implementation). Where that occurs the suite must be run in
the local/host execution context; an enclosing-sandbox restriction is not an
AVA failure. In this repository's local context the suite runs with
Bubblewrap available.

### Architecture invariants

- Runtime capability != permission.
- Model qualification != permission; no security path references Granite,
  Qwen, `model_id`, provider, LoRA, or any qualification score.
- Tool availability != operation authorization.
- Model/provider/profile selection cannot grant or elevate write, shell,
  network, or sandbox limits; those remain server/workspace-owned.
- Run cancellation revokes privileged operations for that run only.
- Security contracts remain runtime-neutral and core/application layers import
  no OpenHands SDK types.
- `RunService` continues to depend only on `AgentPort`; no
  `ToolAuthorizationPolicy`, `ToolAuditSink`, `WorkspaceRegistry`,
  `WorkspaceResolver`, `RuntimeRegistry`, or `ModelRegistry` is injected into
  it.
- OpenHands ambient tools (raw `TerminalTool`, TaskTracker, browser, MCP,
  plugins, hooks, skills, default SDK tools, delegation) remain disabled; only
  `file_editor` and `ava_terminal` specs are accepted, and
  `ControlledConversation` disables ambient plugin loading.
- No persistent audit database, no auth/RBAC, no Git tooling, and no
  production repository registration were introduced. The workspace registry
  starts empty; temporary test workspaces only.

### Validation

- Focused tool/security suite (authorization matrix, audit, security matrix,
  contained FileEditor, command policy, Bubblewrap runner): **116 passed**.
  Including architecture guards and workspace-execution tests: **184 passed**.
- Full backend suite: **498 passed, 2 skipped** (both skips are the opt-in
  live local-model qualification tests gated by
  `AVA_RUN_LOCAL_MODEL_QUALIFICATION=1`).
- Bubblewrap integration: **15 passed** in the local execution context.
- Ruff: `ruff check src tests` → all checks passed.
- Strict mypy: `mypy src` → success, **86 source files**.
- Python client: unchanged public contract; client tests pass (**7 passed**).
- No model inference was run or required.

### Audit boundary (explicit non-goals)

Step 36 implements the audit *contract and internal generation* only. It does
**not** implement a persistent audit database, a public audit API or UI, user
attribution, or RBAC. Persistent audit storage belongs to the future
persistence architecture.

### Known limitations

- The OpenHands SDK worker/thread may outlive cancellation; AVA revokes
  privileged AVA-controlled operations but does not forcibly terminate that
  thread.
- No persistent security audit storage.
- No auth/RBAC or user attribution.
- No Git authorization.
- No production repository workspace is registered.
- No package-management policy (executables are allowlisted; no `pip`/`apt`).
- TOCTOU remains between path validation and sandbox mount.
- Bubblewrap/user-namespace availability and rlimits (not cgroup aggregate
  accounting) remain environment constraints.

---

## Step 37 — Multi-Model Architecture Seam Audit

**Status: COMPLETE — audit only; no multi-model subsystem implemented, no model
inference required**

### Goal

Before any Model Registry is built, determine which seams of the planned
multi-model foundation already exist, which are partial, and which are missing,
and confirm the Step 32–36 security invariants still hold. The full findings are
recorded in `docs/AVA_Multi_Model_Architecture_Audit.md`.

Target foundation (three separated concerns): a descriptive **Model Registry**
(what models exist, nominal capabilities, measured qualifications, hosting,
availability — never permissions), a **Model Orchestrator** (selection policy),
and a **Resource Manager** (residency/leases). The audit checks the existing
code against these boundaries.

### Findings (summary)

Existing and wired: the model-provider port/registry/resolver
(`ava.models.contracts/registry/resolver`), the OpenAI-compatible protocol
adapter, the agent-runtime port/registry/resolver and the native/OpenHands
runtimes, the provider→runtime binding (`models/bindings.py`), `ModelInfo` /
`ModelCapabilities`, `RuntimeInfo` / `RuntimeCapabilities`, measured
qualification (`runtimes/qualification.py`), run execution-selection identity,
and the `/model-providers`, `/runtimes`, `/workspaces`, `/execution-profiles`
endpoints.

Partial or missing (documented as gaps G1–G9 in the audit): provider:model
cardinality is 1:1 with no model catalog; no hosting-mode representation or
local-only enforcement; model identity is provider-scoped; auto routing is a
placeholder that discards the request, hardcodes an `openhands` exclusion, and
validates only the `chat` capability; no persisted identity-keyed qualification;
execution profiles conflate runtime+provider and are hardcoded; configuration is
single-model; `RuntimeModelBinding` carries an `api_key` and must stay internal.

### Security invariants

No invariant was weakened. Model/runtime metadata and execution-selection
identities remain descriptive; permission, sandbox, and authorization decisions
stay server/workspace-owned. `RunService` still depends only on `AgentPort`;
`ToolAuthorizationPolicy` still has no model/provider/runtime/profile dependency.
Two narrow architecture guard tests were added to lock in the
descriptive-not-authoritative boundary:

- `test_model_and_runtime_metadata_contracts_carry_no_permission_grants`
- `test_runtime_model_binding_carries_no_permission_grants`

### Explicit non-goals

No Model Registry, ModelProfile, `/models` endpoint, Model Orchestrator,
Resource Manager, automatic model routing, fallback chains, phase-aware
multi-model behavior, new inference runtime, training/SFT-v2, auth/RBAC,
persistence, production repository workspace, Git tooling, or Step 38 work was
implemented.

### Validation

- Architecture guard suite (including the two new boundary tests): **38 passed**.
- Full backend suite: **500 passed, 2 skipped** (both skips the opt-in live
  local-model qualification tests).
- Ruff: `ruff check src tests` → all checks passed.
- Strict mypy: `mypy src` → success, **86 source files**.
- No model inference was run or required.


## Step 38 — Stable Model Identity and Provider Cardinality Foundation

**Status: COMPLETE — foundation only; no Model Registry, no `/models`, no
inference required**

### Goal

Remove the provider↔model 1:1 assumption (Step 37 gap G1) and the
provider-scoped model identity (gap G3) by introducing a stable, provider-neutral
AVA `model_id` and decoupling model bindings from concrete provider instances.
The provider is explicitly told which provider-native model name to run on each
call and never selects a model itself.

### Identity model

Three identities are now distinct and carried separately:

- **stable AVA `model_id`** — opaque, provider-neutral, used in selection and run
  metadata (e.g. `ava/qwen-small`);
- **`provider_id`** — the AVA provider registry identity (e.g. `local`);
- **`provider_model_name`** — the deployment-native name a runtime/provider must
  target (e.g. `qwen3.5:9b-q4_K_M`).

`ConfiguredModelBinding(model_id, provider_id, provider_model_name)` in
`ava/models/bindings.py` maps a stable identity to one provider deployment;
`ModelBindingResolver` is a small immutable index over configured bindings with
`resolve` (explicit, fail-closed `UnknownModelError`), `default`,
`default_for_provider` (`NoModelConfiguredForProviderError`), `contains`, and
`list_model_ids`. It is deliberately **not** the Model Registry: no
qualification, hosting mode, hardware, resource state, licensing, or routing
scores.

### Execution flow

```
RunRequest.execution.model_id (optional, preferred)
  → ExecutionSelector.resolve
  → ModelBindingResolver.resolve / default_for_provider / default
  → ResolvedExecution(runtime, model_provider, model_binding)
  → NativeAgentAdapter → runtime.execute(model_binding=...)
  → provider.generate(request, model_name=provider_model_name)
```

- `RunExecutionOverride` gains an optional `model_id`. `model_provider_id`
  remains for backward compatibility (provider-only selection binds that
  provider's configured default model); if both are supplied and conflict, the
  run fails cleanly.
- `RunExecutionSelection.model_id` now records the stable AVA identity (not the
  provider-native name).
- `AgentRuntimePort.execute` gains an optional keyword-only
  `model_binding: ConfiguredModelBinding | None`.
- `ModelProviderPort.generate(request, *, model_name=None)` is additive; the
  OpenAI-compatible provider targets the explicit name or falls back to its
  bootstrap name.
- `RuntimeModelBinding` now carries `model_id`, `provider_id`, and
  `provider_model_name` alongside protocol/endpoint/credential; the OpenHands
  runtime sends `openai/<provider_model_name>` to LiteLLM.
- `Settings.model_id` (`AVA_MODEL_ID`) is optional; blank derives a legacy id
  `"{provider_id}-{model_name}"`, so existing deployments need no
  reconfiguration. `create_configured_model_bindings(settings)` composes the
  bootstrap resolver; `create_agent_adapter` receives it and `create_app` stores
  it on `app.state.model_binding_resolver`.

### Cardinality

One provider object may serve many bindings. The provider registry and resolver
remain strictly provider-only; model identity never selects a provider on its
own, and the runtime resolves the provider from the binding's `provider_id`.

### Security invariants

Unchanged. `runtime capability != permission`, `model qualification !=
permission`, `tool availability != operation authorization`. Model identity and
bindings are descriptive; they grant no write/shell/network/sandbox authority.
`ConfiguredModelBinding` carries no credential or connection fields, and
`RuntimeModelBinding` (which does carry `api_key`) remains internal-only and is
never serialized to a contract or client. `RunService` still depends only on
`AgentPort`; `ToolAuthorizationPolicy` is untouched.

### Explicit non-goals

No Model Registry, `/models` endpoint, Model Orchestrator, Resource Manager,
hosting-mode policy, automatic model routing, fallback chains, persisted
qualification, execution-profile refactor, new inference runtime, auth/RBAC,
training, persistence, Git tooling, or Step 39 work.

### Validation

- Full backend suite: **515 passed, 2 skipped** (both skips the opt-in live
  local-model qualification tests).
- Step 38 tests (`tests/test_stable_model_identity.py`): resolver cardinality /
  identity separation / unknown-identity fail-closed / conflict handling /
  legacy bootstrap, plus explicit and provider-only execution selection.
- Architecture guards (binding/allowlist) remain green, including the extended
  `test_runtime_model_binding_carries_no_permission_grants` over
  `ConfiguredModelBinding`.
- Ruff: `ruff check src tests` → all checks passed.
- Strict mypy: `mypy src` → success, **86 source files**.
- TypeScript contracts: `@ava/contracts` tests **9 passed**; `tsc --noEmit`
  clean. Python client tests **7 passed**.
- No model inference was run or required.

## Step 39 — Hosting Mode and Model Deployment Classification

**Status: COMPLETE — placement classification + local-only enforcement seam;
no Model Registry, no `/models`, no routing policy, no inference required**

### Goal

Make *where a configured model deployment runs* an explicit, server-owned
classification (Step 37 gap G2) and add the smallest runtime-neutral seam that
can enforce a local-only placement constraint, without introducing a routing
policy, a Model Registry, or per-run client control over placement.

### Hosting modes

`ModelHostingMode` (StrEnum) in `ava/contracts/models.py` is a closed set of
exactly three values, with defined semantics:

- **`local`** — inference runs on the user's / local AVA-controlled machine
  (e.g. Ollama on localhost, llama.cpp, local vLLM/SGLang);
- **`company_hosted`** — inference runs on company-operated/approved
  infrastructure reached through a company-controlled gateway (e.g. a company
  GenAI gateway or company cloud inference); no provider- or vendor-specific
  logic lives in core contracts;
- **`external`** — inference runs through an external third-party/SaaS service
  (e.g. public OpenAI or Anthropic APIs).

The mode is **descriptive deployment metadata only**. It is never inferred from
a provider id, provider name, protocol, endpoint, hostname, or URL scheme
(OpenAI-compatible can be local, company-hosted, or external), and it grants no
workspace, file, shell, network, or sandbox authority. It is distinct from
provider identity, inference runtime, `ModelCapabilities`, resource state
(loaded/available/GPU-resident — Resource Manager), operational status
(configured-but-unavailable), and data classification.

### Identity and composition

- `ConfiguredModelBinding` gains `hosting_mode: ModelHostingMode` with a
  back-compat default of `local`; production composition always sets it
  explicitly. `RuntimeModelBinding` intentionally does **not** carry hosting
  mode (runtimes do not make placement decisions), and `ModelInfo` intentionally
  does **not** carry it (it is server-owned classification, not
  provider-discovery data).
- `Settings.model_hosting_mode` reads `AVA_MODEL_HOSTING_MODE` through a strict
  parser: absent/blank → `local`; an unrecognized explicit value raises a
  configuration error (no silent fallback, no inference). Existing
  `AVA_MODEL_PROVIDER` / `AVA_MODEL_NAME` / `AVA_MODEL_ID` keep working.
  `create_configured_model_bindings` propagates the setting to the binding.
- `RunExecutionSelection` gains `hosting_mode: ModelHostingMode | None`, mirroring
  the placement of the resolved binding; `NativeAgentAdapter._selection` records
  it. `RunExecutionOverride` deliberately does **not** expose a hosting override:
  clients cannot dictate placement.

### Enforcement seam

`ava/execution/hosting.py` adds `ModelHostingRequirement` — a frozen value object
over a non-empty `frozenset[ModelHostingMode]` with `permits(...)` and the
`local_only()` constructor — plus stable internal `HostingReason` codes
(`hosting_mode_not_allowed`, `hosting_classification_unavailable`).

`ExecutionCompatibilityValidator.validate` gains optional keyword-only
`hosting_mode` and `hosting_requirement`. When a requirement is present, an
unpermitted mode (or a missing classification) is rejected **before** provider
invocation. The validator stays runtime-neutral; providers never enforce
placement policy. `NativeAgentAdapter`/`create_agent_adapter`/`create_app` accept
an optional server-owned `hosting_requirement` (default `None` = unconstrained).
There is no fallback: an explicitly selected incompatible model fails the run.
The public failure message stays sanitized ("Selected execution configuration is
not compatible"); the reason code is internal only.

### Security invariants

Unchanged and authoritative. `ToolAuthorizationPolicy` (Step 36) remains the sole
authority gate for tools; `runtime capability != permission`, `model
qualification != permission`, `hosting mode != permission`. Hosting classification
is placement data, not a security grant, and location never implies trust.
`RuntimeModelBinding.api_key` remains internal-only; hosting mode is non-secret
descriptive metadata. `RunService` still depends only on `AgentPort`.

### Explicit non-goals

No Model Registry, `/models` endpoint, Model Orchestrator, Resource Manager,
routing/scoring policy, automatic provider selection, fallback chains, per-run
hosting override, persisted qualification, execution-profile refactor, new
provider or runtime, auth/RBAC, training, persistence, or Git tooling.

### Validation

- Full backend suite: **533 passed, 2 skipped** (both skips the opt-in live
  local-model qualification tests).
- Step 39 tests (`tests/test_hosting_mode.py`): closed enum, capability/discovery
  exclusion, requirement `permits`/empty-set rejection, validator no-op vs.
  reject vs. fail-closed vs. permit, end-to-end local-only gate (local completes
  and records `hosting_mode`, external fails without executing and without
  leaking the reason), strict `AVA_MODEL_HOSTING_MODE` parsing, and composition
  propagation.
- `tests/test_stable_model_identity.py` extended: hosting mode is independent of
  provider identity and the configured binding still carries no connection or
  credential fields.
- Architecture guard added: `test_hosting_mode_is_closed_descriptive_metadata`.
- Ruff: `ruff check src tests` → all checks passed.
- Strict mypy: `mypy src` → success, **87 source files**.
- TypeScript contracts: `@ava/contracts` tests **10 passed** (hosting-aware
  selection mirror); `tsc --noEmit` clean. Python client tests **7 passed**.
- No model inference was run or required.

## Step 40 — Model Registry v1

**Status: COMPLETE — PASS.**

`ModelRegistry` is AVA's authoritative read-only catalog of frozen
`ModelProfile` records, keyed by stable `model_id`. Profiles hold only
`model_id`, `display_name`, `provider_id`, `provider_model_name`, `hosting_mode`,
declared `ModelCapabilities`, and `enabled`; they contain no credentials,
endpoints, paths, permissions, sandbox grants, qualification, resource, or
routing state.

`ModelBindingResolver` is registry-backed and derives `ConfiguredModelBinding`
from the selected profile, leaving no second configured-model catalog. The
startup default is registry-validated. Unknown and disabled explicit model ids,
or a conflicting provider id, fail before provider invocation. One provider can
serve multiple profiles while `model_id`, `provider_id`, `provider_model_name`,
and `hosting_mode` remain distinct.

The path is model id → `ExecutionSelector` → registry-backed resolver → profile
→ provider resolver → derived binding → internal `RuntimeModelBinding` → runtime.
`RunExecutionSelection` retains model identity and hosting mode; `RunService`
continues to depend only on `AgentPort`. Step 39 local-only enforcement remains
before provider invocation.

`GET /models` reads only the registry, makes no provider call or inference,
sorts by `model_id`, and includes disabled profiles. Public `ModelInfo` exposes
safe identity, display, provider, hosting, declared capabilities (including
`tool_calling`), and enabled state. Provider-native names, endpoints,
credentials, paths, and security metadata are excluded. TypeScript contracts and
API-client `getModels()`, plus Python-client `list_models()`, mirror this
response; no UI was added.

Architecture tests cover registry/provider/runtime separation, public metadata
safety, internal-only runtime credentials, and the AgentPort-only RunService
boundary.

### Validation

- Backend: **563 passed, 2 skipped**; Ruff passed and strict mypy passed for
  **90 source files**.
- TypeScript: contracts **11 passed** and `tsc --noEmit`; API client **23
  passed** and `tsc --noEmit`.
- Python client: **9 passed**; Ruff and strict mypy passed.
- No model inference was run.

G4 automatic routing, G5 persisted qualification, G6 execution-profile redesign,
G7 declarative multi-model configuration, G8 credential transport, a Model
Orchestrator, and a Resource Manager remain future work. No model training,
automatic model selection, fallback, phase-aware routing, auth/RBAC,
persistence, or Step 41 work was performed.

## Step 41 — Qualification Metadata Integration and Model Discovery Enrichment

**Status: COMPLETE — PARTIAL (persistence deliberately deferred).**

AVA now represents measured qualification as immutable `ModelQualification`
records in a separate read-only `ModelQualificationStore`, keyed by stable
`model_id` with optional `runtime_id` and `qualification_id`. The closed status
vocabulary is `pass`, `partial`, `fail`, and `not_tested`. The store rejects an
unknown configured model and duplicate identity keys, and it never imports or
invokes provider adapters, runtimes, the qualification harness, tools, or
inference.

`GET /models` enriches each catalog model with deterministic public-safe
qualification summaries sorted by task class, runtime id, and qualification id.
An empty list means no evidence is recorded; an explicit `not_tested` entry is
preserved as measured metadata. Qualification stays distinct from declared
`ModelCapabilities`, grants no permission, and does not alter hosting checks,
execution eligibility, routing, scoring, selection, or `RunService`.

Production composition intentionally supplies no historical qualification
records: the configured bootstrap `model_id` cannot be mapped deterministically
to existing harness artifacts. TypeScript and Python client contracts mirror
the enriched response. No UI, persistence, artifact scraping, model training,
or inference was added.

## Step 42 — Deterministic Model Orchestrator

**Status: COMPLETE — PASS.**

`ModelOrchestrator` performs the first model-only selection pass over the
configured `ModelRegistry` and `ModelQualificationStore`. It accepts structured
requirements only; prompts, transcripts, workspace data, credentials, provider
implementations, runtime adapters, and security mechanisms are outside its
boundary. An explicit `model_id` is authoritative when eligible and fails
closed when unknown, disabled, hosting-incompatible, provider-conflicting,
capability-incompatible, or insufficiently qualified.

Auto selection applies hard filters in order for enabled state, server-owned
hosting requirements, a fixed provider, declared capabilities, and requested
measured qualifications. It distinguishes missing evidence from non-PASS
evidence. Eligible candidates are ordered with the configured default first,
then stable lexical `model_id`; this is a bounded candidate ordering only and
does not execute provider/runtime fallback.

`ExecutionSelector` delegates model choice to the orchestrator in production
composition while runtime selection remains separate. The existing
`ExecutionCompatibilityValidator` continues to validate resolved
runtime/provider execution before invocation. `RunService` remains AgentPort
only. Selection neither grants nor changes workspace, tool, shell, network,
sandbox, credential, or file permissions. No endpoint, learned scoring,
resource management, training, or inference was added.

## Step 43 — Model Resource Manager

**Status: COMPLETE — PASS.**

`ModelResourceManager` is a runtime-neutral lifecycle layer below model
selection and above runtime invocation. It owns closed `cold`, `warm`,
`loading`, `hot`, `unloading`, and `unavailable` states, model-id-keyed
`ModelResourceDescriptor` metadata, explicit leases, transition validation,
and serialized acquire/unload operations. Transient residency and lease state
remain outside `ModelProfile`, `ModelRegistry`, qualification metadata, and the
orchestrator.

`acquire(model_id)` issues a lease immediately for HOT state, or performs
`COLD/WARM → LOADING → HOT` through a provider-specific resource adapter before
issuing one. Load and unload failures move the record to `UNAVAILABLE`; an
active lease prevents unload; release never triggers automatic eviction. The
manager applies known local RAM/VRAM descriptor estimates against optional
capacity and fails closed without unloading another model. It does not preload
models or execute fallback.

Current production composition uses a provider-managed pass-through adapter
with unknown capacity because no current provider exposes a verified load/unload
hook. It coordinates leases without claiming GPU telemetry or managing remote
provider memory. Concrete local lifecycle adapters remain a later
provider-specific increment; deterministic fake adapters cover local state
transitions and capacity behavior in tests. Company-hosted and external models
use the same adapter-owned ready semantics and consume no AVA-local capacity.

`NativeAgentAdapter` acquires the selected model lease immediately before
runtime execution and releases it in `finally` on success, runtime/provider
failure, or cancellation. `RunService` remains AgentPort-only. Resource
management has no prompt, workspace, file, credential, tool, shell, network,
sandbox, or permission authority. No public API or public run contract changed,
and no model inference or training was run.

### Validation (Step 43)

- Backend full suite: **588 passed / 2 skipped** (`pytest -q`).
- Ruff: clean (`ruff check src tests`).
- Strict mypy: clean across **93 source files**.
- Step-43 targeted coverage: `tests/test_model_resources.py` (includes fake
  resource lifecycle, cold→hot load, concurrent same-model acquire/reuse with a
  single load and per-lease release, capacity fails-closed with no eviction,
  unknown/transitioning/unload-with-active-lease, failure- and
  cancellation-released leases, explicit unknown-model failure without
  fallback).
- Architecture seams from Step 43, violated only by design: orchestrator does
  not import the resource manager (no lifecycle ownership), the resource
  manager does not import the orchestrator/routing (no selection), and neither
  gains workspace, tool/security, sandbox, provider-implementation, or
  runtime-adapter authority. New static guards: resource manager and
  orchestrator imports are asserted against that split.
- Python client: **10 passed**; Ruff and strict mypy clean.
- `@ava/contracts`: **11 passed** + `tsc --noEmit`; `@ava/api-client`: **23
  passed** + `tsc --noEmit`.
- Frontend builds: web and desktop build; web desktop/platform and agent-ui
  TypeScript-compile and test surfaces were re-run. (Two pre-existing agent-ui
  prompt-composer assertions lag the intentional Send glyph; they are
  unrelated to Step 43's backend-internal lifecycle work.)
