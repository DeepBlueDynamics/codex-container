#!/usr/bin/env python3
"""MCP: vhf-control

Expose tools to query and control the VHF monitor REST API from inside the
codex container. Supports channel changes, arbitrary frequency tuning, and
recording toggles with graceful HTTP error handling.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict, Optional

from mcp.server.fastmcp import FastMCP

try:
    import aiohttp
except Exception:
    aiohttp = None  # Optional dependency; fallback to urllib if missing.

mcp = FastMCP("vhf-control")

VHF_HOST = os.environ.get("VHF_MONITOR_HOST", "host.docker.internal")
VHF_PORT = int(os.environ.get("VHF_MONITOR_PORT", "8080"))
VHF_TIMEOUT = float(os.environ.get("VHF_MONITOR_TIMEOUT", "5"))
VHF_BASE_URL = f"http://{VHF_HOST}:{VHF_PORT}"


async def _call_vhf_api(
    endpoint: str,
    method: str = "GET",
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Call the VHF monitor API using aiohttp when available, else urllib."""
    url = f"{VHF_BASE_URL}{endpoint}"

    if aiohttp is not None:
        try:
            timeout = aiohttp.ClientTimeout(total=VHF_TIMEOUT)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                if method.upper() == "GET":
                    async with session.get(url) as resp:
                        text = await resp.text()
                        if resp.status >= 400:
                            return {"error": f"HTTP {resp.status}: {text}"}
                        return json.loads(text)
                else:
                    async with session.post(url, json=payload or {}) as resp:
                        text = await resp.text()
                        if resp.status >= 400:
                            return {"error": f"HTTP {resp.status}: {text}"}
                        return json.loads(text)
        except aiohttp.ClientResponseError as exc:
            return {"error": f"HTTP {exc.status}: {exc.message}"}
        except aiohttp.ClientError as exc:
            return {"error": f"Connection failed: {exc}"}
        except json.JSONDecodeError as exc:
            return {"error": f"Invalid JSON response: {exc}"}
        except Exception as exc:
            return {"error": str(exc)}

    return await asyncio.to_thread(_call_vhf_api_sync, url, method, payload)


def _call_vhf_api_sync(url: str, method: str, payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Blocking urllib fallback used when aiohttp is unavailable."""
    import urllib.error
    import urllib.request

    req: urllib.request.Request
    if method.upper() == "GET":
        req = urllib.request.Request(url, method="GET")
    else:
        data = json.dumps(payload or {}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={"Content-Type": "application/json"},
        )

    try:
        with urllib.request.urlopen(req, timeout=VHF_TIMEOUT) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="ignore")
        return {"error": f"HTTP {exc.code}: {error_body}"}
    except urllib.error.URLError as exc:
        return {"error": f"Connection failed: {exc.reason}"}
    except json.JSONDecodeError as exc:
        return {"error": f"Invalid JSON response: {exc}"}
    except Exception as exc:
        return {"error": str(exc)}


def _format_frequency(freq_hz: Optional[int]) -> str:
    if not freq_hz:
        return "Unknown frequency"
    freq_mhz = freq_hz / 1_000_000
    return f"{freq_mhz:.3f} MHz ({freq_hz} Hz)"


def _error_or(result: Dict[str, Any]) -> Optional[str]:
    error = result.get("error")
    if error:
        return f"Error: {error}"
    return None


@mcp.tool()
async def vhf_get_status() -> Dict[str, Any]:
    """Get current VHF monitor status including channel, frequency, and recording state."""
    result = await _call_vhf_api("/status", method="GET")
    error_text = _error_or(result)
    if error_text:
        return {"success": False, "message": error_text}

    channel = result.get("channel")
    freq_hz = result.get("frequency_hz")
    recording = bool(result.get("recording"))

    lines = ["VHF Monitor Status:"]
    if channel is not None:
        lines.append(f"  Channel: {channel}")
    lines.append(f"  Frequency: {_format_frequency(freq_hz)}")
    lines.append(f"  Recording: {'ENABLED' if recording else 'DISABLED'}")

    return {"success": True, "status": result, "message": "\n".join(lines)}


@mcp.tool()
async def vhf_set_channel(channel: int) -> Dict[str, Any]:
    """Set the VHF monitor to a specific marine VHF channel (1-88)."""
    if channel < 1 or channel > 88:
        return {"success": False, "message": "Channel must be between 1 and 88."}

    result = await _call_vhf_api("/channel", method="POST", payload={"channel": int(channel)})
    error_text = _error_or(result)
    if error_text:
        return {"success": False, "message": error_text}

    freq_hz = result.get("frequency_hz")
    return {
        "success": True,
        "status": result,
        "message": f"✓ Changed to VHF Channel {channel} ({_format_frequency(freq_hz)})",
    }


@mcp.tool()
async def vhf_set_frequency(frequency_hz: int) -> Dict[str, Any]:
    """Set the VHF monitor to a custom frequency in Hz (e.g. 156800000 for channel 16)."""
    if frequency_hz <= 0:
        return {"success": False, "message": "Frequency must be a positive integer in Hz."}

    result = await _call_vhf_api("/channel", method="POST", payload={"frequency_hz": int(frequency_hz)})
    error_text = _error_or(result)
    if error_text:
        return {"success": False, "message": error_text}

    return {
        "success": True,
        "status": result,
        "message": f"✓ Changed to {_format_frequency(frequency_hz)}",
    }


@mcp.tool()
async def vhf_set_recording(recording: bool) -> Dict[str, Any]:
    """Enable or disable audio recording of transmissions."""
    result = await _call_vhf_api("/recording", method="POST", payload={"recording": bool(recording)})
    error_text = _error_or(result)
    if error_text:
        return {"success": False, "message": error_text}

    state = "ENABLED" if recording else "DISABLED"
    return {
        "success": True,
        "status": result,
        "message": f"✓ Recording {state}",
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
