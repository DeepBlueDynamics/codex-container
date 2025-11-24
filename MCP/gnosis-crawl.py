#!/usr/bin/env python3
"""
Gnosis Crawl MCP Bridge
=======================

Exposes Wraith crawler capabilities to Codex via MCP, mirroring
the MCP style used in this repo (FastMCP over stdio).

Defaults to LOCAL crawling (gnosis-crawl:8080) with NO AUTH required.
Automatically fixes localhost/127.0.0.1 references to gnosis-crawl:8080.

Tools:
  - crawl_url: fetch markdown from a single URL (supports JS injection)
  - crawl_batch: process multiple URLs (supports JS injection, async/collated)
  - raw_html: fetch raw HTML without markdown conversion
  - set_auth_token: save Wraith API token to .wraithenv (optional)
  - crawl_status: report configuration (base URL, token presence)

JavaScript Injection for Markdown Extraction:
  - For crawl_url and crawl_batch: pass javascript_payload to inject code
  - The JavaScript will execute FIRST on the page, modifying the DOM
  - Then markdown extraction will run on the modified content
  - Useful for expanding hidden content, interacting with JS, etc.

Env/config:
  - WRAITH_AUTH_TOKEN        (optional, preferred if present)
  - GNOSIS_CRAWL_BASE_URL    (overrides default gnosis-crawl:8080)
  - .wraithenv file in repo root with line: WRAITH_AUTH_TOKEN=...

Defaults:
  - Local: "http://gnosis-crawl:8080" (default, always used unless overridden)
  - Auth: None required
"""

import os
from typing import Any, Dict, List, Optional

import aiohttp
from mcp.server.fastmcp import FastMCP, Context
from urllib.parse import urlparse

mcp = FastMCP("gnosis-crawl")

# Default to local gnosis-crawl:8080 - always the primary server
LOCAL_SERVER_URL = "http://gnosis-crawl:8080"
WRAITH_ENV_FILE = os.path.join(os.getcwd(), ".wraithenv")


def _normalize_server_url(url: str) -> str:
    """
    Normalize server URLs, converting localhost/127.0.0.1 to gnosis-crawl:8080.
    
    If someone passes localhost or 127.0.0.1 with any port, convert it to the
    standard gnosis-crawl:8080 local server.
    
    Args:
        url: Server URL to normalize
    
    Returns:
        str: Normalized URL (gnosis-crawl:8080 if localhost detected, otherwise original)
    """
    if not url:
        return LOCAL_SERVER_URL
    
    try:
        parsed = urlparse(url)
        # Fix localhost/127.0.0.1 references to use gnosis-crawl:8080
        if parsed.hostname in ("localhost", "127.0.0.1"):
            return LOCAL_SERVER_URL
    except Exception:
        pass
    
    return url


def _extract_domain(url: str) -> str:
    """
    Extract the domain name from a URL for storage organization.
    
    Args:
        url: Full URL to parse (e.g., "https://example.com/path")
    
    Returns:
        str: Lowercase domain name (e.g., "example.com") or "unknown" if parsing fails
    """
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return "unknown"

def _is_google_host(url: str) -> bool:
    """Block direct Google crawling so users route through the serpapi-search MCP tool."""
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        host = ""
    host = host.lower()
    return host.endswith("google.com")

def _get_auth_token() -> Optional[str]:
    """
    Retrieve Wraith API authentication token from environment or .wraithenv file.
    
    Checks WRAITH_AUTH_TOKEN environment variable first, then falls back to
    reading from .wraithenv file in the current working directory.
    
    Returns None by default (no auth required for local gnosis-crawl:8080).
    
    Returns:
        Optional[str]: Authentication token if found, None otherwise
    """
    # Env wins
    tok = os.environ.get("WRAITH_AUTH_TOKEN")
    if tok:
        return tok.strip()
    # Fallback to .wraithenv
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



def _resolve_base_url(server_url: Optional[str] = None) -> str:
    """
    Determine which Wraith server URL to use (defaults to gnosis-crawl:8080).
    
    Args:
        server_url: Optional explicit server URL. Automatically normalized
                   (localhost/127.0.0.1 converted to gnosis-crawl:8080)
    
    Returns:
        str: The resolved base URL for API calls (gnosis-crawl:8080 by default)
    """
    # If explicit server_url provided, normalize it
    if server_url:
        return _normalize_server_url(server_url)
    
    # Default to local gnosis-crawl:8080
    return LOCAL_SERVER_URL



