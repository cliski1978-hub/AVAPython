# AVA Local Development

## Prerequisites

- Python **3.12+**
- Node.js **18+**
- pnpm **9+**
- Tauri system dependencies (for building/running the desktop app)

## Environment Configuration

Copy the example configuration to repository-root `.env`:

```bash
cp .env.example .env
```

`.env` is the single documented configuration location and is never
committed. It is loaded automatically:

- **Backend** — `./scripts/dev_backend.sh` sources the repository-root `.env`
  before launching Uvicorn, so `AVA_*` variables apply.
- **Frontend** — the Web and Desktop Vite configs set `envDir` to the
  repository root, so `VITE_API_BASE_URL` is available to both apps.

Running Uvicorn or Vite directly (outside the scripts) requires the
variables to be exported manually.

## Backend

### Create environment

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Start FastAPI

```bash
./scripts/dev_backend.sh
```

Or directly:

```bash
cd backend
source .venv/bin/activate
uvicorn ava.api.app:create_app --factory --reload
```

The backend listens on `http://localhost:8000` by default.

### Run tests

```bash
cd backend
source .venv/bin/activate
python -m pytest
```

Lint and typecheck:

```bash
ruff check src tests
mypy src
```

## Frontend

### Install pnpm dependencies

```bash
cd frontend
pnpm install
```

### Start Web

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

### Build Web

```bash
cd frontend
pnpm --filter @ava/web build
```

### Run frontend tests

```bash
cd frontend
pnpm -r test        # vitest
pnpm -r lint        # tsc --noEmit
```

## Verification

Start the backend and check the two Sprint 1 endpoints:

```text
GET /health
GET /capabilities
```

```bash
curl http://localhost:8000/health
curl http://localhost:8000/capabilities
```

## Convenience Scripts

- `./scripts/dev_backend.sh` — start the backend with reload.
- `./scripts/dev_web.sh` — start the Web app.
- `./scripts/test_all.sh` — run backend and frontend tests/lint.
- `./scripts/build_all.sh` — build backend and frontend artifacts.

## Environment Variables

Reference: `.env.example`. All settings are `AVA_*` prefixed.

| Variable | Default | Purpose |
| --- | --- | --- |
| `AVA_APPLICATION` | `AVA` | Application name reported by contracts |
| `AVA_ENVIRONMENT` | `development` | Application environment |
| `AVA_AGENT_PROVIDER` | `mock` | Agent provider selection |
| `AVA_MODEL_PROVIDER` | `local` | Model provider selection |
| `AVA_HOST` | `127.0.0.1` | Backend bind host (localhost-only by default; set `0.0.0.0` for LAN access) |
| `AVA_PORT` | `8000` | Backend bind port |
| `AVA_DEBUG` | `true` | Debug mode |
| `AVA_LOG_LEVEL` | `info` | Log level |
| `VITE_API_BASE_URL` | `http://localhost:8000` | Web → backend base URL |

Provider selections are configuration-driven and become functional as
adapters land in later sprints.