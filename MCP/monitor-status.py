#!/usr/bin/env python3
"""MCP: monitor-status

Check the status of the file monitor queue and processing state.
"""

from __future__ import annotations

import sys
import json
import os
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("monitor-status")


DEFAULT_STATUS_URL = os.environ.get("CODEX_GATEWAY_STATUS_URL", "")
DEFAULT_STATUS_CANDIDATES = [
    "http://localhost:4000/status",
    "http://host.docker.internal:4000/status",
]


def _build_watcher_message(watcher_info: Dict[str, object]) -> str:
    if not watcher_info:
        return "Watcher status unknown (no data)"
    if not watcher_info.get("enabled"):
        return "Watcher disabled (no valid paths configured)"
    paths = watcher_info.get("paths") or []
    prompt = watcher_info.get("prompt_file") or "built-in prompt"
    return f"Watcher enabled on {len(paths)} path(s); prompt={prompt}"


@mcp.tool()
async def check_monitor_status(
    watch_path: str = "",
    status_url: str | None = None,
) -> Dict[str, object]:
    """Check the current status of the gateway file watcher / monitor.

    Args:
        watch_path: Optional legacy session file directory (set only when needed)
        status_url: Optional override for gateway status endpoint

    Returns:
        Dictionary with monitor status including:
        - is_running: Whether monitor is active
        - watcher: Detailed watcher configuration from gateway (if available)
        - webhook/env: Gateway webhook/env status (if available)
        - concurrency: Gateway concurrency information (if available)
        - session_id: Current monitor session ID (from legacy file fallback)

    Example:
        check_monitor_status()
    """

    try:
        gateway_url = status_url or DEFAULT_STATUS_URL

        tried_urls = []
        candidate_urls = []
        if gateway_url:
            candidate_urls.append(gateway_url)
        candidate_urls.extend(url for url in DEFAULT_STATUS_CANDIDATES if url not in candidate_urls)

        payload = None
        used_url = None

        for url in candidate_urls:
            try:
                req = urllib.request.Request(
                    url,
                    headers={"Accept": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=3) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                used_url = url
                break
            except Exception as status_error:
                tried_urls.append(f"{url} -> {status_error}")
                continue

        if payload is not None:
            watcher_info = payload.get("watcher") or {}
            concurrency = payload.get("concurrency")
            uptime = payload.get("uptime")
            memory = payload.get("memory")
            webhook = payload.get("webhook") or {}
            env_status = payload.get("env") or {}

            return {
                "success": True,
                "is_running": bool(watcher_info.get("enabled")),
                "watcher": watcher_info,
                "webhook": webhook,
                "env": env_status,
                "concurrency": concurrency,
                "uptime": uptime,
                "memory": memory,
                "session_id": payload.get("session_id"),
                "message": f"{_build_watcher_message(watcher_info)} (from {used_url})",
            }
        # If no payload retrieved, fall back to legacy session file

        watch_dir = Path(watch_path)
        session_file = watch_dir / ".codex-monitor-session"

        # Check if session file exists (indicates monitor has run)
        if not session_file.exists():
            return {
                "success": True,
                "is_running": False,
                "watcher": {
                    "enabled": False,
                },
                "session_id": None,
                "message": "Monitor not active or never started"
            }

        # Read session ID
        session_id = session_file.read_text().strip()

        # In the future, we could add a status file that monitor writes to
        # For now, we just check if session exists
        return {
            "success": True,
            "is_running": True,
            "watcher": {
                "enabled": True,
                "paths": [str(watch_dir)],
                "source": "legacy-session-file",
            },
            "session_id": session_id,
            "message": f"Monitor session active (legacy session file): {session_id}"
        }

    except Exception as e:
        print(f"❌ Failed to check monitor status: {e}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return {
            "success": False,
            "error": str(e),
            "message": "Failed to check monitor status"
        }


if __name__ == "__main__":
    mcp.run()
