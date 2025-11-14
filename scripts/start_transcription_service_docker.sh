#!/usr/bin/env bash
#
# Start the persistent transcription service container
#
# DESCRIPTION:
#   Builds and starts the GPU-enabled transcription service using docker-compose.
#   The service keeps the Whisper large-v3 model loaded in memory for fast transcription.
#
# USAGE:
#   ./start_transcription_service_docker.sh [OPTIONS]
#
# OPTIONS:
#   --build     Rebuild the Docker image before starting
#   --logs      Show service logs after starting
#   --stop      Stop the transcription service
#   --restart   Restart the transcription service
#   --help      Show this help message
#
# EXAMPLES:
#   ./start_transcription_service_docker.sh
#       Start the service (uses existing image)
#
#   ./start_transcription_service_docker.sh --build
#       Rebuild image and start service
#
#   ./start_transcription_service_docker.sh --logs
#       Start and follow logs
#
#   ./start_transcription_service_docker.sh --stop
#       Stop the service

set -euo pipefail

# Parse arguments
BUILD=false
LOGS=false
STOP=false
RESTART=false

while [[ $# -gt 0 ]]; do
  case $1 in
    --build)
      BUILD=true
      shift
      ;;
    --logs)
      LOGS=true
      shift
      ;;
    --stop)
      STOP=true
      shift
      ;;
    --restart)
      RESTART=true
      shift
      ;;
    --help|-h)
      grep "^#" "$0" | sed 's/^# \?//'
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      echo "Run with --help for usage information" >&2
      exit 1
      ;;
  esac
done

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
COMPOSE_FILE="$PROJECT_ROOT/docker-compose.transcription.yml"

if [[ ! -f "$COMPOSE_FILE" ]]; then
  echo "Error: docker-compose.transcription.yml not found at $COMPOSE_FILE" >&2
  exit 1
fi

cd "$PROJECT_ROOT"

# Handle stop
if [[ "$STOP" == "true" ]]; then
  echo "Stopping transcription service..."
  docker-compose -f "$COMPOSE_FILE" down
  echo "Transcription service stopped."
  exit 0
fi

# Handle restart
if [[ "$RESTART" == "true" ]]; then
  echo "Restarting transcription service..."
  docker-compose -f "$COMPOSE_FILE" restart
  echo "Transcription service restarted."

  if [[ "$LOGS" == "true" ]]; then
    echo ""
    echo "Following logs (Ctrl+C to exit)..."
    docker-compose -f "$COMPOSE_FILE" logs -f
  fi
  exit 0
fi

# Check if NVIDIA runtime is available
if ! docker info 2>&1 | grep -q nvidia; then
  echo "WARNING: NVIDIA Docker runtime not detected. GPU acceleration may not work." >&2
  echo "To enable GPU support:" >&2
  echo "  1. Install nvidia-docker2" >&2
  echo "  2. Configure Docker to use nvidia runtime" >&2
  echo "" >&2
  echo "Continuing with CPU-only mode..." >&2
  sleep 3
fi

# Ensure codex-network exists
if ! docker network inspect codex-network >/dev/null 2>&1; then
  echo "Creating codex-network for inter-container communication..."
  docker network create codex-network 2>/dev/null || echo "Warning: Network may already exist"
fi

# Build if requested
if [[ "$BUILD" == "true" ]]; then
  echo "Building transcription service image..."
  docker-compose -f "$COMPOSE_FILE" build --no-cache
  echo "Build complete!"
fi

# Start the service
echo "Starting transcription service..."
docker-compose -f "$COMPOSE_FILE" up -d

echo ""
echo "Transcription service started!"
echo "  Container: gnosis-transcription-service"
echo "  Endpoint:  http://localhost:8765"
echo ""
echo "Service endpoints:"
echo "  POST http://localhost:8765/transcribe   - Upload WAV file"
echo "  GET  http://localhost:8765/status/{id}  - Check job status"
echo "  GET  http://localhost:8765/download/{id} - Download transcript"
echo "  GET  http://localhost:8765/health        - Health check"
echo ""
echo "Management commands:"
echo "  View logs:    docker-compose -f docker-compose.transcription.yml logs -f"
echo "  Stop service: docker-compose -f docker-compose.transcription.yml down"
echo "  Check status: docker ps | grep transcription"

# Follow logs if requested
if [[ "$LOGS" == "true" ]]; then
  echo ""
  echo "Following logs (Ctrl+C to exit)..."
  sleep 2
  docker-compose -f "$COMPOSE_FILE" logs -f
else
  # Wait for health check
  echo ""
  echo "Waiting for service to be healthy..."
  MAX_WAIT=60
  WAITED=0
  while [[ $WAITED -lt $MAX_WAIT ]]; do
    if curl -sf http://localhost:8765/health >/dev/null 2>&1; then
      echo "Service is healthy!"
      break
    fi
    sleep 2
    WAITED=$((WAITED + 2))
    echo -n "."
  done
  echo ""

  if [[ $WAITED -ge $MAX_WAIT ]]; then
    echo "WARNING: Service health check timeout. Check logs with:"
    echo "  docker-compose -f docker-compose.transcription.yml logs"
  fi
fi
