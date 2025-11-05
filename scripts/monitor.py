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
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from monitor_scheduler import (
    CONFIG_FILENAME,
    TriggerRecord,
    list_trigger_records,
    load_config,
    save_config,
    render_template,
)

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
        if file_path.name == CONFIG_FILENAME:
            print(f"[schedule] Trigger configuration changed: {file_path.name}", file=sys.stderr, flush=True)
            self.monitor.reload_triggers()
            return False

        if file_path.name.startswith(".") and file_path.name not in [".codex-monitor", ".codex-monitor-session", CONFIG_FILENAME]:
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
        self.trigger_config_path = watch_path / CONFIG_FILENAME
        self.new_session = new_session
        self.json_mode = json_mode
        self.codex_args = codex_args or []
        self.exec_args = exec_args or []

        # Current session ID
        self.session_id: Optional[str] = None

        # Queue management for batch processing
        self.processing = False
        self.pending_changes: List[Dict[str, Any]] = []
        self.max_concurrent = 1  # Only 1 Codex run at a time

        # Scheduler state
        self.triggers_lock = threading.Lock()
        self.triggers: Dict[str, TriggerRecord] = {}
        self.scheduler_event = threading.Event()
        self.scheduler_stop = threading.Event()
        self.scheduler_thread: Optional[threading.Thread] = None

    def queue_file(self, file_path: Path, action: str):
        """Add file to pending changes queue."""
        change = {
            "type": "file",
            "path": str(file_path),
            "action": action,
            "timestamp": time.time(),
        }
        self.pending_changes.append(change)
        print(f"[queue] Added file {file_path.name} (total: {len(self.pending_changes)})", file=sys.stderr, flush=True)

        # Try to process if not busy
        if not self.processing:
            self.process_pending()

    def queue_trigger_event(self, trigger: TriggerRecord, fired_at: datetime):
        """Queue a scheduled trigger execution."""

        task = {
            "type": "trigger",
            "trigger": trigger,
            "fired_at": fired_at.astimezone(timezone.utc).isoformat(),
        }
        self.pending_changes.append(task)
        print(
            f"[schedule] Queued trigger '{trigger.title}' for execution (pending: {len(self.pending_changes)})",
            file=sys.stderr,
            flush=True,
        )

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
        try:
            batch = self.pending_changes.copy()
            self.pending_changes.clear()
            if not batch:
                return

            payload, triggers_fired = self._build_combined_payload(batch)
            if not payload:
                return

            output = self.execute_codex(payload)

            if not self.session_id:
                session_id = self.extract_session_id(output)
                if session_id:
                    self.session_id = session_id
                    self.save_session(session_id)
                    print(f"[monitor] Persisted session: {self.session_id}", file=sys.stderr, flush=True)

            for trigger, fired_at in triggers_fired:
                self.mark_trigger_fired(trigger, fired_at)

        except Exception as exc:
            print(f"[queue] Error processing batch: {exc}", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)
        finally:
            self.processing = False
            if self.pending_changes:
                self.process_pending()

    def load_triggers(self) -> List[TriggerRecord]:
        records = list_trigger_records(self.trigger_config_path)
        with self.triggers_lock:
            self.triggers = {record.id: record for record in records if record.enabled}

        if records:
            enabled_count = len([r for r in records if r.enabled])
            disabled_count = len(records) - enabled_count
            print(f"[schedule] Loaded {len(records)} trigger(s) from {self.trigger_config_path.name}", file=sys.stderr, flush=True)

            for record in records:
                status = "✓ enabled" if record.enabled else "✗ disabled"
                next_fire_str = record.next_fire.strftime('%Y-%m-%d %H:%M:%S %Z') if record.next_fire else "never"
                mode = record.schedule.get("mode", "unknown")
                schedule_detail = self._format_schedule_detail(record)
                print(f"  [{status}] '{record.title}' ({mode}: {schedule_detail}) - next: {next_fire_str}", file=sys.stderr, flush=True)

            if disabled_count > 0:
                print(f"[schedule] Summary: {enabled_count} enabled, {disabled_count} disabled", file=sys.stderr, flush=True)
        else:
            print(f"[schedule] No triggers configured in {self.trigger_config_path}", file=sys.stderr, flush=True)

        self.scheduler_event.set()
        return records

    def _format_schedule_detail(self, record: TriggerRecord) -> str:
        """Format schedule details for logging."""
        mode = record.schedule.get("mode", "unknown")
        if mode == "daily":
            time_str = record.schedule.get("time", "??:??")
            tz = record.schedule.get("timezone", "UTC")
            return f"{time_str} {tz}"
        elif mode == "interval":
            minutes = record.schedule.get("interval_minutes", 0)
            return f"every {minutes} min"
        elif mode == "once":
            at_str = record.schedule.get("at", "unknown")
            return f"at {at_str}"
        return "unknown"

    def reload_triggers(self):
        """Reload triggers and optionally fire newly added/enabled ones immediately."""
        print("[schedule] Reloading triggers from configuration", file=sys.stderr, flush=True)

        # Track previous trigger states
        old_triggers = {}
        with self.triggers_lock:
            old_triggers = {tid: rec for tid, rec in self.triggers.items()}

        # Load new configuration
        new_records = self.load_triggers()

        # Check for newly added or newly enabled triggers
        for record in new_records:
            if not record.enabled:
                continue

            was_new_or_enabled = False
            if record.id not in old_triggers:
                # Brand new trigger
                print(f"[schedule] New trigger detected: '{record.title}'", file=sys.stderr, flush=True)
                was_new_or_enabled = True
            elif not old_triggers[record.id].enabled and record.enabled:
                # Was disabled, now enabled
                print(f"[schedule] Trigger enabled: '{record.title}'", file=sys.stderr, flush=True)
                was_new_or_enabled = True

            # Fire immediately if it's a new/enabled trigger and has fire_on_reload tag
            if was_new_or_enabled and "fire_on_reload" in record.tags:
                print(f"[schedule] Firing trigger immediately (fire_on_reload tag): '{record.title}'", file=sys.stderr, flush=True)
                now = datetime.now(timezone.utc)
                self.queue_trigger_event(record, now)

    def start_scheduler(self):
        self.scheduler_stop.clear()
        self.load_triggers()
        if self.scheduler_thread and self.scheduler_thread.is_alive():
            return
        self.scheduler_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self.scheduler_thread.start()

    def stop_scheduler(self):
        self.scheduler_stop.set()
        self.scheduler_event.set()
        if self.scheduler_thread and self.scheduler_thread.is_alive():
            self.scheduler_thread.join(timeout=2)

    def _scheduler_loop(self):
        while not self.scheduler_stop.is_set():
            trigger, wait_seconds = self._next_scheduled_trigger()
            if trigger is None or wait_seconds is None:
                self.scheduler_event.clear()
                self.scheduler_event.wait(timeout=60)
                continue

            self.scheduler_event.clear()
            woke_early = self.scheduler_event.wait(timeout=wait_seconds)
            if woke_early:
                continue

            now = datetime.now(timezone.utc)
            self.queue_trigger_event(trigger, now)

    def _next_scheduled_trigger(self) -> tuple[Optional[TriggerRecord], Optional[float]]:
        with self.triggers_lock:
            if not self.triggers:
                return None, None
            now = datetime.now(timezone.utc)
            upcoming: List[TriggerRecord] = []
            for trigger in self.triggers.values():
                try:
                    next_fire = trigger.compute_next_fire(now)
                    trigger.next_fire = next_fire
                    if next_fire:
                        upcoming.append(trigger)
                except Exception as exc:
                    print(f"[schedule] Trigger {trigger.id} disabled due to error: {exc}", file=sys.stderr, flush=True)
            if not upcoming:
                return None, None
            upcoming.sort(key=lambda rec: rec.next_fire)
            next_trigger = upcoming[0]
            wait_seconds = max(0.0, (next_trigger.next_fire - now).total_seconds())
            return next_trigger, wait_seconds

    def mark_trigger_fired(self, trigger: TriggerRecord, fired_at: datetime):
        trigger.last_fired = fired_at.isoformat()
        config = load_config(self.trigger_config_path)
        updated = False
        for item in config.get("triggers", []):
            if item.get("id") == trigger.id:
                item["last_fired"] = trigger.last_fired
                updated = True
                break
        if updated:
            save_config(self.trigger_config_path, config)
        with self.triggers_lock:
            trigger.next_fire = trigger.compute_next_fire(fired_at + timedelta(seconds=1))
            self.triggers[trigger.id] = trigger
        self.scheduler_event.set()
        print(
            f"[schedule] Trigger '{trigger.title}' recorded at {trigger.last_fired}",
            file=sys.stderr,
            flush=True,
        )

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

    def build_file_event_payload(self, event: Dict[str, Any]) -> str:
        """Build the payload for a file event."""

        file_path = Path(event["path"])
        timestamp = datetime.fromtimestamp(event.get("timestamp", time.time()), timezone.utc).isoformat()
        action = event.get("action", "modified")

        abs_file_path = file_path.resolve()
        abs_workspace_path = self.workspace_path.resolve()
        relative_path = abs_file_path.relative_to(abs_workspace_path)
        container_path = f"/workspace/{relative_path.as_posix()}"

        return (
            "FILE EVENT DETECTED\n\n"
            f"Timestamp: {timestamp}\n"
            f"Action: {action}\n"
            f"File: {file_path.name}\n"
            f"Full Path: {abs_file_path.as_posix()}\n"
            f"Container Path: {container_path}"
        )

    def _render_trigger_prompt(self, trigger: TriggerRecord, fired_at_iso: str) -> str:
        fired_at = datetime.fromisoformat(fired_at_iso).astimezone(timezone.utc)
        tz = trigger.timezone
        local_time = fired_at.astimezone(tz)

        substitutions = {
            "now_iso": fired_at.isoformat(),
            "now_local": local_time.isoformat(),
            "trigger_time": trigger.schedule.get("time") or trigger.schedule.get("at") or local_time.isoformat(),
            "trigger_id": trigger.id,
            "trigger_title": trigger.title,
            "trigger_description": trigger.description,
            "watch_root": str(self.watch_path),
            "created_at": trigger.created_at,
            "created_by.id": trigger.created_by.get("id", "unknown"),
            "created_by.name": trigger.created_by.get("name", "unknown"),
            "session_id": self.session_id or "",
        }

        prompt_text = trigger.prompt_text or "Scheduled trigger fired with no prompt text provided."
        return render_template(prompt_text, substitutions)

    def _build_combined_payload(self, items: List[Dict[str, Any]]) -> tuple[str, List[tuple[TriggerRecord, datetime]]]:
        files = [item for item in items if item.get("type") == "file"]
        triggers = [item for item in items if item.get("type") == "trigger"]

        sections: List[str] = []
        triggers_fired: List[tuple[TriggerRecord, datetime]] = []

        if files:
            prompt_text = self.prompt_file.read_text()
            first = files[0]
            first_path = Path(first["path"])
            abs_file_path = first_path.resolve()
            abs_workspace_path = self.workspace_path.resolve()
            relative_path = abs_file_path.relative_to(abs_workspace_path)
            container_path = f"/workspace/{relative_path.as_posix()}"

            prompt_text = prompt_text.replace("{{container_path}}", container_path)
            prompt_text = prompt_text.replace("{{filename}}", first_path.name)
            prompt_text = prompt_text.replace("{{action}}", first.get("action", "modified"))
            prompt_text = prompt_text.replace(
                "{{timestamp}}",
                datetime.fromtimestamp(first.get("timestamp", time.time()), timezone.utc).isoformat(),
            )

            sections.append(prompt_text)

            if len(files) > 1:
                for event in files[1:]:
                    sections.append(self.build_file_event_payload(event))

        for trigger_item in triggers:
            trigger: TriggerRecord = trigger_item["trigger"]
            fired_at_iso: str = trigger_item["fired_at"]
            sections.append(self._render_trigger_prompt(trigger, fired_at_iso))
            triggers_fired.append((trigger, datetime.fromisoformat(fired_at_iso).astimezone(timezone.utc)))

        if not sections:
            return "", []

        payload = "\n\n---\n\n".join(sections)
        print(
            f"[queue] Combined payload contains {len(files)} file events and {len(triggers)} trigger(s)",
            file=sys.stderr,
            flush=True,
        )

        return payload, triggers_fired

    def execute_codex(self, payload: str) -> str:
        """Execute Codex with the given payload."""
        # Detect if running inside container by checking if codex_script is "codex" CLI
        is_in_container = (str(self.codex_script) == "codex")

        if is_in_container:
            # Running inside container - call codex CLI directly
            # Format: codex exec [FLAGS] [resume SESSION_ID] -- <prompt>
            cmd = ["codex", "exec"]

            # Add --skip-git-repo-check flag (only available on exec subcommand)
            cmd.append("--skip-git-repo-check")

            # Add JSON mode if specified
            if self.json_mode == "legacy":
                cmd.append("--json")
            elif self.json_mode == "experimental":
                cmd.append("--json-e")

            # Add custom codex args
            cmd.extend(self.codex_args)

            # Add custom exec args
            cmd.extend(self.exec_args)

            # If we have a session, use "codex exec resume <session-id>"
            if self.session_id:
                cmd.extend(["resume", self.session_id])

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
        self.start_scheduler()
        observer.start()

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n✋ Monitor stopped by user", file=sys.stderr)
        finally:
            observer.stop()
            observer.join()
            self.stop_scheduler()


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
