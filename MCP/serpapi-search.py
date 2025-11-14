#!/usr/bin/env python3
"""
SerpAPI Google Search (MCP)
===========================

Provides Google web search via SerpAPI and returns either structured JSON
or convenient Markdown. Optionally, fetches Markdown from result URLs using
the remote Wraith server (same behavior as MCP/gnosis-crawl.py, non-localhost).

Tools:
- serpapi_status(): quick config check
- google_search(query, ...): raw SerpAPI JSON
- google_search_markdown(query, ..., fetch_pages_top_k?): Markdown summary

Env/config:
- SERPAPI_API_KEY            (required for live calls)
- SERPAPI_ENGINE             (default: "google")
- GNOSIS_CRAWL_BASE_URL      (default: https://wraith.nuts.services)
- WRAITH_AUTH_TOKEN          (optional; also read from .wraithenv)

Notes:
- For Wraith, we post to {base}/api/markdown to convert pages to Markdown.
- This module mirrors the FastMCP style used across MCP/.
"""

from __future__ import annotations

import os
import json
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
from mcp.server.fastmcp import FastMCP


mcp = FastMCP("serpapi-search")


# ------------------------------
# Config helpers
# ------------------------------
SERPAPI_API_URL = "https://serpapi.com/search.json"
SERPAPI_ENGINE = os.environ.get("SERPAPI_ENGINE", "google").strip() or "google"
WRAITH_ENV_FILE = os.path.join(os.getcwd(), ".wraithenv")
# Default to local gnosis-crawl service on the codex network.
# Local deployments should listen on 6792.
REMOTE_WRAITH = os.environ.get("GNOSIS_CRAWL_BASE_URL", "http://gnosis-crawl:6792").strip()
SERPAPI_ENV_FILE = os.path.join(os.getcwd(), ".serpapi.env")


