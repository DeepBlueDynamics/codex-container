#!/usr/bin/env python3
"""
MCP server for OpenSearch.

Environment variables:
  OPENSEARCH_URL          Base URL, e.g. http://localhost:9200 (default)
  OPENSEARCH_USER         Optional basic auth user
  OPENSEARCH_PASS         Optional basic auth password
  OPENSEARCH_VERIFY_TLS   "true"/"false" (default true)
  OPENSEARCH_TIMEOUT      Request timeout seconds (default 10)

Tools:
  os_health() -> cluster ping/health
  os_list_indices(pattern="*")
  os_create_index(index, settings=None, mappings=None)
  os_delete_index(index)
  os_index_doc(index, doc, id=None, refresh=False)
  os_get_doc(index, id)
  os_delete_doc(index, id, refresh=False)
  os_search(index, query: dict, size=10, from_=0)
"""
from __future__ import annotations

import os
import urllib.parse
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP
from opensearchpy import OpenSearch, RequestsHttpConnection
from opensearchpy.exceptions import OpenSearchException

mcp = FastMCP("open-search")


def _env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return str(val).lower() in ("1", "true", "yes", "on")


def _client() -> OpenSearch:
    # Prefer explicit env; otherwise default to service name on the codex-network
    url = os.environ.get("OPENSEARCH_URL", "http://gnosis-opensearch:9200")
    parsed = urllib.parse.urlparse(url)
    if not parsed.scheme or not parsed.hostname:
        raise RuntimeError(f"Invalid OPENSEARCH_URL: {url}")
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    use_ssl = parsed.scheme == "https"
    verify = _env_bool("OPENSEARCH_VERIFY_TLS", True)
    timeout = float(os.environ.get("OPENSEARCH_TIMEOUT", "10"))
    http_auth = None
    user = os.environ.get("OPENSEARCH_USER")
    pwd = os.environ.get("OPENSEARCH_PASS")
    if user:
        http_auth = (user, pwd or "")
    return OpenSearch(
        hosts=[{"host": host, "port": port, "scheme": parsed.scheme}],
        http_auth=http_auth,
        use_ssl=use_ssl,
        verify_certs=verify,
        ssl_show_warn=False,
        connection_class=RequestsHttpConnection,
        timeout=timeout,
    )


def _err(e: Exception) -> RuntimeError:
    return RuntimeError(f"opensearch error: {e}")


@mcp.tool()
async def os_health() -> Dict[str, Any]:
    """Return basic cluster health info."""
    try:
        with _client() as cli:
            return {"ping": bool(cli.ping()), "health": cli.cluster.health()}
    except OpenSearchException as e:
        raise _err(e)


@mcp.tool()
async def os_list_indices(pattern: str = "*") -> List[str]:
    """List indices matching pattern (default '*')."""
    try:
        with _client() as cli:
            # CatClient.indices signature: indices(self, params=None, headers=None)
            cats = cli.cat.indices(params={"index": pattern, "h": "index", "format": "json"})
            return [c.get("index") for c in cats if c.get("index")]
    except OpenSearchException as e:
        raise _err(e)


@mcp.tool()
async def os_create_index(
    index: str,
    settings: Optional[Dict[str, Any]] = None,
    mappings: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create an index if it does not exist."""
    try:
        with _client() as cli:
            if cli.indices.exists(index=index):
                return {"acknowledged": True, "message": "exists"}
            body: Dict[str, Any] = {}
            if settings:
                body["settings"] = settings
            if mappings:
                body["mappings"] = mappings
            return cli.indices.create(index=index, body=body)
    except OpenSearchException as e:
        raise _err(e)


@mcp.tool()
async def os_delete_index(index: str) -> Dict[str, Any]:
    """Delete an index."""
    try:
        with _client() as cli:
            return cli.indices.delete(index=index, ignore_unavailable=False)
    except OpenSearchException as e:
        raise _err(e)


@mcp.tool()
async def os_index_doc(
    index: str,
    doc: Dict[str, Any],
    id: Optional[str] = None,
    refresh: bool = False,
) -> Dict[str, Any]:
    """Index a document (optional id)."""
    try:
        with _client() as cli:
            res = cli.index(index=index, id=id, body=doc, refresh="wait_for" if refresh else False)
            return res
    except OpenSearchException as e:
        raise _err(e)


@mcp.tool()
async def os_get_doc(index: str, id: str) -> Dict[str, Any]:
    """Get a document by id."""
    try:
        with _client() as cli:
            return cli.get(index=index, id=id)
    except OpenSearchException as e:
        raise _err(e)


@mcp.tool()
async def os_delete_doc(index: str, id: str, refresh: bool = False) -> Dict[str, Any]:
    """Delete a document by id."""
    try:
        with _client() as cli:
            return cli.delete(index=index, id=id, refresh="wait_for" if refresh else False)
    except OpenSearchException as e:
        raise _err(e)


@mcp.tool()
async def os_search(
    index: str,
    query: Dict[str, Any],
    size: int = 10,
    from_: int = 0,
) -> Dict[str, Any]:
    """Run a search query (DSL) on an index."""
    try:
        with _client() as cli:
            return cli.search(index=index, body=query, size=size, from_=from_)
    except OpenSearchException as e:
        raise _err(e)


if __name__ == "__main__":
    mcp.run()
