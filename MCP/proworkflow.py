#!/usr/bin/env python3
"""
MCP: proworkflow

Lightweight connector for the ProWorkflow REST API.

Auth model (per docs):
- Basic Auth with your ProWorkflow username/password (or email).
- API key supplied via `apikey` HTTP header (recommended) or `apikey` query param.

Environment / config:
- PROWORKFLOW_API_KEY        (required)
- PROWORKFLOW_USERNAME       (required)
- PROWORKFLOW_PASSWORD       (required)
- PROWORKFLOW_BASE_URL       (optional, default: https://api.proworkflow.net)
- PROWORKFLOW_TIMEOUT        (optional, seconds, default: 30)

Tools:
- proworkflow_status(): quick config check
- proworkflow_request(method, path, params?, body?, headers?): generic REST call
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
from typing import Any, Dict, Optional

import aiohttp
from mcp.server.fastmcp import FastMCP


mcp = FastMCP("proworkflow")

DEFAULT_BASE = os.environ.get("PROWORKFLOW_BASE_URL", "https://api.proworkflow.net").rstrip("/")
DEFAULT_TIMEOUT = float(os.environ.get("PROWORKFLOW_TIMEOUT", "30"))


def _get_basic_auth() -> Optional[str]:
    user = os.environ.get("PROWORKFLOW_USERNAME")
    pwd = os.environ.get("PROWORKFLOW_PASSWORD")
    if not user or not pwd:
        return None
    token = base64.b64encode(f"{user}:{pwd}".encode("utf-8")).decode("utf-8")
    return f"Basic {token}"


def _get_api_key() -> Optional[str]:
    key = os.environ.get("PROWORKFLOW_API_KEY")
    return key.strip() if key else None


@mcp.tool()
async def proworkflow_status() -> Dict[str, Any]:
    """Report whether configuration is present for ProWorkflow."""
    return {
        "success": True,
        "base_url": DEFAULT_BASE,
        "api_key_present": _get_api_key() is not None,
        "basic_auth_present": _get_basic_auth() is not None,
        "timeout_seconds": DEFAULT_TIMEOUT,
    }


@mcp.tool()
async def proworkflow_request(
    method: str,
    path: str,
    params: Optional[Dict[str, Any]] = None,
    body: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Perform a generic ProWorkflow API request.

    Args:
        method: HTTP verb (GET, POST, PUT, DELETE).
        path: Resource path, e.g., "/projects" or "projects/123".
        params: Optional query parameters (dict).
        body: Optional JSON body for POST/PUT.
        headers: Optional extra headers (merged with auth headers).
    """
    api_key = _get_api_key()
    auth_hdr = _get_basic_auth()
    if not api_key or not auth_hdr:
        return {
            "success": False,
            "error": "Missing credentials. Set PROWORKFLOW_API_KEY, PROWORKFLOW_USERNAME, PROWORKFLOW_PASSWORD.",
        }

    verb = method.upper().strip()
    if verb not in {"GET", "POST", "PUT", "DELETE"}:
        return {"success": False, "error": f"Unsupported method '{method}'"}

    # Normalize path
    cleaned = path.strip()
    if cleaned.startswith("http://") or cleaned.startswith("https://"):
        url = cleaned
    else:
        if cleaned.startswith("/"):
            cleaned = cleaned[1:]
        url = f"{DEFAULT_BASE}/{cleaned}"

    req_headers = {
        "Authorization": auth_hdr,
        "apikey": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if headers:
        for k, v in headers.items():
            if v is not None:
                req_headers[k] = str(v)

    timeout = aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            async with session.request(
                verb,
                url,
                headers=req_headers,
                params=params,
                json=body,
            ) as resp:
                status = resp.status
                text = await resp.text()
                try:
                    data = json.loads(text) if text else None
                except Exception:
                    data = text
                ok = 200 <= status < 300
                return {
                    "success": ok,
                    "status": status,
                    "url": str(resp.url),
                    "headers": {k: v for k, v in resp.headers.items()},
                    "data": data,
                }
        except asyncio.TimeoutError:
            return {"success": False, "error": f"Request timed out after {DEFAULT_TIMEOUT}s", "url": url}
        except Exception as e:
            return {"success": False, "error": str(e), "url": url}


if __name__ == "__main__":
    mcp.run()
