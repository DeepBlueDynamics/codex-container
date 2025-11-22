#!/usr/bin/env bash
set -euo pipefail

CODEX_HOME_OVERRIDE=""
REMOVE_IMAGE=false
TAG="gnosis/codex-service:dev"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --codex-home)
      shift
      if [[ $# -eq 0 ]]; then
        echo "Error: --codex-home requires a value" >&2
        exit 1
      fi
      CODEX_HOME_OVERRIDE="$1"
      shift
      ;;
    --remove-image)
      REMOVE_IMAGE=true
      shift
      ;;
    --tag)
      shift
      if [[ $# -eq 0 ]]; then
        echo "Error: --tag requires a value" >&2
        exit 1
      fi
      TAG="$1"
      shift
      ;;
    --help|-h)
      cat <<'USAGE'
Cleanup Codex container state.

Options:
  --codex-home <path>   Override the Codex home directory to delete
  --remove-image        Remove the Docker image (default tag gnosis/codex-service:dev)
  --tag <image:tag>     Image tag to remove when --remove-image is set
  --help                Show this help text
USAGE
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

resolve_codex_home() {
  local override="$1"
  local candidate="$override"
  if [[ -z "$candidate" && -n "${CODEX_CONTAINER_HOME:-}" ]]; then
    candidate="$CODEX_CONTAINER_HOME"
  fi
  if [[ -z "$candidate" ]]; then
    if [[ -n "${HOME:-}" ]]; then
      candidate="$HOME/.codex-service"
    else
      candidate="$(getent passwd "$(id -u 2>/dev/null)" 2>/dev/null | cut -d: -f6)/.codex-service"
    fi
  fi

  if command -v python3 >/dev/null 2>&1; then
    python3 - "$candidate" <<'PY'
import os, sys
print(os.path.abspath(os.path.expanduser(sys.argv[1])))
PY
  elif command -v python >/dev/null 2>&1; then
    python - "$candidate" <<'PY'
import os, sys
print(os.path.abspath(os.path.expanduser(sys.argv[1])))
PY
  else
    local path="$candidate"
    if [[ "$path" == ~* ]]; then
      path="${path/#\~/${HOME:-}}"
    fi
    (cd "${path%/*}" >/dev/null 2>&1 && mkdir -p "${path##*/}" && cd "${path##*/}" >/dev/null 2>&1 && pwd)
  fi
}

CODEX_HOME_PATH="$(resolve_codex_home "$CODEX_HOME_OVERRIDE")"

if [[ -n "$CODEX_HOME_PATH" && -d "$CODEX_HOME_PATH" ]]; then
  rm -rf "$CODEX_HOME_PATH"
  echo "Removed $CODEX_HOME_PATH"
else
  echo "Codex home not found at $CODEX_HOME_PATH"
fi

if [[ "$REMOVE_IMAGE" == true ]]; then
  if ! command -v docker >/dev/null 2>&1; then
    echo "docker command not found; skipping image removal." >&2
    exit 0
  fi
  docker image rm "$TAG"
fi
