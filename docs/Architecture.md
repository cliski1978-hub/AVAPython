# AVA Architecture

## Overview

AVA is a reusable AI application platform built as a multi-application
monorepo. The Python backend is a modular monolith following Hexagonal
Architecture (Ports and Adapters). Frontend applications share TypeScript
packages and talk to the backend only through the shared API client.

```text
                         AVA
                          │
          ┌───────────────┴────────────────┐
          │                                │
   Frontend Platform                 Python Backend
          │                                │
   Shared Packages                  Modular Monolith
          │                                │
 ┌────────┼─────────┐                  AVA Core
 │        │         │                     │
Web    Desktop    Mobile           Ports / Contracts
 │        │         │                     │
 │        │         │              Replaceable Adapters
 │        │         │
 └────────┴─────────┘
          │
       FastAPI
          │
      AVA Backend
```

## Architectural Patterns

- Multi-application monorepo
- Modular monolith for the Python backend
- Hexagonal Architecture / Ports and Adapters
- Dependency Inversion
- Contract-first APIs
- Shared cross-platform frontend packages
- Thin platform-specific application shells

## Dependency Rules

AVA Core and AVA Contracts must **never** depend directly on:

- FastAPI, Uvicorn
- React, Tauri, React Native
- LangChain / LangGraph
- AWS / Databricks
- Ollama / OpenAI / Anthropic
- SQLAlchemy or any specific database
- Any specific AI provider SDK
- Any vendor framework

Those technologies integrate through **adapters**. Dependencies point inward
toward application-owned contracts and core logic.

## Dependency Path

```text
AVA Web / Desktop
      ↓
Shared API Client
      ↓
FastAPI Adapter
      ↓
Application Services
      ↓
AVA Core / Ports
```

AVA Contracts are not a sequential processing layer between FastAPI and Core;
they are shared, versioned contracts exchanged across these boundaries:

```text
              AVA Contracts
           ↙       ↓       ↘
      Frontend    API    Services
```

## Adapter Boundaries

```text
AVA Core
   │
   ├── Agent Port
   │      ├── Mock Adapter
   │      ├── AWS Adapter
   │      └── Databricks Adapter
   │
   ├── Model Provider Port
   │      ├── Local Adapter
   │      ├── Company Gateway Adapter
   │      └── External Adapter
   │
   └── Persistence Port
          └── Future Storage Adapter
```

In Sprint 1 only the ports exist. No real agent, model, or database adapters
are implemented.

## Backend Layers

### API (`backend/src/ava/api`)

Transport concerns only: HTTP, request parsing, response generation, and
eventual streaming. Routes are thin; business logic lives in services and
core. `app.py` wires the application root, the capability service, CORS, and
the routers.

### Core (`backend/src/ava/core`)

Framework-neutral AVA application behavior. Will coordinate agent runs,
conversations, document operations, approvals, tools, events, model provider
selection, and agent adapter selection. `ApplicationConfig` holds the
framework-neutral application name, environment, and provider selection
values.

### Contracts (`backend/src/ava/contracts`)

AVA-owned, framework-neutral, provider-neutral, JSON-compatible, versionable
contracts. Vendor SDK objects never appear here. See
[Contract Standards](Contract%20Standards).

### Agents (`backend/src/ava/agents`)

AVA-owned adapter contracts (`AgentPort`) that future agent frameworks
implement. See [Agent Adapter](Agent%20Adapter).

### Models (`backend/src/ava/models`)

AVA-owned provider contracts (`ModelProviderPort`) that future model
providers implement. See [Model Provider](Model%20Provider).

### Services (`backend/src/ava/services`)

Application services. `CapabilityService` produces the current capability
snapshot; `RunService` maps AVA run contracts to the agent port.

### Configuration (`backend/src/ava/configuration`)

Environment-driven operational settings (`Settings`, loaded from `AVA_*`
environment variables). Provider selection is configuration-driven so future
changes (`model_provider = company_gateway`) require no core rewrite.

### Infrastructure (`backend/src/ava/infrastructure`)

Cross-cutting concerns such as logging.

## Frontend Layers

### Shared Packages

- **`@ava/contracts`** — TypeScript representations of AVA's JSON API
  contracts. Independent of React.
- **`@ava/api-client`** — one shared client for the AVA backend. No frontend
  app duplicates FastAPI request logic.
- **`@ava/ui-core`** — shared presentation and application UI logic:
  controls, layouts, hooks, state, theme.
- **`@ava/document-core`** — reserved for future document abstractions.
- **`@ava/agent-ui`** — reserved for shared agent interaction
  components/logic.

### Application Shells

- **Web** (Priority 1) — the first fully developed AVA client.
- **Desktop** (Priority 2) — Tauri shell reusing the shared React packages.
- **Mobile** (Priority 3) — placeholder structure; implementation is later.

Shared code is the default; platform-specific code is the exception.