#!/usr/bin/env python3
"""MCP: marketbot

Bridge the MarketBot API into MCP so agents can push/pull competitive intelligence.

Rather than thinking of "competitors" in abstract, the platform tracks specific
companies (the "common name" your team uses internally) plus their recent activities,
alerts, and trending keywords. These tools deliberately surface that naming guidance to
encourage consistent deduplication—always reuse the same canonical company name when
creating a record so downstream dashboards group intelligence correctly.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional, Sequence

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("marketbot")

# Configuration mirrors the ProductBotAI deployment exposed via ngrok.
_DEFAULT_BASE_URL = "http://localhost:3000/api/marketbot"
_ENV_FILE = Path(os.getenv("MARKETBOT_ENV_FILE", "/workspace/.marketbot.env"))


def _read_env_file() -> Dict[str, str]:
    """Parse .marketbot.env for fallback configuration."""

    candidates: Sequence[Path] = [
        Path(os.getenv("MARKETBOT_ENV_FILE", "")),
        _ENV_FILE,
        Path("/workspace/.marketbot.env"),
        Path(__file__).resolve().parent.parent / ".marketbot.env",
        Path("/opt/codex-home/.marketbot.env"),
    ]

    session_id = os.getenv("CODEX_SESSION_ID")
    sessions_root = Path("/opt/codex-home/sessions")
    if session_id:
        candidates.append(sessions_root / session_id / ".env")
    candidates.append(sessions_root / "unknown" / ".env")

    values: Dict[str, str] = {}
    for candidate in candidates:
        if not candidate or not candidate.is_file():
            continue
        for raw_line in candidate.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values.setdefault(key.strip(), value.strip())
        if values:
            break
    return values


def _resolve_setting(name: str, default: Optional[str] = None) -> Optional[str]:
    """Return env value from process or .marketbot.env fallback."""

    return os.getenv(name) or _read_env_file().get(name) or default


class MarketBotError(RuntimeError):
    """Raised when the MarketBot API returns an error."""


def _debug_info() -> Dict[str, Optional[str]]:
    """Return non-sensitive context for tool responses."""

    api_key = _resolve_setting("MARKETBOT_API_KEY", "")
    suffix: Optional[str] = api_key[-4:] if api_key else None
    return {
        "base_url": _resolve_setting("MARKETBOT_API_URL", _DEFAULT_BASE_URL),
        "team_id": _resolve_setting("MARKETBOT_TEAM_ID", ""),
        "api_key_suffix": suffix,
    }


def _with_next_actions(resp: Dict[str, Any], actions: Optional[Sequence[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Ensure every response carries next_actions (default: empty list)."""

    if actions is None:
        actions = []
    if isinstance(resp, dict) and "next_actions" not in resp:
        resp["next_actions"] = list(actions)
    return resp


