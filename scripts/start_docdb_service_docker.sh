#!/usr/bin/env bash
set -euo pipefail

# Build/run/stop the docdb + docdb-mcp services (uses docker-compose.docdb.yml)
# Usage:
#   ./scripts/start_docdb_service_docker.sh --build
#   ./scripts/start_docdb_service_docker.sh --run
#   ./scripts/start_docdb_service_docker.sh --stop

action=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --build) action="build"; shift ;;
    --run) action="run"; shift ;;
    --stop) action="stop"; shift ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$action" ]]; then
  echo "Specify --build or --run or --stop"
  exit 1
fi

COMPOSE_FILE="docker-compose.docdb.yml"

if [[ ! -f "$COMPOSE_FILE" ]]; then
  echo "Compose file not found: $COMPOSE_FILE"
  exit 1
fi

# ensure network exists
if ! docker network ls --format "{{.Name}}" | grep -q "^codex-network$"; then
  docker network create codex-network || true
fi

if [[ "$action" == "build" ]]; then
  docker-compose -f "$COMPOSE_FILE" build
  exit 0
fi

if [[ "$action" == "stop" ]]; then
  docker-compose -f "$COMPOSE_FILE" down
  exit 0
fi

docker-compose -f "$COMPOSE_FILE" up -d
