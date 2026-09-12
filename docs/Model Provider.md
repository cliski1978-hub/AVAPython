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

class ModelInfo(BaseModel):
    provider_name: str
    model_id: str
    display_name: str | None = None
    context_limit: int | None = None

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

These are deliberately minimal for Sprint 1. Tools, structured output,
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
    def get_capabilities(self) -> set[CapabilityName]: ...

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
  information as `ModelInfo`.
- **`get_capabilities()`** — reports the capabilities the provider actually
  supports as a set of `CapabilityName` values.
- **`generate(request)`** — generates a model response from an
  AVA-owned `ModelRequest` and returns an AVA-owned `ModelResponse`.

## Selection Is Configuration-Driven

Future provider selection changes require no AVA Core rewrite:

```text
model_provider = local
model_provider = company_gateway
model_provider = external
```

The selection value lives in `ApplicationConfig.model_provider` and is driven
by the `AVA_MODEL_PROVIDER` environment variable (see `Local Development`).

## Rules

- Provider SDK types must never escape adapters. Inputs and outputs use
  AVA-owned contracts (`ava.contracts.models`).
- Provider adapters translate between provider-specific SDK types and these
  AVA-owned contracts at the adapter boundary.
- `get_capabilities()` reports only what the provider actually supports.
- No real model is connected in Sprint 1.

## Future Provider Capabilities

The port is designed to eventually accommodate text generation, streaming,
structured output, tool calling, context limits, cancellation, and usage
information. These are future work added through additive contract changes.