def _request(
    method: str,
    path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    body: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Make an HTTP request to the MarketBot API."""

    api_key = _resolve_setting("MARKETBOT_API_KEY")
    team_id = _resolve_setting("MARKETBOT_TEAM_ID")
    base_url = (_resolve_setting("MARKETBOT_API_URL", _DEFAULT_BASE_URL) or _DEFAULT_BASE_URL).rstrip("/")

    if not api_key:
        raise MarketBotError("MARKETBOT_API_KEY is not set (set env or /workspace/.marketbot.env)")
    if not team_id:
        raise MarketBotError("MARKETBOT_TEAM_ID is not set (set env or /workspace/.marketbot.env)")

    base = base_url or _DEFAULT_BASE_URL
    url = f"{base.rstrip('/')}/{path.lstrip('/')}"
    if params:
        query_params = {k: v for k, v in params.items() if v is not None}
        if query_params:
            query = urllib.parse.urlencode(query_params)
            url = f"{url}?{query}"

    data = None
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {api_key}",
        "X-API-Key": api_key,
        "X-Team-Id": team_id,
    }
    if "ngrok" in base:
        headers["ngrok-skip-browser-warning"] = "true"
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # type: ignore[no-untyped-call]
            payload = resp.read().decode("utf-8")
            if resp.status >= 400:
                raise MarketBotError(payload)
            return json.loads(payload)
    except urllib.error.HTTPError as exc:  # type: ignore[attr-defined]
        detail = exc.read().decode("utf-8")
        raise MarketBotError(f"HTTP {exc.code}: {detail}") from exc


@mcp.tool()
async def marketbot_ping() -> Dict[str, Any]:
    """Ping the MarketBot API and report the base URL in use.

    Returns the resolved base URL and health check response (or error).
    """
    try:
        response = _request("GET", "/health")
        if isinstance(response, dict):
            response.setdefault("base_url", _resolve_setting("MARKETBOT_API_URL", _DEFAULT_BASE_URL))
            response.setdefault("debug", _debug_info())
        else:
            response = {"success": True, "data": response, "debug": _debug_info()}
        return _with_next_actions(response)
    except Exception as err:
        return _with_next_actions(
            {
                "success": False,
                "base_url": _resolve_setting("MARKETBOT_API_URL", _DEFAULT_BASE_URL),
                "debug": _debug_info(),
                "error": str(err),
            }
        )


@mcp.tool()
async def marketbot_health() -> Dict[str, Any]:
    """Return the MarketBot API health check.

    Use this first if requests fail—it confirms the MCP process can reach the
    ProductBotAI MarketBot service. Override MARKETBOT_API_URL if you're not on
    the default localhost/ngrok tunnel.
    """
    try:
        response = _request("GET", "/health")
        if isinstance(response, dict):
            response.setdefault("base_url", _resolve_setting("MARKETBOT_API_URL", _DEFAULT_BASE_URL))
            response.setdefault("debug", _debug_info())
        else:
            response = {"success": True, "data": response, "debug": _debug_info()}
        return _with_next_actions(response)
    except Exception as err:
        return _with_next_actions(
            {
                "success": False,
                "error": str(err),
                "base_url": _resolve_setting("MARKETBOT_API_URL", _DEFAULT_BASE_URL),
                "debug": _debug_info(),
            }
        )


@mcp.tool()
async def list_competitors(
    industry: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> Dict[str, Any]:
    """List known companies (a.k.a. competitors) with optional filters.

    Args:
        industry: Filter companies by industry tag.
        status: Filter by lifecycle (active, monitoring, inactive).
        limit/offset: Paginate through large result sets.

    Reminder: each entry represents a single company with a canonical "common name".
    Reuse that name when creating activities to avoid duplicates.
    """
    try:
        params = {
            "industry": industry,
            "status": status,
            "limit": limit,
            "offset": offset,
        }
        payload = _request("GET", "/competitors", params=params)
        payload.setdefault("debug", _debug_info())
        return _with_next_actions(payload)
    except Exception as err:
        return _with_next_actions({"success": False, "error": str(err), "debug": _debug_info()})


@mcp.tool()
async def create_competitor(
    name: str,
    website: str,
    industry: str,
    status: str = "active",
    logo_url: Optional[str] = None,
    summary: Optional[str] = None,
    competes_with_ids: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Create a company record used across MarketBot dashboards.

    Args:
        name: Canonical common name (e.g., "Splunk" or "Microsoft Sentinel").
        website: Primary marketing site.
        industry: Free-form grouping used for dashboard filters.
        status: "active", "monitoring", etc.
        logo_url/summary: Optional embellishments for richer cards.
        competes_with_ids: Optional list of other competitor IDs this company overlaps with.

    Always reuse the same `name` (common name) so deduplication is effortless. If the
    company already exists, `list_competitors` can help you find the canonical slug.
    """
    try:
        body = {
            "name": name,
            "website": website,
            "industry": industry,
            "status": status,
            "logo_url": logo_url,
            "summary": summary,
            "competes_with_ids": list(competes_with_ids) if competes_with_ids else None,
        }
        payload = _request("POST", "/competitors", body=body)
        payload.setdefault("debug", _debug_info())
        return _with_next_actions(payload)
    except Exception as err:
        return _with_next_actions({"success": False, "error": str(err), "debug": _debug_info()})


@mcp.tool()
async def get_competitor_detail(competitor_id: str) -> Dict[str, Any]:
    """Fetch one company plus up to five recent activities.

    Args:
        competitor_id: The `id` returned from `list_competitors` / `create_competitor`.

    Returns the metadata block plus `recent_activities` for storyboarded cards.
    """
    try:
        payload = _request("GET", f"/competitors/{competitor_id}")
        payload.setdefault("debug", _debug_info())
        return _with_next_actions(payload)
    except Exception as err:
        return _with_next_actions({"success": False, "error": str(err), "debug": _debug_info()})


@mcp.tool()
async def list_activities(
    competitor_id: Optional[str] = None,
    category: Optional[str] = None,
    time_range_days: Optional[int] = None,
    search: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> Dict[str, Any]:
    """List or search activities tied to tracked companies.

    Args:
        competitor_id: Filter to a single company.
        category: e.g., Product, Pricing, Funding, News.
        time_range_days: quick lookback filtering.
        search: semantic search term (uses Chroma similarity).
        limit/offset: Pagination controls.
    """
    try:
        params = {
            "competitor_id": competitor_id,
            "category": category,
            "time_range_days": time_range_days,
            "search": search,
            "limit": limit,
            "offset": offset,
        }
        payload = _request("GET", "/activities", params=params)
        payload.setdefault("debug", _debug_info())
        return _with_next_actions(payload)
    except Exception as err:
        return _with_next_actions({"success": False, "error": str(err), "debug": _debug_info()})


@mcp.tool()
async def create_activity(
    competitor_id: str,
    title: str,
    description: Optional[str] = None,
    category: str = "News",
    source_url: Optional[str] = None,
    source_type: Optional[str] = None,
    detected_at: Optional[str] = None,
    published_at: Optional[str] = None,
    confidence_score: Optional[float] = None,
    is_verified: bool = False,
) -> Dict[str, Any]:
    """Append a competitive intel activity (product launch, pricing move, etc.).

    Args:
        competitor_id: ID of the company record (canonical common name already stored).
        title/description: Short headline plus supporting blurb.
        category: Product, Pricing, Funding, News, etc.
        source_url/source_type: Where the intel came from.
        detected_at/published_at: ISO timestamps (optional; omit if unknown).
        confidence_score/is_verified: Confidence bookkeeping.

    Tip: omit `detected_at` unless you have a precise timestamp—MarketBot will fill in
    the current time, avoiding malformed values.
    """
    try:
        body = {
            "competitor_id": competitor_id,
            "title": title,
            "description": description,
            "category": category,
            "source_url": source_url,
            "source_type": source_type,
            "detected_at": detected_at,
            "published_at": published_at,
            "confidence_score": confidence_score,
            "is_verified": is_verified,
        }
        payload = _request("POST", "/activities", body=body)
        payload.setdefault("debug", _debug_info())
        return _with_next_actions(payload)
    except Exception as err:
        return _with_next_actions({"success": False, "error": str(err), "debug": _debug_info()})


@mcp.tool()
async def list_trends(limit: int = 10) -> Dict[str, Any]:
    """Return trending keywords extracted from all competitor activities.

    Args:
        limit: Number of ranked keywords to fetch (default 10).
    """
    try:
        payload = _request("GET", "/trends", params={"limit": limit})
        payload.setdefault("debug", _debug_info())
        return _with_next_actions(payload)
    except Exception as err:
        return _with_next_actions({"success": False, "error": str(err), "debug": _debug_info()})


@mcp.tool()
async def recompute_trends(top_n: int = 25, lookback_days: int = 180) -> Dict[str, Any]:
    """Recompute trending keywords from activities and return the updated list.

    Args:
        top_n: Number of keywords to keep (1–50; default 25).
        lookback_days: Only consider activities in this recent window (default 180).

    Notes:
        - Calls POST /api/trends/recompute under the hood.
        - After recompute, GET /api/trends will reflect the new rankings.
    """
    try:
        body = {"top_n": top_n, "lookback_days": lookback_days}
        payload = _request("POST", "/trends", body=body)
        payload.setdefault("debug", _debug_info())
        return _with_next_actions(payload)
    except Exception as err:
        return _with_next_actions({"success": False, "error": str(err), "debug": _debug_info()})


@mcp.tool()
async def list_alerts(unread_only: bool = False) -> Dict[str, Any]:
    """List alert records (optionally unread only).

    Args:
        unread_only: True to fetch only unread alerts (UI badge scenario).
    """
    try:
        params = {"unread_only": str(bool(unread_only)).lower()}
        payload = _request("GET", "/alerts", params=params)
        payload.setdefault("debug", _debug_info())
        return _with_next_actions(payload)
    except Exception as err:
        return _with_next_actions({"success": False, "error": str(err), "debug": _debug_info()})


@mcp.tool()
async def update_alert(alert_id: str, is_read: bool = True) -> Dict[str, Any]:
    """Mark an alert read/unread."""
    try:
        body = {"is_read": is_read}
        payload = _request("PATCH", f"/alerts/{alert_id}", body=body)
        payload.setdefault("debug", _debug_info())
        return _with_next_actions(payload)
    except Exception as err:
        return _with_next_actions({"success": False, "error": str(err), "debug": _debug_info()})


if __name__ == "__main__":
    # Match other MCP tools: run the server over stdio for the Codex harness.
    mcp.run(transport="stdio")
