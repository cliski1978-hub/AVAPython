#!/usr/bin/env bash
# Run all AVA tests (backend and frontend).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

detect_python() {
  local venv="$ROOT/backend/.venv/bin/python"
  if [ -x "$venv" ]; then
    echo "$venv"
    return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    echo "python3"
  elif command -v python >/dev/null 2>&1; then
    echo "python"
  else
    echo "python: command not found" >&2
    return 1
  fi
}

PYTHON_BIN="$(detect_python)"
CLIENT_PYTHON="$ROOT/clients/python/.venv/bin/python"

if [ ! -x "$CLIENT_PYTHON" ]; then
  echo "Python client venv not found. Create it with: cd clients/python && python -m venv .venv && .venv/bin/pip install -e '.[dev]'" >&2
  exit 1
fi

echo "==> Backend tests"
(cd "$ROOT/backend" && "$PYTHON_BIN" -m pytest)

echo "==> Backend lint"
(cd "$ROOT/backend" && "$PYTHON_BIN" -m ruff check src tests)

echo "==> Backend typecheck"
(cd "$ROOT/backend" && "$PYTHON_BIN" -m mypy src)

echo "==> Frontend tests"
(cd "$ROOT/frontend" && pnpm -r --if-present test)

echo "==> Lint (frontend)"
(cd "$ROOT/frontend" && pnpm -r --if-present lint)

echo "==> Python client checks"
(cd "$ROOT/clients/python" && "$CLIENT_PYTHON" -m pytest)
(cd "$ROOT/clients/python" && "$CLIENT_PYTHON" -m ruff check src tests)
(cd "$ROOT/clients/python" && "$CLIENT_PYTHON" -m mypy src)
