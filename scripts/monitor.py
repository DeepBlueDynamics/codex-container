#!/usr/bin/env python3
"""
Monitor mode for Codex container - watches directory for file changes and dispatches to Codex.

This replaces the bash-based monitor implementation with a more portable Python version
that works on macOS (bash 3.2), Linux, and Windows.

Uses watchdog for efficient event-driven file monitoring instead of polling.
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

from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver
from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent


class CodexFileHandler(FileSystemEventHandler):
    """Handles file system events and dispatches to Codex."""

    def __init__(self, monitor):
        super().__init__()
        self.monitor = monitor
        # Track last processed time to debounce multiple events
        self.last_processed: Dict[str, float] = {}
        self.debounce_seconds = 3.0  # Debounce to avoid processing same file multiple times (create + write events)

    def should_process(self, file_path: Path) -> bool:
        """Check if file should be processed (debouncing and filtering)."""
        # Skip directories
        if not file_path.is_file():
            return False

        # Skip hidden files except our config files
        if file_path.name.startswith(".") and file_path.name not in [".codex-monitor", ".codex-monitor-session"]:
            return False

        # Skip monitor log file
        if file_path.name == "codex-monitor.log":
            return False

        # Debounce: skip if processed recently
        key = str(file_path)
        now = time.time()
        if key in self.last_processed:
            if (now - self.last_processed[key]) < self.debounce_seconds:
                return False

        self.last_processed[key] = now
        return True

    def on_created(self, event):
        """Handle file creation events."""
        if event.is_directory:
            return

        file_path = Path(event.src_path)
        if self.should_process(file_path):
            print(f"[monitor] File created: {file_path.name}", file=sys.stderr, flush=True)
            self.monitor.queue_file(file_path, "created")

    def on_modified(self, event):
        """Handle file modification events."""
        if event.is_directory:
            return

        file_path = Path(event.src_path)
        if self.should_process(file_path):
            print(f"[monitor] File modified: {file_path.name}", file=sys.stderr, flush=True)
            self.monitor.queue_file(file_path, "modified")


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

        # Current session ID
        self.session_id: Optional[str] = None

        # Queue management for batch processing
        self.processing = False
        self.pending_changes: list = []  # List of (file_path, action) tuples
        self.max_concurrent = 1  # Only 1 Codex run at a time

    def queue_file(self, file_path: Path, action: str):
        """Add file to pending changes queue."""
        # Add to pending list
        change = (str(file_path), action, time.time())
        self.pending_changes.append(change)
        print(f"[queue] Added {file_path.name} to queue (total: {len(self.pending_changes)})", file=sys.stderr, flush=True)

        # Try to process if not busy
        if not self.processing:
            self.process_pending()

    def process_pending(self):
        """Process all pending changes in a single batch."""
        if self.processing:
            print(f"[queue] Already processing, {len(self.pending_changes)} changes waiting", file=sys.stderr, flush=True)
            return

        if not self.pending_changes:
            return

        # Mark as processing
        self.processing = True

        # Get all pending changes
        batch = self.pending_changes.copy()
        self.pending_changes.clear()

        print(f"[queue] Processing batch of {len(batch)} changes", file=sys.stderr, flush=True)

        try:
            # Build combined payload - ALWAYS send full template with substitution
            # Agent needs the full instructions every time to remember to check for duplicates
            prompt_text = self.prompt_file.read_text()

            # Use first file for template substitution
            if batch:
                file_path_str, action, timestamp_val = batch[0]
                file_path = Path(file_path_str)
                abs_file_path = file_path.resolve()
                abs_workspace_path = self.workspace_path.resolve()
                relative_path = abs_file_path.relative_to(abs_workspace_path)
                container_path = f"/workspace/{relative_path.as_posix()}"

                # Substitute template variables
                prompt_text = prompt_text.replace("{{container_path}}", container_path)
                prompt_text = prompt_text.replace("{{filename}}", file_path.name)
                prompt_text = prompt_text.replace("{{action}}", action)
                prompt_text = prompt_text.replace("{{timestamp}}", datetime.fromtimestamp(timestamp_val, timezone.utc).isoformat())

            payload_parts = [prompt_text]

            # Add additional files if batch has more than one
            if len(batch) > 1:
                for file_path_str, action, timestamp_val in batch[1:]:
                    file_path = Path(file_path_str)
                    payload_parts.append(self.build_file_event_payload(file_path))

            payload = "\n\n".join(payload_parts)

            # Execute Codex
            output = self.execute_codex(payload)

            # If this is first event, try to extract session ID
            if not self.session_id:
                session_id = self.extract_session_id(output)
                if session_id:
                    self.session_id = session_id
                    self.save_session(session_id)
                    print(f"[monitor] Persisted session: {self.session_id}", file=sys.stderr, flush=True)

        except Exception as e:
            print(f"[queue] Error processing batch: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)
        finally:
            # Mark as done
            self.processing = False
            print(f"[queue] Batch complete, processing={self.processing}, pending={len(self.pending_changes)}", file=sys.stderr, flush=True)

            # Process next batch if anything queued while we were busy
            if self.pending_changes:
                print(f"[queue] New changes arrived during processing, starting next batch", file=sys.stderr, flush=True)
                self.process_pending()

    def process_file(self, file_path: Path):
        """Process a file event and dispatch to Codex."""
        try:
            # Build payload
            if self.session_id:
                # Resuming - send only file event
                payload = self.build_file_event_payload(file_path)
            else:
                # First event - send full prompt + file details
                prompt_text = self.prompt_file.read_text()
                payload = f"{prompt_text}\n\n{self.build_file_event_payload(file_path)}"

            # Execute Codex
            output = self.execute_codex(payload)

            # If this is first event, try to extract session ID
            if not self.session_id:
                session_id = self.extract_session_id(output)
                if session_id:
                    self.session_id = session_id
                    self.save_session(session_id)
                    print(f"Monitor persisted session: {self.session_id}", file=sys.stderr, flush=True)

        except Exception as e:
            print(f"Error processing file {file_path}: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)

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

        # Resolve to absolute paths
        abs_file_path = file_path.resolve()
        abs_workspace_path = self.workspace_path.resolve()

        relative_path = abs_file_path.relative_to(abs_workspace_path)
        container_path = f"/workspace/{relative_path.as_posix()}"

        return f"""FILE EVENT DETECTED

