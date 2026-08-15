#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required. Install it from https://docs.astral.sh/uv/." >&2
  exit 1
fi

cd "${ROOT}"
PYTHONPATH="${ROOT}/backend" exec uv run --project "${ROOT}/backend" --locked \
  python "${ROOT}/demo/rehearse.py" "$@"
