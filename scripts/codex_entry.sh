#!/usr/bin/env bash
set -euo pipefail

install_mcp_servers_runtime() {
  local mcp_source="/opt/mcp-installed"
  local mcp_dest="/opt/codex-home/mcp"
  local mcp_python="/opt/mcp-venv/bin/python3"
  local config_dir="/opt/codex-home/.codex"
  local config_path="${config_dir}/config.toml"
  local helper_script="/opt/update_mcp_config.py"

  # Check if MCP servers are already installed
  if [[ -f "${mcp_dest}/.installed" ]]; then
    return 0
  fi

  # Check if we have MCP servers to install
  if [[ ! -d "$mcp_source" || ! -f "${mcp_source}/.manifest" ]]; then
    return 0
  fi

  echo "[codex_entry] Installing MCP servers..." >&2

  # Create destination directory
  mkdir -p "$mcp_dest"
  mkdir -p "$config_dir"

  # Copy MCP server files
  cp -r "${mcp_source}"/*.py "$mcp_dest/" 2>/dev/null || true

  # Read manifest to get list of server names
  local manifest
  manifest=$(cat "${mcp_source}/.manifest")

  if [[ -z "$manifest" ]]; then
    echo "[codex_entry] No MCP servers found in manifest" >&2
    return 0
  fi

  # Update config with MCP servers
  if [[ -f "$helper_script" ]]; then
    # shellcheck disable=SC2086
    "$mcp_python" "$helper_script" "$config_path" "$mcp_python" $manifest || true
    echo "[codex_entry] Installed MCP servers: $manifest" >&2
  fi

  # Mark as installed
  touch "${mcp_dest}/.installed"
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

# Install MCP servers on first run
install_mcp_servers_runtime

if [[ "${ENABLE_OSS_BRIDGE:-}" == "1" ]]; then
  start_oss_bridge
fi

ensure_codex_api_key

exec "$@"
