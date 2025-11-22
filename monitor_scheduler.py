"""Utilities for Codex monitor scheduling configuration."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo
import uuid


CONFIG_FILENAME = ".codex-monitor-triggers.json"
SESSION_TRIGGERS_FILENAME = "triggers.json"
CODEX_HOME = Path("/opt/codex-home")
WORKSPACE_ROOT = Path("/workspace")
WORKSPACE_TRIGGER_PATH = (WORKSPACE_ROOT / CONFIG_FILENAME).resolve()
DEFAULT_SESSION_SENTINELS = {"workspace", "project", "cwd", "default", "unknown"}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_timezone(tz_name: Optional[str]) -> ZoneInfo:
    if not tz_name:
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(tz_name)
    except Exception as exc:  # pragma: no cover - rely on validation
        raise ValueError(f"Invalid timezone '{tz_name}': {exc}")


def _parse_iso(value: str) -> datetime:
    try:
        dt = datetime.fromisoformat(value)
    except ValueError as exc:  # pragma: no cover
        raise ValueError(f"Invalid ISO timestamp '{value}': {exc}")

    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_hhmm(value: str) -> datetime:
    if not value:
        raise ValueError("Schedule time must be provided as HH:MM")
    try:
        hour, minute = value.split(":", 1)
        return datetime(2000, 1, 1, int(hour), int(minute))
    except Exception as exc:  # pragma: no cover
        raise ValueError(f"Invalid schedule time '{value}': {exc}")


def get_session_dir(session_id: str) -> Path:
    """Get the session directory path for a given session ID."""
    session_dir = CODEX_HOME / "sessions" / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def get_session_triggers_path(session_id: str) -> Path:
    """Get the triggers file path for a session."""
    return get_session_dir(session_id) / SESSION_TRIGGERS_FILENAME


def resolve_custom_session_path(session_id: str) -> Optional[Path]:
    if session_id is None:
        return WORKSPACE_TRIGGER_PATH
    normalized = session_id.strip()
    if not normalized:
        return WORKSPACE_TRIGGER_PATH
    lowered = normalized.lower()
    if lowered in DEFAULT_SESSION_SENTINELS:
        return WORKSPACE_TRIGGER_PATH
    if normalized.startswith(("~", "/", ".")):
        candidate = Path(normalized).expanduser().resolve()
        if candidate.is_dir():
            return (candidate / CONFIG_FILENAME).resolve()
        return candidate
    return None


def get_config_path_for_session(session_id: str) -> Path:
    """Return the config path honoring workspace/absolute overrides."""
    custom = resolve_custom_session_path(session_id)
    if custom:
        custom.parent.mkdir(parents=True, exist_ok=True)
        return custom
    return get_session_triggers_path(session_id)


def get_session_env_path(session_id: str) -> Path:
    """Get the .env file path for a session."""
    return get_session_dir(session_id) / ".env"


@dataclass
class TriggerRecord:
    id: str
    title: str
    description: str
    schedule: Dict[str, Any]
    prompt_text: str
    created_by: Dict[str, Any]
    created_at: str
    enabled: bool = True
    tags: List[str] = field(default_factory=list)
    last_fired: Optional[str] = None

    # runtime-only fields
    next_fire: Optional[datetime] = None

    @property
    def timezone(self) -> ZoneInfo:
        tz_name = self.schedule.get("timezone") or self.schedule.get("tz")
        return _ensure_timezone(tz_name)

    def compute_next_fire(self, reference: Optional[datetime] = None) -> Optional[datetime]:
        if not self.enabled:
            return None

        reference = (reference or _utc_now()).astimezone(timezone.utc)
        mode = (self.schedule.get("mode") or "daily").lower()

        if mode == "once":
            fire_at = self.schedule.get("at")
            if not fire_at:
                raise ValueError(f"Trigger {self.id} missing 'at' for once schedule")
            target = _parse_iso(fire_at)
            if target <= reference:
                return None
            return target

        if mode == "daily":
            hhmm = self.schedule.get("time")
            if not hhmm:
                raise ValueError(f"Trigger {self.id} missing 'time' for daily schedule")
            parsed = _parse_hhmm(hhmm)
            tz = self.timezone
            local_now = reference.astimezone(tz)
            candidate = datetime.combine(local_now.date(), parsed.time(), tz)
            if candidate <= local_now:
                candidate = candidate + timedelta(days=1)
            return candidate.astimezone(timezone.utc)

        if mode == "interval":
            minutes = self.schedule.get("interval_minutes") or self.schedule.get("minutes")
            if not minutes or minutes <= 0:
                raise ValueError(f"Trigger {self.id} interval must be positive minutes")
            interval = timedelta(minutes=float(minutes))
            if self.last_fired:
                base = _parse_iso(self.last_fired)
            else:
                base = _parse_iso(self.created_at)
            candidate = base
            while candidate <= reference:
                candidate += interval
            return candidate

        raise ValueError(f"Unknown schedule mode '{mode}' for trigger {self.id}")

    def to_dict(self) -> Dict[str, Any]:
        data = {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "schedule": self.schedule,
            "prompt_text": self.prompt_text,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "enabled": self.enabled,
            "tags": self.tags,
        }
        if self.last_fired:
            data["last_fired"] = self.last_fired
        return data

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "TriggerRecord":
        missing = [key for key in ["id", "title", "description", "schedule", "prompt_text", "created_by", "created_at"] if key not in payload]
        if missing:
            raise ValueError(f"Trigger record missing fields: {missing}")
        record = cls(
            id=str(payload["id"]),
            title=str(payload["title"]),
            description=str(payload.get("description", "")),
            schedule=dict(payload["schedule"]),
            prompt_text=str(payload.get("prompt_text", "")),
            created_by=dict(payload.get("created_by", {})),
            created_at=str(payload.get("created_at")),
            enabled=bool(payload.get("enabled", True)),
            tags=list(payload.get("tags", []) or []),
            last_fired=payload.get("last_fired"),
        )
        return record


def load_config(config_path: Path) -> Dict[str, Any]:
    if not config_path.exists():
        return {"version": 1, "updated_at": _utc_now().isoformat(), "triggers": []}
    data = json.loads(config_path.read_text(encoding="utf-8"))
    if "triggers" not in data:
        data["triggers"] = []
    return data


def save_config(config_path: Path, config: Dict[str, Any]) -> None:
    config["updated_at"] = _utc_now().isoformat()
    config_path.write_text(json.dumps(config, indent=2, sort_keys=True), encoding="utf-8")


def ensure_trigger_list(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    triggers = config.get("triggers")
    if triggers is None:
        triggers = []
        config["triggers"] = triggers
    return triggers


def upsert_trigger(config_path: Path, record: TriggerRecord) -> TriggerRecord:
    config = load_config(config_path)
    triggers = ensure_trigger_list(config)
    filtered = [t for t in triggers if t.get("id") != record.id]
    filtered.append(record.to_dict())
    config["triggers"] = filtered
    save_config(config_path, config)
    return record


def remove_trigger(config_path: Path, trigger_id: str) -> bool:
    config = load_config(config_path)
    triggers = ensure_trigger_list(config)
    new_list = [t for t in triggers if t.get("id") != trigger_id]
    removed = len(triggers) != len(new_list)
    if removed:
        config["triggers"] = new_list
        save_config(config_path, config)
    return removed


def list_trigger_records(config_path: Path) -> List[TriggerRecord]:
    config = load_config(config_path)
    records: List[TriggerRecord] = []
    for item in ensure_trigger_list(config):
        try:
            record = TriggerRecord.from_dict(item)
            record.next_fire = record.compute_next_fire()
            records.append(record)
        except Exception as exc:
            # skip invalid entries but include placeholder for visibility
            placeholder = TriggerRecord(
                id=str(item.get("id", uuid.uuid4())),
                title=item.get("title", "Invalid Trigger"),
                description=f"Invalid trigger: {exc}",
                schedule=item.get("schedule", {}),
                prompt_text=item.get("prompt_text", ""),
                created_by=item.get("created_by", {}),
                created_at=item.get("created_at", _utc_now().isoformat()),
                enabled=False,
            )
            placeholder.next_fire = None
            records.append(placeholder)
    return records


def load_trigger(config_path: Path, trigger_id: str) -> Optional[TriggerRecord]:
    for record in list_trigger_records(config_path):
        if record.id == trigger_id:
            return record
    return None


def generate_trigger_id() -> str:
    return uuid.uuid4().hex


def render_template(template: str, values: Dict[str, Any]) -> str:
    output = template
    for key, value in values.items():
        output = output.replace(f"{{{{{key}}}}}", str(value))
    return output


__all__ = [
    "CONFIG_FILENAME",
    "SESSION_TRIGGERS_FILENAME",
    "CODEX_HOME",
    "WORKSPACE_ROOT",
    "WORKSPACE_TRIGGER_PATH",
    "TriggerRecord",
    "get_session_dir",
    "get_session_triggers_path",
    "get_session_env_path",
    "get_config_path_for_session",
    "resolve_custom_session_path",
    "load_config",
    "save_config",
    "list_trigger_records",
    "load_trigger",
    "upsert_trigger",
    "remove_trigger",
    "generate_trigger_id",
    "render_template",
]
