# AVA Phase 3 Architecture Audit

Status: DOCUMENTATION ONLY — Sprint 2 baseline.

This document records the AVA architecture **as it exists at the end of
Sprint 2**, discovered by direct inspection of the repository. It is the
input for Phase 3 (model providers + agent runtimes as independently
configurable runtime/model platform). No production code was modified and no
Phase 3 component was implemented.

All paths below are relative to the repository root.

**Repository root (backend):** `backend/src/ava`
**Repository root (frontend):** `frontend/packages/...` (pnpm workspace)

---

## 1. Executive Summary

AVA at the end of Sprint 2 has:

* **One concrete agent adapter** — `MockAgentAdapter`, which implements the
  AVA-owned `AgentPort`. It is deterministic, framework-neutral, and injectable
  through configuration (`agent_provider: str` → adapter factory).
* **One defined but unused model-provider port** — `ModelProviderPort`
  (`ava.models.contracts`). It is completely decoupled: nothing constructs it,
  nothing imports it into the run path, and no concrete implementation exists
  (only an empty `local` placeholder package). The run path does **not** touch
  it today.
* **A working run lifecycle** owned entirely by AVA: `RunService` + `RunStore`
  + `RunEventStore`. Run/event identifiers are AVA-generated; the store
  enforces a single-terminal-event invariant and idempotent cancellation.
* **A thin FastAPI transport layer** (`/runs`, `/runs/{id}`, `/runs/{id}/events`,
  `/runs/{id}/cancel`, `/capabilities`, `/health`) that never imports vendor
  SDKs or concrete adapters.
* **A frontend** (`@ava/api-client`, `@ava/agent-ui`, `@ava/workspace`,
  `@ava/document-core`, `@ava/ui-core`) that starts/cancels runs and reads
  capabilities/events through the AVA-owned client contract, plus a shared
  Chat + Document workspace with conversation/editor preservation.

**Phase 3 implication:** agent-runtime selection and model-provider selection
are already architecturally separate fields (`agent_provider`,
`model_provider`) in both `Settings` and `ApplicationConfig`. The run path is
agent-only today; model providers are a pending, intentionally-unused port
waiting for Phase 3 wiring.

---

## 2. Current Agent Architecture

### Port: `AgentPort`

Defined in `backend/src/ava/agents/contracts.py`.

```python
class AgentPort(ABC):
    @abstractmethod
    def name(self) -> str: ...
    @abstractmethod
    async def start_run(self, run_id: str, request: RunRequest) -> AgentRunResult: ...
    @abstractmethod
    async def cancel_run(self, run_id: str) -> RunResponse: ...
    @abstractmethod
    def get_capabilities(self) -> set[CapabilityName]: ...
```

* `AgentRunResult` is an AVA-owned DTO: `status: RunStatus` + `content: str | None`.
* Port inputs/outputs use AVA-owned contracts (`RunRequest`, `RunResponse`,
  `RunStatus`, `CapabilityName`). No vendor SDK types appear.

### Adapter: `MockAgentAdapter`

Defined in `backend/src/ava/agents/adapters/mock/mock_agent.py`.

* Deterministic; `run_id` is always AVA-owned (never invented by the adapter).
* Only capabilities: `{CapabilityName.RUNS, CapabilityName.CANCELLATION}`.
* In-memory active-run tracking; supports deterministic cancellation during a
  tiny in-progress window.

### Construction / Dependency Injection

`backend/src/ava/infrastructure/composition.py`:

```python
_AGENT_ADAPTER_FACTORIES: dict[str, Callable[[], AgentPort]] = {
    "mock": MockAgentAdapter,
}

def create_agent_adapter(provider: str) -> AgentPort: ...
```

Provider selection is **configuration-driven** (a thin factory registry keyed
by name), not static. Unknown provider name → `ValueError`. This is the
composition/adaptation layer; core and services never import adapters
directly.

### Call path (real, from repo)

