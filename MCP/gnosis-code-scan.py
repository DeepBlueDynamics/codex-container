#!/usr/bin/env python3
"""
MCP: gnosis-code-scan

High-performance directory scanning, metadata aggregation, and fuzzy file discovery.
Designed for codebases and large repositories that need fast stats and contextual insights.
"""

from __future__ import annotations

import os
import fnmatch
import sys
from pathlib import Path
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple

from rapidfuzz import process, fuzz
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("gnosis-code-scan")


def _file_iterator(
    directory: Path,
    recursive: bool,
    pattern: Optional[str],
    include_hidden: bool
) -> List[Path]:
    files: List[Path] = []
    stack = [directory]

    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    name = entry.name
                    if not include_hidden and name.startswith('.'):
                        continue

                    if entry.is_dir(follow_symlinks=False):
                        if recursive:
                            stack.append(Path(entry.path))
                        continue

                    if pattern:
                        if not fnmatch.fnmatch(name, pattern):
                            continue

                    files.append(Path(entry.path))
        except PermissionError:
            continue

    return files


def _gather_metadata(paths: List[Path]) -> Tuple[List[Dict[str, Any]], Dict[int, Dict[str, Any]]]:
    metadata: List[Dict[str, Any]] = []
    year_buckets: Dict[int, Dict[str, Any]] = defaultdict(lambda: {"count": 0, "total_size": 0, "paths": []})

    for path in paths:
        if not path.is_file():
            continue

        try:
            stat = path.stat()
        except OSError:
            continue

        modified = datetime.fromtimestamp(stat.st_mtime)
        year = modified.year
        size = stat.st_size
        entry = {
            "path": str(path),
            "name": path.name,
            "size": size,
            "modified": stat.st_mtime,
            "modified_iso": modified.isoformat(),
            "year": year,
            "extension": path.suffix.lower().lstrip('.') or "<no_ext>",
        }

        metadata.append(entry)
        bucket = year_buckets[year]
        bucket["count"] += 1
        bucket["total_size"] += size
        if len(bucket["paths"]) < 20:
            bucket["paths"].append(str(path))

    return metadata, year_buckets


def _summarize(metadata: List[Dict[str, Any]], year_buckets: Dict[int, Dict[str, Any]]) -> Dict[str, Any]:
    total_files = len(metadata)
    total_bytes = sum(item["size"] for item in metadata)
    last_touched = max((item["modified"] for item in metadata), default=0)
    last_touched_iso = datetime.fromtimestamp(last_touched).isoformat() if last_touched else None

    extensions: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"count": 0, "size": 0})
    for item in metadata:
        ext = item["extension"]
        extensions[ext]["count"] += 1
        extensions[ext]["size"] += item["size"]

    return {
        "total_files": total_files,
        "total_bytes": total_bytes,
        "last_touched": last_touched,
        "last_touched_iso": last_touched_iso,
        "per_year": {
            year: {
                "count": bucket["count"],
                "total_size": bucket["total_size"],
                "sample_paths": bucket["paths"],
            }
            for year, bucket in sorted(year_buckets.items(), reverse=True)
        },
        "extensions": {
            ext: {
                "count": info["count"],
                "size": info["size"]
            }
            for ext, info in sorted(extensions.items(), key=lambda kv: kv[1]["count"], reverse=True)[:20]
        }
    }


@mcp.tool()
async def scan_codebase(
    directory: str,
    recursive: bool = True,
    pattern: Optional[str] = None,
    include_hidden: bool = False,
    max_files: int = 10000
) -> Dict[str, Any]:
    """Scan a code directory, gather stats, and return structured summaries.

    Scans directories quickly via os.scandir, optionally filtering by glob pattern.
    Returns file metadata plus aggregated data by year and extension, enabling large-scale insights.
    """
    try:
        path = Path(directory).expanduser().resolve()
        if not path.exists():
            return {"success": False, "error": f"Directory not found: {directory}"}
        if not path.is_dir():
            return {"success": False, "error": f"Not a directory: {directory}"}

        files = _file_iterator(path, recursive, pattern, include_hidden)
        if len(files) > max_files:
            files = files[:max_files]
            truncated = True
        else:
            truncated = False

        metadata, year_buckets = _gather_metadata(files)
        summary = _summarize(metadata, year_buckets)

        return {
            "success": True,
            "directory": str(path),
            "file_count": summary["total_files"],
            "total_bytes": summary["total_bytes"],
            "last_touched_iso": summary["last_touched_iso"],
            "years": summary["per_year"],
            "extensions": summary["extensions"],
            "truncated": truncated
        }

    except Exception as exc:
        return {"success": False, "error": f"Scan failed: {exc}"}


@mcp.tool()
async def fuzzy_search_files(
    directory: str,
    query: str,
    limit: int = 20,
    score_threshold: int = 50,
    include_hidden: bool = False
) -> Dict[str, Any]:
    """Fuzzy search filenames using rapidfuzz scoring for fast relevance ranking."""
    try:
        path = Path(directory).expanduser().resolve()
        if not path.exists() or not path.is_dir():
            return {"success": False, "error": f"Directory not found: {directory}"}

        files = _file_iterator(path, recursive=True, pattern=None, include_hidden=include_hidden)
        metadata_map = {str(f): f.name for f in files}
        names = list(metadata_map.values())
        results = process.extract(
            query,
            names,
            scorer=fuzz.WRatio,
            score_cutoff=score_threshold,
            limit=limit
        )

        files_by_name = {f.name: f for f in files}
        matches = []
        for name, score, _ in results:
            file_path = files_by_name.get(name)
            if not file_path:
                continue
            try:
                stat = file_path.stat()
            except OSError:
                continue
            matches.append({
                "path": str(file_path),
                "score": score,
                "size": stat.st_size,
                "modified_iso": datetime.fromtimestamp(stat.st_mtime).isoformat()
            })

        return {
            "success": True,
            "query": query,
            "items": matches,
            "count": len(matches)
        }
    except Exception as exc:
        return {"success": False, "error": f"Fuzzy search failed: {exc}"}


if __name__ == "__main__":
    print("[gnosis-code-scan] Starting high-performance directory scanner", file=sys.stderr, flush=True)
    mcp.run()
