# AVA

**AVA** is a reusable AI application platform. It is organized as a
multi-application monorepo with a shared frontend platform and a Python
backend modular monolith built on Hexagonal Architecture (Ports and
Adapters).

## Architecture Summary

- **Multi-application monorepo** — Web, Desktop, and Mobile share as much
  code as reasonably possible.
- **Modular monolith** — The Python backend is a single deployable with
  clearly separated internal modules.
- **Hexagonal Architecture** — AVA Core depends only on application-owned
  contracts (ports); all frameworks and vendors integrate through adapters.
- **Contract-first APIs** — AVA owns its JSON contracts; vendor SDK objects
  never appear in shared contracts.
- **Shared frontend packages** — cross-platform code is the default, and
  thin shell apps are the exception.

The frontend applications are clients of the Python application. The Python
backend remains independent of frontend technologies.

## Repository Structure

```text
ava/
├── backend/                  # Python modular monolith (src-layout)
│   ├── src/ava/
│   │   ├── api/              # Transport only (FastAPI)
│   │   ├── core/             # Framework-neutral application core
│   │   ├── contracts/        # AVA-owned JSON contracts
│   │   ├── agents/           # Agent adapters (port + placeholders)
│   │   ├── models/           # Model provider adapters (port + placeholders)
│   │   ├── services/         # Application services
│   │   ├── configuration/    # Environment settings
│   │   └── infrastructure/   # Cross-cutting concerns (logging)
│   └── tests/
├── clients/python/           # Lightweight Python API client
├── frontend/
│   ├── packages/             # Shared TS packages
│   │   ├── contracts/        # TS representations of API contracts
│   │   ├── api-client/       # Single shared backend client
│   │   ├── ui-core/          # Shared UI, hooks, state, theme
│   │   ├── document-core/    # Shared Tiptap editor integration
│   │   ├── agent-ui/         # Shared agent interaction UI
│   │   └── workspace/        # Shared Chat / Documents workspace composition
│   └── apps/                 # Thin application shells
│       ├── web/              # Priority 1
│       ├── desktop/          # Priority 2 (Tauri)
│       └── mobile/           # Priority 3 (placeholder)
├── docs/
│   ├── AVA Phase 5 Complete Documentation.md
│   ├── AVA Phase 5.40 Full Validation.md
│   ├── AVA Canonical Development Plan Current to Completion.md
│   ├── AVA Development Plan.md
│   ├── Architecture.md
│   ├── Repository Structure.md
│   ├── Contract Standards.md
│   ├── Agent Adapter.md
│   ├── Model Provider.md
│   └── Local Development.md
└── scripts/                  # Developer convenience scripts
```

## Development Priorities

1. **Web** — highest development priority
2. **Desktop** — second development priority (Tauri)
3. **Mobile** — final development priority (placeholder structure only)

## Prerequisites

- Python **3.12+**
- Node.js **18+**
- pnpm **9+**
- Tauri system dependencies (for building/running the desktop app)

## Python Environment Setup

The Python project (packaging, dependencies, and tool configuration) lives in
`backend/pyproject.toml`. Create the environment from within `backend/`:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

`.[dev]` installs the backend runtime dependencies (FastAPI, Uvicorn,
Pydantic, httpx) plus the development tools (pytest, Ruff, mypy).

## Environment Configuration

Copy `.env.example` to a repository-root `.env` to configure the backend
(`AVA_*`) and the frontend (`VITE_API_BASE_URL`). The development scripts
load it: `dev_backend.sh` sources the root `.env`, and the Web/Desktop Vite
configs read it via `envDir`. `.env` is never committed.

## pnpm Setup

```bash
pnpm install
```

## Backend Startup

```bash
./scripts/dev_backend.sh
```

Or directly:

```bash
cd backend
source .venv/bin/activate
uvicorn ava.api.app:create_app --factory --reload
```

The backend listens on `http://localhost:8000` by default. Sprint 1
endpoints:

```text
GET /health
GET /capabilities
```

## Web Startup

```bash
./scripts/dev_web.sh
```

Or directly:

```bash
cd frontend
pnpm --filter @ava/web dev
```

The web application starts at `http://localhost:5173` and reports the
application status by calling `/health` through the shared `@ava/api-client`.

## Running Tests

```bash
./scripts/test_all.sh
```

Or individually:

```bash
cd backend && pytest                 # backend tests
cd backend && ruff check src tests   # backend lint
cd backend && mypy src               # backend typecheck
cd frontend && pnpm -r test          # frontend tests
```

## Architecture Boundaries

```text
AVA Web
   ↓
Shared API Client
   ↓
FastAPI Adapter
   ↓
Application Services
   ↓
AVA Core / Ports
```

AVA Contracts are not a sequential layer between FastAPI and Core; they are
shared contracts exchanged across these boundaries:

```text
             AVA Contracts
          ↙       ↓       ↘
     Frontend    API    Services
```

Reserved adapter boundaries (not implemented yet):

```text
AVA Core
   ├── Agent Port          → Mock / AWS / Databricks adapters
   ├── Model Provider Port → Local / Company Gateway / External adapters
   └── Persistence Port    → Future storage adapter
```

See `docs/Architecture.md` for details.

## Contract-First APIs

AVA owns its JSON contracts (contract version `v1`). Every payload carries
`contract_version`. Run, event, capability, and error contracts are defined
in `backend/src/ava/contracts/` and mirrored in
`frontend/packages/contracts/`. See `docs/Contract Standards.md`.

## License

MIT
