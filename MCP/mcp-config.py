#!/usr/bin/env python3
"""MCP: mcp-config

Manage which MCP tools are installed in the current workspace.

This tool allows discovering available MCP tools, viewing currently installed
tools, and modifying the workspace .codex-mcp.config file to add or remove
tools. Changes take effect on the next container restart.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

# Setup logging
log_dir = Path("/workspace/.mcp-logs")
log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / "mcp-config.log"),
    ]
)
logger = logging.getLogger("mcp-config")

mcp = FastMCP("mcp-config")

# Paths
MCP_SOURCE = Path("/opt/mcp-installed")
MCP_DEST = Path("/opt/codex-home/mcp")
WORKSPACE_CONFIG = Path("/workspace/.codex-mcp.config")
DEFAULT_CONFIG = MCP_SOURCE / ".codex-mcp.config"


def _list_available_tools() -> List[str]:
    """List all MCP tools available in the image."""
    if not MCP_SOURCE.exists():
        return []

    tools = []
    for f in sorted(MCP_SOURCE.glob("*.py")):
        # Skip helper modules (prefixed with _)
        if not f.name.startswith("_"):
            tools.append(f.name)

    return tools


def _list_installed_tools() -> List[str]:
    """List currently installed MCP tools."""
    if not MCP_DEST.exists():
        return []

    tools = []
    for f in sorted(MCP_DEST.glob("*.py")):
        if not f.name.startswith("_"):
            tools.append(f.name)

    return tools


def _read_config(config_path: Path) -> List[str]:
    """Read tool list from config file."""
    if not config_path.exists():
        return []

    tools = []
    try:
        for line in config_path.read_text(encoding="utf-8").splitlines():
            # Strip whitespace and carriage returns
            line = line.strip().rstrip('\r')
            # Skip empty lines and comments
            if not line or line.startswith("#"):
                continue
            tools.append(line)
    except Exception as e:
        logger.error(f"Failed to read config {config_path}: {e}")

    return tools


def _write_config(config_path: Path, tools: List[str]) -> None:
    """Write tool list to config file."""
    config_path.parent.mkdir(parents=True, exist_ok=True)

    lines = ["# MCP Tools Configuration\n"]
    lines.append("# One tool per line. Changes take effect on next container restart.\n")
    lines.append("\n")

    for tool in sorted(tools):
        lines.append(f"{tool}\n")

    config_path.write_text("".join(lines), encoding="utf-8")


@mcp.tool()
async def mcp_list_available() -> Dict[str, Any]:
    """List all MCP tools available in the Docker image.

    This shows all tools that can be installed, regardless of whether they're
    currently active in this workspace.

    Returns:
        Dictionary with list of available tool filenames.

    Example:
        {
            "success": true,
            "count": 34,
            "tools": ["time-tool.py", "calculate.py", "gnosis-crawl.py", ...]
        }
    """
    logger.info("Listing available MCP tools")

    try:
        tools = _list_available_tools()
        return {
            "success": True,
            "count": len(tools),
            "tools": tools,
            "source_path": str(MCP_SOURCE)
        }
    except Exception as e:
        logger.error(f"Failed to list available tools: {e}")
        return {"success": False, "error": str(e)}


@mcp.tool()
async def mcp_list_installed() -> Dict[str, Any]:
    """List currently installed (active) MCP tools in this workspace.

    These are the tools that were loaded at container startup based on the
    active .codex-mcp.config file.

    Returns:
        Dictionary with list of currently installed tool filenames.

    Example:
        {
            "success": true,
            "count": 12,
            "tools": ["time-tool.py", "gnosis-crawl.py", ...],
            "config_source": "workspace" or "default"
        }
    """
    logger.info("Listing installed MCP tools")

    try:
        tools = _list_installed_tools()

        # Determine if using workspace or default config
        config_source = "workspace" if WORKSPACE_CONFIG.exists() else "default"

        return {
            "success": True,
            "count": len(tools),
            "tools": tools,
            "config_source": config_source,
            "install_path": str(MCP_DEST)
        }
    except Exception as e:
        logger.error(f"Failed to list installed tools: {e}")
        return {"success": False, "error": str(e)}


@mcp.tool()
async def mcp_show_config() -> Dict[str, Any]:
    """Show the current MCP configuration for this workspace.

    Displays which config file is being used (workspace or default) and what
    tools are configured.

    Returns:
        Dictionary with configuration details and tool list.

    Example:
        {
            "success": true,
            "using_workspace_config": false,
            "config_path": "/opt/mcp-installed/.codex-mcp.config",
            "tools": ["time-tool.py", "calculate.py", ...],
            "note": "To customize, create /workspace/.codex-mcp.config"
        }
    """
    logger.info("Showing current MCP config")

    try:
        if WORKSPACE_CONFIG.exists():
            config_path = WORKSPACE_CONFIG
            using_workspace = True
            tools = _read_config(WORKSPACE_CONFIG)
            note = "Using workspace-specific configuration"
        elif DEFAULT_CONFIG.exists():
            config_path = DEFAULT_CONFIG
            using_workspace = False
            tools = _read_config(DEFAULT_CONFIG)
            note = "Using default configuration. Create /workspace/.codex-mcp.config to customize."
        else:
            return {
                "success": False,
                "error": "No configuration file found",
                "note": "Create /workspace/.codex-mcp.config to configure tools"
            }

        return {
            "success": True,
            "using_workspace_config": using_workspace,
            "config_path": str(config_path),
            "tools": tools,
            "count": len(tools),
            "note": note
        }
    except Exception as e:
        logger.error(f"Failed to show config: {e}")
        return {"success": False, "error": str(e)}


@mcp.tool()
async def mcp_add_tool(tool_name: str) -> Dict[str, Any]:
    """Add an MCP tool to the workspace configuration.

    Adds the specified tool to /workspace/.codex-mcp.config. If the workspace
    config doesn't exist, it will be created with the current default tools
    plus the new tool. Changes take effect on next container restart.

    Args:
        tool_name: Name of the tool file to add (e.g., "gnosis-crawl.py")

    Returns:
        Dictionary with success status and next steps.

    Example:
        {
            "success": true,
            "tool": "gnosis-crawl.py",
            "config_path": "/workspace/.codex-mcp.config",
            "message": "Added gnosis-crawl.py to configuration. Restart container to apply changes."
        }
    """
    logger.info(f"Adding tool: {tool_name}")

    try:
        # Validate tool exists
        available = _list_available_tools()
        if tool_name not in available:
            return {
                "success": False,
                "error": f"Tool '{tool_name}' not found in available tools",
                "available_tools": available
            }

        # Read current config (workspace or default)
        if WORKSPACE_CONFIG.exists():
            current_tools = _read_config(WORKSPACE_CONFIG)
            created_new = False
        elif DEFAULT_CONFIG.exists():
            # Create workspace config from default
            current_tools = _read_config(DEFAULT_CONFIG)
            created_new = True
        else:
            # Start with empty config
            current_tools = []
            created_new = True

        # Check if already present
        if tool_name in current_tools:
            return {
                "success": False,
                "error": f"Tool '{tool_name}' is already in the configuration",
                "config_path": str(WORKSPACE_CONFIG)
            }

        # Add tool and write config
        current_tools.append(tool_name)
        _write_config(WORKSPACE_CONFIG, current_tools)

        logger.info(f"Successfully added {tool_name} to workspace config")

        return {
            "success": True,
            "tool": tool_name,
            "config_path": str(WORKSPACE_CONFIG),
            "created_new_config": created_new,
            "total_tools": len(current_tools),
            "message": f"Added {tool_name} to configuration. Restart container to apply changes.",
            "next_step": "Restart the container for changes to take effect"
        }
    except Exception as e:
        logger.error(f"Failed to add tool {tool_name}: {e}")
        return {"success": False, "error": str(e)}


@mcp.tool()
async def mcp_remove_tool(tool_name: str) -> Dict[str, Any]:
    """Remove an MCP tool from the workspace configuration.

    Removes the specified tool from /workspace/.codex-mcp.config. If the
    workspace config doesn't exist, it will be created from the default config
    with the specified tool removed. Changes take effect on next container restart.

    Args:
        tool_name: Name of the tool file to remove (e.g., "gnosis-crawl.py")

    Returns:
        Dictionary with success status and next steps.

    Example:
        {
            "success": true,
            "tool": "gnosis-crawl.py",
            "config_path": "/workspace/.codex-mcp.config",
            "message": "Removed gnosis-crawl.py from configuration. Restart container to apply changes."
        }
    """
    logger.info(f"Removing tool: {tool_name}")

    try:
        # Read current config (workspace or default)
        if WORKSPACE_CONFIG.exists():
            current_tools = _read_config(WORKSPACE_CONFIG)
            created_new = False
        elif DEFAULT_CONFIG.exists():
            # Create workspace config from default
            current_tools = _read_config(DEFAULT_CONFIG)
            created_new = True
        else:
            return {
                "success": False,
                "error": "No configuration file found",
                "note": "Create /workspace/.codex-mcp.config first"
            }

        # Check if present
        if tool_name not in current_tools:
            return {
                "success": False,
                "error": f"Tool '{tool_name}' is not in the configuration",
                "current_tools": current_tools
            }

        # Remove tool and write config
        current_tools.remove(tool_name)
        _write_config(WORKSPACE_CONFIG, current_tools)

        logger.info(f"Successfully removed {tool_name} from workspace config")

        return {
            "success": True,
            "tool": tool_name,
            "config_path": str(WORKSPACE_CONFIG),
            "created_new_config": created_new,
            "remaining_tools": len(current_tools),
            "message": f"Removed {tool_name} from configuration. Restart container to apply changes.",
            "next_step": "Restart the container for changes to take effect"
        }
    except Exception as e:
        logger.error(f"Failed to remove tool {tool_name}: {e}")
        return {"success": False, "error": str(e)}


@mcp.tool()
async def mcp_set_tools(tool_names: List[str]) -> Dict[str, Any]:
    """Set the complete list of MCP tools for this workspace.

    Replaces the entire /workspace/.codex-mcp.config with the specified list
    of tools. This is useful for bulk configuration changes. Changes take
    effect on next container restart.

    Args:
        tool_names: List of tool filenames to configure (e.g., ["time-tool.py", "calculate.py"])

    Returns:
        Dictionary with success status and next steps.

    Example:
        {
            "success": true,
            "tool_count": 5,
            "tools": ["time-tool.py", "calculate.py", ...],
            "message": "Configuration updated with 5 tools. Restart container to apply changes."
        }
    """
    logger.info(f"Setting tools: {tool_names}")

    try:
        # Validate all tools exist
        available = _list_available_tools()
        invalid_tools = [t for t in tool_names if t not in available]

        if invalid_tools:
            return {
                "success": False,
                "error": f"Invalid tools: {', '.join(invalid_tools)}",
                "available_tools": available
            }

        # Write new config
        _write_config(WORKSPACE_CONFIG, tool_names)

        logger.info(f"Successfully set {len(tool_names)} tools in workspace config")

        return {
            "success": True,
            "tool_count": len(tool_names),
            "tools": sorted(tool_names),
            "config_path": str(WORKSPACE_CONFIG),
            "message": f"Configuration updated with {len(tool_names)} tools. Restart container to apply changes.",
            "next_step": "Restart the container for changes to take effect"
        }
    except Exception as e:
        logger.error(f"Failed to set tools: {e}")
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    mcp.run()
