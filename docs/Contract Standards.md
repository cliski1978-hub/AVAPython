# AVA Contract Standards

AVA owns its API contracts. Every public contract must:

- Be **application owned** — defined by AVA, not by any vendor.
- Be **JSON compatible** — serializable to plain JSON that clients parse
  without a vendor SDK.
- Be **versionable** — carry the contract version.
- Avoid **framework-specific** objects.
- Avoid **provider-specific** objects.
- Prefer **additive changes** over breaking changes.
- Support **safe handling of unknown optional fields**.
- Use **stable identifiers**.
- Use **explicit enums** where appropriate.

## Versioning

The current contract version is:

```text
v1
```

Defined once in `backend/src/ava/contracts/version.py`
(`CONTRACT_VERSION = "v1"`) and mirrored in
`frontend/packages/contracts/src/version.ts`. Every public contract payload
carries `contract_version` — including response and request contracts such as
`HealthResponse`, `CapabilitiesResponse`, `RunResponse`, `ErrorResponse`,
`RunEvent`, `RunRequest`, and the model contracts.

Versioning prefers additive changes. New optional fields, new enum values,
and new capability names should not break existing clients.

## JSON Safety

Fields that carry arbitrary JSON (`RunEvent.payload`, `ErrorResponse.details`)
use the AVA-owned `JsonValue` type defined in
`backend/src/ava/contracts/json_types.py`:

```text
JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
```

This enforces at the type level that such fields can only contain
JSON-serializable values. Provider SDK objects, `datetime` objects, `bytes`,
and other non-JSON-safe types are rejected.

## Contract Locations

- **Backend (authoritative):** `backend/src/ava/contracts/`
- **TypeScript:** `frontend/packages/contracts/src/`
- **Python client:** `clients/python/src/ava_client/models.py`

These definitions must be kept in sync as the authoritative backend contract
evolves.

## HTTP Endpoints

### `GET /health`

```json
{
  "status": "healthy",
  "application": "AVA",
  "contract_version": "v1"
}
```

### `GET /capabilities`

```json
{
  "contract_version": "v1",
  "application": "AVA",
  "capabilities": {
    "health": true,
    "runs": false,
    "streaming": false,
    "tool_calling": false,
    "structured_output": false,
    "cancellation": false,
    "document_operations": false,
    "approvals": false,
    "local_model": false,
    "local_execution": false
  }
}
```

Only capabilities that actually exist are reported as `true`. The presence of
a capability name does not imply the capability is implemented.

### `GET /model-providers`

Discover the composed model providers with model identity and health
(read-only; never selects or starts a provider). Added in Step 10; a
dedicated resource endpoint rather than an extension of `/capabilities`.

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
        "capabilities": {
          "chat": true,
          "streaming": false,
          "tool_calling": false,
          "structured_output": false,
          "vision": false,
          "embeddings": false,
          "reasoning": false,
          "code_specialization": false,
          "contract_version": "v1"
        },
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

- `default_provider_id` truthfully reports the configured default
  (`Settings.model_provider`) even when nothing is registered under it; an
  unknown default yields no `is_default` entry, never a fabricated one.
- Per-provider `health` reuses the `ModelProviderHealth` contract; one
  raising/unreachable provider is reported as
  `available=false, status=runtime_unavailable` (never an HTTP error) and
  does not affect the others.
- Providers appear in registry insertion order. No startup health checks —
  the endpoint performs I/O only when called.

## Contract Families (v1)

- **`version.py`** — `CONTRACT_VERSION`
- **`json_types.py`** — `JsonValue` (JSON-safe recursive value type)
- **`requests.py`** — `RunRequest`
- **`responses.py`** — `HealthResponse`, `CapabilitiesResponse`, `RunResponse`,
  `ModelProviderDiscoveryItem`, `ModelProviderDiscoveryResponse`
  (with `HealthStatus`, `RunStatus`)
- **`events.py`** — `RunEvent` (with `EventType`)
- **`capabilities.py`** — `CapabilityName`
- **`errors.py`** — `ErrorResponse` (with `ErrorCategory`)
- **`models.py`** — `ModelProviderHealth`, `ModelCapabilities`, `ModelInfo`,
  `ModelMessage`, `ModelRequest`, `ModelResponse` (with
  `ModelProviderHealthStatus`)
