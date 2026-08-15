#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCENARIO="${1:-opencode}"

export LANGSMITH_PROJECT="docshound-${SCENARIO}-demo"
export OTEL_SERVICE_NAME="docshound"

"${ROOT}/demo/preflight.sh" "${SCENARIO}" --require-free-app-ports

export DOCSHOUND_DEMO_SCENARIO="${SCENARIO}"
exec "${ROOT}/run.sh"
