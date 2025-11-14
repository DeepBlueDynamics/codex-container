#!/usr/bin/env python3
"""MCP: monitor-scheduler

Manage Codex monitor time-based triggers (create/list/update/delete).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

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

from monitor_scheduler import (
    CONFIG_FILENAME,
    TriggerRecord,
    generate_trigger_id,
    get_session_triggers_path,
    list_trigger_records,
    load_config,
    load_trigger,
    remove_trigger,
    save_config,
    upsert_trigger,
)


LOG_PATH = Path(__file__).resolve().parent / "monitor-scheduler.log"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler()
    ],
)

logger = logging.getLogger("monitor-scheduler")
mcp = FastMCP("monitor-scheduler")


def _config_path(watch_path: str) -> Path:
    """DEPRECATED: Get config path from watch directory. Use _session_config_path instead."""
    root = Path(watch_path).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root / CONFIG_FILENAME


def _session_config_path(session_id: str) -> Path:
    """Get config path for a session ID."""
    return get_session_triggers_path(session_id)


def _record_to_payload(record: TriggerRecord) -> Dict[str, Any]:
    data = record.to_dict()
    next_fire = record.compute_next_fire()
    data["next_fire"] = next_fire.isoformat() if next_fire else None
    return data


def _apply_updates(record: TriggerRecord, updates: Dict[str, Any]) -> TriggerRecord:
    allowed_simple = {"title", "description", "prompt_text", "enabled", "tags"}
    for key in allowed_simple:
        if key in updates and updates[key] is not None:
            setattr(record, key, updates[key])

    if "schedule" in updates and updates["schedule"]:
        record.schedule = dict(updates["schedule"])

    if "created_by" in updates and updates["created_by"]:
        record.created_by = dict(updates["created_by"])

    return record


@mcp.tool()
async def list_triggers(session_id: str) -> Dict[str, Any]:
    """List configured monitor triggers for a session."""

    config_path = _session_config_path(session_id)
    records = list_trigger_records(config_path)
    payload = [_record_to_payload(r) for r in records]
    return {
        "success": True,
        "session_id": session_id,
        "count": len(payload),
        "triggers": payload,
        "config_path": str(config_path),
    }


@mcp.tool()
async def get_trigger(session_id: str, trigger_id: str) -> Dict[str, Any]:
    """Get a single trigger definition."""

    config_path = _session_config_path(session_id)
    record = load_trigger(config_path, trigger_id)
    if not record:
        return {"success": False, "error": f"Trigger {trigger_id} not found"}

    return {"success": True, "trigger": _record_to_payload(record)}


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
    interval_minutes: Optional[float] = None,
    created_by_id: Optional[str] = None,
    created_by_name: Optional[str] = None,
    tags: Optional[List[str]] = None,
    enabled: bool = True,
) -> Dict[str, Any]:
    """Create a new monitor trigger."""

    config_path = _session_config_path(session_id)

    schedule_mode = (schedule_mode or "").lower()
    schedule: Dict[str, Any]

    if schedule_mode == "daily":
        if not schedule_time:
            return {"success": False, "error": "schedule_time (HH:MM) required for daily mode"}
        schedule = {"mode": "daily", "time": schedule_time, "timezone": timezone_name}
    elif schedule_mode == "once":
        if not once_at:
            return {"success": False, "error": "once_at (ISO timestamp) required for once mode"}
        schedule = {"mode": "once", "at": once_at, "timezone": timezone_name}
    elif schedule_mode == "interval":
        if not interval_minutes or interval_minutes <= 0:
            return {"success": False, "error": "interval_minutes must be positive for interval mode"}
        schedule = {"mode": "interval", "interval_minutes": interval_minutes, "timezone": timezone_name}
    else:
        return {"success": False, "error": f"Unsupported schedule_mode '{schedule_mode}'"}

    if not prompt_text:
        return {"success": False, "error": "prompt_text is required"}

    created = {
        "id": created_by_id or "unknown",
        "name": created_by_name or "unknown",
    }

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

    try:
        record.next_fire = record.compute_next_fire()
    except Exception as exc:
        return {"success": False, "error": f"Invalid schedule: {exc}"}

    upsert_trigger(config_path, record)
    logger.info("Created trigger %s at %s", record.id, config_path)

    return {"success": True, "trigger": _record_to_payload(record), "config_path": str(config_path)}


@mcp.tool()
async def update_trigger(
    session_id: str,
    trigger_id: str,
    updates_json: str,
) -> Dict[str, Any]:
    """Update fields on an existing trigger.

    Pass a JSON object with fields to modify. Supported keys: title, description,
    prompt_text, enabled, tags, schedule, created_by.
    """

    config_path = _session_config_path(session_id)
    record = load_trigger(config_path, trigger_id)
    if not record:
        return {"success": False, "error": f"Trigger {trigger_id} not found"}

    try:
        updates = json.loads(updates_json)
    except json.JSONDecodeError as exc:
        return {"success": False, "error": f"updates_json is not valid JSON: {exc}"}

    record = _apply_updates(record, updates)

    try:
        record.next_fire = record.compute_next_fire()
    except Exception as exc:
        return {"success": False, "error": f"Updated schedule invalid: {exc}"}

    upsert_trigger(config_path, record)
    logger.info("Updated trigger %s", trigger_id)
    return {"success": True, "trigger": _record_to_payload(record)}


@mcp.tool()
async def toggle_trigger(session_id: str, trigger_id: str, enabled: bool) -> Dict[str, Any]:
    """Enable or disable a trigger."""

    config_path = _session_config_path(session_id)
    record = load_trigger(config_path, trigger_id)
    if not record:
        return {"success": False, "error": f"Trigger {trigger_id} not found"}

    record.enabled = enabled
    record.next_fire = record.compute_next_fire()
    upsert_trigger(config_path, record)
    logger.info("Set trigger %s enabled=%s", trigger_id, enabled)
    return {"success": True, "trigger": _record_to_payload(record)}


@mcp.tool()
async def delete_trigger(session_id: str, trigger_id: str) -> Dict[str, Any]:
    """Delete a trigger."""

    config_path = _session_config_path(session_id)
    removed = remove_trigger(config_path, trigger_id)
    if removed:
        logger.info("Deleted trigger %s", trigger_id)
        return {"success": True}
    return {"success": False, "error": f"Trigger {trigger_id} not found"}


@mcp.tool()
async def record_fire_result(
    session_id: str,
    trigger_id: str,
    fired_at_iso: str,
) -> Dict[str, Any]:
    """Update the stored last_fired value for a trigger.

    This tool is intended to be invoked by the monitor runtime after a scheduled
    trigger fires successfully so that external observers can see usage data.
    """

    config_path = _session_config_path(session_id)
    record = load_trigger(config_path, trigger_id)
    if not record:
        return {"success": False, "error": f"Trigger {trigger_id} not found"}

    record.last_fired = fired_at_iso
    record.next_fire = record.compute_next_fire()
    upsert_trigger(config_path, record)
    logger.info("Recorded fire for %s at %s", trigger_id, fired_at_iso)
    return {"success": True, "trigger": _record_to_payload(record)}


if __name__ == "__main__":
    mcp.run()
