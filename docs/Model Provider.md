# AVA Model Provider

## Purpose

The Model Provider port is the boundary between AVA and model runtimes /
providers. AVA Core depends on this abstraction; provider SDKs depend on
AVA's boundary — not the other way around.

```text
AVA Core
    │
Model Provider Port
    │
    ├── Local
    ├── Company Gateway
    └── External
```

## Data Contracts

Defined in `backend/src/ava/contracts/models.py`.

```python
class ModelProviderHealthStatus(StrEnum):
    HEALTHY        = "healthy"
    DEGRADED       = "degraded"
    UNAVAILABLE    = "unavailable"
    RUNTIME_UNAVAILABLE = "runtime_unavailable"
    MODEL_NOT_LOADED    = "model_not_loaded"
    AUTHENTICATION_FAILED = "authentication_failed"
    CONFIGURATION_INVALID = "configuration_invalid"

class ModelProviderHealth(BaseModel):
    available: bool
    status: ModelProviderHealthStatus
    message: str | None = None

class ModelCapabilities(BaseModel):
    chat: bool = False
    streaming: bool = False
    tool_calling: bool = False
    structured_output: bool = False
    vision: bool = False
    embeddings: bool = False
    reasoning: bool = False
    code_specialization: bool = False

class ModelInfo(BaseModel):
    provider_name: str
    model_id: str
    display_name: str | None = None
    context_limit: int | None = None
    capabilities: ModelCapabilities

class ModelMessage(BaseModel):
    role: str
    content: str

class ModelRequest(BaseModel):
    messages: list[ModelMessage]
    temperature: float | None = None
    max_output_tokens: int | None = None

class ModelResponse(BaseModel):
    content: str
    model_id: str
```

Capability defaults are conservative: a capability is only `True` when the
provider's adapter confirms the model supports it. Tools, structured output,
usage, and metadata fields will be added through additive contract changes.

## Port

Defined in `backend/src/ava/models/contracts.py`.

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

### Operations

- **`name()`** — returns the provider name.
- **`health()`** — returns a structured `ModelProviderHealth` with a coarse
  `available` flag, a normalized `status`, and an optional human-readable
  `message`. Asynchronous because health checks may require I/O against a
  local runtime, a company gateway, or an external provider.
- **`get_model_info()`** — returns AVA-owned provider and model identity
  information as `ModelInfo`, including the model's normalized capabilities.
- **`get_capabilities()`** — reports the capabilities the provider actually
  supports as an AVA-owned `ModelCapabilities` contract. This is *not* the
  application-level `CapabilityName` vocabulary (`/capabilities`, `AgentPort`);
  it describes the model's capabilities (chat, streaming, tool calling, ...).
- **`generate(request)`** — generates a model response from an
  AVA-owned `ModelRequest` and returns an AVA-owned `ModelResponse`.

## Registry

Defined in `backend/src/ava/models/registry.py`.

```python
class ModelProviderRegistry:
    def register(self, provider_id: str, provider: ModelProviderPort) -> None
    def get(self, provider_id: str) -> ModelProviderPort | None
    def contains(self, provider_id: str) -> bool
    def list(self) -> list[str]
```

The central backend container of available model providers. Providers register
under an AVA provider identity (e.g. `mock`, `local`, `corporate`, `external`).
These ids are AVA identities, not framework classes.

- `register()` — binds a `ModelProviderPort` implementation under a provider
  identity. Raises `ValueError` on blank or duplicate ids.
- `get()` — returns the registered provider, or `None` if unknown.
- `contains()` — explicit existence check.
- `list()` — registered ids in insertion order.

The registry is a pure container over the port abstraction: it holds no
provider logic and never imports vendor SDKs. Resolution from configuration
(reading `ApplicationConfig.model_provider` and selecting through the
registry) is performed by the `ModelProviderResolver`; the registry itself
never selects a provider.

## Resolver

Defined in `backend/src/ava/models/resolver.py`.

```python
class ModelProviderResolver:
    def __init__(self, registry: ModelProviderRegistry) -> None
    def resolve(self, provider_id: str) -> ModelProviderPort

class UnknownModelProviderError(ValueError):
    provider_id: str
```

The AVA-owned service that resolves a configured model provider id into the
registered `ModelProviderPort`:

```text
Configuration (provider id)
    ↓
ModelProviderResolver
    ↓
ModelProviderRegistry
    ↓
ModelProviderPort
```

