#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV_BIN="${ROOT}/.venv/bin"

exec "${VENV_BIN}/uvicorn" app.main:app --reload --host 127.0.0.1 --port 8000
