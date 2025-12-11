#!/usr/bin/env python3
"""Update Codex config.toml with MCP server definitions."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import tomlkit


def ensure_table(doc: tomlkit.TOMLDocument, key: str) -> tomlkit.items.Table:
    """Return an existing table or create a new mutable table."""
    table = doc.get(key)
    if table is None:
        table = tomlkit.table()
        doc[key] = table
    return table


def main(argv: list[str]) -> int:
    if len(argv) < 4:
        sys.stderr.write(
            "Usage: update_mcp_config.py <config-path> <python-cmd> <script1> [script2...]\n"
        )
        return 1

    config_path = Path(argv[1])
    python_cmd = argv[2]
    script_names = argv[3:]

    config_path.parent.mkdir(parents=True, exist_ok=True)
    if config_path.exists():
        doc = tomlkit.parse(config_path.read_text(encoding="utf-8"))
    else:
        doc = tomlkit.document()

    mcp_table = ensure_table(doc, "mcp_servers")

    # Remove managed entries whose targets are no longer installed.
    desired_names = {Path(filename).stem for filename in script_names}
    managed_prefix = "/opt/codex-home/mcp/"

    for name in list(mcp_table):
        entry = mcp_table[name]
        if not isinstance(entry, tomlkit.items.Table):
            continue

        command = entry.get("command")
        args = entry.get("args")
        if command != python_cmd or not isinstance(args, list) or len(args) < 2:
            continue

        managed_arg = None
        for arg in args:
            if isinstance(arg, str) and arg.startswith(managed_prefix):
                managed_arg = arg
                break

        if managed_arg and name not in desired_names:
            del mcp_table[name]

    for filename in script_names:
        name = Path(filename).stem
        table = tomlkit.table()
        table.add("command", python_cmd)
        table.add("args", ["-u", f"/opt/codex-home/mcp/{filename}"])
        
        # Collect environment variables to pass to MCP servers
        env_vars = {}
        
        # Pass ANTHROPIC_API_KEY if set (safe - not session-specific)
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
        if anthropic_key:
            env_vars["ANTHROPIC_API_KEY"] = anthropic_key
        
        # ⭐ CRITICAL: DO NOT set MARKETBOT_* variables in MCP config!
        # 
        # The marketbot.py MCP tool is a SINGLE long-lived process that handles multiple
        # Codex sessions concurrently. If we set MARKETBOT_* variables in the MCP config,
        # they will be in the MCP server's process environment, causing cross-team data leakage.
        #
        # The marketbot.py tool MUST read from session-specific files based on CODEX_SESSION_ID,
        # NOT from process environment. Setting these here would break session isolation.
        #
        # MarketBot credentials are provided by Codex Gateway via session-specific .env files:
        # - /opt/codex-home/sessions/gateway/session-{sessionId}/.env
        # The marketbot.py tool reads these files directly, not from process environment.
        
        # Add env table if we have any variables
        if env_vars:
            env_table = tomlkit.table()
            for key, value in env_vars.items():
                env_table.add(key, value)
            table.add("env", env_table)
        
        mcp_table[name] = table

    config_path.write_text(tomlkit.dumps(doc), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
