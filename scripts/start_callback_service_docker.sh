#!/usr/bin/env bash
#
# Start/stop the simple callback logger (gnosis-callback) on codex-network.
# Uses docker-compose.callback.yml
#
# Usage:
#   ./scripts/start_callback_service_docker.sh --run    # default
#   ./scripts/start_callback_service_docker.sh --stop
#   ./scripts/start_callback_service_docker.sh --restart
#   ./scripts/start_callback_service_docker.sh --logs
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

COMPOSE_FILE="docker-compose.callback.yml"
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
    echo "Stopping callback service..."
    docker-compose -f "$COMPOSE_FILE" down
    exit 0
    ;;
  restart)
    echo "Restarting callback service..."
    docker-compose -f "$COMPOSE_FILE" restart
    ;;
  run)
    echo "Starting callback service..."
    docker-compose -f "$COMPOSE_FILE" up -d
    ;;
esac

if [[ "$LOGS" == "true" ]]; then
  echo "Following logs (Ctrl+C to exit)..."
  docker-compose -f "$COMPOSE_FILE" logs -f
else
  echo "Callback service listening on http://localhost:8088 (container name: gnosis-callback)"
fi
