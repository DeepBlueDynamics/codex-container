#!/usr/bin/env bash
set -euo pipefail

install_mcp_servers_runtime() {
  local mcp_source="/opt/mcp-installed"
  local mcp_dest="/opt/codex-home/mcp"
  local mcp_python="/opt/mcp-venv/bin/python3"
  local mcp_requirements="/opt/mcp-requirements/requirements.txt"
  local config_dir="/opt/codex-home/.codex"
  local config_path="${config_dir}/config.toml"
  local helper_script="/opt/update_mcp_config.py"
  local manifest_src="${mcp_source}/.manifest"
  local installed_marker="${mcp_dest}/.installed"
  local manifest_dest="${mcp_dest}/.manifest"

  # Ensure we have MCP servers prepared during image build
  if [[ ! -d "$mcp_source" || ! -f "$manifest_src" ]]; then
    return 0
  fi

  local new_manifest
  new_manifest=$(cat "$manifest_src" 2>/dev/null)
  if [[ -z "$new_manifest" ]]; then
    echo "[codex_entry] No MCP servers found in manifest" >&2
    return 0
  fi

  local current_manifest=""
  if [[ -f "$installed_marker" ]]; then
    current_manifest=$(cat "$installed_marker" 2>/dev/null)
  elif [[ -f "$manifest_dest" ]]; then
    current_manifest=$(cat "$manifest_dest" 2>/dev/null)
  fi

  # Always update MCP servers to ensure latest code is deployed
  # This ensures edits to existing MCP files are picked up
  if [[ -n "$current_manifest" ]]; then
    echo "[codex_entry] Updating MCP servers..." >&2
  else
    echo "[codex_entry] Installing MCP servers..." >&2
  fi

  mkdir -p "$mcp_dest"
  mkdir -p "$config_dir"

  if [[ -f "$mcp_requirements" ]]; then
    echo "[codex_entry] Ensuring MCP Python dependencies are installed..." >&2
    if ! "$mcp_python" -m pip install --no-cache-dir -r "$mcp_requirements" >/dev/null 2>&1; then
      echo "[codex_entry] Warning: MCP dependency installation failed" >&2
    fi
  fi

  # Remove previously installed servers that we manage
  if [[ -n "$current_manifest" ]]; then
    for server_file in $current_manifest; do
      rm -f "${mcp_dest}/${server_file}" 2>/dev/null || true
    done
  fi

  cp -r "${mcp_source}"/*.py "$mcp_dest/" 2>/dev/null || true
  cp "$manifest_src" "$manifest_dest" 2>/dev/null || true

  # Copy MCP data directories if they exist (e.g., product_search_data)
  if [[ -d "/opt/mcp-data" ]]; then
    echo "[codex_entry] Copying MCP data directories..." >&2
    cp -r /opt/mcp-data/* "$mcp_dest/" 2>/dev/null || true
  fi

  if [[ -f "$helper_script" ]]; then
    # Split manifest into array while respecting word boundaries
    # shellcheck disable=SC2206
    local servers=( $new_manifest )
    if [[ ${#servers[@]} -gt 0 ]]; then
      "$mcp_python" "$helper_script" "$config_path" "$mcp_python" "${servers[@]}" || true
      echo "[codex_entry] Installed MCP servers: $new_manifest" >&2
    fi
  fi

  printf '%s\n' "$new_manifest" > "$installed_marker"
}

start_oss_bridge() {
  local target="${OSS_SERVER_URL:-${OLLAMA_HOST:-}}"
  if [[ -z "$target" ]]; then
    target="http://host.docker.internal:11434"
  fi

  if [[ "$target" =~ ^http://([^:/]+)(:([0-9]+))?/?$ ]]; then
    local host="${BASH_REMATCH[1]}"
    local port="${BASH_REMATCH[3]:-80}"
  else
    echo "[codex_entry] Unrecognized OSS target '$target'; skipping bridge" >&2
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

# Install MCP servers on first run
install_mcp_servers_runtime

if [[ "${ENABLE_OSS_BRIDGE:-}" == "1" ]]; then
  start_oss_bridge
fi

ensure_codex_api_key
ensure_baml_workspace

# Log environment variable status for debugging
if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
  echo "[codex_entry] ANTHROPIC_API_KEY is set (${#ANTHROPIC_API_KEY} chars)" >&2
else
  echo "[codex_entry] ANTHROPIC_API_KEY is NOT set" >&2
fi

# Note: Transcription daemon is now a separate persistent service container
# Started via scripts/start_transcription_service.ps1
# This keeps Whisper model loaded and avoids reloading on every Codex run

exec "$@"
