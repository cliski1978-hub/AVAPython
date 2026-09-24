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

The default `local` model provider targets an OpenAI-compatible endpoint
(Ollama's `/v1` route) at `http://localhost:11434/v1`. The backend starts
without the endpoint running; `/health` works immediately, but model
operations require a compatible runtime to be available.

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
| `AVA_AGENT_RUNTIME` | `native` | Agent runtime selection (composed but not yet used by runs) |
| `AVA_MODEL_PROVIDER` | `local` | Model provider selection |
| `AVA_MODEL_NAME` | `local-model` | Model name/id selection |
| `AVA_LOCAL_MODEL_BASE_URL` | `http://localhost:11434/v1` | OpenAI-compatible base URL for the local model provider |
| `AVA_HOST` | `127.0.0.1` | Backend bind host (localhost-only by default; set `0.0.0.0` for LAN access) |
| `AVA_PORT` | `8000` | Backend bind port |
| `AVA_DEBUG` | `true` | Debug mode |
| `AVA_LOG_LEVEL` | `info` | Log level |
| `VITE_API_BASE_URL` | `http://localhost:8000` | Web → backend base URL |

Provider selections are configuration-driven and become functional as
adapters land in later sprints.
## Optional real local-model validation (Phase 3 Step 12)

This manual check requires an already running Ollama and an installed chat
model. It is not part of `test_all.sh`; do not install or download anything
merely to run the deterministic suite.

1. Inspect the local runtime with `ollama --version`, `ollama list`, and
   `ollama ps`. Choose an installed chat model, preferably your configured one.
2. Set the following in your developer-controlled repository-root `.env`
   (record previous values so you can restore them):

   ```dotenv
   AVA_AGENT_PROVIDER=native
   AVA_MODEL_PROVIDER=local
   AVA_MODEL_NAME=<installed model id from ollama list>
   AVA_LOCAL_MODEL_BASE_URL=http://localhost:11434/v1
   ```

   Alternatively, if no root `.env` exists, export these variables for the
   backend process only. `dev_backend.sh` loads root `.env` after inherited
   variables, so existing file values take precedence. Keep `.env.example`
   and the source default at `mock`.
3. Start `./scripts/dev_backend.sh`. In a second terminal, run:

   ```bash
   curl --fail http://localhost:8000/health
   curl --fail http://localhost:8000/model-providers
   curl --fail -H 'Content-Type: application/json' \
     -d '{"prompt":"Reply with exactly: AVA LOCAL MODEL OK"}' \
     http://localhost:8000/runs
   ```

   Discovery should report default `local`, your model id, and health
   `available=true`, `status=healthy`. Discovery probes `/v1/models`; startup
   itself does not contact Ollama. A healthy discovery response proves endpoint
   reachability, not model existence. Generation must return `completed`.
4. Copy the returned run id into the retrieval requests:

   ```bash
   curl --fail http://localhost:8000/runs/<run_id>
   curl --fail http://localhost:8000/runs/<run_id>/events
   ```

   Expect `run_started → message_started → message_content → run_completed`,
   with non-empty assistant content. Retrieve before restarting: stores are
   in memory. Exact model text and latency may vary.
5. For a safe failure check, restart only this AVA process with a confirmed
   unused local port in `AVA_LOCAL_MODEL_BASE_URL`; do not stop Ollama or
   unrelated services. Repeat the API calls. Application health should still
   work; provider health should be unavailable. `POST /runs` should return
   HTTP 200 with status `failed`, followed by `run_started → run_failed`.
   The event message is `The agent failed to complete the run.`; it must not
   contain transport errors, URLs, or response bodies.
6. Restore your previous local configuration, stop the temporary validation
   backend, and run `./scripts/test_all.sh` (and `./scripts/build_all.sh` for
   the application build check).

Live cancellation is not externally testable through the current synchronous
route: the client receives the generated run id only after the run finishes.
Step 11 deterministic cancellation tests remain authoritative; do not redesign
the API to perform this manual check. Provider generation currently uses a
30-second HTTP timeout, which can matter for slower cold starts or longer
responses.