@mcp.tool()
async def set_auth_token(token: str, ctx: Context = None) -> Dict[str, Any]:
    """
    Save Wraith API authentication token to .wraithenv file (optional).
    
    Stores the token persistently so it doesn't need to be passed with each request.
    The token is saved in .wraithenv in the current working directory.
    
    Note: auth is not required for local gnosis-crawl:8080.
    
    Args:
        token: Wraith API authentication token to save
        ctx: MCP context (optional)
    
    Returns:
        Dict[str, Any]: Success status and file path where token was saved
    """

    if not token:
        return {"success": False, "error": "No token provided"}
    try:
        with open(WRAITH_ENV_FILE, "w", encoding="utf-8") as f:
            f.write(f"WRAITH_AUTH_TOKEN={token}\n")
        return {"success": True, "message": "Saved token to .wraithenv", "file": WRAITH_ENV_FILE}
    except Exception as e:
        return {"success": False, "error": f"Failed to save token: {e}"}


@mcp.tool()
async def crawl_status(server_url: Optional[str] = None) -> Dict[str, Any]:
    """
    Check Wraith crawler configuration and connection status.
    
    Reports the server URL being used (defaults to gnosis-crawl:8080) and 
    whether an auth token is configured. Auth is optional for local server.
    
    Args:
        server_url: Optional explicit server URL to check (defaults to gnosis-crawl:8080)
    
    Returns:
        Dict[str, Any]: Server URL being used and token availability status
    """

    base = _resolve_base_url(server_url)
    return {
        "success": True,
        "base_url": base,
        "token_present": _get_auth_token() is not None,
        "auth_required": False,  # Auth not required for local gnosis-crawl:8080
    }


