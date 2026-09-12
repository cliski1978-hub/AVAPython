# AVA Agent Adapter

## Purpose

The Agent Adapter port is the boundary between AVA Core and future agent
implementations. AVA depends on this abstraction; agent frameworks depend on
AVA's boundary — not the other way around.

```text
AVA Core
   │
Agent Adapter Port
   │
   ├── Mock Agent
   ├── LangGraph
   ├── AWS
   ├── Databricks
   └── Future Agent
```

## Port

Defined in `backend/src/ava/agents/contracts.py`.

```python
class AgentPort(ABC):
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    async def start_run(self, run_id: str, request: RunRequest) -> RunResponse: ...

    @abstractmethod
    async def cancel_run(self, run_id: str) -> RunResponse: ...

    @abstractmethod
    def get_capabilities(self) -> set[CapabilityName]: ...
```

### Operations

- **`name()`** — returns the adapter name.
- **`start_run(run_id, RunRequest)`** — starts an agent run under an
  AVA-generated run identifier. The identifier is assigned by the run
  service (AVA owns run IDs), never by the caller or the adapter.
- **`cancel_run(run_id)`** — cancels an in-progress run and returns the
  updated run state.
- **`get_capabilities()`** — reports the capabilities the adapter actually
  supports as a set of `CapabilityName` values.

### Event Boundary

Event streaming and delivery are **not** part of the Sprint 1 port. When
streaming is implemented (Sprint 2 with the mock agent and run lifecycle), it
must be AVA-event-based — one normalized path using the AVA event contracts
(`RunEvent`, `EventType`) — so clients never depend on LangGraph, AWS,
Databricks, or provider-specific events. No status-only listener is
introduced alongside the event system.

## Rules

- Framework SDK types must never escape adapters. Inputs and outputs use
  AVA contracts.
- `get_capabilities()` reports only what the adapter actually supports.
- No real agent is implemented in Sprint 1. A placeholder/mock may exist
  only where architecture testing requires it.

## Future Adapters

- **Mock agent** — deterministic, offline; first Sprint 2 target.
- **LangGraph** — general agent composition.
- **AWS / Databricks** — hosted agent platforms.

None are implemented yet.