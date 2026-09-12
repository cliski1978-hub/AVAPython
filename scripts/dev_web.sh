#!/usr/bin/env bash
# Start the AVA web application (Priority 1).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/frontend"

PNPM_BIN="pnpm"
if ! command -v "$PNPM_BIN" >/dev/null 2>&1 && [ -x "$HOME/.npm-global/bin/pnpm" ]; then
  PNPM_BIN="$HOME/.npm-global/bin/pnpm"
fi

exec "$PNPM_BIN" --filter @ava/web dev