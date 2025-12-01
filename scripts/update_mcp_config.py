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
        
        # Pass ANTHROPIC_API_KEY if set
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
        if anthropic_key:
            env_vars["ANTHROPIC_API_KEY"] = anthropic_key
        
        # Pass MarketBot environment variables if set
        marketbot_key = os.environ.get("MARKETBOT_API_KEY")
        marketbot_team = os.environ.get("MARKETBOT_TEAM_ID")
        marketbot_url = os.environ.get("MARKETBOT_API_URL")
        
        if marketbot_key:
            env_vars["MARKETBOT_API_KEY"] = marketbot_key
        if marketbot_team:
            env_vars["MARKETBOT_TEAM_ID"] = marketbot_team
        if marketbot_url:
            env_vars["MARKETBOT_API_URL"] = marketbot_url
        
        # Also try to read from .marketbot.env file if env vars aren't set
        if not marketbot_key or not marketbot_team:
            marketbot_env_paths = [
                Path("/workspace/.marketbot.env"),
                Path("/opt/codex-home/.marketbot.env"),
                Path.home() / ".marketbot.env",
            ]
            
            # Check session-specific env if CODEX_SESSION_ID is set
            session_id = os.environ.get("CODEX_SESSION_ID")
            if session_id:
                marketbot_env_paths.insert(0, Path(f"/opt/codex-home/sessions/{session_id}/.env"))
            
            for env_path in marketbot_env_paths:
                if env_path.exists() and env_path.is_file():
                    try:
                        for line in env_path.read_text(encoding="utf-8").splitlines():
                            line = line.strip()
                            if not line or line.startswith("#") or "=" not in line:
                                continue
                            key, value = line.split("=", 1)
                            key = key.strip()
                            value = value.strip()
                            if key.startswith("MARKETBOT_") and key not in env_vars:
                                env_vars[key] = value
                        if env_vars.get("MARKETBOT_API_KEY") or env_vars.get("MARKETBOT_TEAM_ID"):
                            break  # Found MarketBot config, stop searching
                    except Exception:
                        continue  # Skip invalid files
        
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