@mcp.tool()
async def crawl_url(
    url: str,
    take_screenshot: bool = False,
    javascript_enabled: bool = False,
    javascript_payload: Optional[str] = None,
    markdown_extraction: str = "enhanced",
    server_url: Optional[str] = None,
    timeout: int = 30,
    title: Optional[str] = None,
    ctx: Context = None,
) -> Dict[str, Any]:
    """
    Crawl a single URL and extract clean markdown content.
    
    Fetches a web page through the Wraith API on gnosis-crawl:8080 (local default),
    which handles JavaScript rendering, content extraction, and markdown conversion.
    Returns structured markdown optimized for AI consumption.
    
    JavaScript injection: If javascript_payload is provided, it will be executed
    FIRST on the page, then markdown extraction will run on the modified content.
    
    Defaults to LOCAL gnosis-crawl:8080 with NO AUTH required.
    
    Args:
        url: Target URL to crawl
        take_screenshot: If True, capture a full-page screenshot
        javascript_enabled: If True, execute JavaScript before extracting content
        javascript_payload: Optional JavaScript code to inject and execute BEFORE
                          markdown extraction. Runs first, then markdown processes
                          the modified page content.
        markdown_extraction: Extraction mode ("enhanced" applies content pruning)
        server_url: Optional explicit server URL (defaults to gnosis-crawl:8080)
        timeout: Request timeout in seconds (minimum 5)
        title: Optional title for the crawl report (defaults to domain name)
        ctx: MCP context (optional)
    
    Returns:
        Dict[str, Any]: Crawl results including markdown content, metadata, and any errors
    """

    if not url:
        return {"success": False, "error": "No URL provided"}
    if _is_google_host(url):
        return {
            "success": False,
            "error": "Direct Google crawling is disabled—use the serpapi-search MCP tools instead.",
        }

    base = _resolve_base_url(server_url)
    endpoint = f"{base}/api/markdown"

    if not title:
        title = f"Crawl: {_extract_domain(url)}"

    payload: Dict[str, Any] = {
        "url": url,
        "javascript_enabled": bool(javascript_enabled),
        "screenshot_mode": "full" if take_screenshot else None,
    }
    # Inject JavaScript BEFORE markdown extraction
    if javascript_payload:
        payload["javascript_payload"] = javascript_payload
    
    if markdown_extraction == "enhanced":
        payload["filter"] = "pruning"
        payload["filter_options"] = {"threshold": 0.48, "min_words": 2}

    headers: Dict[str, str] = {}
    tok = _get_auth_token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"

    try:
        timeout_cfg = aiohttp.ClientTimeout(total=max(5, int(timeout)))
        async with aiohttp.ClientSession(timeout=timeout_cfg) as session:
            async with session.post(endpoint, json=payload, headers=headers) as resp:
                if resp.status == 200:
                    return await resp.json()
                return {"success": False, "error": f"{resp.status}: {await resp.text()}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def crawl_batch(
    urls: List[str],
    javascript_enabled: bool = False,
    javascript_payload: Optional[str] = None,
    take_screenshot: bool = False,
    async_mode: bool = True,
    collate: bool = False,
    collate_title: Optional[str] = None,
    server_url: Optional[str] = None,
    timeout: int = 60,
    ctx: Context = None,
) -> Dict[str, Any]:
    """
    Crawl multiple URLs in a single batch operation.
    
    Processes multiple URLs through Wraith on gnosis-crawl:8080 (local default),
    with options for asynchronous processing and automatic collation into a 
    single markdown document. Max 50 URLs per batch.
    
    JavaScript injection: If javascript_payload is provided, it will be executed
    FIRST on each page, then markdown extraction will run on the modified content.
    
    Defaults to LOCAL gnosis-crawl:8080 with NO AUTH required.
    
    Args:
        urls: List of URLs to crawl (max 50)
        javascript_enabled: If True, execute JavaScript on each page
        javascript_payload: Optional JavaScript code to inject and execute BEFORE
                          markdown extraction on each URL. Runs first, then markdown
                          processes the modified page content.
        take_screenshot: If True, capture screenshots for each URL
        async_mode: If True, process URLs asynchronously (faster)
        collate: If True, combine all results into a single markdown document
        collate_title: Title for collated document (auto-generated if not provided)
        server_url: Optional explicit server URL (defaults to gnosis-crawl:8080)
        timeout: Request timeout in seconds (minimum 10)
        ctx: MCP context (optional)
    
    Returns:
        Dict[str, Any]: Batch crawl results, either individual or collated markdown
    """

    if not urls:
        return {"success": False, "error": "No URLs provided"}
    if len(urls) > 50:
        return {"success": False, "error": "Maximum 50 URLs allowed per batch"}
    for target in urls:
        if _is_google_host(target):
            return {
                "success": False,
                "error": "Direct Google crawling is disabled—use the serpapi-search MCP tools instead.",
            }

    base = _resolve_base_url(server_url)
    endpoint = f"{base}/api/markdown"

    payload: Dict[str, Any] = {
        "url": urls,
        "javascript_enabled": bool(javascript_enabled),
        "screenshot_mode": "full" if take_screenshot else None,
        "async": bool(async_mode),
        "collate": bool(collate),
    }
    # Inject JavaScript BEFORE markdown extraction
    if javascript_payload:
        payload["javascript_payload"] = javascript_payload
    
    if collate:
        payload["collate_options"] = {
            "title": collate_title or f"Batch Crawl Results ({len(urls)} URLs)",
            "add_toc": True,
            "add_source_headers": True,
        }

    headers: Dict[str, str] = {}
    tok = _get_auth_token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"

    try:
        timeout_cfg = aiohttp.ClientTimeout(total=max(10, int(timeout)))
        async with aiohttp.ClientSession(timeout=timeout_cfg) as session:
            async with session.post(endpoint, json=payload, headers=headers) as resp:
                if resp.status in (200, 202):
                    return await resp.json()
                return {"success": False, "error": f"{resp.status}: {await resp.text()}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def raw_html(
    url: str,
    javascript_enabled: bool = True,
    javascript_payload: Optional[str] = None,
    server_url: Optional[str] = None,
    timeout: int = 30,
    ctx: Context = None,
) -> Dict[str, Any]:
    """
    Fetch raw HTML from a URL without markdown conversion.
    
    Returns the raw HTML source from a web page via gnosis-crawl:8080 (local default),
    optionally with JavaScript execution. Useful when you need the actual HTML 
    structure rather than cleaned markdown content.
    
    Defaults to LOCAL gnosis-crawl:8080 with NO AUTH required.
    
    Args:
        url: Target URL to fetch
        javascript_enabled: If True, execute JavaScript before capturing HTML
        javascript_payload: Optional JavaScript code to execute on the page
        server_url: Optional explicit server URL (defaults to gnosis-crawl:8080)
        timeout: Request timeout in seconds (minimum 5)
        ctx: MCP context (optional)
    
    Returns:
        Dict[str, Any]: Raw HTML content and metadata
    """

    if not url:
        return {"success": False, "error": "No URL provided"}
    if _is_google_host(url):
        return {
            "success": False,
            "error": "Direct Google crawling is disabled—use the serpapi-search MCP tools instead.",
        }

    base = _resolve_base_url(server_url)
    endpoint = f"{base}/api/raw"

    payload: Dict[str, Any] = {
        "url": url,
        "javascript_enabled": bool(javascript_enabled),
    }
    if javascript_payload:
        payload["javascript_payload"] = javascript_payload

    headers: Dict[str, str] = {}
    tok = _get_auth_token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"

    try:
        timeout_cfg = aiohttp.ClientTimeout(total=max(5, int(timeout)))
        async with aiohttp.ClientSession(timeout=timeout_cfg) as session:
            async with session.post(endpoint, json=payload, headers=headers) as resp:
                if resp.status == 200:
                    return await resp.json()
                return {"success": False, "error": f"{resp.status}: {await resp.text()}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    mcp.run(transport="stdio")
