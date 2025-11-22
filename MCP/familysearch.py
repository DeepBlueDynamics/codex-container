#!/usr/bin/env python3
"""MCP: familysearch

Lightweight client for FamilySearch public APIs focusing on the unauthenticated
session grant. Provides helper tools to request an access token and run person
search queries that do not require user credentials.

Env/config:
- FAMILYSEARCH_CLIENT_ID: required app key (or pass per-call)
- FAMILYSEARCH_IP_ADDRESS: optional IP override to send with token requests
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

import aiohttp
from mcp.server.fastmcp import FastMCP


mcp = FastMCP("familysearch")

TOKEN_URL = "https://ident.familysearch.org/cis-web/oauth2/v3/token"
PERSON_SEARCH_URL = "https://api.familysearch.org/platform/tree/persons/search"
CLIENT_ID_ENV = "FAMILYSEARCH_CLIENT_ID"
IP_ENV = "FAMILYSEARCH_IP_ADDRESS"


async def _fetch_json(
    method: str,
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    data: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.request(
            method,
            url,
            headers=headers,
            data=data,
            params=params,
        ) as resp:
            text = await resp.text()
            try:
                payload = await resp.json(content_type=None)
            except Exception:
                payload = {"raw": text}
            if 200 <= resp.status < 300:
                return {"success": True, "data": payload}
            return {
                "success": False,
                "status_code": resp.status,
                "error": payload.get("error") if isinstance(payload, dict) else text,
                "data": payload,
            }


def _resolve_client_id(explicit: Optional[str]) -> Optional[str]:
    return explicit or os.environ.get(CLIENT_ID_ENV)


def _resolve_ip(explicit: Optional[str]) -> Optional[str]:
    return explicit or os.environ.get(IP_ENV)


async def _get_token_from_familysearch(client_id: str, ip_address: Optional[str]) -> Dict[str, Any]:
    form: Dict[str, str] = {
        "grant_type": "unauthenticated_session",
        "client_id": client_id,
    }
    if ip_address:
        form["ip_address"] = ip_address
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    return await _fetch_json("POST", TOKEN_URL, headers=headers, data=form)


@mcp.tool()
async def familysearch_get_unauth_token(
    client_id: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> Dict[str, Any]:
    """Request an unauthenticated session token from FamilySearch."""
    cid = _resolve_client_id(client_id)
    if not cid:
        return {"success": False, "error": "Missing client_id; set FAMILYSEARCH_CLIENT_ID or pass argument."}
    result = await _get_token_from_familysearch(cid, _resolve_ip(ip_address))
    if not result.get("success"):
        return result
    data = result["data"] or {}
    token = data.get("access_token") or data.get("token")
    if not token:
        return {"success": False, "error": "Token response missing access_token", "data": data}
    return {"success": True, "access_token": token, "raw": data}


async def _ensure_token(
    token: Optional[str], client_id: Optional[str], ip_address: Optional[str]
) -> Dict[str, Any]:
    if token:
        return {"success": True, "access_token": token}
    cid = _resolve_client_id(client_id)
    if not cid:
        return {"success": False, "error": "Missing client_id; set FAMILYSEARCH_CLIENT_ID or pass argument."}
    fresh = await _get_token_from_familysearch(cid, _resolve_ip(ip_address))
    if not fresh.get("success"):
        return fresh
    data = fresh["data"] or {}
    token_value = data.get("access_token") or data.get("token")
    if not token_value:
        return {"success": False, "error": "Token response missing access_token", "data": data}
    return {"success": True, "access_token": token_value}


@mcp.tool()
async def familysearch_person_search(
    query: str,
    count: int = 5,
    token: Optional[str] = None,
    client_id: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> Dict[str, Any]:
    """Search Tree persons using the unauthenticated FamilySearch endpoint."""
    if not query.strip():
        return {"success": False, "error": "Query cannot be empty."}
    ensure = await _ensure_token(token, client_id, ip_address)
    if not ensure.get("success"):
        return ensure
    access_token = ensure["access_token"]
    params = {"q": query.strip(), "count": max(1, min(count, 50))}
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {access_token}",
    }
    result = await _fetch_json("GET", PERSON_SEARCH_URL, headers=headers, params=params)
    if not result.get("success"):
        return result
    return {"success": True, "results": result["data"]}


if __name__ == "__main__":
    mcp.run()
