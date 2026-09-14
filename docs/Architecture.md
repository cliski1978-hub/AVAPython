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
are implemented. In Sprint 2 the Mock Adapter is implemented as the first
concrete `AgentPort` adapter; it accepts an AVA-owned `run_id`, returns
deterministic assistant content, emits normalized AVA run events, and
advertises only the capabilities it truthfully supports. Future adapters
(AWS, Databricks, model providers) continue to implement the same contracts
and do not leak into shared UI or core code.

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
snapshot; `RunService` implements the first run lifecycle (start, status,
cancel, retrieval), maps AVA run contracts to the agent port, and persists
run state and normalized events in memory through `RunStore` and
`RunEventStore`. Runs are snapshot-only in Sprint 2 — event retrieval is
not a streaming/SSE endpoint.

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
  app duplicates FastAPI request logic. It is the *only* module that performs
  `fetch`/XHR calls on the frontend.
- **`@ava/ui-core`** — shared presentation and application UI logic:
  controls, layouts, hooks, state, theme.
- **`@ava/document-core`** — AVA's frontend document domain. It owns the
  serializable document model, in-memory document collection and active
  document state, and the shared workspace. Tiptap setup, commands, toolbar
  state, and content conversion remain an internal editor adapter.
- **`@ava/agent-ui`** — shared AI conversation/run UI: conversation state,
  the run lifecycle (`ConversationRunProvider`), the `runEventProcessor`
  that normalizes backend events, and conversation/message/prompt-composer
  components. Provider-neutral — it must not know about Ollama, OpenAI,
  LangGraph, or any future adapter.

### Application Shells

- **Web** (Priority 1) — the first fully developed AVA client.
- **Desktop** (Priority 2) — Tauri shell reusing the shared React packages.
- **Mobile** (Priority 3) — placeholder structure; implementation is later.

Shared code is the default; platform-specific code is the exception. The Web
and Desktop application shells are thin React wrappers around `@ava/api-client`
and the shared `@ava/workspace` composition package; they contain no data
fetching, agent logic, editor commands, or UI implementation of their own.

## Document Workspace

The shared `@ava/workspace` package owns the in-session selection between the
Chat and Documents workspaces. `@ava/document-core` provides one AVA-owned
in-memory document with a stable ID, title, serializable HTML content,
timestamps, and dirty state. It uses a document collection plus an explicit
active document ID, preparing future multi-document work without adding that
user interface now.

```text
Web / Desktop
      ↓
Document Workspace
      ↓
AVA Document State
      ↓
Editor Abstraction
      ↓
Tiptap Adapter
      ↓
Tiptap
```

Both panes remain mounted after the user first opens Documents, preserving
conversation messages and document state while switching surfaces. The state
provider can reconstruct an editor from AVA content after component remounting.
Reloading resets the in-memory state; no document persistence, document API,
file operation, or backend document contract exists.

The document provider owns the current in-memory operations: create, select,
rename, update, save, and close. Save marks the active document clean against
the current session baseline only; it does not write to a backend, browser
storage, disk, or a Tauri filesystem API. The shared workspace presents the
document list and requests these operations without accessing Tiptap state.

`@ava/document-core` is the only AVA package that imports Tiptap. The editor
uses StarterKit for paragraphs, headings, bold, italic, bullet and ordered
lists, undo, and redo. Tiptap commands and types do not appear in the Web or
Desktop shells, AVA contracts, run events, or backend modules.

## Sprint 2 Runtime Flow

```text
User submits prompt
        ↓
Prompt Composer → ConversationRunProvider
        ↓
$ava/api-client (POST /runs → run_id)
        ↓
RunService → AgentPort → Mock Adapter
        ↓
Normalized run events (run_started, message_started,
message_content, run_completed / run_failed / run_cancelled)
        ↓
runEventProcessor (shared interpreter) → conversation state
        ↓
ConversationView / MessageList render
```

One active run per conversation is enforced; cancellation and retry operate
against the AVA-owned `run_id`. Conversation state is in-memory and resets on
refresh, matching the Sprint 2 scope.
