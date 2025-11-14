#!/usr/bin/env python3
"""MCP: monitor-env

Manage environment variables for Codex monitor sessions.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from mcp.server.fastmcp import FastMCP

import sys

HELPER_PATHS = [
    Path(__file__).resolve().parent.parent / "monitor_scheduler.py",
    Path("/opt/scripts/monitor_scheduler.py"),
]

for candidate in HELPER_PATHS:
    if candidate.exists():
        helper_dir = candidate.parent
        if str(helper_dir) not in sys.path:
            sys.path.insert(0, str(helper_dir))
        break

from monitor_scheduler import get_session_env_path


LOG_PATH = Path(__file__).resolve().parent / "monitor-env.log"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler()
    ],
)

logger = logging.getLogger("monitor-env")
mcp = FastMCP("monitor-env")


def _parse_env_file(env_path: Path) -> Dict[str, str]:
    """Parse .env file into key-value pairs."""
    env_vars = {}
    if not env_path.exists():
        return env_vars

    try:
        content = env_path.read_text(encoding="utf-8")
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                env_vars[key.strip()] = value.strip().strip('"').strip("'")
    except Exception as e:
        logger.error(f"Error parsing env file {env_path}: {e}")

    return env_vars


def _write_env_file(env_path: Path, env_vars: Dict[str, str]):
    """Write environment variables to .env file."""
    lines = []
    for key, value in sorted(env_vars.items()):
        # Quote values that contain spaces
        if " " in value:
            lines.append(f'{key}="{value}"')
        else:
            lines.append(f"{key}={value}")

    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@mcp.tool()
async def monitor_set_env(session_id: str, key: str, value: str) -> Dict[str, Any]:
    """
    Set an environment variable for a monitor session.

    Args:
        session_id: The session ID
        key: Environment variable name (e.g., "ANTHROPIC_API_KEY")
        value: Environment variable value

    Returns:
        Success status and confirmation
    """
    try:
        env_path = get_session_env_path(session_id)
        env_vars = _parse_env_file(env_path)

        # Update or add the variable
        old_value = env_vars.get(key)
        env_vars[key] = value

        # Write back to file
        _write_env_file(env_path, env_vars)

        logger.info(f"Set env var {key} for session {session_id}")

        return {
            "success": True,
            "session_id": session_id,
            "key": key,
            "action": "updated" if old_value else "created",
            "env_file": str(env_path)
        }

    except Exception as e:
        logger.error(f"Failed to set env var: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
async def monitor_get_env(session_id: str, key: str) -> Dict[str, Any]:
    """
    Get an environment variable value for a monitor session.

    Args:
        session_id: The session ID
        key: Environment variable name

    Returns:
        The value if found, or error if not found
    """
    try:
        env_path = get_session_env_path(session_id)
        env_vars = _parse_env_file(env_path)

        if key in env_vars:
            return {
                "success": True,
                "session_id": session_id,
                "key": key,
                "value": env_vars[key]
            }
        else:
            return {
                "success": False,
                "error": f"Environment variable '{key}' not found"
            }

    except Exception as e:
        logger.error(f"Failed to get env var: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
async def monitor_delete_env(session_id: str, key: str) -> Dict[str, Any]:
    """
    Delete an environment variable from a monitor session.

    Args:
        session_id: The session ID
        key: Environment variable name to delete

    Returns:
        Success status
    """
    try:
        env_path = get_session_env_path(session_id)
        env_vars = _parse_env_file(env_path)

        if key in env_vars:
            del env_vars[key]
            _write_env_file(env_path, env_vars)
            logger.info(f"Deleted env var {key} for session {session_id}")

            return {
                "success": True,
                "session_id": session_id,
                "key": key,
                "action": "deleted"
            }
        else:
            return {
                "success": False,
                "error": f"Environment variable '{key}' not found"
            }

    except Exception as e:
        logger.error(f"Failed to delete env var: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
async def monitor_list_env(session_id: str, show_values: bool = False) -> Dict[str, Any]:
    """
    List all environment variables for a monitor session.

    Args:
        session_id: The session ID
        show_values: If True, show actual values. If False, mask them (default: False)

    Returns:
        Dictionary of environment variables (masked or full values)
    """
    try:
        env_path = get_session_env_path(session_id)
        env_vars = _parse_env_file(env_path)

        if show_values:
            vars_output = env_vars
        else:
            # Mask values for security
            vars_output = {k: "***" for k in env_vars.keys()}

        return {
            "success": True,
            "session_id": session_id,
            "count": len(env_vars),
            "env_file": str(env_path),
            "variables": vars_output
        }

    except Exception as e:
        logger.error(f"Failed to list env vars: {e}")
        return {
            "success": False,
            "error": str(e)
        }


if __name__ == "__main__":
    mcp.run()
