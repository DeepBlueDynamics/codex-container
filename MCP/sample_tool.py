#!/usr/bin/env python3
"""Sample MCP server providing a hello_world tool for testing."""

from __future__ import annotations

from typing import Dict

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("sample-tool")


@mcp.tool()
async def hello_world(name: str = "Codex") -> Dict[str, str]:
    """Return a friendly greeting.

    Args:
        name: Name to include in the greeting.
    """
    return {"message": f"Hello {name}, MCP sample tool is ready!"}


if __name__ == "__main__":
    mcp.run()
