#!/usr/bin/env bash
set -euo pipefail

# Build and run mcphost service container on codex-network
# Usage:
#   ./scripts/start_mcphost_service_docker.sh --build
#   ./scripts/start_mcphost_service_docker.sh --run
#   ./scripts/start_mcphost_service_docker.sh --stop
#
# Options:
#   --tag <image>          Docker image tag (default: gnosis/mcphost:dev)
#   --config <file>        Path to mcphost config (default: scripts/mcphost_config.yml)
#   --name <container>     Container name (default: gnosis-mcphost)

TAG="gnosis/mcphost:dev"
CONFIG="scripts/mcphost_config.yml"
NAME="gnosis-mcphost"

action=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --build) action="build"; shift ;;
    --run) action="run"; shift ;;
    --stop) action="stop"; shift ;;
    --tag) TAG="$2"; shift 2 ;;
    --config) CONFIG="$2"; shift 2 ;;
    --name) NAME="$2"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$action" ]]; then
  echo "Specify --build or --run or --stop"
  exit 1
fi

if [[ "$action" == "build" ]]; then
  docker build -f Dockerfile.mcphost -t "$TAG" \
    --build-arg MCPSRC=github.com/mark3labs/mcphost \
    --build-arg GO_VERSION=1.24 \
    --no-cache \
    .
  exit 0
fi

if [[ "$action" == "stop" ]]; then
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  exit 0
fi

# run
if [[ ! -f "$CONFIG" ]]; then
  echo "Config file not found: $CONFIG"
  exit 1
fi

docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d \
  --name "$NAME" \
  --network codex-network \
  -v "$(realpath "$CONFIG")":/mcphost/config.yml:ro \
  "$TAG"