```text
HTTP POST /runs
    ↓
routes/runs.py : start_run()
    ↓
RunService.start_run(request)
    ↓
RunService stores run (AVA-owned run_id = uuid4)
    ↓
agent_port.start_run(run_id=run_id, request=request)   ← AgentPort
    ↓
MockAgentAdapter.start_run(...)                        ← adapter
    ↓
AgentRunResult(status=..., content=...) → normalized events
```

Cancellation path:

```text
HTTP POST /runs/{run_id}/cancel
    ↓
RunService.cancel_run(run_id)
    ↓
agent_port.cancel_run(run_id)   ← AgentPort
    ↓
RunResponse(status=...)
```

### How RunService invokes the agent

`backend/src/ava/services/run_service.py` holds the single lifecycle
coordinator: it owns run identity, event identity, stores, and the terminal
event sequences. It never reads concrete adapter internals.

---

## 3. Current Model Provider Architecture

### Port: `ModelProviderPort`

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

Contracts used by this port live in `ava.contracts.models`:
`ModelInfo`, `ModelProviderHealth`, `ModelRequest`, `ModelResponse` — all
AVA-owned, pydantic DTOs Scott.

### Concrete implementations

**None.** `backend/src/ava/models/providers/local/` contains only an
`__init__.py` placeholder that documents the intent ("Implements the
AVA-owned ModelProviderPort contract") with **no real inference**.

### Is ModelProviderPort currently used by the run path?

**No.** A repository-wide search for any instantiation of
`ModelProviderPort`/`ModelProviderAdapter` returns nothing in the run path.
`RunService` depends only on `AgentPort`, `RunStore`, and `RunEventStore`.
The model-provider port is defined, provider-neutral, and deliberately unused.

### Assessment for Phase 3

* **Complete enough for a real provider?** Partially — the port shape
  (`name`, `health`, `get_model_info`, `get_capabilities`, `generate`) is
  exactly right for Phase 3 Step 4+; no streaming method exists yet (streaming
  is not required by the run slice).
* **Tightly coupled?** No — it imports only AVA-owned contracts. This is the
  desired baseline.
* **Note:** the port has no registry/resolver and no configuration wiring yet;
  those are Phase 3 steps, not Sprint-2 gaps to fix now.

---

## 4. Current Run Lifecycle

Owned by `RunService` (`backend/src/ava/services/run_service.py`) with state
in `RunStore` (`services/run_store.py`) and events in `RunEventStore`
(`services/run_event_store.py`).

### Run states (`ava.contracts.responses`)

`RunStatus` (StrEnum): `PENDING, RUNNING, WAITING_FOR_APPROVAL, COMPLETED,
CANCELLED, FAILED`.

### Terminal event types (`ava.contracts.events`)

`EventType` (StrEnum): `RUN_STARTED, MESSAGE_STARTED, MESSAGE_CONTENT,
TOOL_STARTED, TOOL_PROGRESS, TOOL_COMPLETED, APPROVAL_REQUESTED,
DOCUMENT_CHANGE_PROPOSED, ARTIFACT_CREATED, RUN_COMPLETED, RUN_CANCELLED,
RUN_FAILED`.

Terminal set used by the store: `{RUN_COMPLETED, RUN_CANCELLED, RUN_FAILED}`.

### Lifecycle (request → terminal), real sequences

```text
POST /runs
  RunService.start_run()
    run_id = str(uuid4())                  # AVA-owned identity
    RunStore.create(run_id)                # status PENDING
    append RUN_STARTED
    RunStore.update_status(run_id, RUNNING)
    await agent.start_run(run_id, request)
    ├─ agent → COMPLETED
    │    append MESSAGE_STARTED
    │    append MESSAGE_CONTENT (result.content)
    │    RunStore.update_status(COMPLETED)
    │    append RUN_COMPLETED
    ├─ agent → FAILED
    │    RunStore.update_status(FAILED)
    │    append RUN_FAILED (error payload)
    └─ agent → CANCELLED (observed mid-flight)
         RunStore.update_status(CANCELLED)
         append RUN_CANCELLED
```

```text
POST /runs/{run_id}/cancel
  RunService.cancel_run(run_id)
    unknown run        → idempotent no-op, response CANCELLED
    already terminal   → return recorded status (no new events)
    else               → await agent.cancel_run(run_id)
                         update status, append RUN_CANCELLED when cancelled
```

### Enforced invariants

* **Single terminal event per run** — `RunEventStore.append` refuses a second
  terminal event (`RUN_COMPLETED`/`RUN_CANCELLED`/`RUN_FAILED`) once a run has
  a terminal event. This keeps the lifecycle deterministic.
* **Backend-owned run identity** — `RunService` (not the client or adapter)
  generates `run_id` and `event_id` (`uuid4`).
* **Idempotent cancellation** — unknown runs and already-terminal runs return
  stable responses without side effects; concurrent cancellation appends at
  most one `RUN_CANCELLED`.

---

## 5. Current API Surface

`backend/src/ava/api/` — FastAPI. Routes are thin; all orchestration lives in
services. Vendor SDKs never appear here.

| Method | Path | Handler (routes/) | Returns |
|--------|------|-------------------|---------|
| POST | `/runs` | `runs.py: start_run` | `RunResponse` |
| POST | `/runs/{run_id}/cancel` | `runs.py: cancel_run` | `RunResponse` |
| GET | `/runs/{run_id}` | `runs.py: get_run` | `RunResponse` (404 = `run_not_found`) |
| GET | `/runs/{run_id}/events` | `runs.py: get_run_events` | `list[RunEvent]` (404) |
| GET | `/capabilities` | `capabilities.py: get_capabilities` | `CapabilitiesResponse` |
| GET | `/health` | `health.py: health` | `HealthResponse` |

### Request contracts (`ava.contracts.requests`)

`RunRequest`: `prompt` (min_length=1, non-blank) + `contract_version` frozen
to `CONTRACT_VERSION`.

### Response contracts (`ava.contracts.responses`)

* `RunResponse`: `run_id`, `status` (`RunStatus`), `contract_version`.
* `RunEvent` (`ava.contracts.events`): `event_id`, `run_id`, `event_type`,
  `timestamp`, `payload: dict[str, JsonValue]`.
* `CapabilitiesResponse`: `contract_version`, `application`,
  `capabilities: dict[CapabilityName, bool]`.
* `HealthResponse`/`HealthStatus`.
* `ErrorResponse` (`ava.contracts.errors`): `error_code`, `category`
  (`ErrorCategory`), `message`, `recoverable`, `details`.

### Dependency construction in routes

Routes obtain services from `request.app.state`:

```python
service: RunService = request.app.state.run_service
return await service.start_run(body)
```

Services are composed once in the app factory (see §7).

---

## 6. Current Application Configuration

### `Settings` (environment-driven) — `ava.configuration.settings`

```python
AVA_APPLICATION   → application_name (default "AVA")
AVA_ENVIRONMENT   → environment (default "development")
AVA_HOST          → host (default 127.0.0.1)
AVA_PORT          → port (default 8000)
AVA_DEBUG         → debug (default True)
AVA_LOG_LEVEL     → log_level (default "info")
AVA_AGENT_PROVIDER→ agent_provider (default "mock")
AVA_MODEL_PROVIDER→ model_provider (default "local")
```

`get_settings()` returns a cached singleton.

### `ApplicationConfig` — `backend/src/ava/core/application.py`

Frozen dataclass: `application_name`, `environment`, `agent_provider`,
`model_provider`. AVA-root (`Application`) holds it.

### Agent vs model independence

**Already independent.** `agent_provider` and `model_provider` are separate
config fields with separate env vars and separate defaults. Nothing couples
"agent selection" to "model selection" in configuration. This satisfies the
Phase 3 guardrail at the config level already; what is missing is a real
*model-provider* that the `model_provider` field actually selects (currently
`"local"` resolves to an empty placeholder and the run path ignores it).

---

## 7. Dependency Construction

Factory: `backend/src/ava/api/app.py` → `create_app()`.

```python
settings = get_settings()
core_application = Application(config=ApplicationConfig(...))   # AVA core root
app = FastAPI(title="AVA", version="0.1.0")
app.state.application = core_application
agent_port = create_agent_adapter(settings.agent_provider)      # "mock"
app.state.agent_port = agent_port
app.state.run_service = RunService(agent_port)                  # + default stores
app.state.capability_service = CapabilityService(application=..., agent=agent_port)
# CORS, exception handler, routers (health, capabilities, runs)
```

Pattern: **direct construction inside the app factory (composition root) +
dedicated configuration-driven registry for adapter choice
(`_AGENT_ADAPTER_FACTORIES`).** No DI framework, no module globals for
services (only the cached `Settings` singleton), no background task layer.

Object creation map:

| Object | Where created | How |
|--------|---------------|-----|
| `ApplicationConfig` | `app.py` | from env `Settings` |
| `Application` | `app.py` | via `ApplicationConfig` |
| `AgentPort` (Mock) | `composition.create_agent_adapter` | name→factory registry |
| `ModelProviderPort` | **nowhere** | port defined, no implementation yet |
| `RunService` | `app.py` | direct `RunService(agent_port)` |
| `RunStore` | `RunService.__init__` default | fresh in-memory |
| `RunEventStore` | `RunService.__init__` default | fresh in-memory |
| `RunService` (state) | `request.app.state.run_service` | FastAPI app state |

---

## 8. Current AVA Contracts

`backend/src/ava/contracts/` — framework-neutral pydantic DTOs only.

* `contracts/models.py` — `ModelRequest`, `ModelResponse`, `ModelInfo`,
  `ModelProviderHealth`.
* `contracts/requests.py` — `RunRequest`.
* `contracts/responses.py` — `RunResponse`, `RunStatus`,
  `CapabilitiesResponse`, `HealthResponse`.
* `contracts/events.py` — `RunEvent`, `EventType`.
* `contracts/capabilities.py` — `CapabilityName` (StrEnum).
* `contracts/errors.py` — `ErrorResponse`, `ErrorCategory`.
* `contracts/json_types.py` — `JsonValue`.
* `contracts/version.py` — `CONTRACT_VERSION`.

Program against ports (`AgentPort`/`ModelProviderPort`) with these contracts.
Vendor SDK/framework types are confined to adapters; they never cross the AVA
boundary (verified: no `ollama`/`openai`/langgraph/agentcore/OpenHands SDK
references leak into AVA contracts or core).

No framework-specific type currently leaks into AVA-owned contracts — verified
by inspection.

---

## 9. Frontend/API Client Boundary

`frontend/packages/api-client/src/`

* `client.ts` — `ApiClient`: baseUrl, `request()` with `AbortController`
  timeout + `Content-Type`; `ApiError`.
* `runs.ts` — `startRun`, `getRun`, `getRunEvents`, `cancelRun`.
* `capabilities.ts` — `getCapabilities`.
* `health.ts` — `getHealth`.

`frontend/packages/agent-ui/` — `ConversationRunProvider` / `useAgentRun`
(submit/stop/cancel), ConversationView, Composer; run event processor
(`runEventProcessor.ts`).

`frontend/packages/workspace/` — `AppWorkspace` (shared by Web and Desktop):
`WorkspaceTabs` (Chat / Documents), both panes mounted with `display`
toggling so conversation + editor state survive switching (verified by tests
`AppWorkspace.test.tsx`).

`frontend/packages/document-core/` — Tiptap editor (`DocumentWorkspace`,
`EditorAdapter`, ProfM Editor, toolbar Bold/Italic/H1/H2/lists/Undo/Redo,
aria-pressed) with its own state reducer/provider.

ApiClient usage: runs are started via `startRun` (await response), events read
via `getRunEvents`, cancellation via `cancelRun`, health via `getHealth`;
`/capabilities` consumed via `getCapabilities`. No provider/runtime
information is exposed to the client today (endpoint returns AVA-owned
capability booleans only).

---

## 10. Existing Test Coverage

Backend (`backend/tests/`, pytest):

* `test_contracts.py` — AVA contract DTO construction/validation.
* `test_health.py` — /health.
* `test_capabilities.py` — /capabilities + CapabilityService aggregation.
* `test_runs.py` — run route contracts (start/cancel/get/events, 404 paths).
* `test_run_service.py` — RunService lifecycle incl. terminal events.
* `test_run_events.py` — RunEventStore terminal-event invariant.
* `test_mock_agent.py` — MockAgentAdapter deterministic behavior/cancel.
* `test_architecture.py` — dependency-direction/architecture guardrails
  (ports vs adapters).

Coverage map for Phase 3:

| Area | Sprint-2 coverage | Phase-3 gap |
|------|-------------------|-------------|
| `AgentPort` | contracts + MockAgentAdapter tests | none — port is concrete-tested |
| `RunService` | lifecycle, cancel idempotency, terminal events | run/metadata recording (Step 17) |
| `RunStore` | covered via RunService tests | optional direct unit tests |
| `RunEventStore` | `test_run_events` (terminal invariant) | good baseline |
| `ModelProviderPort` | contract defined; **no provider tests** | Phase 3 Steps 4–8 must add adapter tests |
| `ApplicationConfig`/`Settings` | implicit via app factory | config resolution tests (Steps 6–7) |
| capabilities/cancellation | covered | compatibility validator (Step 19) |

Frontend (`frontend/packages/*/.../*.test.tsx|ts`, vitest): contracts,
api-client (client/runs/capabilities/health), agent-ui
(conversation/prompt/run event processor), workspace (`AppWorkspace` state
preservation), document-core (prosemirror reducer/editor), ui-core
(components/theme). All green at Sprint-2 end.

---

## 11. Coupling and Architectural Risks

Findings from repository search (evidence only; **nothing fixed**):

1. **Agent selection factory is name-keyed, not capability-keyed.** `mock` is
   the only key in `_AGENT_ADAPTER_FACTORIES`. Fine for now, but Phase 3 Step
   15+ (runtime registry) will want capability/health metadata per runtime.
2. **Model selection is config-only, not resolved.** `model_provider:
   "local"` currently resolves to a placeholder and is ignored by the run
   path. Risk for Steps 5–8: ensure `ModelProviderRegistry`/resolver replace
   this empty placeholder rather than the run path reaching into a concrete
   provider.
3. **All run/event state is in-memory.** Intentional for Sprint 2; Phase 3
   must not assume persistence when adding registries/providers.
4. **`RunService` holds the run lifecycle and generates AVA-run identity.**
   `AgentRuntimePort` (Step 13) must wrap this so runtime selection doesn't
   force `RunService` to know providers.
5. **No streaming.** The events endpoint is snapshot-pull; Phase 3
   streaming is out of scope for the run slice.
6. **Frontend only knows AVA contracts.** Good — no provider SDK leakage;
   the `model_provider` value never reaches the client today. Risk is only
   that capability booleans are generic (Phase 3 discovery API should extend
   this rather than duplicate).

No vendor SDK types leak anywhere into AVA contracts/core/frontend (verified
by grep).

---

## 12. Phase 3 Extension Points

Identified attach points for Phase 3 components (analysis only — **not
implemented**):

* **Model provider registry** — attach beside `_AGENT_ADAPTER_FACTORIES` in
  `backend/src/ava/infrastructure/composition.py` (a sibling name-keyed
  registry `{"local": ..., "corporate": ..., ...}`), used by a
  resolver that reads `Settings.model_provider`.
* **ModelProviderPort wiring** — `app.py` composes `ModelProviderPort` the
  same way it composes `AgentPort` today (`create_model_provider_adapter(
  settings.model_provider)`), stored on `app.state` and injected into
  `RunService` later (Step 11).
* **Model capability contract** — `ava.contracts.models` is the right home
  for `ModelCapabilities` / `ModelDescriptor` (Step 2).
* **Runtime capability contract** — new `ava.models`/`ava.runtime` contracts
  for `RuntimeDescriptor` (Step 3) parallel to `ModelInfo`.
* **AgentRuntimePort (Step 13)** — a new port wrapping `AgentPort` +
  `ModelProviderPort`; `RunService` would program against it so runtime
  choice (native/OpenHands/LangGraph/AgentCore) stays independent of model
  choice.
* **Registries + resolvers** — `ModelProviderRegistry`/`RuntimeRegistry`
  alongside `_AGENT_ADAPTER_FACTORIES` pattern; resolvers driven by
  `Settings`/`ApplicationConfig` (already independent fields — no config
  change needed).
* **Health/discovery** — `ModelProviderPort.health` already exists; Step 10
  extends it with normalized availability states via the existing
  capabilities configuration API.

Proposed conceptual layers (not yet present in code):

```text
ApplicationConfig
   ├── agent_provider  → AgentAdapterRegistry → AgentPort        (exists)
   └── model_provider  → ModelProviderRegistry → ModelProviderPort (TO ADD)
RunService → AgentRuntimePort → (native | openhands | langgraph | agentcore)
```

---

## 13. Files Likely to Be Affected by Phase 3

Backend (expected impact by step):

* `backend/src/ava/models/contracts.py` — harden `ModelProviderPort`
  (Step 4), streaming note (Step 4).
* `backend/src/ava/models/providers/local/` — implement the local provider
  (Steps 8–9) behind the port.
* `backend/src/ava/infrastructure/composition.py` — add
  `ModelProviderRegistry`, resolver/factories (Steps 5, 7, 15, 16).
* `backend/src/ava/services/run_service.py` — connect native agent → port
  (Step 11), optional run metadata fields (Step 17).
* `backend/src/ava/core/application.py` + `api/app.py` — compose the model
  provider + runtime adapters; any registry wiring.
* `backend/src/ava/api/routes/capabilities.py` + services — health/discovery
  extension (Steps 10, 20).
* `backend/src/ava/contracts/` — capability/model contracts extensions
  (Steps 2–3), run-request overrides (Step 18).
* `backend/tests/` — new provider/runtime/resolver tests per step.

Frontend (later Phase 3 steps only):

* `frontend/packages/api-client/src/{runs,capabilities}.ts` — model/runtime
  selection + discovery API (Steps 21–22).
* `frontend/packages/agent-ui` + `workspace` — selection UI (steps 22+).

---

## 14. Recommended Next-Step Constraints

If Phase 3 proceeds (to be reviewed/decided separately), the following
constraints are recommended based on this audit:

1. Preserve the existing `AgentPort` and `RunService` run lifecycle verbatim;
   runtime abstraction (Phase 3 Step 13) must wrap, not rewrite, it.
2. Keep `AgentPort` and `ModelProviderPort` independent both in config
   (already true) and in the run path (add model wiring without coupling
   agent runtime choice to provider choice).
3. Do not leak any provider/framework SDK type across AVA contracts (the
   current boundary is already clean — keep it clean).
4. Keep all state in-memory unless a later step explicitly introduces
   persistence.
5. Add capabilities/metrics for the local model provider before wiring real
   external providers.
6. Do not add streaming to the run slice unless the existing snapshot
   architecture can support it cleanly.
7. Add the model-provider registry/resolver as siblings of
   `_AGENT_ADAPTER_FACTORIES` rather than threading provider logic into
   `RunService` or routes.
8. Extend the existing capabilities configuration/API for health/discovery
   instead of creating a parallel architecture.

---

## Validation

This step is documentation-only. Run the repository's normal validation to
confirm no behavior was disturbed:

```bash
cd backend && ./scripts/test_all.sh
```

No production code was modified; only this audit document was created.
