#!/usr/bin/env python3
"""
Quick search across Codex rollout session logs (rollout-*.jsonl).

Usage examples:
  python scripts/search-sessions.py --pattern "error" --days 3
  python scripts/search-sessions.py --substring "docker build" --limit 20

By default, it looks in:
  $CODEX_HOME/.codex/sessions    (CODEX_HOME from env, or ~/.codex-service)
You can override with --codex-home.
"""

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path


def default_codex_home() -> Path:
    env = os.environ.get("CODEX_HOME") or os.environ.get("CODEX_CONTAINER_HOME")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".codex-service"


def iter_rollouts(root: Path, days: int, limit: int):
    sessions_dir = root / ".codex" / "sessions"
    if not sessions_dir.is_dir():
        return []
    cutoff = None
    if days > 0:
        cutoff = dt.datetime.utcnow() - dt.timedelta(days=days)
    files = []
    for path in sessions_dir.rglob("rollout-*.jsonl"):
        try:
            stat = path.stat()
        except OSError:
            continue
        if cutoff:
            mtime = dt.datetime.utcfromtimestamp(stat.st_mtime)
            if mtime < cutoff:
                continue
        files.append((stat.st_mtime, path))
    files.sort(reverse=True, key=lambda t: t[0])
    if limit and limit > 0:
        files = files[:limit]
    return [p for _, p in files]


def search_file(path: Path, matcher, max_hits_per_file: int):
    hits = []
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            for idx, line in enumerate(f, start=1):
                if matcher(line):
                    snippet = line.strip()
                    hits.append((idx, snippet))
                    if max_hits_per_file and len(hits) >= max_hits_per_file:
                        break
    except OSError:
        return []
    return hits


def extract_session_id(path: Path) -> str:
    m = re.search(r"rollout-.*-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.jsonl$", path.name)
    return m.group(1) if m else ""


def main():
    ap = argparse.ArgumentParser(description="Search Codex session rollout logs.")
    ap.add_argument("--pattern", help="Regex pattern to search for (mutually exclusive with --substring)")
    ap.add_argument("--substring", help="Plain substring to search for (case-insensitive)")
    ap.add_argument("--codex-home", help="Override Codex home (default: env CODEX_HOME or ~/.codex-service)")
    ap.add_argument("--days", type=int, default=3, help="Only include files modified within last N days (0=all) [default: 3]")
    ap.add_argument("--limit", type=int, default=50, help="Max files to scan, newest first [default: 50]")
    ap.add_argument("--hits-per-file", type=int, default=3, help="Max hits to report per file [default: 3]")
    ap.add_argument("--json", action="store_true", help="Emit JSON output (full hits)")
    ap.add_argument("--quiet", action="store_true", help="No stdout output (exit 0/1 can be used to test for matches)")
    ap.add_argument("--ids-only", action="store_true", help="Print only matching session IDs (one per line)")
    args = ap.parse_args()

    if args.pattern and args.substring:
        ap.error("Use either --pattern or --substring, not both.")
    if not args.pattern and not args.substring:
        ap.error("Provide --pattern or --substring.")

    home = Path(args.codex_home).expanduser() if args.codex_home else default_codex_home()
    matcher = None
    if args.pattern:
        rx = re.compile(args.pattern)
        matcher = lambda line: bool(rx.search(line))
    else:
        needle = args.substring.lower()
        matcher = lambda line: needle in line.lower()

    rollouts = iter_rollouts(home, args.days, args.limit)
    results = []
    for path in rollouts:
        hits = search_file(path, matcher, args.hits_per_file)
        if not hits:
            continue
        results.append({
            "session_id": extract_session_id(path),
            "file": str(path),
            "hits": [{"line": ln, "text": text} for ln, text in hits],
        })

    if args.json:
        json.dump({"count": len(results), "results": results}, sys.stdout, indent=2)
    elif args.ids_only:
        # unique session IDs, newest first
        seen = set()
        for entry in results:
            sid = entry["session_id"] or ""
            if sid and sid not in seen:
                print(sid)
                seen.add(sid)
    elif not args.quiet:
        print(f"Scanned {len(rollouts)} files, matches: {len(results)}")
        for entry in results:
            print(f"\n{entry['session_id'] or '<unknown>'}")
            print(f"  {entry['file']}")
            for hit in entry["hits"]:
                print(f"    L{hit['line']}: {hit['text']}")

    # Exit code: 0 if matches found or quiet/json requested; 1 if none and not quiet/json
    if not args.quiet and not args.json and len(results) == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
