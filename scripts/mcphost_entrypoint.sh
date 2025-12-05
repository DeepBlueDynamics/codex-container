#!/usr/bin/env bash
set -euo pipefail

CONFIG="${MCPHOST_CONFIG:-/mcphost/config.yml}"

if [[ ! -f "$CONFIG" ]]; then
  echo "mcphost entrypoint: no config found at $CONFIG"
  echo "Mount a config file or set MCPHOST_CONFIG to a path."
  exit 1
fi

exec "$@" --config "$CONFIG"
