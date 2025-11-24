#!/usr/bin/env python3
"""MCP: speaker-bridge

Expose tools for interacting with the host-side speaker service. Useful for
manual verification when automatic streaming is blocked.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Dict, Any
from urllib import error as urlerror
from urllib import request as urlrequest

from mcp.server.fastmcp import FastMCP


mcp = FastMCP("speaker-bridge")


def _default_url() -> str:
    return os.environ.get("VOICE_SPEAKER_URL", "http://host.docker.internal:8777/play")


def _default_outbox() -> str:
    return os.environ.get("VOICE_OUTBOX_CONTAINER_PATH", "/workspace/voice-outbox")


def _default_timeout() -> int:
    # Allow longer host responses; overridable via VOICE_SPEAKER_TIMEOUT (seconds).
    try:
        return int(os.environ.get("VOICE_SPEAKER_TIMEOUT", "30"))
    except ValueError:
        return 30


def _post_json(url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = urlrequest.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urlrequest.urlopen(req, timeout=_default_timeout()) as resp:
        resp_body = resp.read().decode("utf-8")
        status = resp.status
    return {"status": str(status), "body": resp_body}


def _get_status() -> Dict[str, Any]:
    """Best-effort fetch of playback status."""
    url = _default_url().replace("/play", "/status")
    try:
        with urlrequest.urlopen(url, timeout=_default_timeout()) as resp:
            resp_body = resp.read().decode("utf-8")
            status = resp.status
        return {"status": str(status), "body": resp_body}
    except Exception as exc:  # pylint: disable=broad-except
        return {"status": "error", "error": str(exc)}


def _format_response(success: bool, **kwargs: Any) -> Dict[str, Any]:
    result = {"success": "true" if success else "false"}
    result.update({k: str(v) for k, v in kwargs.items()})
    return result


@mcp.tool()
async def speaker_ping() -> Dict[str, Any]:
    """Call GET /health on the speaker service to verify connectivity."""

    url = _default_url().replace("/play", "/health")
    try:
        with urlrequest.urlopen(url, timeout=5) as resp:
            body = resp.read().decode("utf-8")
            status = resp.status
        return _format_response(True, status=status, body=body)
    except urlerror.URLError as exc:
        return _format_response(False, error=str(exc))


@mcp.tool()
async def speaker_play(relative_path: str) -> Dict[str, Any]:
    """Request playback for a file inside the voice outbox."""

    outbox = _default_outbox()
    try:
        os.makedirs(outbox, exist_ok=True)
        rel = relative_path.lstrip("/\\")
        print(f"[speaker-bridge] requesting playback for {rel}", file=sys.stderr)
        result = _post_json(_default_url(), {"relative_path": rel})
        result["path"] = os.path.join(outbox, rel)
        return _format_response(True, **result)
    except Exception as exc:  # pylint: disable=broad-except
        print(f"[speaker-bridge] playback failed: {exc}", file=sys.stderr)
        return _format_response(False, error=str(exc))


@mcp.tool()
async def speaker_status() -> Dict[str, Any]:
    """Return best-effort playback status from the speaker service."""

    try:
        status = _get_status()
        return _format_response(True, **status)
    except Exception as exc:  # pylint: disable=broad-except
        print(f"[speaker-bridge] status failed: {exc}", file=sys.stderr)
        return _format_response(False, error=str(exc))


@mcp.tool()
async def speaker_open_url(url: str, new_window: bool = False) -> Dict[str, Any]:
    """Open a URL on the host via the speaker service's Chrome controller."""

    browser_endpoint = _default_url().replace("/play", "/browser")
    payload = {"action": "open", "url": url, "new_window": new_window}
    try:
        result = _post_json(browser_endpoint, payload)
        return _format_response(True, **result)
    except Exception as exc:  # pylint: disable=broad-except
        return _format_response(False, error=str(exc))


if __name__ == "__main__":  # pragma: no cover
    mcp.run()
