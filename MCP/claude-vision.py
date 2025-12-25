#!/usr/bin/env python3
"""
MCP: claude-vision

Send image(s) + prompt to Anthropic Claude via the Messages API.
"""

from __future__ import annotations

import base64
import mimetypes
import os
from pathlib import Path
from typing import Dict, List, Optional

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    anthropic = None
    ANTHROPIC_AVAILABLE = False

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("claude-vision")

DEFAULT_MODEL = os.getenv("CLAUDE_VISION_MODEL", "claude-sonnet-4-5-20250929")


def _encode_image(path: Path) -> Dict[str, str]:
    data = path.read_bytes()
    mime, _ = mimetypes.guess_type(path.name)
    mime = mime or "application/octet-stream"
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": mime,
            "data": base64.b64encode(data).decode("utf-8"),
        },
    }


@mcp.tool()
async def claude_vision(
    prompt: str,
    image_paths: List[str],
    system: str = "",
    model: Optional[str] = None,
    max_tokens: int = 1024,
) -> Dict[str, object]:
    """
    Send image(s) + prompt to Claude.

    Args:
        prompt: User prompt
        image_paths: List of image file paths (PNG/JPG)
        system: Optional system prompt
        model: Claude model ID
        max_tokens: Output token limit
    """
    if not ANTHROPIC_AVAILABLE:
        return {"success": False, "error": "anthropic_package_missing"}
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {"success": False, "error": "ANTHROPIC_API_KEY_not_set"}
    if not prompt:
        return {"success": False, "error": "prompt_required"}
    if not image_paths:
        return {"success": False, "error": "image_paths_required"}

    parts: List[Dict[str, object]] = [{"type": "text", "text": prompt}]
    for p in image_paths:
        path = Path(p)
        if not path.exists():
            return {"success": False, "error": f"image_not_found: {path}"}
        parts.append(_encode_image(path))

    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=model or DEFAULT_MODEL,
            max_tokens=max_tokens,
            system=system or None,
            messages=[{"role": "user", "content": parts}],
        )
        text = message.content[0].text if message.content else ""
        return {
            "success": True,
            "model": message.model,
            "response": text,
            "usage": {
                "input_tokens": message.usage.input_tokens,
                "output_tokens": message.usage.output_tokens,
            },
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    mcp.run()
