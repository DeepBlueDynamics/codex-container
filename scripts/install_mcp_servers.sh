#!/bin/bash
set -euo pipefail

# This script runs inside the container during build to prepare MCP servers
# It copies MCP Python files from /opt/mcp-source to /opt/mcp-installed
# These files will be copied to /opt/codex-home/mcp at runtime by the entrypoint.

MCP_SOURCE="/opt/mcp-source"
MCP_DEST="/opt/mcp-installed"
MCP_PYTHON="/opt/mcp-venv/bin/python3"

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

# Copy files and collect basenames
BASENAMES=()
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
  BASENAMES+=("$base")
  COPIED=$((COPIED + 1))
  log "Successfully copied ${base}"
done

# Create a manifest file with the list of MCP servers
echo "${BASENAMES[*]}" > "${MCP_DEST}/.manifest"

log "Successfully prepared ${COPIED} MCP server(s) in ${MCP_DEST}"
log "These will be installed to /opt/codex-home/mcp at container startup"
