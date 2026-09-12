# AVA Development Plan

AVA is a reusable AI application platform. It is a multi-application
monorepo with a Python backend built as a modular monolith using Hexagonal
Architecture (Ports and Adapters) and shared TypeScript frontend packages.

## Development Priorities

1. **Web** — highest priority
2. **Desktop** — second priority (Tauri)
3. **Mobile** — final priority (placeholder structure)

All three applications share as much frontend code as reasonably possible.

## Phased Plan

### Sprint 1 — Foundation and Core Contracts (complete)

- [x] Monorepo structure validated
- [x] Backend runs locally with one command
- [x] Web runs locally and communicates with the backend
- [x] Shared API client used by Web
- [x] `GET /health`
- [x] `GET /capabilities`
- [x] Contract versioning (`v1`)
- [x] Run contracts (`RunRequest`, `RunResponse`, `RunStatus`)
- [x] Event contracts (`RunEvent`, `EventType`)
- [x] Capability contracts (`CapabilityName`, `CapabilitiesResponse`)
- [x] Error contracts (`ErrorCategory`, `ErrorResponse`)
- [x] Agent Adapter port (`start_run`, `cancel_run`, `get_capabilities`)
- [x] Model Provider port (`health`, `get_model_info`, `get_capabilities`, `generate`)
- [x] Configuration foundation (application / environment / agent / model provider / api / logging)
- [x] Backend tests and architecture enforcement tests
- [x] Documentation

Sprint 1 deliberately introduces no real AI provider, no database, and no
vendor framework in AVA Core.

### Sprint 2 — Mock Agent and Run Lifecycle

- Mock agent adapter implementing the Agent Port
- Run lifecycle over the run contracts
- Run status transitions and normalized run events

### Sprint 3 — Local Model Provider

- Local model provider implementing the Model Provider Port
- Health and model info reporting
- Generate over the AVA contracts

### Sprint 4 — AVA Workspace / Agent UI

- Agent interaction UI on the shared frontend packages
- Document operations on `document-core`

## Deferred (reserved, not started)

SQL persistence, user authentication, document editing (Tiptap), LangChain /
LangGraph integration, local inference (Ollama), AWS integration, Databricks
integration, company AI gateway, external AI providers, plugin execution,
vector databases / embeddings / RAG, production deployment, mobile (React
Native) implementation, Databricks notebook integration.

## Primary Architectural Rule

> AVA depends on its own contracts. External frameworks depend on AVA's
> boundaries — not the other way around.

## Architecture Decision Records

Decisions that materially affect the platform should be captured as
Architecture Decision Records under:

```text
docs/
└── decisions/
    ├── ADR-001-monorepo.md
    ├── ADR-002-hexagonal-backend.md
    └── ADR-003-shared-frontend.md
```

None have been written yet; none were required for Sprint 1 completion.