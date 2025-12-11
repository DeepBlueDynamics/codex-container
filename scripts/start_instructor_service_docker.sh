#!/usr/bin/env bash
#
# Start the GPU-enabled Instructor XL embedding service
#
# USAGE:
#   ./start_instructor_service_docker.sh [--build] [--logs] [--stop] [--restart]
#

set -euo pipefail

BUILD=false
LOGS=false
STOP=false
RESTART=false

while [[ $# -gt 0 ]]; do
  case $1 in
    --build) BUILD=true; shift ;;
    --logs) LOGS=true; shift ;;
    --stop) STOP=true; shift ;;
    --restart) RESTART=true; shift ;;
    --help|-h)
      grep "^#" "$0" | sed 's/^# \?//'
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
COMPOSE_FILE="$PROJECT_ROOT/docker-compose.instructor.yml"

if [[ ! -f "$COMPOSE_FILE" ]]; then
  echo "Error: $COMPOSE_FILE not found" >&2
  exit 1
fi

cd "$PROJECT_ROOT"

if [[ "$STOP" == "true" ]]; then
  echo "Stopping instructor service..."
  docker-compose -f "$COMPOSE_FILE" down
  exit 0
fi

if [[ "$RESTART" == "true" ]]; then
  echo "Restarting instructor service..."
  docker-compose -f "$COMPOSE_FILE" restart
  [[ "$LOGS" == "true" ]] && docker-compose -f "$COMPOSE_FILE" logs -f
  exit 0
fi

if ! docker network inspect codex-network >/dev/null 2>&1; then
  echo "Creating codex-network..."
  docker network create codex-network 2>/dev/null || true
fi

if [[ "$BUILD" == "true" ]]; then
  echo "Building instructor service image..."
  docker-compose -f "$COMPOSE_FILE" build --no-cache
fi

echo "Starting instructor service..."
docker-compose -f "$COMPOSE_FILE" up -d

echo "Instructor service running on http://localhost:8787"
echo "Endpoints:"
echo "  POST /embed  {\"texts\": [\"...\"], \"instruction\": \"...\"}"
echo "  GET  /health"

if [[ "$LOGS" == "true" ]]; then
  docker-compose -f "$COMPOSE_FILE" logs -f
fi
