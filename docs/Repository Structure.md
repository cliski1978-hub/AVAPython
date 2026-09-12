# AVA Repository Structure

```text
ava/
├── backend/                    # Python modular monolith (src-layout)
│   ├── src/ava/
│   │   ├── api/                # Transport only (FastAPI)
│   │   │   └── routes/         #   Thin routes (health, capabilities)
│   │   ├── core/               # Framework-neutral application core
│   │   │   └── application.py  #   ApplicationConfig, Application root
│   │   ├── contracts/          # AVA-owned JSON contracts (v1)
│   │   │   ├── version.py      #   CONTRACT_VERSION = "v1"
│   │   │   ├── json_types.py   #   JsonValue (JSON-safe values)
│   │   │   ├── requests.py     #   RunRequest
│   │   │   ├── responses.py    #   Health, Capabilities, Runs
│   │   │   ├── events.py       #   EventType, RunEvent
│   │   │   ├── capabilities.py #   CapabilityName
│   │   │   ├── errors.py       #   ErrorCategory, ErrorResponse
│   │   │   ├── models.py       #   ModelRequest, ModelResponse, ModelInfo
│   │   │   └── approvals.py    #   Reserved approval scaffold
│   │   ├── agents/             # Agent adapters (port)
│   │   │   └── contracts.py    #   AgentPort
│   │   ├── models/             # Model provider adapters (port)
│   │   │   └── contracts.py    #   ModelProviderPort
│   │   ├── services/           # Application services
│   │   │   ├── capability_service.py
│   │   │   └── run_service.py
│   │   ├── configuration/      # Environment settings
│   │   │   └── settings.py
│   │   └── infrastructure/     # Cross-cutting concerns (logging)
│   ├── tests/                  # Backend tests
│   └── pyproject.toml          # Backend packaging + tooling (pytest, ruff, mypy)
├── clients/python/             # Lightweight Python API client
├── frontend/
│   ├── packages/               # Shared TS packages
│   │   ├── contracts/          # TS representations of API contracts
│   │   │   └── src/            #   health, capabilities, runs, events,
│   │   │                       #   errors, models, version
│   │   ├── api-client/         # Single shared backend client
│   │   ├── ui-core/            # Shared UI, hooks, state, theme
│   │   ├── document-core/      # Reserved for document abstractions
│   │   └── agent-ui/           # Reserved for agent interaction UI
│   └── apps/                   # Thin application shells
│       ├── web/                # Priority 1
│       ├── desktop/            # Priority 2 (Tauri)
│       └── mobile/             # Priority 3 (placeholder)
├── docs/                       # Canonical documentation library
│   ├── AVA Development Plan.md
│   ├── Architecture.md
│   ├── Repository Structure.md
│   ├── Contract Standards.md
│   ├── Agent Adapter.md
│   ├── Model Provider.md
│   └── Local Development.md
├── scripts/                    # Developer convenience scripts
│   ├── dev_backend.sh
│   ├── dev_web.sh
│   ├── test_all.sh
│   └── build_all.sh
└── .env.example                # Environment variable reference
```

## Boundary Rules

- `backend/` never depends on `frontend/` or `clients/`.
- AVA Core and AVA Contracts never import transport or vendor frameworks.
- Frontend application shells use `@ava/api-client`; they never duplicate
  backend request logic.
- Application shells are thin; shared packages carry the implementation.