def _get_serpapi_key() -> Optional[str]:
    key = os.environ.get("SERPAPI_API_KEY")
    if key:
        return key.strip()
    # Fallback to local .serpapi.env file if present
    try:
        if os.path.exists(SERPAPI_ENV_FILE):
            with open(SERPAPI_ENV_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.startswith("SERPAPI_API_KEY="):
                        return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return None


def _get_wraith_token() -> Optional[str]:
    tok = os.environ.get("WRAITH_AUTH_TOKEN")
    if tok:
        return tok.strip()
    # Fallback to .wraithenv file
    try:
        if os.path.exists(WRAITH_ENV_FILE):
            with open(WRAITH_ENV_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("WRAITH_AUTH_TOKEN="):
                        return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return None


# ------------------------------
# Tools
# ------------------------------
@mcp.tool()
async def serpapi_status() -> Dict[str, Any]:
    """Report whether configuration is present for SerpAPI and Wraith."""
    return {
        "success": True,
        "engine": SERPAPI_ENGINE,
        "serpapi_key_present": _get_serpapi_key() is not None,
        "wraith_base_url": REMOTE_WRAITH,
        "wraith_token_present": _get_wraith_token() is not None,
    }


def _extract_key_from_text(text: str) -> Optional[str]:
    """Try to extract a plausible SerpAPI key from arbitrary text.

    Accepts forms like:
    - "SERPAPI_API_KEY=..."
    - "api_key: ..." or "serpapi key ..."
    - a bare token (alphanum, dashes/underscores) length 20-80
    """
    if not text:
        return None
    raw = text.strip()
    # Direct assignment line
    for prefix in ("SERPAPI_API_KEY=", "serpapi_api_key=", "api_key=", "key="):
        if prefix in raw:
            try:
                candidate = raw.split(prefix, 1)[1].strip().strip('"').strip("'")
                if candidate:
                    return candidate
            except Exception:
                pass
    # Scan lines for assignment
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if "SERPAPI_API_KEY=" in line:
            return line.split("SERPAPI_API_KEY=", 1)[1].strip().strip('"').strip("'")
        if line.lower().startswith("serpapi_api_key="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    # Fallback: regex-like filter (no regex import to keep light):
    # find longest token-like segment in the text
    tokens: List[str] = []
    current: List[str] = []
    for ch in raw:
        if ch.isalnum() or ch in ("-", "_"):
            current.append(ch)
        else:
            if current:
                tokens.append("".join(current))
                current = []
    if current:
        tokens.append("".join(current))
    # Choose a plausible length
    candidates = [t for t in tokens if 20 <= len(t) <= 80]
    if candidates:
        # Prefer the longest plausible token
        candidates.sort(key=len, reverse=True)
        return candidates[0]
    return None


def _write_serpapi_env_file(key: str) -> Tuple[bool, Optional[str]]:
    try:
        with open(SERPAPI_ENV_FILE, "w", encoding="utf-8") as f:
            f.write(f"SERPAPI_API_KEY={key}\n")
        return True, None
    except Exception as e:
        return False, str(e)


@mcp.tool()
async def set_serpapi_key(text: str, persist: bool = False) -> Dict[str, Any]:
    """Extract and set the SerpAPI API key from pasted text.

    - Parses common forms (e.g., "SERPAPI_API_KEY=..." or raw token)
    - Sets the key in-memory for the current process (os.environ)
    - If persist=True, writes to a local .serpapi.env file

    Security note: By default, nothing is written to disk. You may paste a key
    into a sticky, call this tool to capture it, then delete the sticky so no
    key remains in notes. Use persist=True only if you want local reuse.
    """
    if not text:
        return {"success": False, "error": "No text provided"}
    key = _extract_key_from_text(text)
    if not key:
        return {"success": False, "error": "No valid key found in text"}

    os.environ["SERPAPI_API_KEY"] = key
    result: Dict[str, Any] = {
        "success": True,
        "set_in_memory": True,
        "key_last4": key[-4:],
        "persisted": False,
        "source": "env",
    }
    if persist:
        ok, err = _write_serpapi_env_file(key)
        result["persisted"] = bool(ok)
        if not ok:
            result["persist_error"] = err
        else:
            result["source"] = ".serpapi.env"
    return result


@mcp.tool()
async def google_search(
    query: str,
    num: int = 10,
    hl: str = "en",
    gl: str = "us",
    location: Optional[str] = None,
    device: str = "desktop",
    no_cache: bool = False,
) -> Dict[str, Any]:
    """Run a Google search via SerpAPI and return JSON results.

    Args:
      - query: search query
      - num: max results to return (SerpAPI forwards; not guaranteed by Google)
      - hl: interface language code
      - gl: country code
      - location: optional location bias string (e.g., "Seattle, Washington, United States")
      - device: "desktop" | "mobile" | "tablet"
      - no_cache: if true, force fresh fetch on SerpAPI
    """
    if not query:
        return {"success": False, "error": "Missing query"}
    api_key = _get_serpapi_key()
    if not api_key:
        return {"success": False, "error": "SERPAPI_API_KEY not configured"}

    try:
        params = {
            "engine": SERPAPI_ENGINE,
            "q": query,
            "num": max(1, min(int(num), 100)),
            "hl": hl,
            "gl": gl,
            "device": device,
            "api_key": api_key,
        }
        if location:
            params["location"] = location
        if no_cache:
            params["no_cache"] = "true"

        timeout_cfg = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout_cfg) as session:
            async with session.get(SERPAPI_API_URL, params=params) as resp:
                data = await resp.json(content_type=None)
                if resp.status == 200:
                    data["success"] = True
                    return data
                return {"success": False, "status": resp.status, "data": data}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _format_result_item(item: Dict[str, Any]) -> str:
    title = item.get("title") or item.get("name") or "(untitled)"
    link = item.get("link") or item.get("url") or ""
    snippet = item.get("snippet") or item.get("description") or ""
    parts = [f"- [{title}]({link})" if link else f"- {title}"]
    if snippet:
        parts.append(f"  - {snippet}")
    return "\n".join(parts)


async def _wraith_markdown(session: aiohttp.ClientSession, url: str, *, timeout: int = 45) -> str:
    endpoint = f"{REMOTE_WRAITH}/api/markdown"
    payload: Dict[str, Any] = {
        "url": url,
        "javascript_enabled": False,
        "filter": "pruning",
        "filter_options": {"threshold": 0.48, "min_words": 2},
    }
    headers: Dict[str, str] = {}
    tok = _get_wraith_token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"

    try:
        timeout_cfg = aiohttp.ClientTimeout(total=max(10, int(timeout)))
        async with session.post(endpoint, json=payload, headers=headers, timeout=timeout_cfg) as resp:
            if resp.status == 200:
                j = await resp.json()
                md = j.get("markdown") or j.get("markdown_plain") or ""
                return md or ""
            return f"(failed to fetch markdown: {resp.status})"
    except Exception as e:
        return f"(failed to fetch markdown: {e})"


@mcp.tool()
async def google_search_markdown(
    query: str,
    num: int = 10,
    hl: str = "en",
    gl: str = "us",
    location: Optional[str] = None,
    device: str = "desktop",
    no_cache: bool = False,
    fetch_pages_top_k: int = 0,
) -> Dict[str, Any]:
    """Run a Google search and return a Markdown-formatted summary.

    Optionally fetches Markdown for the top K result links via the remote
    Wraith service. Set fetch_pages_top_k > 0 to enable.
    """
    base = await google_search(query, num=num, hl=hl, gl=gl, location=location, device=device, no_cache=no_cache)
    if not base.get("success"):
        return base

    lines: List[str] = []
    lines.append(f"# Google Search: {query}")
    info = base.get("search_information") or {}
    displayed = info.get("query_displayed") or query
    total_results = info.get("total_results")
    if total_results is not None:
        lines.append(f"- Total results: {total_results}")
    lines.append("")
    lines.append("## Top Results")

    organic = base.get("organic_results") or []
    if not organic and base.get("news_results"):
        organic = base.get("news_results") or []

    for item in organic[: max(1, min(int(num), 100))]:
        lines.append(_format_result_item(item))

    # Optionally fetch Markdown from top K links
    k = max(0, min(int(fetch_pages_top_k), len(organic)))
    if k > 0:
        lines.append("")
        lines.append("## Page Markdown (Top Results)")
        timeout_cfg = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout_cfg) as session:
            for idx, item in enumerate(organic[:k], start=1):
                link = item.get("link") or item.get("url")
                title = item.get("title") or item.get("name") or link or f"Result {idx}"
                if not link:
                    continue
                md = await _wraith_markdown(session, link)
                lines.append("")
                lines.append(f"### {idx}. {title}")
                lines.append(f"Source: {link}")
                lines.append("")
                if md:
                    # keep it bounded if extremely long
                    if len(md) > 8000:
                        md = md[:8000] + "\n\n… (truncated)"
                    lines.append(md)
                else:
                    lines.append("(no markdown extracted)")

    return {"success": True, "markdown": "\n".join(lines), "query": displayed}


if __name__ == "__main__":
    mcp.run(transport="stdio")