- `resolve()` returns the registered port for an AVA provider identity.
- Unknown or blank ids raise `UnknownModelProviderError` (a `ValueError`
  subclass) carrying the unresolved id. No default provider is returned and
  resolution never returns `None`.
- The resolver depends on the registry through composition only; there is no
  global or hidden registry state, and it never constructs or registers
  providers.
- `model_name` is never the resolver's concern: Step 6 keeps
  `model_provider` and `model_name` independent, and resolution operates on
  the provider id alone.

The registry/resolver are part of application composition since Step 9:
`create_app()` composes the registry (via
`infrastructure/create_model_provider_registry`) and stores the registry and a
resolver over it on `app.state`. Discovery reads the registry since Step 10;
Step 11 resolves a provider for native-agent execution at composition time.
The default mock agent remains independent of model resolution.

## OpenAI-Compatible Provider

Defined in
`backend/src/ava/models/providers/openai_compatible/provider.py`.

```python
class OpenAICompatibleModelProvider(ModelProviderPort):
    def __init__(
        self,
        *,
        base_url: str,
        model_name: str,
        provider_name: str = "openai-compatible",
        api_key: str | None = None,
        timeout: float | None = None,
        capabilities: ModelCapabilities | None = None,
        context_limit: int | None = None,
        display_name: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None: ...
```

The first real `ModelProviderPort` adapter. It speaks the OpenAI-compatible
chat-completions HTTP protocol directly over a generic async HTTP client
(`httpx`) — no OpenAI SDK, Ollama SDK, or other vendor SDK.

The adapter represents a **protocol**, not a deployment. The same class is
intended for a local Ollama `/v1` endpoint, a company OpenAI-compatible
gateway, or an approved external endpoint. It never reads application settings
or environment variables; configuration is passed in at construction.

```text
AVA ModelRequest
    ↓  (translation stays inside the adapter)
POST {base_url}/chat/completions
    ↓
OpenAI-compatible response JSON
    ↓
AVA ModelResponse
```

### Protocol mapping

- Generation: `POST {base_url}/chat/completions`
- Health: `GET {base_url}/models`

| AVA (`ModelRequest`) | Compatible request JSON |
| --- | --- |
| `messages[].role` / `content` | `messages[].role` / `content` |
| `temperature` (when set) | `temperature` |
| `max_output_tokens` (when set) | `max_tokens` |
| adapter identity | `model` = configured `model_name` |

The compatible response's `choices[0].message.content` becomes
`ModelResponse.content`; the response `model` becomes `ModelResponse.model_id`.
Raw HTTP responses, JSON dicts, and provider objects never leave the adapter.

### Health

`health()` probes `GET {base_url}/models` and maps the result:

| Condition | Status |
| --- | --- |
| 2xx | `HEALTHY` |
| 401 / 403 | `AUTHENTICATION_FAILED` |
| connection refused | `RUNTIME_UNAVAILABLE` |
| timeout / other transport error | `UNAVAILABLE` |
| invalid URL | `CONFIGURATION_INVALID` |
| blank `base_url` (`""`, `"   "`) | `CONFIGURATION_INVALID` |
| other non-2xx status | `UNAVAILABLE` |

### HTTP client lifecycle

The adapter's HTTP client ownership is explicit:

- **Injected client** (`http_client=`): owned by the caller. The provider
  never closes it, and `aclose()` leaves it open and usable.
- **Provider-created client**: owned by the provider. Call
  `await provider.aclose()` (or use `async with provider:`) to close it.
- One client is created per provider instance and **reused** across
  `health()` / `generate()` calls — never one per request.
- `aclose()` is idempotent: calling it more than once never fails. A
  caller-injected client is a no-op for `aclose()`.

`aclose()` is adapter resource lifecycle, not (yet) a `ModelProviderPort`
requirement.

### Invalid URL handling

Malformed configuration is detected **before any I/O** via a provider-local
stdlib (`urllib.parse.urlsplit`) check covering the scheme (`http`/`https`), a
hostname, and (when present) an in-range numeric port. This prevents an
out-of-range port (e.g. `http://localhost:99999/v1`) from surfacing as a raw
`ExceptionGroup` from the transport stack, and a non-numeric port from
surfacing as `httpx.InvalidURL` (neither is a `RequestError`):

- `generate()` → `ModelProviderError` (static message; no URL or API key).
- `health()` → `CONFIGURATION_INVALID` with `available = False`, never raising.

