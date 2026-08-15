#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PYTHON_BIN="${ROOT}/.venv/bin/python"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="${ROOT}/backend/.venv/bin/python"
fi
if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "DocsHound's Python environment is missing. Follow the backend setup in README.md." >&2
  exit 1
fi

cd "${ROOT}"
PYTHONPATH="${ROOT}/backend" exec "${PYTHON_BIN}" "${ROOT}/demo/rehearse.py" "$@"
