#!/usr/bin/env python3
"""MCP: env-test

Bare bones test to check environment variables and call Anthropic API.
"""

from __future__ import annotations

import os
import sys
from typing import Dict

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    anthropic = None
    ANTHROPIC_AVAILABLE = False

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("env-test")


@mcp.tool()
async def check_env() -> Dict[str, object]:
    """Check if ANTHROPIC_API_KEY environment variable is set.

    Returns:
        Dictionary with environment variable status.

    Example:
        check_env()
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")

    if api_key:
        return {
            "success": True,
            "key_set": True,
            "key_length": len(api_key),
            "key_prefix": api_key[:10] + "..." if len(api_key) > 10 else api_key,
            "message": f"ANTHROPIC_API_KEY is set ({len(api_key)} chars)"
        }
    else:
        return {
            "success": True,
            "key_set": False,
            "message": "ANTHROPIC_API_KEY is NOT set"
        }


@mcp.tool()
async def say_hello() -> Dict[str, object]:
    """Call Anthropic API to say hello.

    Returns:
        Dictionary with Claude's response or error.

    Example:
        say_hello()
    """
    if not ANTHROPIC_AVAILABLE:
        return {
            "success": False,
            "error": "anthropic package not available"
        }

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {
            "success": False,
            "error": "ANTHROPIC_API_KEY environment variable not set"
        }

    try:
        client = anthropic.Anthropic(api_key=api_key)

        message = client.messages.create(
            model="claude-3-5-sonnet-20240620",
            max_tokens=100,
            messages=[{"role": "user", "content": "Say hello"}]
        )

        return {
            "success": True,
            "response": message.content[0].text,
            "model": message.model,
            "usage": {
                "input_tokens": message.usage.input_tokens,
                "output_tokens": message.usage.output_tokens
            }
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


if __name__ == "__main__":
    print(f"[env-test] Starting MCP server", file=sys.stderr, flush=True)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        print(f"[env-test] ANTHROPIC_API_KEY found: {len(api_key)} chars", file=sys.stderr, flush=True)
    else:
        print(f"[env-test] ANTHROPIC_API_KEY not found", file=sys.stderr, flush=True)

    print(f"[env-test] Anthropic SDK available: {ANTHROPIC_AVAILABLE}", file=sys.stderr, flush=True)

    mcp.run()
