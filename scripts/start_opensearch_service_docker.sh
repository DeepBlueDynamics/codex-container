#!/usr/bin/env bash
#
# Start/stop OpenSearch single-node service (no security) via docker-compose.opensearch.yml
#
# Usage:
#   ./scripts/start_opensearch_service_docker.sh --run        # default if no args
#   ./scripts/start_opensearch_service_docker.sh --stop
#   ./scripts/start_opensearch_service_docker.sh --restart
#   ./scripts/start_opensearch_service_docker.sh --logs
#
set -euo pipefail

ACTION="run"
LOGS=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run) ACTION="run"; shift ;;
    --stop) ACTION="stop"; shift ;;
    --restart) ACTION="restart"; shift ;;
    --logs) LOGS=true; shift ;;
    --help|-h)
      grep "^# " "$0" | sed 's/^# //'
      exit 0
      ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

COMPOSE_FILE="docker-compose.opensearch.yml"

if [[ ! -f "$COMPOSE_FILE" ]]; then
  echo "Compose file not found: $COMPOSE_FILE" >&2
  exit 1
fi

# ensure network exists
if ! docker network ls --format "{{.Name}}" | grep -q "^codex-network$"; then
  docker network create codex-network || true
fi

case "$ACTION" in
  stop)
    echo "Stopping OpenSearch..."
    docker-compose -f "$COMPOSE_FILE" down
    exit 0
    ;;
  restart)
    echo "Restarting OpenSearch..."
    docker-compose -f "$COMPOSE_FILE" restart
    ;;
  run)
    echo "Starting OpenSearch..."
    docker-compose -f "$COMPOSE_FILE" up -d
    ;;
esac

if [[ "$LOGS" == "true" ]]; then
  echo "Following logs (Ctrl+C to exit)..."
  docker-compose -f "$COMPOSE_FILE" logs -f
else
  echo "OpenSearch running on http://localhost:9200 (no auth, security disabled)"
fi
