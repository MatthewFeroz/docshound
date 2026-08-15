#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCENARIO="${1:-opencode}"

"${ROOT}/demo/phoenix.sh" start

export OTEL_EXPORTER_OTLP_ENDPOINT="http://127.0.0.1:6006"
export OTEL_EXPORTER_OTLP_HEADERS="x-project-name=docshound-${SCENARIO}-demo"
export OTEL_SERVICE_NAME="docshound"

"${ROOT}/demo/preflight.sh" "${SCENARIO}" --require-free-app-ports

export DOCSHOUND_DEMO_SCENARIO="${SCENARIO}"
exec "${ROOT}/run.sh"
