#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"

"${ROOT}/backend/run.sh" &
BACKEND_PID=$!

cleanup() {
  kill "${BACKEND_PID}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

bun run --cwd "${ROOT}/frontend" dev
