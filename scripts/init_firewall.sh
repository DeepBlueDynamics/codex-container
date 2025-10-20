#!/usr/bin/env bash
set -euo pipefail

PORT="${1:-1455}"

log() {
  echo "[init_firewall] $*" >&2
}

ensure_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    log "This script must run as root (needs iptables access)."
    exit 1
  fi
}

find_gateway() {
  if [[ -n "${DOCKER_HOST_GATEWAY:-}" ]]; then
    echo "${DOCKER_HOST_GATEWAY}"
    return 0
  fi

  if command -v getent >/dev/null 2>&1; then
    local host_ip
    host_ip="$(getent hosts host.docker.internal 2>/dev/null | awk 'NR==1 {print $1}')"
    if [[ -n "${host_ip}" ]]; then
      echo "${host_ip}"
      return 0
    fi
  fi

  if command -v ip >/dev/null 2>&1; then
    local route_ip
    route_ip="$(ip -4 route show default 2>/dev/null | awk 'NR==1 {print $3}')"
    if [[ -n "${route_ip}" ]]; then
      echo "${route_ip}"
      return 0
    fi
  fi

  return 1
}

ensure_root

if ! command -v iptables >/dev/null 2>&1; then
  log "iptables not found; cannot configure forwarding."
  exit 1
fi

GATEWAY="$(find_gateway || true)"
if [[ -z "${GATEWAY}" ]]; then
  log "Could not determine host gateway IP."
  exit 1
fi

RULE=("-t" "nat" "-C" "OUTPUT" "-p" "tcp" "-d" "127.0.0.1" "--dport" "${PORT}" "-j" "DNAT" "--to-destination" "${GATEWAY}:${PORT}")
if iptables "${RULE[@]}" >/dev/null 2>&1; then
  log "Forwarding rule already present for 127.0.0.1:${PORT} -> ${GATEWAY}:${PORT}."
  exit 0
fi

ADD_RULE=("-t" "nat" "-A" "OUTPUT" "-p" "tcp" "-d" "127.0.0.1" "--dport" "${PORT}" "-j" "DNAT" "--to-destination" "${GATEWAY}:${PORT}")
iptables "${ADD_RULE[@]}"
log "Configured forwarding 127.0.0.1:${PORT} -> ${GATEWAY}:${PORT}."
