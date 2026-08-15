#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${ROOT}/demo/compose.yaml"
ACTION="${1:-start}"

case "${ACTION}" in
  start)
    docker compose -f "${COMPOSE_FILE}" up -d phoenix
    echo "Waiting for the local Phoenix trace viewer..."
    for _ in {1..60}; do
      if curl --fail --silent --output /dev/null http://127.0.0.1:6006/; then
        echo "Phoenix is ready at http://127.0.0.1:6006"
        exit 0
      fi
      sleep 1
    done
    echo "Phoenix did not become ready. Inspect it with: ./demo/phoenix.sh logs" >&2
    exit 1
    ;;
  stop)
    docker compose -f "${COMPOSE_FILE}" stop phoenix
    ;;
  logs)
    docker compose -f "${COMPOSE_FILE}" logs --tail=100 phoenix
    ;;
  status)
    docker compose -f "${COMPOSE_FILE}" ps phoenix
    ;;
  *)
    echo "Usage: $0 {start|stop|logs|status}" >&2
    exit 2
    ;;
esac
