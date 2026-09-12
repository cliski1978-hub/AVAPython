#!/usr/bin/env bash
# Build all AVA frontend applications.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> Building shared packages (packages without a build step are skipped)"
(cd "$ROOT/frontend" && pnpm -r --filter './packages/*' --if-present build)

echo "==> Building web application"
(cd "$ROOT/frontend" && pnpm --filter @ava/web build)

echo "==> Building desktop application"
(cd "$ROOT/frontend" && pnpm --filter @ava/desktop build)
