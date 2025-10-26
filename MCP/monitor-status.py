#!/usr/bin/env python3
"""MCP: monitor-status

Check the status of the file monitor queue and processing state.
"""

from __future__ import annotations

import sys
import json
from pathlib import Path
from typing import Dict

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("monitor-status")


@mcp.tool()
async def check_monitor_status(
    watch_path: str = "/workspace/recordings"
) -> Dict[str, object]:
    """Check the current status of the file monitor.

    Args:
        watch_path: Directory being monitored (default: /workspace/recordings)

    Returns:
        Dictionary with monitor status including:
        - is_running: Whether monitor is active
        - processing: Whether Codex is currently processing files
        - queued_files: Number of files waiting to be processed
        - session_id: Current monitor session ID

    Example:
        check_monitor_status(watch_path="/workspace/recordings")
    """

    try:
        watch_dir = Path(watch_path)
        session_file = watch_dir / ".codex-monitor-session"

        # Check if session file exists (indicates monitor has run)
        if not session_file.exists():
            return {
                "success": True,
                "is_running": False,
                "processing": False,
                "queued_files": 0,
                "session_id": None,
                "message": "Monitor not active or never started"
            }

        # Read session ID
        session_id = session_file.read_text().strip()

        # In the future, we could add a status file that monitor writes to
        # For now, we just check if session exists
        return {
            "success": True,
            "is_running": True,
            "processing": False,  # Would need monitor to write status file
            "queued_files": 0,  # Would need monitor to write status file
            "session_id": session_id,
            "message": f"Monitor session active: {session_id}"
        }

    except Exception as e:
        print(f"❌ Failed to check monitor status: {e}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return {
            "success": False,
            "error": str(e),
            "message": "Failed to check monitor status"
        }


if __name__ == "__main__":
    mcp.run()