Harmless outer whitespace on `base_url` (e.g. `"  http://host/v1/  "`) is
stripped at construction before URL assembly; path content is untouched.

### Capabilities

Defaults are conservative: the adapter enables `chat=True` (it implements the
chat-completions protocol) and leaves every other capability `False`. Explicit
`ModelCapabilities` supplied at construction are used unchanged — no
capability is inferred merely because an OpenAI-compatible server might
support it.

### Authentication

An optional `api_key` is sent as `Authorization: Bearer <key>`. When absent,
no `Authorization` header is sent. Keys are never included in error messages
or stored by the adapter.

### Errors

Provider failures raise `ModelProviderError`
(`ava.models.providers.errors`) — a single, narrow AVA-owned exception that
optionally carries `status_code`. Transport failures, invalid URLs, non-success
HTTP statuses, invalid JSON, and malformed/incomplete responses all map to this
error; raw `httpx` exception types (including `httpx.InvalidURL`) never cross
the port boundary. No retries, backoff, or circuit breakers are implemented.

### Status: discovery and native-agent execution

Since Step 9, composition constructs the local provider from `Settings` and
registers it once. Step 10 added discovery through `GET /model-providers`.
Step 11 adds the first execution consumer: `NativeAgentAdapter` receives that
same provider through `ModelProviderPort` constructor injection.

`AVA_AGENT_PROVIDER=mock` remains the default and never resolves a model.
`AVA_AGENT_PROVIDER=native` resolves `AVA_MODEL_PROVIDER` during composition;
an unknown identity fails explicitly. Startup performs no health or generation
I/O, so an offline runtime does not prevent application construction.

The native agent sends the existing run prompt as one user `ModelMessage`,
then translates complete response content into `AgentRunResult`. Provider
errors and unexpected ordinary exceptions become sanitized failed results;
in-flight task cancellation becomes a cancelled result. `RunService` remains
unchanged and model-provider-free, owning all run events. The agent neither
selects a model nor closes the provider; FastAPI lifespan retains shutdown
ownership. Automated tests use deterministic test ports and require no live
Ollama, internet, or credentials. Streaming, tools, and embeddings remain out
of scope.

## Model Provider Discovery (Step 10)

### Purpose

Answer "what model providers are available, and are they healthy?" through a
read-only endpoint. This is the first place the registry is consumed in
production; it never selects, starts, or executes a provider and does not
touch the run path.

### Contracts

Defined in `backend/src/ava/contracts/responses.py` (reusing the Step 4
port contracts — no parallel vocabulary):

```python
class ModelProviderDiscoveryItem(BaseModel):
    provider_id: str
    is_default: bool
    model_info: ModelInfo              # reused
    health: ModelProviderHealth        # reused
    contract_version: str = "v1"

class ModelProviderDiscoveryResponse(BaseModel):
    contract_version: str = "v1"
    default_provider_id: str
    providers: list[ModelProviderDiscoveryItem]
```

`default_provider_id` truthfully reports the configured default
(`Settings.model_provider`), even when nothing is registered under it. An
unknown default (e.g. `corporate`) yields an empty/sans-default provider
list — no startup failure, no fake provider, no silent substitution to
`local`.

### Service

`backend/src/ava/services/model_provider_discovery_service.py`:

```python
class ModelProviderDiscoveryService:
    def __init__(self, *, registry: ModelProviderRegistry,
                 default_provider_id: str) -> None: ...
    async def discover(self) -> ModelProviderDiscoveryResponse: ...
```

- Depends only on the registry (a pure container), the `ModelProviderPort`,
  and AVA contracts. No adapters, HTTP clients, configuration, agent layers,
  or runtime frameworks.
- Reads the registry through `list()` / `get()` only. It does not know which
  ids are special; the configured default is supplied at composition. The
  resolver is **not** used (discovery enumerates, it does not resolve).
- One raising provider becomes a sanitized `UNAVAILABLE` report
  (`message="Model provider health check failed"`); the others are still
  returned. Raw exceptions never escape.

### Endpoint

`GET /model-providers` (`backend/src/ava/api/routes/model_providers.py`) —
a dedicated resource endpoint rather than an extension of `/capabilities`
(which reports application capability names). The route reads the discovery
service from `app.state`, contains no business logic, and never imports a
concrete provider.

