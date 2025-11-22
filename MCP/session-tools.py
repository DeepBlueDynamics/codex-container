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
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
    get_session_dir,
    get_session_env_path,
    get_session_triggers_path,
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


def _list_sessions_root() -> Path:
    return Path(CODEX_HOME) / "sessions"


def _iter_sessions() -> List[str]:
    root = _list_sessions_root()
    if not root.exists():
        return []
    out: List[str] = []
    for entry in sorted(root.iterdir()):
        if entry.is_dir():
            out.append(entry.name)
    return out


def _session_summary(session_id: str) -> Dict[str, Any]:
    sdir = get_session_dir(session_id)
    env_path = get_session_env_path(session_id)
    trig_path = get_session_triggers_path(session_id)

    # Trigger count via helper for consistency
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
        "env_path": str(env_path),
        "triggers_path": str(trig_path),
        "env_keys": _env_key_count(env_path),
        "trigger_count": trigger_count,
        "exists": sdir.exists(),
        "modified": sdir.stat().st_mtime if sdir.exists() else None,
        "triggers_preview": triggers_preview,
    }


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
    ids = _iter_sessions()
    if query:
        q = query.strip().lower()
        ids = [s for s in ids if q in s.lower()]
    try:
        lim = max(1, min(int(limit), 1000))
    except Exception:
        lim = 200

    summaries = [_session_summary(s) for s in ids[:lim]]
    return {"success": True, "count": len(summaries), "sessions": summaries, "root": str(_list_sessions_root())}


@mcp.tool()
async def session_detail(session_id: str) -> Dict[str, Any]:
    """Get a detailed view for a specific session ID."""
    s = _session_summary(session_id)
    if not s.get("exists"):
        return {"success": False, "error": f"Session '{session_id}' not found", "root": str(_list_sessions_root())}

    # Include more detail: raw triggers metadata (capped) and env keys list (masked)
    env_path = Path(s["env_path"])  # type: ignore
    env_keys: List[str] = []
    if env_path.exists():
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

    trig_path = Path(s["triggers_path"])  # type: ignore
    triggers: List[Dict[str, Any]] = []
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
    return {"success": True, "session": s}


@mcp.tool()
async def session_search(query: str, limit: int = 50) -> Dict[str, Any]:
    """Search sessions by ID, trigger titles/descriptions, and env keys/values.

    Returns ranked matches with a basic heuristic score (100 exact, 80 prefix,
    50 substring), aggregated across fields.
    """
    needle = (query or "").strip()
    if not needle:
        return {"success": False, "error": "Query cannot be empty"}

    results: List[Tuple[int, Dict[str, Any]]] = []
    for sid in _iter_sessions():
        score = _score_match(sid, needle)
        meta = _session_summary(sid)

        # Search triggers
        try:
            tpath = Path(meta["triggers_path"])  # type: ignore
            from monitor_scheduler import list_trigger_records  # type: ignore

            for r in list_trigger_records(tpath):
                score += max(_score_match(r.title, needle), _score_match(r.description or "", needle))
        except Exception:
            pass

        # Search env keys and values (values masked in output)
        try:
            epath = Path(meta["env_path"])  # type: ignore
            if epath.exists():
                for line in epath.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    score += max(_score_match(k, needle), _score_match(v, needle))
        except Exception:
            pass

        if score > 0:
            results.append((score, meta))

    # Rank by score then by modified time desc
    results.sort(key=lambda x: (x[0], x[1].get("modified") or 0), reverse=True)
    capped = results[: max(1, min(int(limit), 200))]
    return {
        "success": True,
        "query": query,
        "count": len(capped),
        "results": [{"score": s, "session": m} for s, m in capped],
        "root": str(_list_sessions_root()),
    }


if __name__ == "__main__":
    mcp.run()