- **`runtimes.py`** — `RuntimeCapabilities`, `RuntimeInfo`
- **`approvals.py`** — reserved scaffold; DTOs to be designed with the
  approval workflow

## Run Contracts

- `RunRequest` — `prompt` (required, minimum length 1), `contract_version`.
  AVA owns and generates run identifiers; callers must not supply one.
- `RunResponse` — `run_id`, `status`, `contract_version`.
- `RunStatus` — `pending`, `running`, `waiting_for_approval`, `completed`,
  `cancelled`, `failed`.

A run has enough identity to later correlate request, conversation, agent,
model, events, tools, approvals, and results. No persistence yet.

## Event Contracts

Every event shares a common envelope:

```json
{
  "event_id": "...",
  "run_id": "...",
  "event_type": "run_started",
  "timestamp": "2026-09-07T00:00:00Z",
  "payload": {},
  "contract_version": "v1"
}
```

`EventType` values: `run_started`, `message_started`, `message_content`,
`tool_started`, `tool_progress`, `tool_completed`, `approval_requested`,
`document_change_proposed`, `artifact_created`, `run_completed`,
`run_cancelled`, `run_failed`.

`payload` is a `dict[str, JsonValue]` — only JSON-safe values are permitted.

## Error Contracts

```json
{
  "error_code": "run_failed",
  "category": "agent",
  "message": "...",
  "recoverable": true,
  "details": {},
  "correlation_id": null,
  "contract_version": "v1"
}
```

`ErrorCategory` values: `validation`, `configuration`, `unavailable`,
`timeout`, `cancelled`, `provider`, `agent`, `internal`.

`details` is a `dict[str, JsonValue]` and may carry structured context such
as bounds or retry hints. It must never contain stack traces, passwords, API
keys, tokens, provider SDK objects, sensitive internal paths, or credential
information.

## Model Contracts

Defined in `backend/src/ava/contracts/models.py`. These are port-level
AVA-owned DTOs; provider adapters translate between these and provider SDK
types.

- **`ModelProviderHealthStatus`** — `healthy`, `degraded`, `unavailable`,
  `runtime_unavailable`, `model_not_loaded`, `authentication_failed`,
  `configuration_invalid`.
- **`ModelProviderHealth`** — `available` (bool), `status`, `message`
  (optional).
- **`ModelCapabilities`** — typed boolean record of a model's capabilities:
  `chat`, `streaming`, `tool_calling`, `structured_output`, `vision`,
  `embeddings`, `reasoning`, `code_specialization`. Defaults are all `False`
  (conservative). This is the normalized capability vocabulary used by
  `ModelProviderPort.get_capabilities()` — distinct from the application-level
  `CapabilityName` vocabulary.
- **`ModelInfo`** — `provider_name`, `model_id`, `display_name` (optional),
  `context_limit` (optional), `capabilities` (`ModelCapabilities`).
- **`ModelMessage`** — `role`, `content`.
- **`ModelRequest`** — `messages`, `temperature` (optional),
  `max_output_tokens` (optional).
- **`ModelResponse`** — `content`, `model_id`.

Model request/response contracts are deliberately minimal for Sprint 1.
Tool calling, structured output, usage, and metadata fields will be added
through additive contract changes.

## Runtime Contracts

Defined in `backend/src/ava/contracts/runtimes.py`. Framework-neutral
descriptions of agent runtime capabilities, parallel to the model contracts.

- **`RuntimeCapabilities`** — typed boolean record of a runtime's
  capabilities: `tools`, `multi_agent`, `shell`, `filesystem`, `browser`,
  `code_execution`, `checkpointing`, `persistence`, `human_approval`,
  `parallel_execution`. Defaults are all `False`. Kept separate from
  `ModelCapabilities`: a runtime may support tools while the selected model
  does not support tool calling.
- **`RuntimeInfo`** — `runtime_id`, `display_name` (optional),
  `capabilities` (`RuntimeCapabilities`).

## Keeping the Definitions in Sync

When a backend contract changes, update in the same change:

- `frontend/packages/contracts/src/` TypeScript mirror.
- `clients/python/src/ava_client/models.py` Python mirror.
- The architecture and contract tests that exercise the contracts.