Timestamp: {timestamp}
Action: Created
File: {file_path.name}
Full Path: {abs_file_path.as_posix()}
Container Path: {container_path}"""

    def execute_codex(self, payload: str) -> str:
        """Execute Codex with the given payload."""
        # Detect if running inside container by checking if codex_script is "codex" CLI
        is_in_container = (str(self.codex_script) == "codex")

        if is_in_container:
            # Running inside container - call codex CLI directly
            cmd = ["codex", "--exec"]

            # Add JSON mode if specified
            if self.json_mode == "legacy":
                cmd.append("--json")
            elif self.json_mode == "experimental":
                cmd.append("--json-e")

            # Add session resume if we have a session
            if self.session_id:
                cmd.extend(["--session-id", self.session_id])

            # Add custom codex args
            cmd.extend(self.codex_args)

            # Add custom exec args
            cmd.extend(self.exec_args)

            # Add separator and payload
            cmd.append("--")
            cmd.append(payload)

        else:
            # Running on host - call codex_container.ps1 script
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

        print(f"[monitor] Executing codex: {' '.join(cmd[:6])}... [payload truncated]", file=sys.stderr, flush=True)

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
            print("[monitor] Error: Codex execution timed out", file=sys.stderr)
            return ""
        except Exception as e:
            print(f"[monitor] Error executing Codex: {e}", file=sys.stderr)
            return ""

    def run(self):
        """Main monitor loop using watchdog."""
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

        # Check that prompt file exists, try defaults if not found
        if not self.prompt_file.exists():
            # Try .codex-monitor as fallback
            alt_prompt = self.watch_path / ".codex-monitor"
            if alt_prompt.exists():
                print(f"[monitor] Using default prompt file: {alt_prompt}", file=sys.stderr, flush=True)
                self.prompt_file = alt_prompt
            else:
                print(f"Error: Monitor prompt file not found", file=sys.stderr)
                print(f"  Looked for: {self.prompt_file}", file=sys.stderr)
                print(f"  Also tried: {alt_prompt}", file=sys.stderr)
                print(f"", file=sys.stderr)
                print(f"Please create one of these files with instructions for how to process detected files.", file=sys.stderr)
                sys.exit(1)

        print(f"🔍 Monitoring {self.watch_path} using watchdog (polling mode)", file=sys.stderr, flush=True)
        print(f"   Prompt file: {self.prompt_file}", file=sys.stderr, flush=True)
        print(f"   Press Ctrl+C to stop", file=sys.stderr, flush=True)

        # Set up watchdog observer with polling (works across Docker volumes)
        event_handler = CodexFileHandler(self)
        observer = PollingObserver()
        observer.schedule(event_handler, str(self.watch_path), recursive=False)
        observer.start()

        try:
            # Keep the script running
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n✋ Monitor stopped by user", file=sys.stderr)
            observer.stop()

        observer.join()


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