```json
{
  "contract_version": "v1",
  "default_provider_id": "local",
  "providers": [
    {
      "provider_id": "local",
      "is_default": true,
      "model_info": {
        "provider_name": "local",
        "model_id": "local-model",
        "display_name": null,
        "context_limit": null,
        "capabilities": { "...": false, "chat": true },
        "contract_version": "v1"
      },
      "health": {
        "available": true,
        "status": "healthy",
        "message": null,
        "contract_version": "v1"
      },
      "contract_version": "v1"
    }
  ]
}
```

### Behavior notes

- The service never probes the network itself — the adapter's `health()`
  does (`GET {base_url}/models`). Health checks are sequential per provider.
- **No startup health checks**: composing the application and serving
  `/health` still never contact a provider runtime; discovery is exercised
  only when the endpoint is called. With Ollama offline, `GET /model-providers`
  returns 200 with the local provider reported
  `available=false, status=runtime_unavailable` (never an error).
- Clients: `@ava/api-client.getModelProviders()`,
  `AvaClient.model_providers()` (Python). No UI was added.

## Configuration

AVA configuration identifies the model provider and model independently of
the agent configuration:

```text
agent_provider = "mock"          # AVA_AGENT_PROVIDER (default: mock)
model_provider = "local"         # AVA_MODEL_PROVIDER (default: local)
model_name     = "local-model"   # AVA_MODEL_NAME     (default: local-model)
local_model_base_url = "http://localhost:11434/v1"
                                 # AVA_LOCAL_MODEL_BASE_URL (default: Ollama /v1)
```

All are separate settings fields with separate environment variables and
independent defaults. Changing the model provider or model never changes the
agent configuration, and vice versa. `model_name` is the one canonical
model-identifier field. The default `local-model` is a neutral placeholder:
the application starts without requiring a live provider or installed model.

`local_model_base_url` is the OpenAI-compatible transport endpoint for the
local provider. It lives in `Settings` only (not the framework-neutral
`ApplicationConfig`): it is an endpoint detail consumed by the composition
layer, not something AVA core needs to know about.

Configuration is AVA-owned and provider-neutral. It does not import the
registry, instantiate providers, resolve provider ids, or validate provider
or model availability — resolution through the registry is handled by the
`ModelProviderResolver`, not by configuration.

## Selection Is Configuration-Driven

Future provider selection changes require no AVA Core rewrite:

```text
model_provider = local
model_provider = company_gateway
model_provider = external
```

The provider selection lives in `Settings.model_provider` /
`ApplicationConfig.model_provider` and is driven by the
`AVA_MODEL_PROVIDER` environment variable. The model itself is selected
independently by `Settings.model_name` / `ApplicationConfig.model_name`
(`AVA_MODEL_NAME`):

## Composition

Production composition (`backend/src/ava/infrastructure/composition.py`) is
the only place that constructs model providers:

```text
Settings
   ↓ create_model_provider_registry(settings)
OpenAICompatibleModelProvider(base_url=settings.local_model_base_url,
                              model_name=settings.model_name,
                              provider_name="local")
   ↓ register("local")
ModelProviderRegistry
   ↓ ModelProviderResolver (over the same registry)
app.state.model_provider_registry / app.state.model_provider_resolver
```

- When `model_provider == "local"` (the default), a real local provider is
  constructed and registered. An unknown identity registers nothing; startup
  never fails eagerly for it.
- Provider construction and provider-specific lifecycle stay in the
  composition layer. `app.py` and services never import the concrete provider.
- Shutdown cleanup (`close_model_providers(registry)`) runs through the API
  factory's FastAPI lifespan handler: it awaits `aclose()` on every provider
  that exposes one (the provider-owned HTTP client), so injected test clients
  are never closed.
- Composing the application or serving `/health` never contacts a provider
  runtime; a configured endpoint is exercised only when `health()` /
  `generate()` is called.

## Rules

- Provider SDK types must never escape adapters. Inputs and outputs use
  AVA-owned contracts (`ava.contracts.models`).
- Provider adapters translate between provider-specific SDK types and these
  AVA-owned contracts at the adapter boundary.
- `get_capabilities()` reports only what the provider actually supports, as
  an AVA-owned `ModelCapabilities` contract.
- No real model is connected in Sprint 1; `ModelProviderPort` is not yet part
  of the run execution path.

## Future Provider Capabilities

The port is designed to eventually accommodate text generation, streaming,
structured output, tool calling, context limits, cancellation, and usage
information. These are future work added through additive contract changes.