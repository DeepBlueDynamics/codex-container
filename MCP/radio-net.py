#!/usr/bin/env python3
"""MCP: radio-net

Maritime radio network communication system for agent-to-agent transmissions.

Allows Alpha India to transmit messages to Alpha Tango (Captain Torwick's T-Deck)
and other callsigns on the maritime radio network.

**MOCK IMPLEMENTATION**: Currently logs transmissions to file for development.
Future: Connect to actual T-Deck hardware/API.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict
import json

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("radio-net")

# Radio network transmission log
TRANSMISSION_LOG = Path("/workspace/radio_transmissions.log")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _format_timestamp(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S %Z")


@mcp.tool()
async def radio_net_transmit(
    callsign: str,
    message: str,
    priority: str = "ROUTINE",
    sender: str = "ALPHAINDIA",
) -> Dict[str, object]:
    """Transmit message over maritime radio network to specified callsign.

    Use this to contact Alpha Tango (Captain Torwick's T-Deck) or other agents
    on the maritime radio network.

    Args:
        callsign: Destination callsign (e.g., "ALPHATANGO", "ALPHAINDIA")
        message: Message content to transmit
        priority: Message priority - "ROUTINE", "PRIORITY", "URGENT", "DISTRESS" (default: "ROUTINE")
        sender: Sender callsign (default: "ALPHAINDIA")

    Returns:
        Dictionary with transmission status and details.

    Example:
        radio_net_transmit(
            callsign="ALPHATANGO",
            message="Weather check complete. Miami: 24.5°C, winds 12 kn from NE. Conditions favorable.",
            priority="ROUTINE"
        )
    """

    if not callsign:
        return {
            "success": False,
            "error": "callsign is required"
        }

    if not message:
        return {
            "success": False,
            "error": "message is required"
        }

    # Validate priority
    valid_priorities = ["ROUTINE", "PRIORITY", "URGENT", "DISTRESS"]
    priority_upper = priority.upper()
    if priority_upper not in valid_priorities:
        return {
            "success": False,
            "error": f"Invalid priority. Must be one of: {', '.join(valid_priorities)}"
        }

    now = _utc_now()
    timestamp = _format_timestamp(now)

    # Create transmission record
    transmission = {
        "timestamp": now.isoformat(),
        "from": sender.upper(),
        "to": callsign.upper(),
        "priority": priority_upper,
        "message": message,
        "status": "TRANSMITTED",
    }

    # Log transmission to file
    try:
        TRANSMISSION_LOG.parent.mkdir(parents=True, exist_ok=True)

        with open(TRANSMISSION_LOG, "a", encoding="utf-8") as f:
            f.write("=" * 80 + "\n")
            f.write(f"TRANSMISSION at {timestamp}\n")
            f.write(f"FROM: {transmission['from']}\n")
            f.write(f"TO: {transmission['to']}\n")
            f.write(f"PRIORITY: {transmission['priority']}\n")
            f.write("-" * 80 + "\n")
            f.write(f"{message}\n")
            f.write("=" * 80 + "\n\n")

        print(f"📡 Radio transmission sent to {callsign}", file=sys.stderr, flush=True)
        print(f"   FROM: {sender}", file=sys.stderr, flush=True)
        print(f"   TO: {callsign}", file=sys.stderr, flush=True)
        print(f"   PRIORITY: {priority_upper}", file=sys.stderr, flush=True)
        print(f"   MESSAGE: {message[:80]}{'...' if len(message) > 80 else ''}", file=sys.stderr, flush=True)
        print(f"   Logged to: {TRANSMISSION_LOG}", file=sys.stderr, flush=True)

        return {
            "success": True,
            "status": "transmitted",
            "from": transmission["from"],
            "to": transmission["to"],
            "priority": transmission["priority"],
            "timestamp": transmission["timestamp"],
            "message_length": len(message),
            "log_file": str(TRANSMISSION_LOG),
            "message": f"Transmission sent to {callsign} and logged to {TRANSMISSION_LOG}",
            "note": "MOCK: Currently logging only. Future implementation will connect to T-Deck hardware."
        }

    except Exception as e:
        print(f"⚠️  Radio transmission failed: {e}", file=sys.stderr, flush=True)
        return {
            "success": False,
            "error": f"Transmission failed: {str(e)}"
        }


@mcp.tool()
async def radio_net_receive(
    callsign: str = "ALPHAINDIA",
    limit: int = 10,
) -> Dict[str, object]:
    """Check for incoming radio transmissions addressed to specified callsign.

    Args:
        callsign: Your callsign to check for messages (default: "ALPHAINDIA")
        limit: Maximum number of recent messages to retrieve (default: 10)

    Returns:
        Dictionary with received messages.

    Example:
        radio_net_receive(callsign="ALPHAINDIA", limit=5)
    """

    if not TRANSMISSION_LOG.exists():
        return {
            "success": True,
            "callsign": callsign.upper(),
            "message_count": 0,
            "messages": [],
            "note": "No transmissions logged yet"
        }

    try:
        # Read transmission log and parse messages addressed to this callsign
        with open(TRANSMISSION_LOG, "r", encoding="utf-8") as f:
            content = f.read()

        # Simple parsing - look for messages TO: this callsign
        messages = []
        blocks = content.split("=" * 80)

        for block in blocks:
            if not block.strip():
                continue

            lines = block.strip().split("\n")
            msg_data = {}

            for line in lines:
                if line.startswith("TRANSMISSION at "):
                    msg_data["timestamp"] = line.replace("TRANSMISSION at ", "").strip()
                elif line.startswith("FROM: "):
                    msg_data["from"] = line.replace("FROM: ", "").strip()
                elif line.startswith("TO: "):
                    msg_data["to"] = line.replace("TO: ", "").strip()
                elif line.startswith("PRIORITY: "):
                    msg_data["priority"] = line.replace("PRIORITY: ", "").strip()
                elif line.startswith("-" * 80):
                    # Message content follows
                    idx = lines.index(line)
                    if idx + 1 < len(lines):
                        msg_data["message"] = lines[idx + 1].strip()

            # Only include if addressed to this callsign
            if msg_data.get("to", "").upper() == callsign.upper():
                messages.append(msg_data)

        # Return most recent messages
        messages = messages[-limit:] if limit > 0 else messages

        print(f"📻 Checked radio network for {callsign}", file=sys.stderr, flush=True)
        print(f"   Found {len(messages)} message(s)", file=sys.stderr, flush=True)

        return {
            "success": True,
            "callsign": callsign.upper(),
            "message_count": len(messages),
            "messages": messages,
            "log_file": str(TRANSMISSION_LOG)
        }

    except Exception as e:
        print(f"⚠️  Radio receive failed: {e}", file=sys.stderr, flush=True)
        return {
            "success": False,
            "error": f"Receive failed: {str(e)}"
        }


if __name__ == "__main__":
    mcp.run()
