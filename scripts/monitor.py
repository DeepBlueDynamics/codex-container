#!/usr/bin/env python3
"""
Monitor mode for Codex container - watches directory for file changes and dispatches to Codex.

This replaces the bash-based monitor implementation with a more portable Python version
that works on macOS (bash 3.2), Linux, and Windows.
"""

import argparse
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional


class CodexMonitor:
    """Monitors a directory and dispatches file events to Codex container."""

    def __init__(
        self,
        watch_path: Path,
        workspace_path: Path,
        codex_script: Path,
        monitor_prompt_file: str = ".codex-monitor",
        new_session: bool = False,
        json_mode: Optional[str] = None,
        codex_args: Optional[list] = None,
        exec_args: Optional[list] = None,
    ):
        self.watch_path = watch_path
        self.workspace_path = workspace_path
        self.codex_script = codex_script
        self.prompt_file = watch_path / monitor_prompt_file
        self.session_file = watch_path / ".codex-monitor-session"
        self.new_session = new_session
        self.json_mode = json_mode
        self.codex_args = codex_args or []
        self.exec_args = exec_args or []

        # Track seen files by path -> mtime
        self.seen_files: Dict[str, float] = {}

        # Current session ID
        self.session_id: Optional[str] = None

    def get_existing_session(self) -> Optional[str]:
        """Read persisted session ID from file."""
        if not self.session_file.exists():
            return None

        try:
            session_id = self.session_file.read_text().strip()
            if session_id:
                return session_id
        except Exception as e:
            print(f"Warning: Could not read session file: {e}", file=sys.stderr)

        return None

    def save_session(self, session_id: str):
        """Persist session ID to file."""
        try:
            self.session_file.write_text(session_id)
        except Exception as e:
            print(f"Warning: Could not save session file: {e}", file=sys.stderr)

    def extract_session_id(self, output: str) -> Optional[str]:
        """Extract session ID from Codex output."""
        # Look for patterns like: session id: 019a0ef0-76b1-7cb0-8298-ddb7232cf646
        match = re.search(r"session id:\s*([0-9a-f-]+)", output, re.IGNORECASE)
        if match:
            return match.group(1)

        # Also check for UUID-like patterns
        match = re.search(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", output)
        if match:
            return match.group(0)

        return None

    def build_file_event_payload(self, file_path: Path) -> str:
        """Build the payload for a file event."""
        timestamp = datetime.now(timezone.utc).isoformat()
        relative_path = file_path.relative_to(self.workspace_path)
        container_path = f"/workspace/{relative_path.as_posix()}"

        return f"""FILE EVENT DETECTED

Timestamp: {timestamp}
Action: Created
File: {file_path.name}
Full Path: {file_path.as_posix()}
Container Path: {container_path}"""

    def execute_codex(self, payload: str) -> str:
        """Execute Codex container with the given payload."""
        cmd = [
            str(self.codex_script),
            "--exec",
            "--workspace",
            str(self.workspace_path),
        ]

        # Add JSON mode if specified
        if self.json_mode == "legacy":
            cmd.append("--json")
        elif self.json_mode == "experimental":
            cmd.append("--json-e")

        # Add session resume if we have a session
        if self.session_id:
            cmd.extend(["--session-id", self.session_id])

        # Add custom codex args
        for arg in self.codex_args:
            cmd.extend(["--codex-arg", arg])

        # Add custom exec args
        for arg in self.exec_args:
            cmd.extend(["--exec-arg", arg])

        # Add separator and payload
        cmd.append("--")
        cmd.append(payload)

        print(f"DEBUG: Executing: {' '.join(cmd[:6])}... [payload truncated]", file=sys.stderr, flush=True)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
            )

            output = result.stdout + result.stderr
            print(output, flush=True)

            return output

        except subprocess.TimeoutExpired:
            print("Error: Codex execution timed out", file=sys.stderr)
            return ""
        except Exception as e:
            print(f"Error executing Codex: {e}", file=sys.stderr)
            return ""

    def scan_directory(self):
        """Scan directory for new or modified files."""
        if not self.watch_path.exists():
            print(f"Error: Watch path does not exist: {self.watch_path}", file=sys.stderr)
            return

        for file_path in self.watch_path.iterdir():
            if not file_path.is_file():
                continue

            # Skip hidden files except our config files
            if file_path.name.startswith(".") and file_path.name not in [".codex-monitor", ".codex-monitor-session"]:
                continue

            try:
                mtime = file_path.stat().st_mtime
                key = str(file_path)

                # Check if we've seen this file before
                if key in self.seen_files:
                    if self.seen_files[key] == mtime:
                        # No change
                        continue

                # New or modified file
                print(f"[monitor] Change detected: {file_path.name}", file=sys.stderr, flush=True)
                self.seen_files[key] = mtime

                # Process this file
                yield file_path

            except Exception as e:
                print(f"Warning: Could not process {file_path}: {e}", file=sys.stderr)

    def run(self):
        """Main monitor loop."""
        # Check for existing session unless --new-session
        if not self.new_session:
            self.session_id = self.get_existing_session()

        if self.session_id:
            print(f"Monitor resuming session: {self.session_id}", file=sys.stderr, flush=True)
        else:
            if self.new_session:
                print("Monitor starting fresh session (forced by --new-session)", file=sys.stderr, flush=True)
                # Clear any existing session file
                if self.session_file.exists():
                    self.session_file.unlink()
            else:
                print("Monitor starting new session", file=sys.stderr, flush=True)

        # Check that prompt file exists
        if not self.prompt_file.exists():
            print(f"Error: Monitor prompt file not found: {self.prompt_file}", file=sys.stderr)
            sys.exit(1)

        print(f"Monitoring {self.watch_path} using prompt {self.prompt_file}", file=sys.stderr, flush=True)

        # Main loop
        while True:
            try:
                for file_path in self.scan_directory():
                    # Build payload
                    if self.session_id:
                        # Resuming - send only file event
                        payload = self.build_file_event_payload(file_path)
                    else:
                        # First event - send full prompt + file details
                        prompt_text = self.prompt_file.read_text()
                        payload = f"{prompt_text}\n\nFile: {file_path}"

                    # Execute Codex
                    output = self.execute_codex(payload)

                    # If this is first event, try to extract session ID
                    if not self.session_id:
                        session_id = self.extract_session_id(output)
                        if session_id:
                            self.session_id = session_id
                            self.save_session(session_id)
                            print(f"Monitor persisted session: {self.session_id}", file=sys.stderr, flush=True)

                # Sleep between scans
                time.sleep(2)

            except KeyboardInterrupt:
                print("\nMonitor stopped by user", file=sys.stderr)
                break
            except Exception as e:
                print(f"Error in monitor loop: {e}", file=sys.stderr)
                time.sleep(5)


def main():
    parser = argparse.ArgumentParser(description="Monitor directory and dispatch to Codex")
    parser.add_argument("--watch-path", type=Path, required=True, help="Directory to watch")
    parser.add_argument("--workspace", type=Path, required=True, help="Workspace path")
    parser.add_argument("--codex-script", type=Path, required=True, help="Path to codex_container script")
    parser.add_argument("--monitor-prompt-file", default=".codex-monitor", help="Monitor prompt filename")
    parser.add_argument("--new-session", action="store_true", help="Force new session")
    parser.add_argument("--json-mode", choices=["legacy", "experimental"], help="JSON output mode")
    parser.add_argument("--codex-arg", action="append", dest="codex_args", help="Additional codex arguments")
    parser.add_argument("--exec-arg", action="append", dest="exec_args", help="Additional exec arguments")

    args = parser.parse_args()

    monitor = CodexMonitor(
        watch_path=args.watch_path,
        workspace_path=args.workspace,
        codex_script=args.codex_script,
        monitor_prompt_file=args.monitor_prompt_file,
        new_session=args.new_session,
        json_mode=args.json_mode,
        codex_args=args.codex_args,
        exec_args=args.exec_args,
    )

    monitor.run()


if __name__ == "__main__":
    main()
