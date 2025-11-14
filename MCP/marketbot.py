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
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("marketbot")

# Default to service name on codex-network so the MCP server shares the same network.
_DEFAULT_BASE_URL = "http://marketbot-api:8000"
_ENV_BASE_URL = os.getenv("MARKETBOT_API_URL")


class MarketBotError(RuntimeError):
    """Raised when the MarketBot API returns an error."""


def _probe_base(url: str, timeout: float = 2.0) -> bool:
    try:
        req = urllib.request.Request(urllib.parse.urljoin(url, "/healthz"), method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # type: ignore[no-untyped-call]
            return resp.status == 200
    except Exception:
        return False


def _detect_base_url() -> str:
    candidates = [
        _ENV_BASE_URL,
        _DEFAULT_BASE_URL,
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "https://api.marketbot.local",
    ]
    for cand in candidates:
        if not cand:
            continue
        if _probe_base(cand):
            return cand
    # Fallback to env or default even if probe fails; _request will still raise
    return _ENV_BASE_URL or _DEFAULT_BASE_URL


_BASE_URL = _detect_base_url()


def _request(
    method: str,
    path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    body: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Make an HTTP request to the MarketBot API."""

    url = urllib.parse.urljoin(_BASE_URL, path)
    if params:
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        url = f"{url}?{query}"

    data = None
    headers = {"Accept": "application/json"}
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
        return {"success": True, "base_url": _BASE_URL, "data": _request("GET", "/healthz")}
    except Exception as err:
        return {"success": False, "base_url": _BASE_URL, "error": str(err)}


@mcp.tool()
async def marketbot_health() -> Dict[str, Any]:
    """Return the MarketBot API health check.

    Use this first if requests fail—it confirms the MCP process can reach the
    MarketBot FastAPI service. The base URL is auto-detected among common hosts
    or can be overridden with MARKETBOT_API_URL.
    """
    try:
        return {"success": True, "data": _request("GET", "/healthz"), "base_url": _BASE_URL}
    except Exception as err:
        return {"success": False, "error": str(err), "base_url": _BASE_URL}


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
        return {"success": True, **_request("GET", "/api/competitors", params=params)}
    except Exception as err:
        return {"success": False, "error": str(err), "base_url": _BASE_URL}


@mcp.tool()
async def create_competitor(
    name: str,
    website: str,
    industry: str,
    status: str = "active",
    logo_url: Optional[str] = None,
    summary: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a company record used across MarketBot dashboards.

    Args:
        name: Canonical common name (e.g., "Splunk" or "Microsoft Sentinel").
        website: Primary marketing site.
        industry: Free-form grouping used for dashboard filters.
        status: "active", "monitoring", etc.
        logo_url/summary: Optional embellishments for richer cards.

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
        }
        return {"success": True, "competitor": _request("POST", "/api/competitors", body=body)}
    except Exception as err:
        return {"success": False, "error": str(err), "base_url": _BASE_URL}


@mcp.tool()
async def get_competitor_detail(competitor_id: str) -> Dict[str, Any]:
    """Fetch one company plus up to five recent activities.

    Args:
        competitor_id: The `id` returned from `list_competitors` / `create_competitor`.

    Returns the metadata block plus `recent_activities` for storyboarded cards.
    """
    try:
        data = _request("GET", f"/api/competitors/{competitor_id}")
        return {"success": True, "competitor": data}
    except Exception as err:
        return {"success": False, "error": str(err), "base_url": _BASE_URL}


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
        return {"success": True, **_request("GET", "/api/activities", params=params)}
    except Exception as err:
        return {"success": False, "error": str(err), "base_url": _BASE_URL}


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
        return {"success": True, "activity": _request("POST", "/api/activities", body=body)}
    except Exception as err:
        return {"success": False, "error": str(err), "base_url": _BASE_URL}


@mcp.tool()
async def list_trends(limit: int = 10) -> Dict[str, Any]:
    """Return trending keywords extracted from all competitor activities.

    Args:
        limit: Number of ranked keywords to fetch (default 10).
    """
    try:
        return {"success": True, **_request("GET", "/api/trends", params={"limit": limit})}
    except Exception as err:
        return {"success": False, "error": str(err), "base_url": _BASE_URL}


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
        return {
            "success": True,
            **_request(
                "POST",
                "/api/trends/recompute",
                params={"top_n": top_n, "lookback_days": lookback_days},
            ),
        }
    except Exception as err:
        return {"success": False, "error": str(err), "base_url": _BASE_URL}


@mcp.tool()
async def list_alerts(unread_only: bool = False) -> Dict[str, Any]:
    """List alert records (optionally unread only).

    Args:
        unread_only: True to fetch only unread alerts (UI badge scenario).
    """
    try:
        params = {"unread": str(unread_only).lower()}
        return {"success": True, **_request("GET", "/api/alerts", params=params)}
    except Exception as err:
        return {"success": False, "error": str(err), "base_url": _BASE_URL}


@mcp.tool()
async def update_alert(alert_id: str, is_read: bool = True) -> Dict[str, Any]:
    """Mark an alert read/unread."""
    try:
        body = {"is_read": is_read}
        return {"success": True, "alert": _request("PATCH", f"/api/alerts/{alert_id}", body=body)}
    except Exception as err:
        return {"success": False, "error": str(err), "base_url": _BASE_URL}


if __name__ == "__main__":
    mcp.run()
