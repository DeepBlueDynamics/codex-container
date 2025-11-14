#!/bin/bash
set -euo pipefail

# This script runs inside the container during build to prepare MCP servers
# It copies MCP Python files from /opt/mcp-source to /opt/mcp-installed
# These files will be selectively copied to /opt/codex-home/mcp at runtime based on .codex-mcp.config

MCP_SOURCE="/opt/mcp-source"
MCP_DEST="/opt/mcp-installed"
MCP_CONFIG="${MCP_SOURCE}/.codex-mcp.config"

log() {
  echo "[install_mcp] $*" >&2
}

if [[ ! -d "$MCP_SOURCE" ]]; then
  log "MCP source directory not found at ${MCP_SOURCE}; skipping MCP install."
  exit 0
fi

# Use POSIX globbing for macOS compatibility
shopt -s nullglob 2>/dev/null || true
FILES=("${MCP_SOURCE}"/*.py)
shopt -u nullglob 2>/dev/null || true

if [[ ${#FILES[@]} -eq 0 ]]; then
  log "No MCP server scripts found under ${MCP_SOURCE}; skipping MCP install."
  exit 0
fi

# Filter to ensure they're actual files
FILTERED=()
for src_path in "${FILES[@]}"; do
  if [[ -f "$src_path" ]]; then
    FILTERED+=("$src_path")
  fi
done

if [[ ${#FILTERED[@]} -eq 0 ]]; then
  log "No valid MCP server scripts after filtering; skipping MCP install."
  exit 0
fi

# Sort the files
IFS=$'\n'
SORTED=($(printf '%s\n' "${FILTERED[@]}" | sort))
IFS=$' \t\n'

log "Found ${#SORTED[@]} MCP server script(s):"
for src in "${SORTED[@]}"; do
  log "  - ${src}"
done

# Create destination directory
mkdir -p "$MCP_DEST"

# Copy all MCP files
COPIED=0
for src in "${SORTED[@]}"; do
  base="$(basename "$src")"
  log "Copying ${base} to ${MCP_DEST}"
  cp "$src" "${MCP_DEST}/${base}" || {
    log "Error: Failed to copy ${base}"
    exit 1
  }
  chmod 0644 "${MCP_DEST}/${base}" || {
    log "Error: Failed to chmod ${base}"
    exit 1
  }
  COPIED=$((COPIED + 1))
  log "Successfully copied ${base}"
done

# Copy .codex-mcp.config if it exists (defines which tools to activate)
if [[ -f "$MCP_CONFIG" ]]; then
  log "Copying .codex-mcp.config to ${MCP_DEST}"
  cp "$MCP_CONFIG" "${MCP_DEST}/.codex-mcp.config" || {
    log "Error: Failed to copy .codex-mcp.config"
    exit 1
  }
  chmod 0644 "${MCP_DEST}/.codex-mcp.config"
else
  log "Warning: No .codex-mcp.config found in ${MCP_SOURCE}"
  log "All MCP servers will be available but none will be activated by default"
fi

log "Successfully prepared ${COPIED} MCP server(s) in ${MCP_DEST}"
log "Tools will be selectively installed based on .codex-mcp.config at container startup"
