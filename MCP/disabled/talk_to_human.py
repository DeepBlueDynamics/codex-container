#!/usr/bin/env python3
"""MCP: talk-to-human

Emit a natural-language message intended for the operator. The tool does not
perform any side effects beyond returning the content; Codex should call it
whenever it needs to speak directly to the human outside the usual response
channel (for example, when another tool invocation is still running).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("talk-to-human")


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S %Z")


@mcp.tool()
async def talk_to_human(message: str) -> Dict[str, str]:
    """Package a message to the human along with a polite wait reminder."""

    trimmed = message.strip()
    if not trimmed:
        trimmed = "(no message provided)"

    reply = f"{_utc_stamp()} :: {trimmed}\n\nPLEASE WAIT FOR HUMAN RESPONSE BEFORE PROCEEDING."
    return {
        "success": True,
        "utterance": reply,
    }


if __name__ == "__main__":
    mcp.run()
