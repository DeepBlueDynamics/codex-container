#!/usr/bin/env python3
"""
MCP: session-tools

Discover and search Codex monitor sessions.

This exposes utilities to list sessions, get details, and perform a fuzzy
search across session IDs, trigger metadata, and environment keys.

Sessions are stored under CODEX_HOME/sessions/<session_id> as defined in
monitor_scheduler.py. We reuse the helper to locate paths, keeping behavior
consistent with other monitor tools.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from mcp.server.fastmcp import FastMCP


# Discover helper module (same pattern as other monitor MCP tools)
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
    CODEX_HOME,
    SESSION_TRIGGERS_FILENAME,
    list_trigger_records,
)


mcp = FastMCP("session-tools")


def _safe_read_json(path: Path) -> Any:
    try:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _env_key_count(env_path: Path) -> int:
    if not env_path.exists():
        return 0
    try:
        count = 0
        for line in env_path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if "=" in s:
                count += 1
        return count
    except Exception:
        return 0


def _session_roots() -> List[Path]:
    """Return ordered candidate directories that may contain session logs."""

    candidates: List[Path] = []

    def _add(path_str: Optional[str]) -> None:
        if not path_str:
            return
        trimmed = path_str.strip()
        if trimmed:
            candidates.append(Path(trimmed).expanduser())

    # Gateway may expose comma-separated roots
    env_roots = os.environ.get("CODEX_GATEWAY_SESSION_DIRS")
    if env_roots:
        for part in env_roots.split(","):
            _add(part)

    _add(os.environ.get("CODEX_GATEWAY_SESSION_DIR"))
    _add(os.environ.get("SESSION_TOOLS_ROOT"))

    # Default gateway + legacy fallbacks, then classic monitor path
    candidates.append((Path(CODEX_HOME) / ".codex" / "sessions").resolve())
    candidates.append((Path(CODEX_HOME) / "sessions").resolve())
    candidates.append((Path.cwd() / ".codex-gateway-sessions").resolve())

    # Deduplicate while preserving order
    unique: List[Path] = []
    seen: set = set()
    for c in candidates:
        resolved = c
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return unique


def _read_rollout_session_id(path: Path) -> Optional[str]:
    try:
        with path.open('r', encoding='utf-8') as handle:
            first = handle.readline().strip()
        if not first:
            return None
        payload = json.loads(first)
        if payload.get('type') == 'session_meta':
            meta = payload.get('payload') or {}
            sid = meta.get('id')
            if isinstance(sid, str) and sid:
                return sid
    except Exception:
        return None
    return None


DEFAULT_GATEWAY_DIRS = {"default", "workspace", "project", "cwd", "unknown"}


def _session_mapping() -> Dict[str, Dict[str, Any]]:
    mapping: Dict[str, Dict[str, Any]] = {}
    for root in _session_roots():
        try:
            entries = sorted(root.iterdir())
        except FileNotFoundError:
            continue
        except Exception:
            continue
        for entry in entries:
            if entry.is_dir():
                name = entry.name
                if name.startswith('session-'):
                    sid = name
                elif name in DEFAULT_GATEWAY_DIRS:
                    sid = name
                else:
                    continue
                if sid not in mapping:
                    mapping[sid] = {'path': entry, 'kind': 'gateway'}
                continue
            if entry.is_file() and entry.name.startswith('rollout-'):
                sid = _read_rollout_session_id(entry)
                if sid and sid not in mapping:
                    mapping[sid] = {'path': entry, 'kind': 'cli'}
        for rollout in root.rglob('rollout-*.jsonl'):
            if not rollout.is_file():
                continue
            sid = _read_rollout_session_id(rollout)
            if sid and sid not in mapping:
                mapping[sid] = {'path': rollout, 'kind': 'cli'}
    return mapping


def _monitor_session_dir(session_id: str) -> Path:
    return (Path(CODEX_HOME) / "sessions" / session_id).resolve()


def _entry_path(entry: Union[Dict[str, Any], str, Path]) -> Path:
    raw = entry
    if isinstance(entry, dict):
        raw = entry.get("path")
    return Path(raw).resolve()


def _session_logs(session_dir: Path) -> Dict[str, Path]:
    if not session_dir.is_dir():
        return {}
    return {
        "stdout": session_dir / "stdout.log",
        "stderr": session_dir / "stderr.log",
        "events": session_dir / "events.jsonl",
    }


def _session_summary(session_id: str, session_entry: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    entry = session_entry or {'path': _monitor_session_dir(session_id), 'kind': 'gateway'}
    sdir = _entry_path(entry)
    kind = entry.get('kind') if isinstance(entry, dict) else 'gateway'
    env_path = None
    trig_path = None
    if kind != 'cli' or sdir.is_dir():
        env_path = sdir / ".env"
        trig_path = sdir / SESSION_TRIGGERS_FILENAME

    # Trigger count via helper for consistency against monitor scheduler format
    trigger_count = 0
    triggers_preview: List[Dict[str, Any]] = []
    if trig_path and trig_path.exists():
        try:
            records = list_trigger_records(trig_path)
            trigger_count = len(records)
            triggers_preview = [
                {
                    "id": r.id,
                    "title": r.title,
                    "enabled": r.enabled,
                    "next_fire": r.compute_next_fire().isoformat() if r.compute_next_fire() else None,
                }
                for r in records[:5]
            ]
        except Exception:
            trigger_count = 0
            triggers_preview = []

    return {
        "session_id": session_id,
        "dir": str(sdir),
        "env_path": str(env_path) if env_path else None,
        "triggers_path": str(trig_path) if trig_path else None,
        "env_keys": _env_key_count(env_path) if env_path else 0,
        "trigger_count": trigger_count,
        "exists": sdir.exists(),
        "modified": sdir.stat().st_mtime if sdir.exists() else None,
        "triggers_preview": triggers_preview,
        "type": kind,
    }


def _session_resume_hint(meta: Dict[str, Any]) -> str:
    sid = meta.get("session_id", "")
    stype = meta.get("type")
    if stype == "gateway":
        return (
            "Gateway monitor session directory. Not resumable; inspect stdout/stderr/events logs "
            "or re-run the monitor trigger."
        )
    if stype == "cli":
        return (
            "CLI/API rollout log. Resume with your container script, e.g. `./scripts/codex_container.ps1 "
            f"-SessionId {sid}`, or inspect the JSONL transcript directly."
        )
    return "Session type unknown; inspect the directory manually."


def _session_preview(entry_path: Path, max_chars: int = 600) -> Optional[str]:
    try:
        if entry_path.is_file():
            chunk = entry_path.read_text(encoding="utf-8", errors="ignore")[-max_chars:]
            return chunk.strip() or None
        logs = _session_logs(entry_path)
        for name in ("stdout", "stderr", "events"):
            path = logs.get(name)
            if path and path.exists():
                chunk = path.read_text(encoding="utf-8", errors="ignore")[-max_chars:]
                if chunk.strip():
                    return chunk.strip()
    except Exception:
        return None
    return None


def _score_match(hay: str, needle: str) -> int:
    h = hay.lower()
    n = needle.lower().strip()
    if not n:
        return 0
    if h == n:
        return 100
    if h.startswith(n):
        return 80
    if n in h:
        return 50
    return 0


@mcp.tool()
async def session_list(query: Optional[str] = None, limit: int = 200) -> Dict[str, Any]:
    """List known monitor sessions (optionally filter by substring)."""
    mapping = _session_mapping()
    ids = sorted(mapping.keys())
    if query:
        q = query.strip().lower()
        ids = [s for s in ids if q in s.lower()]
    try:
        lim = max(1, min(int(limit), 1000))
    except Exception:
        lim = 200

    summaries = [_session_summary(s, mapping[s]) for s in ids[:lim]]
    return {
        "success": True,
        "count": len(summaries),
        "sessions": summaries,
        "roots": [str(p) for p in _session_roots()],
    }


@mcp.tool()
async def session_detail(session_id: str) -> Dict[str, Any]:
    """Get a detailed view for a specific session ID."""
    mapping = _session_mapping()
    session_entry = mapping.get(session_id)
    if not session_entry:
        return {
            "success": False,
            "error": f"Session '{session_id}' not found",
            "roots": [str(p) for p in _session_roots()],
        }

    entry_path = _entry_path(session_entry)
    if not entry_path.exists():
        return {
            "success": False,
            "error": f"Session '{session_id}' not found",
            "roots": [str(p) for p in _session_roots()],
        }

    s = _session_summary(session_id, session_entry)

    # Include more detail: raw triggers metadata (capped) and env keys list (masked)
    env_path_str = s.get("env_path")
    env_path = Path(env_path_str) if env_path_str else None
    env_keys: List[str] = []
    if env_path and env_path.exists():
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, _ = line.split("=", 1)
                    env_keys.append(k.strip())
        except Exception:
            pass

    trig_path_str = s.get("triggers_path")
    trig_path = Path(trig_path_str) if trig_path_str else None
    triggers: List[Dict[str, Any]] = []
    if trig_path and trig_path.exists():
        try:
            from monitor_scheduler import list_trigger_records  # type: ignore

            for r in list_trigger_records(trig_path)[:50]:
                triggers.append(
                    {
                        "id": r.id,
                        "title": r.title,
                        "description": r.description,
                        "enabled": r.enabled,
                        "schedule": r.schedule,
                        "last_fired": r.last_fired,
                        "next_fire": r.compute_next_fire().isoformat() if r.compute_next_fire() else None,
                    }
                )
        except Exception:
            pass

    s["env_keys_list"] = env_keys
    s["triggers"] = triggers
    return {"success": True, "session": s, "roots": [str(p) for p in _session_roots()]}


@mcp.tool()
async def session_search(query: str, limit: int = 50) -> Dict[str, Any]:
    """Search sessions by ID, trigger titles/descriptions, and env keys/values.

    Returns ranked matches with a basic heuristic score (100 exact, 80 prefix,
    50 substring), aggregated across fields.
    """
    needle = (query or "").strip()
    if not needle:
        return {"success": False, "error": "Query cannot be empty"}

    results: List[Tuple[int, Dict[str, Any], str, str]] = []
    mapping = _session_mapping()
    for sid, session_entry in mapping.items():
        score = _score_match(sid, needle)
        meta = _session_summary(sid, session_entry)
        entry_path = _entry_path(session_entry)
        preview: Optional[str] = None

        # Search triggers
        tpath_str = meta.get("triggers_path")
        if tpath_str:
            try:
                tpath = Path(tpath_str)
                for r in list_trigger_records(tpath):
                    score += max(_score_match(r.title, needle), _score_match(r.description or "", needle))
            except Exception:
                pass

        # Search env keys and values (values masked in output)
        epath_str = meta.get("env_path")
        if epath_str:
            try:
                epath = Path(epath_str)
                if epath.exists():
                    for line in epath.read_text(encoding="utf-8").splitlines():
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        k, v = line.split("=", 1)
                        score += max(_score_match(k, needle), _score_match(v, needle))
            except Exception:
                pass

        # Search log contents if present
        try:
            if entry_path.is_file():
                chunk = entry_path.read_text(encoding="utf-8", errors="ignore")[-200000:]
                if chunk:
                    score += _score_match(chunk, needle)
                    if not preview:
                        preview = chunk[-600:].strip() or None
            else:
                logs = _session_logs(entry_path)
                for path in logs.values():
                    if not path.exists():
                        continue
                    chunk = path.read_text(encoding="utf-8", errors="ignore")[-200000:]
                    if chunk:
                        score += _score_match(chunk, needle)
                        if not preview:
                            preview = chunk[-600:].strip() or None
        except Exception:
            pass

        if score > 0:
            hint = _session_resume_hint(meta)
            log_preview = preview or _session_preview(entry_path) or ""
            results.append((score, meta, hint, log_preview))

    # Rank by score then by modified time desc
    results.sort(key=lambda x: (x[0], x[1].get("modified") or 0), reverse=True)
    capped = results[: max(1, min(int(limit), 200))]
    return {
        "success": True,
        "query": query,
        "count": len(capped),
        "results": [
            {"score": s, "session": m, "resume_hint": hint, "log_preview": preview}
            for s, m, hint, preview in capped
        ],
        "roots": [str(p) for p in _session_roots()],
    }


if __name__ == "__main__":
    mcp.run()
