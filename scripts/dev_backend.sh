#!/usr/bin/env bash
# Start the AVA backend with uvicorn.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"

# Load the repository-root .env when present so AVA_* variables apply. `.env`
# is developer-controlled and gitignored; .env.example documents the keys.
load_env() {
  [ -f "$ROOT/.env" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      '' | \#*) continue ;;
    esac
    line="${line#export }"
    key="${line%%=*}"
    value="${line#*=}"
    [ -n "$key" ] || continue
    case "$value" in
      \"*\") value="${value#\"}"; value="${value%\"}" ;;
      \'*\') value="${value#\'}"; value="${value%\'}" ;;
    esac
    export "$key=$value"
  done < "$ROOT/.env"
}
load_env

# Use a PYTHONPATH to src so uvicorn can import the package whether or not
# it has been pip-installed in the venv.
export PYTHONPATH="$ROOT/backend/src${PYTHONPATH:+:$PYTHONPATH}"

UVICORN_BIN=".venv/bin/uvicorn"
if [ ! -x "$UVICORN_BIN" ]; then
  UVICORN_BIN="$(command -v uvicorn || true)"
fi
if [ -z "$UVICORN_BIN" ]; then
  echo "uvicorn not found. Create the backend venv first: see README." >&2
  exit 1
fi

exec "$UVICORN_BIN" ava.api.app:create_app --factory \
  --host "${AVA_HOST:-127.0.0.1}" \
  --port "${AVA_PORT:-8000}" \
  --log-level "${AVA_LOG_LEVEL:-info}" \
  --reload