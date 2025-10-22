#!/usr/bin/env bash
set -euo pipefail

ACTION=""
TAG="gnosis/codex-service:dev"
WORKSPACE_OVERRIDE=""
SKIP_UPDATE=false
NO_AUTO_LOGIN=false
PUSH_IMAGE=false
JSON_MODE="none"
CODEX_HOME_OVERRIDE=""
USE_OSS=false
OSS_MODEL=""
NO_CACHE=false
declare -a CODEX_ARGS=()
declare -a EXEC_ARGS=()
declare -a POSITIONAL_ARGS=()
GATEWAY_PORT_OVERRIDE=""
GATEWAY_HOST_OVERRIDE=""
declare -a DOCKER_RUN_EXTRA_ARGS=()
declare -a DOCKER_RUN_EXTRA_ENVS=()
WATCH_PATH=""
declare -a WATCH_PATTERNS=()
WATCH_INTERVAL=""
WATCH_TEMPLATE=""
WATCH_INCLUDE_CONTENT=false
WATCH_CONTENT_BYTES=""
WATCH_STATE_FILE=""
WATCH_ONCE=false
WATCH_DEBOUNCE=""
MONITOR_PROMPT_FILE="MONITOR.md"
SESSION_ID=""
TRANSCRIPTION_SERVICE_URL="http://host.docker.internal:8765"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install)
      if [[ -n "$ACTION" && "$ACTION" != "install" ]]; then
        echo "Error: multiple actions specified" >&2
        exit 1
      fi
      ACTION="install"
      shift
      ;;
    --login)
      if [[ -n "$ACTION" && "$ACTION" != "login" ]]; then
        echo "Error: multiple actions specified" >&2
        exit 1
      fi
      ACTION="login"
      shift
      ;;
    --run)
      if [[ -n "$ACTION" && "$ACTION" != "run" ]]; then
        echo "Error: multiple actions specified" >&2
        exit 1
      fi
      ACTION="run"
      shift
      ;;
    --exec)
      if [[ -n "$ACTION" && "$ACTION" != "exec" ]]; then
        echo "Error: multiple actions specified" >&2
        exit 1
      fi
      ACTION="exec"
      shift
      ;;
    --shell)
      if [[ -n "$ACTION" && "$ACTION" != "shell" ]]; then
        echo "Error: multiple actions specified" >&2
        exit 1
      fi
      ACTION="shell"
      shift
      ;;
    --serve)
      if [[ -n "$ACTION" && "$ACTION" != "serve" ]]; then
        echo "Error: multiple actions specified" >&2
        exit 1
      fi
      ACTION="serve"
      shift
      ;;
    --watch)
      if [[ -n "$ACTION" && "$ACTION" != "watch" ]]; then
        echo "Error: multiple actions specified" >&2
        exit 1
      fi
      ACTION="watch"
      shift
      ;;
    --monitor)
      if [[ -n "$ACTION" && "$ACTION" != "monitor" ]]; then
        echo "Error: multiple actions specified" >&2
        exit 1
      fi
      ACTION="monitor"
      shift
      ;;
    --list-sessions)
      if [[ -n "$ACTION" && "$ACTION" != "list-sessions" ]]; then
        echo "Error: multiple actions specified" >&2
        exit 1
      fi
      ACTION="list-sessions"
      shift
      ;;
    --push)
      PUSH_IMAGE=true
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
    --workspace)
      shift
      if [[ $# -eq 0 ]]; then
        echo "Error: --workspace requires a value" >&2
        exit 1
      fi
      WORKSPACE_OVERRIDE="$1"
      shift
      ;;
    --codex-arg)
      shift
      if [[ $# -eq 0 ]]; then
        echo "Error: --codex-arg requires a value" >&2
        exit 1
      fi
      CODEX_ARGS+=("$1")
      shift
      ;;
    --exec-arg)
      shift
      if [[ $# -eq 0 ]]; then
        echo "Error: --exec-arg requires a value" >&2
        exit 1
      fi
      EXEC_ARGS+=("$1")
      shift
      ;;
    --skip-update)
      SKIP_UPDATE=true
      shift
      ;;
    --no-auto-login)
      NO_AUTO_LOGIN=true
      shift
      ;;
    --codex-home)
      shift
      if [[ $# -eq 0 ]]; then
        echo "Error: --codex-home requires a value" >&2
        exit 1
      fi
      CODEX_HOME_OVERRIDE="$1"
      shift
      ;;
    --json)
      if [[ "$JSON_MODE" != "none" ]]; then
        echo "Error: multiple JSON output modes specified" >&2
        exit 1
      fi
      JSON_MODE="legacy"
      shift
      ;;
    --json-e|--json-experimental)
      if [[ "$JSON_MODE" != "none" ]]; then
        echo "Error: multiple JSON output modes specified" >&2
        exit 1
      fi
      JSON_MODE="experimental"
      shift
      ;;
    --oss)
      USE_OSS=true
      shift
      ;;
    --no-cache)
      NO_CACHE=true
      shift
      ;;
    --gateway-port)
      shift
      if [[ $# -eq 0 ]]; then
        echo "Error: --gateway-port requires a value" >&2
        exit 1
      fi
      GATEWAY_PORT_OVERRIDE="$1"
      shift
      ;;
    --gateway-host)
      shift
      if [[ $# -eq 0 ]]; then
        echo "Error: --gateway-host requires a value" >&2
        exit 1
      fi
      GATEWAY_HOST_OVERRIDE="$1"
      shift
      ;;
    --watch-path)
      shift
      if [[ $# -eq 0 ]]; then
        echo "Error: --watch-path requires a value" >&2
        exit 1
      fi
      WATCH_PATH="$1"
      shift
      ;;
    --watch-pattern)
      shift
      if [[ $# -eq 0 ]]; then
        echo "Error: --watch-pattern requires a value" >&2
        exit 1
      fi
      WATCH_PATTERNS+=("$1")
      shift
      ;;
    --watch-interval)
      shift
      if [[ $# -eq 0 ]]; then
        echo "Error: --watch-interval requires a value" >&2
        exit 1
      fi
      WATCH_INTERVAL="$1"
      shift
      ;;
    --watch-template)
      shift
      if [[ $# -eq 0 ]]; then
        echo "Error: --watch-template requires a value" >&2
        exit 1
      fi
      WATCH_TEMPLATE="$1"
      shift
      ;;
    --watch-include-content)
      WATCH_INCLUDE_CONTENT=true
      shift
      ;;
    --watch-content-bytes)
      shift
      if [[ $# -eq 0 ]]; then
        echo "Error: --watch-content-bytes requires a value" >&2
        exit 1
      fi
      WATCH_CONTENT_BYTES="$1"
      shift
      ;;
    --watch-state-file)
      shift
      if [[ $# -eq 0 ]]; then
        echo "Error: --watch-state-file requires a value" >&2
        exit 1
      fi
      WATCH_STATE_FILE="$1"
      shift
      ;;
    --watch-once)
      WATCH_ONCE=true
      shift
      ;;
    --watch-debounce)
      shift
      if [[ $# -eq 0 ]]; then
        echo "Error: --watch-debounce requires a value" >&2
        exit 1
      fi
      WATCH_DEBOUNCE="$1"
      shift
      ;;
    --monitor-prompt)
      shift
      if [[ $# -eq 0 ]]; then
        echo "Error: --monitor-prompt requires a value" >&2
        exit 1
      fi
      MONITOR_PROMPT_FILE="$1"
      shift
      ;;
    --session-id)
      shift
      if [[ $# -eq 0 ]]; then
        echo "Error: --session-id requires a value" >&2
        exit 1
      fi
      SESSION_ID="$1"
      shift
      ;;
    --transcription-service-url)
      shift
      if [[ $# -eq 0 ]]; then
        echo "Error: --transcription-service-url requires a value" >&2
        exit 1
      fi
      TRANSCRIPTION_SERVICE_URL="$1"
      shift
      ;;
    --model)
      shift
      if [[ $# -eq 0 ]]; then
        echo "Error: --model requires a value" >&2
        exit 1
      fi
      USE_OSS=true
      OSS_MODEL="$1"
      shift
      ;;
    --)
      shift
      POSITIONAL_ARGS=("$@")
      break
      ;;
    *)
      POSITIONAL_ARGS+=("$1")
      shift
      ;;
  esac
done

if [[ -z "$ACTION" ]]; then
  ACTION="run"
fi

if [[ "$ACTION" == "exec" && ${#EXEC_ARGS[@]} -eq 0 && ${#POSITIONAL_ARGS[@]} -gt 0 ]]; then
  EXEC_ARGS=("${POSITIONAL_ARGS[@]}")
fi

if [[ "$ACTION" != "exec" && ${#CODEX_ARGS[@]} -eq 0 && ${#POSITIONAL_ARGS[@]} -gt 0 ]]; then
  CODEX_ARGS=("${POSITIONAL_ARGS[@]}")
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODEX_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CURRENT_DIR="$(pwd)"
abs_path() {
  perl -MCwd=abs_path -le 'print abs_path(shift)' "$1"
}

resolve_absolute_path() {
  local input="$1"
  if command -v python3 >/dev/null 2>&1; then
    python3 - <<'PY' "$input"
import os, sys
print(os.path.abspath(os.path.expanduser(sys.argv[1])))
PY
    return
  elif command -v python >/dev/null 2>&1; then
    python - <<'PY' "$input"
import os, sys
print(os.path.abspath(os.path.expanduser(sys.argv[1])))
PY
    return
  fi

  local expanded="$input"
  if [[ "$expanded" == ~* ]]; then
    expanded="${expanded/#\~/${HOME:-}}"
  fi
  if [[ "$expanded" == /* ]]; then
    printf '%s\n' "$expanded"
    return
  fi
  local base="${HOME:-$CURRENT_DIR}"
  (
    cd "$base" >/dev/null 2>&1 || exit 1
    mkdir -p "$expanded"
    cd "$expanded" >/dev/null 2>&1 || exit 1
    pwd
  )
}

resolve_workspace() {
  local input="$1"
  if [[ -z "$input" ]]; then
    abs_path "$CURRENT_DIR"
    return
  fi
  if [[ "$input" == /* ]]; then
    if [[ -d "$input" ]]; then
      abs_path "$input"
      return
    else
      echo "Error: workspace '$input' not found" >&2
      exit 1
    fi
  fi
  if [[ -d "${CURRENT_DIR}/${input}" ]]; then
    abs_path "${CURRENT_DIR}/${input}"
    return
  fi
  if [[ -d "${CODEX_ROOT}/${input}" ]]; then
    abs_path "${CODEX_ROOT}/${input}"
    return
  fi
  echo "Error: workspace '$input' could not be resolved" >&2
  exit 1
}

WORKSPACE_PATH="$(resolve_workspace "$WORKSPACE_OVERRIDE")"

if [[ "$ACTION" == "watch" && -z "$WATCH_PATH" ]]; then
  WATCH_PATH="$WORKSPACE_PATH"
fi
if [[ "$ACTION" == "monitor" && -z "$WATCH_PATH" ]]; then
  WATCH_PATH="$WORKSPACE_PATH"
fi

if [[ -z "$CODEX_HOME_OVERRIDE" && -n "${CODEX_CONTAINER_HOME:-}" ]]; then
  CODEX_HOME_OVERRIDE="$CODEX_CONTAINER_HOME"
fi

if [[ -n "$CODEX_HOME_OVERRIDE" ]]; then
  CODEX_HOME_RAW="$CODEX_HOME_OVERRIDE"
else
  DEFAULT_HOME="${HOME:-}"
  if [[ -z "$DEFAULT_HOME" ]]; then
    DEFAULT_HOME=$(getent passwd "$(id -u 2>/dev/null)" 2>/dev/null | cut -d: -f6)
  fi
  if [[ -z "$DEFAULT_HOME" ]]; then
    echo "Error: unable to determine a user home directory for Codex state." >&2
    exit 1
  fi
  CODEX_HOME_RAW="${DEFAULT_HOME}/.codex-service"
fi

CODEX_HOME="$(resolve_absolute_path "$CODEX_HOME_RAW")"
if [[ -z "$CODEX_HOME" ]]; then
  echo "Error: failed to resolve Codex home path." >&2
  exit 1
fi

mkdir -p "$CODEX_HOME"

if [[ ! -f "${CODEX_ROOT}/Dockerfile" ]]; then
  echo "Error: Dockerfile not found in ${CODEX_ROOT}" >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Error: docker command not found" >&2
  exit 1
fi

mkdir -p "$CODEX_HOME"

JSON_OUTPUT=0
if [[ "$JSON_MODE" != "none" ]]; then
  JSON_OUTPUT=1
fi

if [[ "$JSON_MODE" == "none" ]]; then
  echo "Codex container context"
  echo "  Image:      ${TAG}"
  echo "  Codex home: ${CODEX_HOME}"
  echo "  Workspace:  ${WORKSPACE_PATH}"
fi

if [[ "$ACTION" != "install" ]]; then
  if ! docker image inspect "$TAG" >/dev/null 2>&1; then
    echo "Docker image '$TAG' not found locally. Run $(basename "$0") --install first." >&2
    exit 1
  fi
fi

show_recent_sessions() {
  local sessions_base="${CODEX_HOME}/.codex/sessions"
  if [[ ! -d "$sessions_base" ]]; then
    echo "No sessions found." >&2
    return
  fi

  echo "" >&2
  echo "Recent Sessions:" >&2
  echo "───────────────────────────────────────────────────────────────────" >&2
  echo "" >&2

  # Find all rollout-*.jsonl files sorted by modification time (newest first)
  local -a session_files=()
  while IFS= read -r -d '' file; do
    session_files+=("$file")
  done < <(find "$sessions_base" -type f -name 'rollout-*.jsonl' -print0 | xargs -0 ls -t 2>/dev/null)

  local count=0
  local max_sessions=5

  for session_file in "${session_files[@]}"; do
    if [[ $count -ge $max_sessions ]]; then
      break
    fi

    local basename
    basename=$(basename "$session_file")

    # Extract UUID from filename: rollout-<timestamp>-<uuid>.jsonl
    local uuid=""
    if [[ "$basename" =~ ([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}) ]]; then
      uuid="${BASH_REMATCH[1]}"
    fi

    if [[ -z "$uuid" ]]; then
      continue
    fi

    # Get short ID (last 5 chars)
    local short_id="${uuid: -5}"

    # Calculate age
    local mtime
    mtime=$(stat -c %Y "$session_file" 2>/dev/null || stat -f %m "$session_file" 2>/dev/null)
    local now
    now=$(date +%s)
    local age_seconds=$((now - mtime))
    local age_str=""

    if [[ $age_seconds -lt 60 ]]; then
      age_str="${age_seconds}s ago"
    elif [[ $age_seconds -lt 3600 ]]; then
      age_str="$((age_seconds / 60))m ago"
    elif [[ $age_seconds -lt 86400 ]]; then
      age_str="$((age_seconds / 3600))h ago"
    else
      age_str="$((age_seconds / 86400))d ago"
    fi

    # Extract first user message preview
    local preview=""
    if [[ -f "$session_file" ]]; then
      # Find first line with "role":"user" and extract text
      preview=$(grep -m 1 '"role":"user"' "$session_file" 2>/dev/null | \
                sed 's/.*"text":"\([^"]*\)".*/\1/' | \
                head -c 60)
      if [[ ${#preview} -eq 60 ]]; then
        preview="${preview}..."
      fi
    fi

    echo "  ${short_id}  (${age_str})" >&2
    if [[ -n "$preview" ]]; then
      echo "    → ${preview}" >&2
    fi
    echo "    ./codex_container.sh --session-id ${short_id}" >&2
    echo "" >&2

    count=$((count + 1))
  done

  if [[ $count -eq 0 ]]; then
    echo "No sessions found." >&2
  fi
  echo "" >&2
}

docker_run() {
  local quiet=0
  local expose_login_port=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --quiet)
        quiet=1
        shift
        ;;
      --expose-login-port)
        expose_login_port=1
        shift
        ;;
      *)
        break
        ;;
    esac
  done

  local -a args=(run --rm)
  if [[ $quiet -eq 1 ]]; then
    args+=(-i)
  else
    args+=(-it)
  fi
  if [[ $expose_login_port -eq 1 ]]; then
    args+=(-p 1455:1455)
  fi
  args+=(--user 0:0 --network codex-container_default --add-host host.docker.internal:host-gateway -v "${CODEX_HOME}:/opt/codex-home" -e HOME=/opt/codex-home -e XDG_CONFIG_HOME=/opt/codex-home)
  if [[ -n "$WORKSPACE_PATH" ]]; then
    local mount_source="${WORKSPACE_PATH//\\//}"
    if [[ "$mount_source" =~ ^[A-Za-z]:$ ]]; then
      mount_source+="/"
    fi
    args+=(-v "${mount_source}:/workspace" -w /workspace)
  fi
  args+=(-v "${CODEX_ROOT}/scripts:/opt/codex-support:ro")
  if [[ "$USE_OSS" == true ]]; then
    args+=(-e OLLAMA_HOST=http://host.docker.internal:11434 -e OSS_SERVER_URL=http://host.docker.internal:11434 -e ENABLE_OSS_BRIDGE=1)
  fi
  if [[ -n "$TRANSCRIPTION_SERVICE_URL" ]]; then
    args+=(-e TRANSCRIPTION_SERVICE_URL="$TRANSCRIPTION_SERVICE_URL")
  fi
  if [[ ${#DOCKER_RUN_EXTRA_ENVS[@]} -gt 0 ]]; then
    for env_kv in "${DOCKER_RUN_EXTRA_ENVS[@]}"; do
      args+=(-e "$env_kv")
    done
  fi
  if [[ ${#DOCKER_RUN_EXTRA_ARGS[@]} -gt 0 ]]; then
    args+=("${DOCKER_RUN_EXTRA_ARGS[@]}")
  fi
  args+=("${TAG}" /usr/local/bin/codex_entry.sh)
  args+=("$@")
  if [[ -n "${CODEX_CONTAINER_TRACE:-}" ]]; then
    printf 'docker'
    printf ' %q' "${args[@]}"
    printf '\n'
  fi
  docker "${args[@]}"
}


install_runner_on_path() {
  local dest_dir
  if [[ -n "${XDG_BIN_HOME:-}" ]]; then
    dest_dir="${XDG_BIN_HOME}"
  else
    dest_dir="${HOME}/.local/bin"
  fi

  if [[ -z "$dest_dir" ]]; then
    echo "Unable to resolve destination for runner install; skipping PATH helper." >&2
    return
  fi

  mkdir -p "$dest_dir"
  local dest="${dest_dir}/codex-container"

  cat >"$dest" <<EOF
#!/usr/bin/env bash
exec "${CODEX_ROOT}/scripts/codex_container.sh" "\$@"
EOF
  chmod 0755 "$dest"

  local on_path=0
  local path_entry
  IFS=':' read -r -a path_entries <<<"${PATH}"
  for path_entry in "${path_entries[@]}"; do
    if [[ "$path_entry" == "$dest_dir" ]]; then
      on_path=1
      break
    fi
  done

  if [[ $on_path -eq 0 ]]; then
    echo "Runner installed to ${dest}. Add ${dest_dir} to PATH to invoke 'codex-container'." >&2
  else
    echo "Runner installed to ${dest} and available on PATH." >&2
  fi
}



CODEX_UPDATE_DONE=0

ensure_codex_cli() {
  local force=${1:-0}
  local silent=${2:-0}
  if [[ "$SKIP_UPDATE" == true && "$force" -ne 1 ]]; then
    return
  fi
  if [[ $CODEX_UPDATE_DONE -eq 1 && "$force" -ne 1 ]]; then
    return
  fi
  local update_script
  update_script=$(cat <<'EOS'
set -euo pipefail
export PATH="$PATH:/usr/local/share/npm-global/bin"
echo "Ensuring Codex CLI is up to date..."
if npm install -g @openai/codex@latest --prefer-online >/tmp/codex-install.log 2>&1; then
  echo "Codex CLI updated."
else
  echo "Failed to install Codex CLI; see /tmp/codex-install.log."
  cat /tmp/codex-install.log
  exit 1
fi
cat /tmp/codex-install.log
EOS
)
  if [[ $silent -eq 1 ]]; then
    docker_run --quiet /bin/bash -lc "$update_script" >/dev/null
  else
    docker_run /bin/bash -lc "$update_script"
  fi
  CODEX_UPDATE_DONE=1
}

codex_authenticated() {
  local auth_path="${CODEX_HOME}/.codex/auth.json"
  if [[ -s "$auth_path" ]]; then
    return 0
  fi
  return 1
}

ensure_codex_auth() {
  local silent=${1:-0}
  if codex_authenticated; then
    return
  fi
  if [[ "$NO_AUTO_LOGIN" == true ]]; then
    echo "Codex credentials not found. Re-run with --login." >&2
    exit 1
  fi
  if [[ $silent -eq 1 ]]; then
    echo "Codex credentials not found. Re-run with --login." >&2
    exit 1
  fi
  echo "No Codex credentials detected; starting login flow..."
  invoke_codex_login
  if ! codex_authenticated; then
    echo "Codex login did not complete successfully." >&2
    exit 1
  fi
}

invoke_codex_login() {
  ensure_codex_cli 0 0
  local login_script_path="/opt/codex-support/codex_login.sh"
  if [[ ! -f "${CODEX_ROOT}/scripts/codex_login.sh" ]]; then
    echo "Error: login helper script missing at ${CODEX_ROOT}/scripts/codex_login.sh" >&2
    exit 1
  fi
  docker_run --expose-login-port /bin/bash "$login_script_path"
}

invoke_codex_run() {
  local silent=${1:-0}
  ensure_codex_cli 0 "$silent"
  local -a cmd=(codex)
  local -a args=()

  # Handle session ID resolution
  if [[ -n "$SESSION_ID" ]]; then
    local sessions_base="${CODEX_HOME}/.codex/sessions"
    if [[ ! -d "$sessions_base" ]]; then
      echo "Error: No sessions directory found at ${sessions_base}" >&2
      exit 1
    fi

    # Find all rollout-*.jsonl files
    local -a matching_sessions=()
    local -a all_uuids=()

    while IFS= read -r -d '' file; do
      local basename
      basename=$(basename "$file")

      # Extract UUID from filename
      if [[ "$basename" =~ ([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}) ]]; then
        local uuid="${BASH_REMATCH[1]}"
        all_uuids+=("$uuid")

        # Check if this UUID matches the session ID (full or partial)
        if [[ "$uuid" == "$SESSION_ID" ]] || [[ "$uuid" == *"$SESSION_ID" ]]; then
          matching_sessions+=("$uuid")
        fi
      fi
    done < <(find "$sessions_base" -type f -name 'rollout-*.jsonl' -print0)

    if [[ ${#matching_sessions[@]} -eq 0 ]]; then
      echo "Error: No session found matching '${SESSION_ID}'" >&2
      echo "" >&2
      echo "Available sessions:" >&2
      for uuid in "${all_uuids[@]:0:5}"; do
        local short="${uuid: -5}"
        echo "  ${short} (${uuid})" >&2
      done
      exit 1
    elif [[ ${#matching_sessions[@]} -gt 1 ]]; then
      echo "Error: Session ID '${SESSION_ID}' is ambiguous. Matches:" >&2
      for uuid in "${matching_sessions[@]}"; do
        local short="${uuid: -5}"
        echo "  ${short} (${uuid})" >&2
      done
      echo "" >&2
      echo "Please provide more characters to uniquely identify the session." >&2
      exit 1
    fi

    # Exactly one match - use it
    local resolved_uuid="${matching_sessions[0]}"
    args+=("resume" "$resolved_uuid")
  fi
  if [[ "$USE_OSS" == true ]]; then
    local has_oss=0
    local has_model=0
    for arg in "${CODEX_ARGS[@]}"; do
      if [[ "$arg" == "--oss" ]]; then
        has_oss=1
      fi
      case "$arg" in
        --model|--model=*) has_model=1 ;;
      esac
    done
    if [[ $has_oss -eq 0 ]]; then
      args+=("--oss")
    fi
    if [[ -n "$OSS_MODEL" && $has_model -eq 0 ]]; then
      args+=("--model" "$OSS_MODEL")
    fi
  fi
  if [[ ${#CODEX_ARGS[@]} -gt 0 ]]; then
    args+=("${CODEX_ARGS[@]}")
  fi
  if [[ ${#args[@]} -gt 0 ]]; then
    cmd+=("${args[@]}")
  fi
  if [[ $silent -eq 1 ]]; then
    docker_run --quiet "${cmd[@]}"
  else
    docker_run "${cmd[@]}"
  fi
}

invoke_codex_exec() {
  local silent=${1:-0}
  ensure_codex_cli 0 "$silent"
  if [[ ${#EXEC_ARGS[@]} -eq 0 ]]; then
    echo "Error: --exec requires arguments to forward to codex." >&2
    exit 1
  fi
  local -a exec_args
  if [[ "${EXEC_ARGS[0]:-}" == "exec" ]]; then
    exec_args=("${EXEC_ARGS[@]}")
  else
    exec_args=("exec" "${EXEC_ARGS[@]}")
  fi

  local -a injected=()
  local has_skip=0
  local has_json=0
  local has_json_exp=0
  local has_oss=0
  local has_server=0
  local has_model=0
  for arg in "${exec_args[@]}"; do
    if [[ "$arg" == "--skip-git-repo-check" ]]; then
      has_skip=1
    elif [[ "$arg" == "--json" ]]; then
      has_json=1
    elif [[ "$arg" == "--experimental-json" ]]; then
      has_json_exp=1
    elif [[ "$arg" == "--oss" ]]; then
      has_oss=1
    elif [[ "$arg" == *"oss_server_url"* ]]; then
      has_server=1
    elif [[ "$arg" == "--model" || "$arg" == --model=* ]]; then
      has_model=1
    fi
  done
  if [[ $has_skip -eq 0 ]]; then
    injected+=("--skip-git-repo-check")
  fi
  if [[ "$JSON_MODE" == "experimental" && $has_json_exp -eq 0 ]]; then
    injected+=("--experimental-json")
  elif [[ "$JSON_MODE" == "legacy" && $has_json -eq 0 ]]; then
    injected+=("--json")
  fi
  if [[ "$USE_OSS" == true && $has_oss -eq 0 ]]; then
    injected+=("--oss")
  fi
  if [[ "$USE_OSS" == true && $has_server -eq 0 ]]; then
    injected+=(-c "oss_server_url=http://host.docker.internal:11434")
  fi
  if [[ "$USE_OSS" == true && -n "$OSS_MODEL" && $has_model -eq 0 ]]; then
    injected+=("--model" "$OSS_MODEL")
  fi

  if [[ ${#injected[@]} -gt 0 ]]; then
    local -a new_exec_args
    new_exec_args+=("${exec_args[0]}")
    for item in "${injected[@]}"; do
      new_exec_args+=("$item")
    done
    if [[ ${#exec_args[@]} -gt 1 ]]; then
      for item in "${exec_args[@]:1}"; do
        new_exec_args+=("$item")
      done
    fi
    exec_args=("${new_exec_args[@]}")
  fi

  local -a cmd=(codex "${exec_args[@]}")
  if [[ $silent -eq 1 ]]; then
    docker_run --quiet "${cmd[@]}"
  else
    docker_run "${cmd[@]}"
  fi
}

invoke_codex_server() {
  ensure_codex_cli 0 0
  local port="${GATEWAY_PORT_OVERRIDE:-${CODEX_GATEWAY_PORT:-4000}}"
  local host="${GATEWAY_HOST_OVERRIDE:-${CODEX_GATEWAY_HOST:-127.0.0.1}}"

  if ! [[ "$port" =~ ^[0-9]+$ ]]; then
    echo "Error: gateway port '$port' is not numeric." >&2
    exit 1
  fi

  local -a prev_extra_args=("${DOCKER_RUN_EXTRA_ARGS[@]+"${DOCKER_RUN_EXTRA_ARGS[@]}"}")
  local -a prev_extra_envs=("${DOCKER_RUN_EXTRA_ENVS[@]+"${DOCKER_RUN_EXTRA_ENVS[@]}"}")

  DOCKER_RUN_EXTRA_ARGS=(-p "${host}:${port}:${port}")
  DOCKER_RUN_EXTRA_ENVS=("CODEX_GATEWAY_PORT=${port}" "CODEX_GATEWAY_BIND=0.0.0.0")
  if [[ -n "${CODEX_GATEWAY_TIMEOUT_MS:-}" ]]; then
    DOCKER_RUN_EXTRA_ENVS+=("CODEX_GATEWAY_TIMEOUT_MS=${CODEX_GATEWAY_TIMEOUT_MS}")
  fi
  if [[ -n "${CODEX_GATEWAY_DEFAULT_MODEL:-}" ]]; then
    DOCKER_RUN_EXTRA_ENVS+=("CODEX_GATEWAY_DEFAULT_MODEL=${CODEX_GATEWAY_DEFAULT_MODEL}")
  fi
  if [[ -n "${CODEX_GATEWAY_EXTRA_ARGS:-}" ]]; then
    DOCKER_RUN_EXTRA_ENVS+=("CODEX_GATEWAY_EXTRA_ARGS=${CODEX_GATEWAY_EXTRA_ARGS}")
  fi

  docker_run node /usr/local/bin/codex_gateway.js

  DOCKER_RUN_EXTRA_ARGS=("${prev_extra_args[@]+"${prev_extra_args[@]}"}")
  DOCKER_RUN_EXTRA_ENVS=("${prev_extra_envs[@]+"${prev_extra_envs[@]}"}")
}

invoke_codex_shell() {
  ensure_codex_cli
  docker_run /bin/bash
}

invoke_codex_watch() {
  ensure_codex_cli 0 0
  local watcher="${CODEX_ROOT}/scripts/watch_directory.py"
  local python_bin=""
  if command -v python3 >/dev/null 2>&1; then
    python_bin=$(command -v python3)
  elif command -v python >/dev/null 2>&1; then
    python_bin=$(command -v python)
  else
    echo "Error: python3 or python is required for --watch." >&2
    exit 1
  }
  if [[ ! -f "$watcher" ]]; then
    echo "Error: watcher script not found at $watcher" >&2
    exit 1
  }
  if [[ -z "$WATCH_PATH" ]]; then
    echo "Error: --watch requires --watch-path or a workspace" >&2
    exit 1
  fi
  local -a cmd=("$python_bin" "$watcher" --path "$WATCH_PATH" --codex-script "${SCRIPT_DIR}/codex_container.sh" --workspace "$WORKSPACE_PATH" --json-mode "$JSON_MODE")
  if [[ ${#WATCH_PATTERNS[@]} -gt 0 ]]; then
    for pattern in "${WATCH_PATTERNS[@]}"; do
      cmd+=(--pattern "$pattern")
    done
  fi
  if [[ -n "$WATCH_INTERVAL" ]]; then
    cmd+=(--interval "$WATCH_INTERVAL")
  fi
  if [[ -n "$WATCH_TEMPLATE" ]]; then
    cmd+=(--template "$WATCH_TEMPLATE")
  fi
  if [[ "$WATCH_INCLUDE_CONTENT" == true ]]; then
    cmd+=(--include-content)
  fi
  if [[ -n "$WATCH_CONTENT_BYTES" ]]; then
    cmd+=(--content-bytes "$WATCH_CONTENT_BYTES")
  fi
  if [[ -n "$WATCH_STATE_FILE" ]]; then
    cmd+=(--state-file "$WATCH_STATE_FILE")
  fi
  if [[ "$WATCH_ONCE" == true ]]; then
    cmd+=(--once)
  fi
  if [[ -n "$WATCH_DEBOUNCE" ]]; then
    cmd+=(--debounce "$WATCH_DEBOUNCE")
  fi
  if [[ ${#CODEX_ARGS[@]} -gt 0 ]]; then
    for arg in "${CODEX_ARGS[@]}"; do
      cmd+=(--codex-arg "$arg")
    done
  fi
  if [[ ${#EXEC_ARGS[@]} -gt 0 ]]; then
    for arg in "${EXEC_ARGS[@]}"; do
      cmd+=(--exec-arg "$arg")
    done
  fi
  exec "${cmd[@]}"
}

invoke_codex_monitor() {
  ensure_codex_cli 0 0
  local monitor_dir="${WATCH_PATH}"
  if [[ -z "$monitor_dir" ]]; then
    echo "Error: --monitor requires --watch-path or a workspace." >&2
    exit 1
  fi
  local prompt_path="${monitor_dir}/${MONITOR_PROMPT_FILE}"
  if [[ ! -f "$prompt_path" ]]; then
    echo "Error: Monitor prompt file '$prompt_path' not found." >&2
    exit 1
  fi
  echo "Monitoring ${monitor_dir} using prompt ${prompt_path}" >&2

  declare -A seen_map=()

  while true; do
    if [[ ! -f "$prompt_path" ]]; then
      echo "Prompt file $prompt_path missing; waiting..." >&2
      sleep 5
      continue
    fi
    local prompt
    prompt=$(cat "$prompt_path" 2>/dev/null)
    if [[ -z "$prompt" ]]; then
      sleep 5
      continue
    fi

    while IFS= read -r -d '' file; do
      local key="$file"
      local stamp
      stamp=$(stat -c %Y "$file" 2>/dev/null)
      local prev="${seen_map[$key]:-}"
      if [[ -n "$prev" && "$prev" -eq "$stamp" ]]; then
        continue
      fi
      echo "[monitor] Change detected: $file" >&2
      seen_map[$key]=$stamp
      local -a cmd=("${SCRIPT_DIR}/codex_container.sh" --exec --workspace "$WORKSPACE_PATH")
      if [[ "$JSON_MODE" == "legacy" ]]; then
        cmd+=(--json)
      elif [[ "$JSON_MODE" == "experimental" ]]; then
        cmd+=(--json-e)
      fi
      if [[ ${#CODEX_ARGS[@]} -gt 0 ]]; then
        for arg in "${CODEX_ARGS[@]}"; do
          cmd+=(--codex-arg "$arg")
        done
      fi
      if [[ ${#EXEC_ARGS[@]} -gt 0 ]]; then
        for arg in "${EXEC_ARGS[@]}"; do
          cmd+=(--exec-arg "$arg")
        done
      fi
      cmd+=(--)
      cmd+=("$prompt" "File: $file")
      "${cmd[@]}"
    done < <(find "$monitor_dir" -maxdepth 1 -type f -print0)

    sleep 5
  done
}

docker_build_image() {
  echo "Checking Docker daemon..." >&2
  if ! docker info --format '{{.ID}}' >/dev/null 2>&1; then
    echo "Docker daemon not reachable. Start Docker Desktop and retry." >&2
    exit 1
  fi
  echo "Building Codex service image" >&2
  echo "  Dockerfile: ${CODEX_ROOT}/Dockerfile" >&2
  echo "  Tag:        ${TAG}" >&2
  local log_dir="${CODEX_HOME}/logs"
  mkdir -p "$log_dir"
  local timestamp
  timestamp="$(date +%Y%m%d-%H%M%S)"
  local build_log="${log_dir}/build-${timestamp}.log"
  echo "  Log file:   ${build_log}" >&2
  local -a build_args=(-f "${CODEX_ROOT}/Dockerfile" -t "${TAG}" "${CODEX_ROOT}")
  if [[ "$NO_CACHE" == true ]]; then
    build_args=(--no-cache "${build_args[@]}")
  fi
  if ! {
    echo "[build] docker build ${build_args[*]}"
    docker build "${build_args[@]}"
  } 2>&1 | tee "$build_log"; then
    local build_status=${PIPESTATUS[0]}
    echo "Build failed. See ${build_log} for details." >&2
    exit $build_status
  fi
  if [[ "$PUSH_IMAGE" == true ]]; then
    echo "Pushing image ${TAG}" >&2
    if ! {
      echo "[build] docker push ${TAG}"
      docker push "${TAG}"
    } 2>&1 | tee -a "$build_log"; then
      local push_status=${PIPESTATUS[0]}
      echo "Push failed. See ${build_log} for details." >&2
      exit $push_status
    fi
  fi
  echo "Build complete." >&2
  echo "Build log saved to ${build_log}" >&2
}

case "$ACTION" in
  install)
    docker_build_image
    ensure_codex_cli 1
    install_runner_on_path
    ;;
  login)
    invoke_codex_login
    ;;
  shell)
    ensure_codex_cli
    invoke_codex_shell
    ;;
  exec)
    ensure_codex_auth "$JSON_OUTPUT"
    invoke_codex_exec "$JSON_OUTPUT"
    ;;
  serve)
    ensure_codex_auth 0
    invoke_codex_server
    ;;
  watch)
    ensure_codex_auth "$JSON_OUTPUT"
    invoke_codex_watch
    ;;
  monitor)
    ensure_codex_auth "$JSON_OUTPUT"
    invoke_codex_monitor
    ;;
  list-sessions)
    show_recent_sessions
    ;;
  run|*)
    # Show recent sessions if no arguments and no session ID
    if [[ ${#CODEX_ARGS[@]} -eq 0 && -z "$SESSION_ID" ]]; then
      show_recent_sessions
    fi
    ensure_codex_auth "$JSON_OUTPUT"
    invoke_codex_run "$JSON_OUTPUT"
    ;;
esac
