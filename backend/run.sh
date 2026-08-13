#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${ROOT}"

if [[ -f ../.env ]]; then
  set -a
  # shellcheck disable=SC1091
  source ../.env
  set +a
fi

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

VENV_BIN="${ROOT}/.venv/bin"
if [[ ! -x "${VENV_BIN}/uvicorn" && -x "${ROOT}/../.venv/bin/uvicorn" ]]; then
  VENV_BIN="${ROOT}/../.venv/bin"
fi

exec "${VENV_BIN}/uvicorn" app.main:app --reload --host 127.0.0.1 --port 8000
