#!/usr/bin/env python3
"""MCP: monitor-server

Unified tools for Codex monitor runtime:
- Environment management for legacy monitor sessions
- Time-based trigger scheduling utilities
- Gateway watcher status inspection

Each tool returns actionable ``next_steps`` hints so the calling agent knows how to follow-up.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

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

from monitor_scheduler import (  # type: ignore
    TriggerRecord,
    generate_trigger_id,
    get_config_path_for_session,
    list_trigger_records,
    load_trigger,
    remove_trigger,
    upsert_trigger,
)

mcp = FastMCP("monitor-server")
LOG_PATH = Path(__file__).resolve().parent / "monitor-server.log"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("monitor-server")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DEFAULT_STATUS_URL = os.environ.get("CODEX_GATEWAY_STATUS_URL", "")
DEFAULT_STATUS_CANDIDATES = [
    "http://localhost:4000/status",
    "http://host.docker.internal:4000/status",
]


def _with_next_steps(result: Dict[str, Any], steps: List[str]) -> Dict[str, Any]:
    data = dict(result)
    data["next_steps"] = steps
    return data


def _env_file_for_session(session_id: str) -> Path:
    root = Path("/opt/codex-home") / "sessions" / session_id
    root.mkdir(parents=True, exist_ok=True)
    return root / ".env"


def _parse_env_file(env_path: Path) -> Dict[str, str]:
    env_vars: Dict[str, str] = {}
    if not env_path.exists():
        return env_vars
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            env_vars[key.strip()] = value.strip().strip('"').strip("'")
    return env_vars


def _write_env_file(env_path: Path, env_vars: Dict[str, str]) -> None:
    lines = []
    for key, value in sorted(env_vars.items()):
        if " " in value:
            lines.append(f'{key}="{value}"')
        else:
            lines.append(f"{key}={value}")
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _session_config_path(session_id: str) -> Path:
    return get_config_path_for_session(session_id)


def _record_to_payload(record: TriggerRecord) -> Dict[str, Any]:
    data = record.to_dict()
    next_fire = record.compute_next_fire()
    data["next_fire"] = next_fire.isoformat() if next_fire else None
    return data


def _apply_trigger_updates(record: TriggerRecord, updates: Dict[str, Any]) -> TriggerRecord:
    simple_fields = {"title", "description", "prompt_text", "enabled", "tags"}
    for key in simple_fields:
        if key in updates and updates[key] is not None:
            setattr(record, key, updates[key])
    if updates.get("schedule"):
        record.schedule = dict(updates["schedule"])
    if updates.get("created_by"):
        record.created_by = dict(updates["created_by"])
    return record


def _build_watcher_message(watcher_info: Dict[str, Any]) -> str:
    if not watcher_info:
        return "Watcher status unknown (no data)"
    if not watcher_info.get("enabled"):
        return "Watcher disabled (no valid paths configured)"
    paths = watcher_info.get("paths") or []
    prompt = watcher_info.get("prompt_file") or "built-in prompt"
    return f"Watcher enabled on {len(paths)} path(s); prompt={prompt}"

# ---------------------------------------------------------------------------
# Environment tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def monitor_set_env(session_id: str, key: str, value: str) -> Dict[str, Any]:
    """Set or update an environment variable in a monitor session .env file.

    Args:
        session_id: Monitor session identifier whose .env file should be edited.
        key: Environment variable name to set or update.
        value: String value that should be stored for the variable.
    """
    try:
        env_path = _env_file_for_session(session_id)
        env_vars = _parse_env_file(env_path)
        old_value = env_vars.get(key)
        env_vars[key] = value
        _write_env_file(env_path, env_vars)
        logger.info("Set env var %s for session %s", key, session_id)
        return _with_next_steps(
            {
                "success": True,
                "session_id": session_id,
                "key": key,
                "action": "updated" if old_value else "created",
                "env_file": str(env_path),
            },
            [
                "monitor_list_env(session_id='{}', show_values=True)".format(session_id),
                "Restart the affected monitor session to pick up new values",
            ],
        )
    except Exception as exc:  # pragma: no cover
        logger.error("Failed to set env var: %s", exc)
        return _with_next_steps(
            {"success": False, "error": str(exc)},
            ["Verify session_id and try monitor_get_env to confirm current values"],
        )


@mcp.tool()
async def monitor_get_env(session_id: str, key: str) -> Dict[str, Any]:
    """Retrieve a specific environment variable value from a session.

    Args:
        session_id: Monitor session identifier to inspect.
        key: Environment variable name to fetch.
    """
    try:
        env_path = _env_file_for_session(session_id)
        env_vars = _parse_env_file(env_path)
        if key in env_vars:
            return _with_next_steps(
                {"success": True, "session_id": session_id, "key": key, "value": env_vars[key]},
                ["Use monitor_set_env to update the value", "monitor_list_env(session_id='{}')".format(session_id)],
            )
        return _with_next_steps(
            {"success": False, "error": f"Environment variable '{key}' not found"},
            ["Check monitor_list_env for available keys"],
        )
    except Exception as exc:
        logger.error("Failed to get env var: %s", exc)
        return _with_next_steps(
            {"success": False, "error": str(exc)},
            ["Inspect the session .env file manually if necessary"],
        )


@mcp.tool()
async def monitor_delete_env(session_id: str, key: str) -> Dict[str, Any]:
    """Remove an environment variable from a session .env file.

    Args:
        session_id: Monitor session identifier whose .env file should be updated.
        key: Environment variable name to delete.
    """
    try:
        env_path = _env_file_for_session(session_id)
        env_vars = _parse_env_file(env_path)
        if key in env_vars:
            del env_vars[key]
            _write_env_file(env_path, env_vars)
            logger.info("Deleted env var %s for session %s", key, session_id)
            return _with_next_steps(
                {"success": True, "session_id": session_id, "key": key, "action": "deleted"},
                ["Confirm via monitor_list_env", "Restart the monitor session if it was running"],
            )
        return _with_next_steps(
            {"success": False, "error": f"Environment variable '{key}' not found"},
            ["Use monitor_get_env to verify spelling"],
        )
    except Exception as exc:
        logger.error("Failed to delete env var: %s", exc)
        return _with_next_steps(
            {"success": False, "error": str(exc)},
            ["Inspect the session .env file manually"],
        )


@mcp.tool()
async def monitor_list_env(session_id: str, show_values: bool = False) -> Dict[str, Any]:
    """List environment variables for a session (optionally showing values).

    Args:
        session_id: Monitor session identifier whose environment file should be shown.
        show_values: If True, return literal values instead of masking with placeholders.
    """
    try:
        env_path = _env_file_for_session(session_id)
        env_vars = _parse_env_file(env_path)
        output = env_vars if show_values else {k: "***" for k in env_vars}
        return _with_next_steps(
            {
                "success": True,
                "session_id": session_id,
                "count": len(env_vars),
                "env_file": str(env_path),
                "variables": output,
            },
            ["Use monitor_get_env for specific values", "Update entries via monitor_set_env"],
        )
    except Exception as exc:
        logger.error("Failed to list env vars: %s", exc)
        return _with_next_steps(
            {"success": False, "error": str(exc)},
            ["Check that the session exists and has a .env file"],
        )

# ---------------------------------------------------------------------------
# Trigger scheduling tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_triggers(session_id: str) -> Dict[str, Any]:
    """List configured monitor triggers for a session.

    Args:
        session_id: Monitor session identifier to inspect for triggers.
    """
    config_path = _session_config_path(session_id)
    records = list_trigger_records(config_path)
    payload = [_record_to_payload(r) for r in records]
    return _with_next_steps(
        {
            "success": True,
            "session_id": session_id,
            "count": len(payload),
            "triggers": payload,
            "config_path": str(config_path),
        },
        ["create_trigger to add new automation", "toggle_trigger to enable/disable entries"],
    )


@mcp.tool()
async def get_trigger(session_id: str, trigger_id: str) -> Dict[str, Any]:
    """Fetch a single trigger definition by ID.

    Args:
        session_id: Monitor session identifier containing the trigger.
        trigger_id: Unique ID of the trigger to retrieve.
    """
    config_path = _session_config_path(session_id)
    record = load_trigger(config_path, trigger_id)
    if not record:
        return _with_next_steps(
            {"success": False, "error": f"Trigger {trigger_id} not found"},
            ["Use list_triggers(session_id='{}') to view IDs".format(session_id)],
        )
    return _with_next_steps(
        {"success": True, "trigger": _record_to_payload(record)},
        ["update_trigger to modify fields", "toggle_trigger to change enabled state"],
    )


@mcp.tool()
async def create_trigger(
    session_id: str,
    title: str,
    description: str,
    prompt_text: str,
    schedule_mode: str,
    timezone_name: str = "UTC",
    schedule_time: Optional[str] = None,
    once_at: Optional[str] = None,
    minutes_from_now: Optional[float] = None,
    interval_minutes: Optional[float] = None,
    created_by_id: Optional[str] = None,
    created_by_name: Optional[str] = None,
    tags: Optional[List[str]] = None,
    enabled: bool = True,
) -> Dict[str, Any]:
    """Create a new monitor trigger (daily/once/interval).

    Args:
        session_id: Monitor session identifier where the trigger should be stored.
        title: Short human readable name for the trigger.
        description: Longer explanation describing the automation.
        prompt_text: Instructions Codex should execute when the trigger fires.
        schedule_mode: One of "daily", "once", or "interval".
        timezone_name: IANA timezone name to interpret schedule parameters in.
        schedule_time: HH:MM string used when schedule_mode="daily".
        once_at: ISO timestamp for schedule_mode="once".
        minutes_from_now: Convenience offset to compute once_at dynamically.
        interval_minutes: Number of minutes between runs for interval schedules.
        created_by_id: Optional identifier for the creator of the trigger.
        created_by_name: Human readable creator name for audit logs.
        tags: Optional list of tag strings to associate with the trigger.
        enabled: Whether the trigger should start enabled immediately.
    """

    schedule_mode = (schedule_mode or "").lower()
    schedule: Dict[str, Any]

    if schedule_mode == "daily":
        if not schedule_time:
            return _with_next_steps(
                {"success": False, "error": "schedule_time (HH:MM) required for daily mode"},
                ["Provide schedule_time like '14:30'"],
            )
        schedule = {"mode": "daily", "time": schedule_time, "timezone": timezone_name}
    elif schedule_mode == "once":
        computed_once_at = once_at
        if not computed_once_at and minutes_from_now is not None:
            delta = timedelta(minutes=float(minutes_from_now))
            computed_once_at = (datetime.now(timezone.utc) + delta).isoformat()
        if not computed_once_at:
            return _with_next_steps(
                {"success": False, "error": "once_at (ISO timestamp) required for once mode"},
                ["Set once_at='2025-12-13T19:00:00Z' or use minutes_from_now"],
            )
        schedule = {"mode": "once", "at": computed_once_at, "timezone": timezone_name}
    elif schedule_mode == "interval":
        if not interval_minutes or interval_minutes <= 0:
            return _with_next_steps(
                {"success": False, "error": "interval_minutes must be positive for interval mode"},
                ["Provide interval_minutes > 0"],
            )
        schedule = {"mode": "interval", "interval_minutes": interval_minutes, "timezone": timezone_name}
    else:
        return _with_next_steps(
            {"success": False, "error": f"Unsupported schedule_mode '{schedule_mode}'"},
            ["Valid options: daily, once, interval"],
        )

    if not prompt_text:
        return _with_next_steps(
            {"success": False, "error": "prompt_text is required"},
            ["Provide instructions for what Codex should do when the trigger fires"],
        )

    created = {"id": created_by_id or "unknown", "name": created_by_name or "unknown"}
    record = TriggerRecord(
        id=generate_trigger_id(),
        title=title,
        description=description,
        schedule=schedule,
        prompt_text=prompt_text,
        created_by=created,
        created_at=datetime.now(timezone.utc).isoformat(),
        enabled=enabled,
        tags=tags or [],
    )

    record.next_fire = record.compute_next_fire()
    config_path = _session_config_path(session_id)
    upsert_trigger(config_path, record)
    logger.info("Created trigger %s at %s", record.id, config_path)
    return _with_next_steps(
        {"success": True, "trigger": _record_to_payload(record), "config_path": str(config_path)},
        ["Use list_triggers to verify scheduling", "toggle_trigger to disable if needed"],
    )


@mcp.tool()
async def update_trigger(session_id: str, trigger_id: str, updates_json: str) -> Dict[str, Any]:
    """Patch fields on an existing trigger via JSON payload.

    Args:
        session_id: Monitor session identifier whose trigger should be patched.
        trigger_id: Trigger identifier to update.
        updates_json: JSON object string containing the fields to merge.
    """
    config_path = _session_config_path(session_id)
    record = load_trigger(config_path, trigger_id)
    if not record:
        return _with_next_steps(
            {"success": False, "error": f"Trigger {trigger_id} not found"},
            ["list_triggers(session_id='{}')".format(session_id)],
        )
    try:
        updates = json.loads(updates_json)
    except json.JSONDecodeError as exc:
        return _with_next_steps(
            {"success": False, "error": f"updates_json is not valid JSON: {exc}"},
            ["Ensure updates_json is a JSON object string"],
        )
    record = _apply_trigger_updates(record, updates)
    record.next_fire = record.compute_next_fire()
    upsert_trigger(config_path, record)
    logger.info("Updated trigger %s", trigger_id)
    return _with_next_steps(
        {"success": True, "trigger": _record_to_payload(record)},
        ["get_trigger to inspect the updated record"],
    )


@mcp.tool()
async def toggle_trigger(session_id: str, trigger_id: str, enabled: bool) -> Dict[str, Any]:
    """Enable or disable a trigger.

    Args:
        session_id: Monitor session identifier that stores the trigger.
        trigger_id: Trigger identifier whose enabled state should change.
        enabled: True to enable, False to disable the trigger.
    """
    config_path = _session_config_path(session_id)
    record = load_trigger(config_path, trigger_id)
    if not record:
        return _with_next_steps(
            {"success": False, "error": f"Trigger {trigger_id} not found"},
            ["list_triggers(session_id='{}')".format(session_id)],
        )
    record.enabled = enabled
    record.next_fire = record.compute_next_fire()
    upsert_trigger(config_path, record)
    logger.info("Set trigger %s enabled=%s", trigger_id, enabled)
    return _with_next_steps(
        {"success": True, "trigger": _record_to_payload(record)},
        ["Use get_trigger to confirm", "record_fire_result if manually executed"],
    )


@mcp.tool()
async def delete_trigger(session_id: str, trigger_id: str) -> Dict[str, Any]:
    """Delete a trigger from the schedule.

    Args:
        session_id: Monitor session identifier containing the trigger.
        trigger_id: Unique trigger identifier to remove.
    """
    config_path = _session_config_path(session_id)
    if remove_trigger(config_path, trigger_id):
        logger.info("Deleted trigger %s", trigger_id)
        return _with_next_steps(
            {"success": True},
            ["list_triggers(session_id='{}') to confirm removal".format(session_id)],
        )
    return _with_next_steps(
        {"success": False, "error": f"Trigger {trigger_id} not found"},
        ["Ensure trigger ID is correct via list_triggers"],
    )


@mcp.tool()
async def record_fire_result(
    session_id: str,
    trigger_id: str,
    fired_at_iso: Optional[str] = None,
) -> Dict[str, Any]:
    """Record that a trigger fired (updates last_fired timestamp).

    Args:
        session_id: Monitor session identifier containing the trigger record.
        trigger_id: Trigger identifier that has fired.
        fired_at_iso: Optional ISO timestamp override for when the trigger fired.
    """
    config_path = _session_config_path(session_id)
    record = load_trigger(config_path, trigger_id)
    if not record:
        return _with_next_steps(
            {"success": False, "error": f"Trigger {trigger_id} not found"},
            ["Use list_triggers(session_id='{}') to locate valid IDs".format(session_id)],
        )
    fired_at = (
        fired_at_iso
        if fired_at_iso
        else datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    record.last_fired = fired_at
    record.next_fire = record.compute_next_fire()
    upsert_trigger(config_path, record)
    logger.info("Recorded fire result for trigger %s at %s", trigger_id, fired_at)
    return _with_next_steps(
        {"success": True, "trigger": _record_to_payload(record)},
        ["Call toggle_trigger to disable if no longer required"],
    )

# ---------------------------------------------------------------------------
# Clock helpers
# ---------------------------------------------------------------------------


@mcp.tool()
async def clock_now(timezone_name: str = "UTC") -> Dict[str, Any]:
    """Return the current time for a given timezone.

    Args:
        timezone_name: IANA timezone string (defaults to "UTC").
    """
    try:
        tz = ZoneInfo(timezone_name)
    except Exception as exc:
        return _with_next_steps(
            {"success": False, "error": f"Invalid timezone '{timezone_name}': {exc}"},
            ["List available zones via Python's zoneinfo module"],
        )
    now = datetime.now(tz)
    return _with_next_steps(
        {"success": True, "timezone": timezone_name, "iso": now.isoformat()},
        ["Use clock_add to compute offsets", "Schedule triggers with schedule_time in this timezone"],
    )


@mcp.tool()
async def clock_add(
    base_iso: Optional[str] = None,
    days: int = 0,
    hours: int = 0,
    minutes: int = 0,
    seconds: int = 0,
    timezone_name: str = "UTC",
) -> Dict[str, Any]:
    """Add offsets to a timestamp (defaults to now).

    Args:
        base_iso: ISO timestamp to start from; uses current UTC time if omitted.
        days: Integer number of days to add (or subtract if negative).
        hours: Integer number of hours to add.
        minutes: Integer number of minutes to add.
        seconds: Integer number of seconds to add.
        timezone_name: IANA timezone string for result_local conversion.
    """
    if base_iso:
        try:
            base = datetime.fromisoformat(base_iso)
        except ValueError as exc:
            return _with_next_steps(
                {"success": False, "error": f"Invalid base_iso '{base_iso}': {exc}"},
                ["Provide ISO timestamps e.g. 2025-12-15T12:00:00+00:00"],
            )
    else:
        base = datetime.now(timezone.utc)
    delta = timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
    target = base + delta
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)
    try:
        tz = ZoneInfo(timezone_name)
        target_local = target.astimezone(tz)
    except Exception:
        tz = None
        target_local = target
    return _with_next_steps(
        {
            "success": True,
            "base": base.isoformat(),
            "result_utc": target.astimezone(timezone.utc).isoformat(),
            "result_local": target_local.isoformat(),
            "timezone": timezone_name if tz else "UTC",
        },
        ["Use once_at=result_utc for create_trigger(mode='once', ...)"],
    )

# ---------------------------------------------------------------------------
# Status / gateway watcher info
# ---------------------------------------------------------------------------


def _status_candidates(extra: Optional[str]) -> List[str]:
    urls: List[str] = []
    if extra:
        urls.append(extra)
    env_url = os.environ.get("CODEX_GATEWAY_STATUS_URL")
    if env_url:
        urls.append(env_url)
    urls.extend(DEFAULT_STATUS_CANDIDATES)
    seen = []
    for url in urls:
        if url and url not in seen:
            seen.append(url)
    return seen


def _fetch_status(url: str) -> Dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "monitor-server/1.0"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


@mcp.tool()
async def check_monitor_status(status_url: Optional[str] = None) -> Dict[str, Any]:
    """Fetch Codex gateway /status for watcher + webhook diagnostics.

    Args:
        status_url: Optional explicit status endpoint to try before defaults.
    """
    errors = []
    for candidate in _status_candidates(status_url):
        try:
            data = _fetch_status(candidate)
            watcher_info = data.get("watcher") or {}
            message = _build_watcher_message(watcher_info)
            webhook = data.get("webhook") or {}
            env_info = data.get("env") or {}
            return _with_next_steps(
                {
                    "success": True,
                    "status_url": candidate,
                    "watcher": watcher_info,
                    "watcher_summary": message,
                    "webhook": webhook,
                    "env": env_info,
                },
                ["If watcher disabled, set CODEX_GATEWAY_WATCH_PATHS and restart gateway"],
            )
        except urllib.error.URLError as exc:
            errors.append(f"{candidate}: {exc}")
        except Exception as exc:  # pragma: no cover
            errors.append(f"{candidate}: {exc}")
    return _with_next_steps(
        {"success": False, "error": "All status URLs failed", "attempts": errors},
        ["Ensure codex gateway is running and accessible on host port 4000"],
    )


if __name__ == "__main__":  # pragma: no cover
    mcp.run()
