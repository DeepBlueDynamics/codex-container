#!/usr/bin/env python3
"""MCP: monitor-scheduler

Manage Codex monitor time-based triggers (create/list/update/delete).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from mcp.server.fastmcp import FastMCP

import sys
from zoneinfo import ZoneInfo

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
    WORKSPACE_TRIGGER_PATH,
    TriggerRecord,
    generate_trigger_id,
    get_config_path_for_session,
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

DEFAULT_GATEWAY_HOST = os.environ.get("CODEX_GATEWAY_HOST") or os.environ.get("CODEX_GATEWAY_BIND")
DEFAULT_HOST_CANDIDATE = DEFAULT_GATEWAY_HOST or "host.docker.internal"
DEFAULT_GATEWAY_PORT = os.environ.get("CODEX_GATEWAY_PORT", "4000")
GATEWAY_URL = os.environ.get("CODEX_GATEWAY_URL") or f"http://{DEFAULT_HOST_CANDIDATE}:{DEFAULT_GATEWAY_PORT}"


def _config_path(watch_path: str) -> Path:
    """DEPRECATED: Get config path from watch directory. Use _session_config_path instead."""
    root = Path(watch_path).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root / CONFIG_FILENAME


def _session_config_path(session_id: Optional[str]) -> Path:
    normalized = (session_id or "").strip()
    return get_config_path_for_session(normalized)


def _trigger_file_params(session_id: str) -> Dict[str, str]:
    return {"trigger_file": str(_session_config_path(session_id))}


def _build_gateway_url(path: str) -> str:
    base = GATEWAY_URL.rstrip('/')
    trimmed = path.lstrip('/')
    return f"{base}/{trimmed}" if trimmed else base


def _sync_gateway_request(method: str, path: str, params: Optional[Dict[str, Any]] = None, json_payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    url = _build_gateway_url(path)
    response = requests.request(
        method,
        url,
        params=params,
        json=json_payload,
        timeout=30,
    )
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        text = response.text.strip()
        raise RuntimeError(f"Gateway request failed ({response.status_code}): {text or exc}") from exc
    if response.status_code == 204:
        return {}
    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError(f"Invalid JSON from gateway: {exc}") from exc


async def _gateway_request(method: str, path: str, params: Optional[Dict[str, Any]] = None, json_payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return await asyncio.to_thread(_sync_gateway_request, method, path, params, json_payload)


def _ensure_trigger_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(entry)
    data.setdefault('id', str(entry.get('id') or entry.get('trigger_id') or generate_trigger_id()))
    data.setdefault('title', data['id'])
    data.setdefault('description', data.get('description', ''))
    data.setdefault('schedule', dict(entry.get('schedule') or {}))
    data.setdefault('prompt_text', data.get('prompt_text', ''))
    data.setdefault('created_by', entry.get('created_by') or {'id': 'unknown', 'name': 'unknown'})
    data.setdefault('created_at', entry.get('created_at') or datetime.now(timezone.utc).isoformat())
    data.setdefault('enabled', bool(entry.get('enabled', True)))
    tags = entry.get('tags')
    data['tags'] = list(tags) if isinstance(tags, list) else []
    return data


def _record_to_payload(entry: Dict[str, Any]) -> Dict[str, Any]:
    data = _ensure_trigger_entry(entry)
    try:
        record = TriggerRecord.from_dict(data)
        next_fire = record.compute_next_fire()
        payload = record.to_dict()
        payload['next_fire'] = next_fire.isoformat() if next_fire else None
        return payload
    except Exception as exc:
        fallback = dict(data)
        fallback['next_fire'] = None
        fallback['next_fire_error'] = str(exc)
        return fallback


def _build_schedule_payload(
    schedule_mode: str,
    timezone_name: str,
    schedule_time: Optional[str],
    once_at: Optional[str],
    minutes_from_now: Optional[float],
    interval_minutes: Optional[float],
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    mode = (schedule_mode or '').lower()
    if mode == 'daily':
        if not schedule_time:
            return None, 'schedule_time (HH:MM) required for daily mode'
        return {'mode': 'daily', 'time': schedule_time, 'timezone': timezone_name}, None
    if mode == 'once':
        computed = once_at
        if not computed and minutes_from_now is not None:
            try:
                delta = timedelta(minutes=float(minutes_from_now))
            except (TypeError, ValueError):
                return None, 'minutes_from_now must be numeric'
            computed = (datetime.now(timezone.utc) + delta).isoformat()
        if not computed:
            return None, 'once_at (ISO timestamp) required for once mode'
        return {'mode': 'once', 'at': computed, 'timezone': timezone_name}, None
    if mode == 'interval':
        if not interval_minutes or interval_minutes <= 0:
            return None, 'interval_minutes must be positive for interval mode'
        return {'mode': 'interval', 'interval_minutes': interval_minutes, 'timezone': timezone_name}, None
    return None, f'Unsupported schedule_mode \"{schedule_mode}\"'


@mcp.tool()
async def list_triggers(session_id: str) -> Dict[str, Any]:
    """List configured monitor triggers for a session."""

    config_path = _session_config_path(session_id)
    params = _trigger_file_params(session_id)
    try:
        response = await _gateway_request("GET", "triggers", params=params)
    except RuntimeError as exc:
        return {"success": False, "error": str(exc)}
    entries = response.get("triggers", [])
    payload = [_record_to_payload(entry) for entry in entries]
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
    params = _trigger_file_params(session_id)
    try:
        response = await _gateway_request("GET", "triggers", params=params)
    except RuntimeError as exc:
        return {"success": False, "error": str(exc)}
    for entry in response.get("triggers", []):
        if str(entry.get("id")) == trigger_id:
            return {
                "success": True,
                "trigger": _record_to_payload(entry),
                "config_path": str(config_path),
            }
    return {"success": False, "error": f"Trigger {trigger_id} not found"}


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
    """Create a new monitor trigger."""

    config_path = _session_config_path(session_id)
    if not prompt_text:
        return {"success": False, "error": "prompt_text is required"}
    schedule, error = _build_schedule_payload(
        schedule_mode,
        timezone_name,
        schedule_time,
        once_at,
        minutes_from_now,
        interval_minutes,
    )
    if error:
        return {"success": False, "error": error}

    created_by = {
        "id": created_by_id or "unknown",
        "name": created_by_name or "unknown",
    }
    record = TriggerRecord(
        id=generate_trigger_id(),
        title=title or "",
        description=description or "",
        schedule=schedule,
        prompt_text=prompt_text,
        created_by=created_by,
        created_at=datetime.now(timezone.utc).isoformat(),
        enabled=enabled,
        tags=tags or [],
    )
    try:
        record.compute_next_fire()
    except Exception as exc:
        return {"success": False, "error": f"Invalid schedule: {exc}"}

    payload = record.to_dict()
    params = _trigger_file_params(session_id)
    try:
        response = await _gateway_request("POST", "triggers", params=params, json_payload=payload)
    except RuntimeError as exc:
        return {"success": False, "error": str(exc)}
    trigger_entry = response.get("trigger", payload)
    return {
        "success": True,
        "trigger": _record_to_payload(trigger_entry),
        "config_path": str(config_path),
    }


@mcp.tool()
async def update_trigger(
    session_id: str,
    trigger_id: str,
    updates_json: str,
) -> Dict[str, Any]:
    """Update fields on an existing trigger."""

    config_path = _session_config_path(session_id)
    try:
        updates = json.loads(updates_json)
    except json.JSONDecodeError as exc:
        return {"success": False, "error": f"updates_json is not valid JSON: {exc}"}

    params = _trigger_file_params(session_id)
    try:
        response = await _gateway_request("PATCH", f"triggers/{trigger_id}", params=params, json_payload=updates)
    except RuntimeError as exc:
        return {"success": False, "error": str(exc)}
    trigger_entry = response.get("trigger")
    if not trigger_entry:
        return {"success": False, "error": f"Trigger {trigger_id} not found"}
    return {
        "success": True,
        "trigger": _record_to_payload(trigger_entry),
        "config_path": str(config_path),
    }


@mcp.tool()
async def toggle_trigger(session_id: str, trigger_id: str, enabled: bool) -> Dict[str, Any]:
    """Enable or disable a trigger."""

    config_path = _session_config_path(session_id)
    params = _trigger_file_params(session_id)
    try:
        response = await _gateway_request("PATCH", f"triggers/{trigger_id}", params=params, json_payload={"enabled": enabled})
    except RuntimeError as exc:
        return {"success": False, "error": str(exc)}
    trigger_entry = response.get("trigger")
    if not trigger_entry:
        return {"success": False, "error": f"Trigger {trigger_id} not found"}
    return {
        "success": True,
        "trigger": _record_to_payload(trigger_entry),
        "config_path": str(config_path),
    }


@mcp.tool()
async def delete_trigger(session_id: str, trigger_id: str) -> Dict[str, Any]:
    """Delete a trigger."""

    config_path = _session_config_path(session_id)
    params = _trigger_file_params(session_id)
    try:
        await _gateway_request("DELETE", f"triggers/{trigger_id}", params=params)
    except RuntimeError as exc:
        return {"success": False, "error": str(exc)}
    return {"success": True, "config_path": str(config_path)}


@mcp.tool()
async def record_fire_result(
    session_id: str,
    trigger_id: str,
    fired_at_iso: str,
) -> Dict[str, Any]:
    """Update the stored last_fired value for a trigger."""

    config_path = _session_config_path(session_id)
    params = _trigger_file_params(session_id)
    try:
        response = await _gateway_request(
            "PATCH",
            f"triggers/{trigger_id}",
            params=params,
            json_payload={"last_fired": fired_at_iso},
        )
    except RuntimeError as exc:
        return {"success": False, "error": str(exc)}
    trigger_entry = response.get("trigger")
    if not trigger_entry:
        return {"success": False, "error": f"Trigger {trigger_id} not found"}
    return {
        "success": True,
        "trigger": _record_to_payload(trigger_entry),
        "config_path": str(config_path),
    }


@mcp.tool()
async def clock_now(timezone_name: str = "UTC") -> Dict[str, Any]:
    """Return the current timestamp."""

    try:
        tz = ZoneInfo(timezone_name)
    except Exception as exc:
        return {"success": False, "error": f"Invalid timezone '{timezone_name}': {exc}"}

    now = datetime.now(tz)
    return {
        "success": True,
        "timezone": timezone_name,
        "iso": now.isoformat(),
        "epoch": now.timestamp(),
    }


@mcp.tool()
async def clock_add(
    base_iso: Optional[str] = None,
    days: float = 0,
    hours: float = 0,
    minutes: float = 0,
    seconds: float = 0,
    timezone_name: str = "UTC",
) -> Dict[str, Any]:
    """Add a delta to a base timestamp (default: now in UTC)."""

    try:
        tz = ZoneInfo(timezone_name)
    except Exception as exc:
        return {"success": False, "error": f"Invalid timezone '{timezone_name}': {exc}"}

    base = datetime.now(tz) if not base_iso else datetime.fromisoformat(base_iso).astimezone(tz)
    try:
        delta = timedelta(days=float(days), hours=float(hours), minutes=float(minutes), seconds=float(seconds))
    except ValueError as exc:
        return {"success": False, "error": f"Invalid delta: {exc}"}

    target = base + delta
    return {
        "success": True,
        "timezone": timezone_name,
        "base_iso": base.isoformat(),
        "delta": {"days": days, "hours": hours, "minutes": minutes, "seconds": seconds},
        "iso": target.isoformat(),
        "epoch": target.timestamp(),
    }


if __name__ == "__main__":
    mcp.run()
