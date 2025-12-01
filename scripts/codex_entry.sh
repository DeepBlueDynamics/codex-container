#!/usr/bin/env bash
set -euo pipefail

load_session_env() {
  local sessions_root="/opt/codex-home/sessions"
  local candidates=()

  if [[ -n "${CODEX_SESSION_ID:-}" ]]; then
    candidates+=("${sessions_root}/${CODEX_SESSION_ID}/.env")
  fi

  local candidate
  for candidate in "${candidates[@]}"; do
    if [[ -f "$candidate" ]]; then
      echo "[codex_entry] Loading session env from ${candidate}" >&2
      set -o allexport
      # shellcheck disable=SC1090
      source "$candidate"
      set +o allexport
      return
    fi
  done
}

load_session_env

install_mcp_servers_runtime() {
  local mcp_source="/opt/mcp-installed"
  local mcp_dest="/opt/codex-home/mcp"
  local mcp_python="/opt/mcp-venv/bin/python3"
  local mcp_requirements="/opt/mcp-requirements/requirements.txt"
  local config_dir="/opt/codex-home/.codex"
  local config_path="${config_dir}/config.toml"
  local helper_script="/opt/update_mcp_config.py"
  local installed_marker="${mcp_dest}/.installed"

  local workspace_config="/workspace/.codex-mcp.config"
  local default_config="${mcp_source}/.codex-mcp.config"
  local active_config=""
  local using_default=false

  # Ensure we have MCP servers prepared during image build
  if [[ ! -d "$mcp_source" ]]; then
    echo "[codex_entry] MCP source directory not found; skipping MCP install" >&2
    return 0
  fi

  # Determine which config to use
  if [[ -f "$workspace_config" ]]; then
    active_config="$workspace_config"
    echo "[codex_entry] Using workspace-specific MCP config: ${workspace_config}" >&2
  elif [[ -f "$default_config" ]]; then
    active_config="$default_config"
    using_default=true
    echo "[codex_entry] Using default MCP config from image" >&2
  else
    echo "[codex_entry] No MCP config found; skipping MCP install" >&2
    return 0
  fi

  # Read the config file into an array (one tool per line)
  # Strip carriage returns to handle Windows line endings
  local tools=()
  while IFS= read -r line; do
    # Strip carriage returns and whitespace
    line="$(echo "$line" | tr -d '\r' | xargs)"
    # Skip empty lines and comments
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    tools+=("$line")
  done < "$active_config"

  if [[ ${#tools[@]} -eq 0 ]]; then
    echo "[codex_entry] No MCP tools listed in config; skipping MCP install" >&2
    return 0
  fi

  # If using default config, show helpful message
  if [[ "$using_default" == true ]]; then
    echo "[codex_entry] To customize MCP tools for this workspace, create /workspace/.codex-mcp.config with:" >&2
    for tool in "${tools[@]}"; do
      echo "[codex_entry]   ${tool}" >&2
    done
  fi

  # Get previously installed tools
  local current_tools=""
  if [[ -f "$installed_marker" ]]; then
    current_tools=$(cat "$installed_marker" 2>/dev/null)
  fi

  # Always update MCP servers to ensure latest code is deployed
  if [[ -n "$current_tools" ]]; then
    echo "[codex_entry] Updating MCP servers..." >&2
  else
    echo "[codex_entry] Installing MCP servers..." >&2
  fi

  mkdir -p "$mcp_dest"
  mkdir -p "$config_dir"

  # Install Python dependencies
  if [[ -f "$mcp_requirements" ]]; then
    echo "[codex_entry] Ensuring MCP Python dependencies are installed..." >&2
    if ! "$mcp_python" -m pip install --no-cache-dir -r "$mcp_requirements" >/dev/null 2>&1; then
      echo "[codex_entry] Warning: MCP dependency installation failed" >&2
    fi
  fi

  # Remove previously installed servers
  if [[ -n "$current_tools" ]]; then
    for server_file in $current_tools; do
      rm -f "${mcp_dest}/${server_file}" 2>/dev/null || true
    done
  fi

  # Copy only the tools listed in the config
  local copied_tools=()
  for tool in "${tools[@]}"; do
    local src_file="${mcp_source}/${tool}"
    if [[ -f "$src_file" ]]; then
      cp "$src_file" "${mcp_dest}/${tool}" 2>/dev/null || {
        echo "[codex_entry] Warning: Failed to copy ${tool}" >&2
        continue
      }
      copied_tools+=("$tool")
      echo "[codex_entry] Installed ${tool}" >&2
    else
      echo "[codex_entry] Warning: Tool ${tool} not found in ${mcp_source}" >&2
    fi
  done

  # Copy MCP data directories if they exist (e.g., product_search_data)
  if [[ -d "/opt/mcp-data" ]]; then
    echo "[codex_entry] Copying MCP data directories..." >&2
    cp -r /opt/mcp-data/* "$mcp_dest/" 2>/dev/null || true
  fi

  # Register tools in Codex config
  if [[ -f "$helper_script" && ${#copied_tools[@]} -gt 0 ]]; then
    "$mcp_python" "$helper_script" "$config_path" "$mcp_python" "${copied_tools[@]}" || true
    echo "[codex_entry] Registered ${#copied_tools[@]} MCP tool(s)" >&2
  fi

  # Save the list of installed tools
  printf '%s\n' "${copied_tools[*]}" > "$installed_marker"
}

start_oss_bridge() {
  if [[ "${OSS_DISABLE_BRIDGE:-}" == "1" ]]; then
    echo "[codex_entry] OSS bridge explicitly disabled" >&2
    return
  fi

  local target="${OSS_SERVER_URL:-${OLLAMA_HOST:-}}"
  if [[ -z "$target" ]]; then
    target="http://host.docker.internal:11434"
  fi

  if [[ "$target" =~ ^http://([^:/]+)(:([0-9]+))?/?$ ]]; then
    local host="${BASH_REMATCH[1]}"
    local port="${BASH_REMATCH[3]:-80}"
  else
    echo "[codex_entry] OSS target '$target' is not a plain http:// host; skipping bridge" >&2
    return
  fi

  if [[ -z "$port" || "$port" == "80" ]]; then
    port=11434
  fi

  echo "[codex_entry] Bridging 127.0.0.1:${port} -> ${host}:${port}" >&2
  socat TCP-LISTEN:${port},fork,reuseaddr,bind=127.0.0.1 TCP:${host}:${port} &
  BRIDGE_PID=$!
  cleanup() {
    if [[ -n "${BRIDGE_PID:-}" ]]; then
      kill "$BRIDGE_PID" 2>/dev/null || true
    fi
  }
  trap cleanup EXIT
}

ensure_codex_api_key() {
  # Prefer explicit Codex variable if already exported.
  if [[ -n "${CODEX_API_KEY:-}" ]]; then
    return
  fi

  # Fall back to the standard OpenAI variable names.
  if [[ -n "${OPENAI_API_KEY:-}" ]]; then
    export CODEX_API_KEY="${OPENAI_API_KEY}"
    return
  fi

  # Support legacy env files that expose lowercase or alternative names.
  if [[ -n "${OPENAI_TOKEN:-}" ]]; then
    export CODEX_API_KEY="${OPENAI_TOKEN}"
    return
  fi

  if [[ -n "${openai_token:-}" ]]; then
    export CODEX_API_KEY="${openai_token}"
    return
  fi
}

ensure_baml_workspace() {
  local workspace="${BAML_WORKSPACE:-/opt/baml-workspace}"
  if [[ -z "${workspace}" ]]; then
    return
  fi

  # Ensure the workspace exists so BAML projects can be mounted or generated.
  mkdir -p "${workspace}"
}

mount_pi_share() {
  # Optionally mount a Raspberry Pi NFS export into the container.
  # Controlled via environment variables:
  #   PI_NFS_DISABLE=1         -> skip mounting
  #   PI_NFS_SERVER            -> default 192.168.86.37
  #   PI_NFS_EXPORT            -> default /srv/share
  #   PI_NFS_MOUNTPOINT        -> default /workspace/pi-share

  if [[ "${PI_NFS_DISABLE:-0}" == "1" ]]; then
    return
  fi

  local server="${PI_NFS_SERVER:-192.168.86.37}"
  local export_path="${PI_NFS_EXPORT:-/srv/share}"
  local mountpoint="${PI_NFS_MOUNTPOINT:-/workspace/pi-share}"

  mkdir -p "${mountpoint}"

  if command -v mountpoint >/dev/null 2>&1; then
    if mountpoint -q "${mountpoint}"; then
      echo "[codex_entry] Pi NFS share already mounted at ${mountpoint}" >&2
      return
    fi
  fi

  if ! command -v mount >/dev/null 2>&1; then
    echo "[codex_entry] mount command not available; skipping Pi NFS mount" >&2
    return
  fi

  # Best-effort mount; failure should not stop Codex from starting.
  if mount -t nfs "${server}:${export_path}" "${mountpoint}" >/dev/null 2>&1; then
    echo "[codex_entry] Mounted Pi NFS share ${server}:${export_path} at ${mountpoint}" >&2
  else
    echo "[codex_entry] Failed to mount Pi NFS share ${server}:${export_path}; continuing without it" >&2
  fi
}

ensure_marketbot_env() {
  # Ensure .marketbot.env is accessible in the workspace for MCP servers.
  # Checks multiple locations and copies to /workspace/.marketbot.env if found.
  
  local workspace_env="/workspace/.marketbot.env"
  local candidates=(
    "/workspace/.marketbot.env"
    "/opt/codex-home/.marketbot.env"
    "${HOME}/.marketbot.env"
    "/opt/codex-home/sessions/.env"
  )
  
  # If workspace env already exists, use it
  if [[ -f "$workspace_env" ]]; then
    echo "[codex_entry] Found .marketbot.env at ${workspace_env}" >&2
    load_marketbot_env "$workspace_env"
    return 0
  fi
  
  # Check session-specific env if CODEX_SESSION_ID is set
  local session_id="${CODEX_SESSION_ID:-}"
  if [[ -n "$session_id" ]]; then
    local session_env="/opt/codex-home/sessions/${session_id}/.env"
    if [[ -f "$session_env" ]] && grep -q "MARKETBOT" "$session_env" 2>/dev/null; then
      echo "[codex_entry] Found MarketBot config in session env: ${session_env}" >&2
      # Extract MarketBot vars and write to workspace
      grep "^MARKETBOT" "$session_env" > "$workspace_env" 2>/dev/null && {
        echo "[codex_entry] Copied MarketBot vars to ${workspace_env}" >&2
        load_marketbot_env "$workspace_env"
        return 0
      }
    fi
  fi
  
  # Try to find and copy from candidate locations
  for candidate in "${candidates[@]}"; do
    if [[ -f "$candidate" ]] && grep -q "MARKETBOT" "$candidate" 2>/dev/null; then
      cp "$candidate" "$workspace_env" 2>/dev/null && {
        echo "[codex_entry] Copied .marketbot.env from ${candidate} to ${workspace_env}" >&2
        load_marketbot_env "$workspace_env"
        return 0
      }
    fi
  done
  
  # If MARKETBOT env vars are set in process environment, write them to file
  if [[ -n "${MARKETBOT_API_KEY:-}" ]] || [[ -n "${MARKETBOT_TEAM_ID:-}" ]]; then
    {
      [[ -n "${MARKETBOT_API_KEY:-}" ]] && echo "MARKETBOT_API_KEY=${MARKETBOT_API_KEY}"
      [[ -n "${MARKETBOT_TEAM_ID:-}" ]] && echo "MARKETBOT_TEAM_ID=${MARKETBOT_TEAM_ID}"
      [[ -n "${MARKETBOT_API_URL:-}" ]] && echo "MARKETBOT_API_URL=${MARKETBOT_API_URL}"
    } > "$workspace_env" 2>/dev/null && {
      echo "[codex_entry] Created ${workspace_env} from environment variables" >&2
      load_marketbot_env "$workspace_env"
      return 0
    }
  fi
  
  echo "[codex_entry] Warning: .marketbot.env not found; MarketBot tools may not work" >&2
  return 1
}

load_marketbot_env() {
  # Load MarketBot environment variables from a file into the current shell.
  # This exports the variables so they're available to child processes.
  
  local env_file="${1:-/workspace/.marketbot.env}"
  
  if [[ ! -f "$env_file" ]]; then
    echo "[codex_entry] Warning: MarketBot env file not found: ${env_file}" >&2
    return 1
  fi
  
  echo "[codex_entry] Loading MarketBot environment variables from ${env_file}" >&2
  
  # Read the file line by line and export variables
  while IFS= read -r line || [[ -n "$line" ]]; do
    # Skip empty lines and comments
    line="${line%%#*}"  # Remove comments
    line="${line#"${line%%[![:space:]]*}"}"  # Trim leading whitespace
    line="${line%"${line##*[![:space:]]}"}"  # Trim trailing whitespace
    
    if [[ -z "$line" ]]; then
      continue
    fi
    
    # Only process MARKETBOT_* variables
    if [[ "$line" =~ ^MARKETBOT_ ]]; then
      # Split on first = sign
      if [[ "$line" =~ ^([^=]+)=(.*)$ ]]; then
        local key="${BASH_REMATCH[1]}"
        local value="${BASH_REMATCH[2]}"
        
        # Remove quotes if present
        value="${value#\"}"
        value="${value%\"}"
        value="${value#\'}"
        value="${value%\'}"
        
        # Export the variable - use printf to safely construct the export command
        # This avoids issues with special characters in the value
        printf -v export_cmd "export %s=%q" "$key" "$value"
        eval "$export_cmd"
        echo "[codex_entry] Loaded ${key} from ${env_file}" >&2
      fi
    fi
  done < "$env_file"
  
  return 0
}

# Install MCP servers on first run (skippable for maintenance/update calls)
mount_pi_share
ensure_marketbot_env
if [[ "${CODEX_SKIP_MCP_SETUP:-0}" != "1" ]]; then
  install_mcp_servers_runtime
else
  echo "[codex_entry] Skipping MCP setup (CODEX_SKIP_MCP_SETUP=1)" >&2
fi

if [[ "${ENABLE_OSS_BRIDGE:-}" == "1" ]]; then
  start_oss_bridge
fi

ensure_codex_api_key
ensure_baml_workspace

# Log environment variable status for debugging
if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
  echo "[codex_entry] ANTHROPIC_API_KEY is set (${#ANTHROPIC_API_KEY} chars)" >&2
else
  echo "[codex_entry] ANTHROPIC_API_KEY is NOT set (Claude-specific MCP tools will be skipped)" >&2
fi

# Log MarketBot environment variable status
if [[ -n "${MARKETBOT_API_KEY:-}" ]]; then
  echo "[codex_entry] MARKETBOT_API_KEY is set (${#MARKETBOT_API_KEY} chars)" >&2
else
  echo "[codex_entry] MARKETBOT_API_KEY is NOT set in environment" >&2
fi
if [[ -n "${MARKETBOT_TEAM_ID:-}" ]]; then
  echo "[codex_entry] MARKETBOT_TEAM_ID is set" >&2
else
  echo "[codex_entry] MARKETBOT_TEAM_ID is NOT set in environment" >&2
fi
if [[ -f "/workspace/.marketbot.env" ]]; then
  echo "[codex_entry] Found /workspace/.marketbot.env" >&2
fi

# Note: Transcription daemon is now a separate persistent service container
# Started via scripts/start_transcription_service.ps1
# This keeps Whisper model loaded and avoids reloading on every Codex run

# Handle --dangerously-bypass-approvals-and-sandbox flag
if [[ "$1" == "--dangerously-bypass-approvals-and-sandbox" ]]; then
  export CODEX_UNSAFE_ALLOW_NO_SANDBOX=1
  shift
fi

# Allow the Docker CLI to pass "--" as a separator without providing a command.
if [[ "$#" -eq 0 ]]; then
  set -- /bin/bash
elif [[ "$1" == "--" ]]; then
  shift
  if [[ "$#" -eq 0 ]]; then
    set -- /bin/bash
  fi
fi

exec "$@"
