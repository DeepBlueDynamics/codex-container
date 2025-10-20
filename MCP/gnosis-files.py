#!/usr/bin/env python3
"""
MCP: file-diff
Safe, robust diff-based file editing with backups, search helpers, and large-file-aware readers.

Follows the MCP patterns used in this repo (FastMCP over stdio), mirroring MCP/gnosis-crawl.py.

Tools exposed (initial set):
- file_diff_write
- text_diff_edit, simple_text_diff
- file_diff_versions, file_diff_restore
- file_stat, file_read, file_read_window, file_read_version, file_read_around
- search_in_file_fuzzy, search_in_file_regex
- get_diff_formats
"""

from __future__ import annotations

import os
import re
import json
import time
import shutil
import difflib
import pathlib
import logging
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

from mcp.server.fastmcp import FastMCP, Context


mcp = FastMCP("file-diff")

__version__ = "0.1.0"


# ----------------------------------
# Logging
# ----------------------------------
def _init_logger() -> logging.Logger:
    """
    Initialize and configure the file-diff logger.
    
    Creates log directory (prefers context_substrate/logs, falls back to logs/)
    and sets up file handler with timestamped formatting.
    
    Returns:
        logging.Logger: Configured logger instance
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    # Prefer MCP/context_substrate/logs if available; else fallback to MCP/logs
    substrate_logs = os.path.join(base_dir, "context_substrate", "logs")
    logs_dir = substrate_logs if os.path.isdir(os.path.join(base_dir, "context_substrate")) else os.path.join(base_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    log_path = os.path.join(logs_dir, "file_diff.log")

    logger = logging.getLogger("file_diff")
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        fh = logging.FileHandler(log_path)
        fmt = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    logger.info("file-diff MCP starting; version=%s", __version__)
    logger.info("Logging to %s", log_path)
    return logger



logger = _init_logger()


# ----------------------------------
# Diff patterns (consolidated)
# ----------------------------------
DIFF_PATTERNS: Dict[str, Dict[str, str]] = {
    "custom_safe": {
        "pattern": r'<<<CUSTOM_SEARCH>>>\n(.*?)\n<<<CUSTOM_REPLACE>>>\n(.*?)\n<<<END_CUSTOM>>>'
    },
    "toolkami_fenced": {
        "pattern": r'```diff\s*\n(.*?)\n<<<<<<< SEARCH\n(.*?)={7}\n(.*?)>>>>>>> REPLACE\n```'
    },
    "toolkami_direct": {
        "pattern": r'(.*?)\n<<<<<<< SEARCH\n(.*?)={7}\n(.*?)>>>>>>> REPLACE'
    },
    "simple_blocks": {
        "pattern": r'<<<<<<< SEARCH\n(.*?)={7}\n(.*?)>>>>>>> REPLACE'
    },
    "evolvemcp_style": {
        "pattern": r'```diff\n(.*?)<<<<<<< SEARCH\n(.*?)={7}\n(.*?)>>>>>>> REPLACE\n```'
    },
    "git_style": {
        "pattern": r'--- a/(.*?)\n\+\+\+ b/.*?\n@@ .*? @@.*?\n(.*?)(?=\n--- a/|$)'
    },
}


# ----------------------------------
# Common utilities
# ----------------------------------
def _norm_path(p: str) -> str:
    """
    Normalize a file path by expanding user home directory and resolving to absolute path.
    
    Args:
        p: Path string (may contain ~ or be relative)
    
    Returns:
        str: Absolute, expanded path
    """
    return os.path.abspath(os.path.expanduser(p))


def _human_size(n: int) -> str:
    """
    Convert byte count to human-readable size string.
    
    Args:
        n: Number of bytes
    
    Returns:
        str: Formatted size (e.g., "4.2KB", "1.5MB", "3.7GB")
    """
    if n < 1024:
        return f"{n}B"
    if n < 1024 * 1024:
        return f"{n/1024:.1f}KB"
    if n < 1024 * 1024 * 1024:
        return f"{n/1048576:.1f}MB"
    return f"{n/1073741824:.1f}GB"



def read_file_content(file_path: str, encoding: str = "utf-8") -> str:
    """
    Read entire file contents as a string.
    
    Args:
        file_path: Path to file to read
        encoding: Text encoding (default: utf-8)
    
    Returns:
        str: File contents
    
    Raises:
        Exception: If file cannot be read
    """
    try:
        return pathlib.Path(file_path).read_text(encoding=encoding)
    except Exception as e:
        logger.error("Error reading %s: %s", file_path, e)
        raise


def write_file_content(file_path: str, content: str, encoding: str = "utf-8") -> None:
    """
    Write string content to file, creating parent directories if needed.
    
    Args:
        file_path: Destination file path
        content: Text content to write
        encoding: Text encoding (default: utf-8)
    
    Raises:
        Exception: If file cannot be written
    """
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        pathlib.Path(file_path).write_text(content, encoding=encoding)
    except Exception as e:
        logger.error("Error writing %s: %s", file_path, e)
        raise



# ----------------------------------
# Backups / versions
# ----------------------------------
def ensure_version_dir(file_path: str) -> str:
    directory = os.path.dirname(file_path)
    filename = os.path.basename(file_path)
    versions_dir = os.path.join(directory, f".{filename}_versions")
    os.makedirs(versions_dir, exist_ok=True)
    return versions_dir


def get_file_versions(file_path: str) -> List[Dict[str, Any]]:
    versions: List[Dict[str, Any]] = []
    if not os.path.exists(file_path):
        return versions
    versions_dir = ensure_version_dir(file_path)
    if not os.path.exists(versions_dir):
        return versions
    try:
        for f in os.listdir(versions_dir):
            full = os.path.join(versions_dir, f)
            if not os.path.isfile(full):
                continue
            m = re.match(r"v(\d+)_(\d+)(\.[\w-]+)?\.backup", f)
            if not m:
                continue
            version_number = int(m.group(1))
            timestamp = int(m.group(2))
            tag = m.group(3)[1:] if m.group(3) else None
            st = os.stat(full)
            versions.append({
                "version": version_number,
                "timestamp": timestamp,
                "date": datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S"),
                "size": st.st_size,
                "size_human": _human_size(st.st_size),
                "path": full,
                "tag": tag,
            })
    except Exception as e:
        logger.warning("get_file_versions error for %s: %s", file_path, e)

    versions.sort(key=lambda x: x["version"], reverse=True)
    if os.path.exists(file_path):
        st = os.stat(file_path)
        versions.insert(0, {
            "version": "current",
            "timestamp": int(st.st_mtime),
            "date": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "size": st.st_size,
            "size_human": _human_size(st.st_size),
            "path": file_path,
        })
    return versions


def _next_version_number(file_path: str) -> int:
    versions = get_file_versions(file_path)
    past = [v for v in versions if v["version"] != "current"]
    if not past:
        return 1
    return max(v["version"] for v in past) + 1


def create_file_backup(file_path: str, change_tag: Optional[str] = None) -> Dict[str, Any]:
    versions_dir = ensure_version_dir(file_path)
    vnum = _next_version_number(file_path)
    ts = int(time.time())
    if change_tag:
        safe = re.sub(r"[^\w\-_]", "_", change_tag)
        fname = f"v{vnum}_{ts}.{safe}.backup"
    else:
        fname = f"v{vnum}_{ts}.backup"
    backup_path = os.path.join(versions_dir, fname)
    shutil.copy2(file_path, backup_path)
    st = os.stat(backup_path)
    logger.info("Created backup: %s", backup_path)
    return {
        "version": vnum,
        "timestamp": ts,
        "date": datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S"),
        "size": st.st_size,
        "size_human": _human_size(st.st_size),
        "path": backup_path,
        "change_tag": change_tag,
    }


def restore_file_version(file_path: str, version_number: int) -> Dict[str, Any]:
    versions = get_file_versions(file_path)
    past = [v for v in versions if v["version"] != "current"]
    if not past:
        raise ValueError("No previous versions found")
    target = next((v for v in past if v["version"] == version_number), None)
    if not target:
        raise ValueError(f"Version {version_number} not found")
    shutil.copy2(target["path"], file_path)
    logger.info("Restored %s to version %d", file_path, version_number)
    return {
        "success": True,
        "file_path": file_path,
        "restored_version": version_number,
    }


# ----------------------------------
# Text processing & fuzzy matching
# ----------------------------------
def normalize_whitespace(text: str, preserve_structure: bool = True) -> str:
    if preserve_structure:
        lines = text.split("\n")
        return "\n".join(re.sub(r"\s+", " ", ln.strip()) for ln in lines)
    return re.sub(r"\s+", " ", text.strip())


def calculate_similarity(a: str, b: str, method: str = "ratio") -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    if method == "ratio":
        return difflib.SequenceMatcher(None, a, b).ratio()
    if method == "token_sort":
        pa = " ".join(sorted(a.lower().split()))
        pb = " ".join(sorted(b.lower().split()))
        return difflib.SequenceMatcher(None, pa, pb).ratio()
    if method == "token_set":
        ta, tb = set(a.lower().split()), set(b.lower().split())
        if not ta and not tb:
            return 1.0
        if not ta or not tb:
            return 0.0
        return len(ta & tb) / max(len(ta), len(tb))
    return difflib.SequenceMatcher(None, a, b).ratio()


def find_fuzzy_matches(search_text: str, content: str, similarity_threshold: float = 0.8,
                       methods: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    if methods is None:
        methods = ["exact", "normalized", "multiline", "single_line", "token"]

    matches: List[Dict[str, Any]] = []

    # Exact
    if "exact" in methods and search_text in content:
        start = content.find(search_text)
        matches.append({
            "text": search_text,
            "similarity": 1.0,
            "start_pos": start,
            "end_pos": start + len(search_text),
            "match_type": "exact",
            "strategy": "exact",
        })
        return matches

    # Whitespace-normalized
    if "normalized" in methods:
        ns, nc = normalize_whitespace(search_text), normalize_whitespace(content)
        if ns in nc:
            # best-effort position
            start = content.lower().find(search_text.strip().lower())
            if start >= 0:
                matches.append({
                    "text": search_text.strip(),
                    "similarity": 0.95,
                    "start_pos": start,
                    "end_pos": start + len(search_text.strip()),
                    "match_type": "normalized",
                    "strategy": "normalized",
                })

    # Multiline sliding window
    if "multiline" in methods and "\n" in search_text:
        s_lines = [ln.strip() for ln in search_text.strip().split("\n") if ln.strip() != ""]
        c_lines = content.split("\n")
        if s_lines:
            s_len = len(s_lines)
            for i in range(0, max(0, len(c_lines) - s_len + 1)):
                seg_lines = [ln.strip() for ln in c_lines[i:i + s_len]]
                seg = "\n".join(seg_lines)
                sim = calculate_similarity("\n".join(s_lines), seg, "ratio")
                if sim >= similarity_threshold:
                    start_pos = sum(len(x) + 1 for x in c_lines[:i])
                    matches.append({
                        "text": "\n".join(c_lines[i:i + s_len]),
                        "similarity": sim,
                        "start_pos": start_pos,
                        "end_pos": start_pos + len("\n".join(c_lines[i:i + s_len])),
                        "match_type": "fuzzy_multiline",
                        "strategy": "multiline",
                    })

    # Single line fuzzy
    if "single_line" in methods and "\n" not in search_text:
        target = search_text.strip()
        best: Optional[Dict[str, Any]] = None
        c_lines = content.split("\n")
        for idx, ln in enumerate(c_lines):
            sim = difflib.SequenceMatcher(None, target, ln.strip()).ratio()
            if sim >= max(0.6, similarity_threshold - 0.2) and (best is None or sim > best["similarity"]):
                start_pos = sum(len(x) + 1 for x in c_lines[:idx])
                best = {
                    "text": ln,
                    "similarity": sim,
                    "start_pos": start_pos,
                    "end_pos": start_pos + len(ln),
                    "match_type": "fuzzy_single_line",
                    "strategy": "single_line",
                }
        if best:
            matches.append(best)

    # Token (approx)
    if "token" in methods:
        sim = calculate_similarity(search_text, content, "token_sort")
        if sim >= similarity_threshold:
            start = content.lower().find(search_text.strip().lower())
            if start < 0:
                first_words = " ".join(search_text.strip().split()[:3])
                start = content.lower().find(first_words.lower())
            if start >= 0:
                matches.append({
                    "text": search_text,
                    "similarity": sim,
                    "start_pos": start,
                    "end_pos": start + len(search_text.strip()),
                    "match_type": "token_based",
                    "strategy": "token",
                })

    matches.sort(key=lambda x: x["similarity"], reverse=True)
    return matches


# ----------------------------------
# Diff extraction & application
# ----------------------------------
def extract_diff_blocks(diff_text: str) -> List[Tuple[str, str, Dict[str, Any]]]:
    blocks: List[Tuple[str, str, Dict[str, Any]]] = []

    # Strategy: custom_safe
    m = re.findall(DIFF_PATTERNS["custom_safe"]["pattern"], diff_text, re.DOTALL)
    if m:
        for search, replace in m:
            blocks.append((search, replace, {"method": "custom_safe"}))
        return blocks

    # toolkami_fenced
    m = re.findall(DIFF_PATTERNS["toolkami_fenced"]["pattern"], diff_text, re.DOTALL)
    if m:
        for filename, search, replace in m:
            blocks.append((search, replace, {"filename_hint": filename.strip(), "method": "toolkami_fenced"}))
        return blocks

    # toolkami_direct
    m = re.findall(DIFF_PATTERNS["toolkami_direct"]["pattern"], diff_text, re.DOTALL)
    if m:
        for filename, search, replace in m:
            blocks.append((search, replace, {"filename_hint": filename.strip(), "method": "toolkami_direct"}))
        return blocks

    # simple_blocks
    m = re.findall(DIFF_PATTERNS["simple_blocks"]["pattern"], diff_text, re.DOTALL)
    if m:
        for search, replace in m:
            blocks.append((search, replace, {"method": "simple_blocks"}))
        return blocks

    # evolvemcp_style
    m = re.findall(DIFF_PATTERNS["evolvemcp_style"]["pattern"], diff_text, re.DOTALL)
    if m:
        for _, search, replace in m:
            blocks.append((search, replace, {"method": "evolvemcp_style"}))
        return blocks

    # git_style
    m = re.findall(DIFF_PATTERNS["git_style"]["pattern"], diff_text, re.DOTALL)
    if m:
        for filename, diff_content in m:
            search_lines: List[str] = []
            replace_lines: List[str] = []
            for ln in diff_content.splitlines():
                if ln.startswith('-'):
                    search_lines.append(ln[1:])
                elif ln.startswith('+'):
                    replace_lines.append(ln[1:])
                else:
                    search_lines.append(ln)
                    replace_lines.append(ln)
            blocks.append(("\n".join(search_lines), "\n".join(replace_lines), {"filename_hint": filename.strip(), "method": "git_style"}))
        return blocks

    return blocks


def apply_diff_edit(original_text: str, search_text: str, replace_text: str,
                    similarity_threshold: float = 0.8,
                    allow_partial_matches: bool = True,
                    replace_all: bool = False) -> Tuple[str, bool, Dict[str, Any]]:
    debug = {"matches_found": 0, "match_details": [], "success": False, "replaced_count": 0}

    if not search_text.strip():
        modified = original_text + ("\n" if not original_text.endswith("\n") else "") + replace_text
        debug.update({"success": True, "operation": "append", "match_type": "empty_search", "replaced_count": 1})
        return modified, True, debug

    methods = ["exact", "normalized"]
    if allow_partial_matches:
        methods.extend(["multiline", "single_line", "token"])

    matches = find_fuzzy_matches(search_text, original_text, similarity_threshold, methods)
    debug["matches_found"] = len(matches)
    debug["match_details"] = matches[:3]

    if not matches:
        debug.update({
            "success": False,
            "error": "no_matches_found",
            "tip": "Try smaller diff blocks, lower similarity_threshold, or use custom_safe fences.",
            "search_preview": (search_text[:100] + ("..." if len(search_text) > 100 else "")),
        })
        return original_text, False, debug

    best = matches[0]
    match_text = best["text"]

    # Replacement
    if replace_all:
        # For fuzzy match text, .count may be zero; ensure at least one replace
        if match_text in original_text:
            count_before = original_text.count(match_text)
            modified = original_text.replace(match_text, replace_text)
            replaced = max(1, count_before)
        else:
            modified = original_text.replace(match_text, replace_text, 1)
            replaced = 1
    else:
        modified = original_text.replace(match_text, replace_text, 1)
        replaced = 1

    debug.update({"success": True, "replaced_count": replaced, "match_type": best.get("match_type")})
    return modified, True, debug


def apply_diff_blocks(original_text: str,
                      diff_blocks: List[Tuple[str, str, Dict[str, Any]]],
                      similarity_threshold: float = 0.8,
                      allow_partial_matches: bool = True,
                      replace_all: bool = False) -> Tuple[str, int, Dict[str, Any]]:
    text = original_text
    changes = 0
    warnings: List[str] = []
    block_results: List[Dict[str, Any]] = []

    for idx, (search, replace, meta) in enumerate(diff_blocks, start=1):
        modified, ok, dbg = apply_diff_edit(text, search, replace, similarity_threshold, allow_partial_matches, replace_all)
        block_result = {"index": idx, "success": ok, "details": dbg, "meta": meta}
        block_results.append(block_result)
        if ok:
            text = modified
            changes += max(1, int(dbg.get("replaced_count", 1)))
        else:
            warnings.append(f"Block {idx} failed: {dbg.get('error', 'no match')}")

    issues = {"warnings": warnings, "block_results": block_results}
    return text, changes, issues


# ----------------------------------
# File stats and readers (large-file aware)
# ----------------------------------
def _line_count_fast(p: str, encoding: str = "utf-8") -> int:
    try:
        with open(p, "r", encoding=encoding, errors="ignore") as f:
            return sum(1 for _ in f)
    except Exception:
        return -1


@mcp.tool()
async def file_stat(file_path: str) -> Dict[str, Any]:
    """
    Get file statistics including size, line count, and whether it's large.
    
    Quick stat check without reading the entire file. Useful for checking
    if a file exists and determining if special handling is needed for large files.
    
    Args:
        file_path: Path to the file to check
    
    Returns:
        Dict[str, Any]: File stats including size, line count, and large file indicators
    """
    path = _norm_path(file_path)
    exists = os.path.exists(path)
    res: Dict[str, Any] = {"success": True, "file_path": path, "exists": exists}

    if not exists:
        return res
    st = os.stat(path)
    res.update({
        "size_bytes": st.st_size,
        "size_human": _human_size(st.st_size),
    })
    lc = _line_count_fast(path)
    if lc >= 0:
        res.update({"line_count": lc})
        res.update({"is_large": lc > 300, "thresholds": {"max_lines_default": 300}})
    return res


@mcp.tool()
async def file_read(file_path: str,
                    max_lines: int = 300,
                    mode: str = "head",
                    allow_large: bool = False,
                    encoding: str = "utf-8") -> Dict[str, Any]:
    """
    Read file contents with built-in large file protection.
    
    Safely reads files with automatic truncation for large files. Supports
    head, tail, or full modes. Prevents accidental loading of huge files
    that could overwhelm context windows.
    
    Args:
        file_path: Path to file to read
        max_lines: Maximum lines to read (default: 300)
        mode: Reading mode - "head" (first lines), "tail" (last lines), or "full"
        allow_large: If True, allow reading files larger than max_lines
        encoding: Text encoding (default: utf-8)
    
    Returns:
        Dict[str, Any]: File content, truncation status, and line count
    """
    path = _norm_path(file_path)

    if not os.path.exists(path):
        return {"success": False, "file_path": path, "error": "File not found"}
    lc = _line_count_fast(path, encoding)
    if mode == "full" and not allow_large and lc > max_lines:
        return {
            "success": False,
            "file_path": path,
            "error": "File too large for full read",
            "tip": "Use head/tail/window or set allow_large=true.",
            "line_count": lc,
            "max_lines": max_lines,
        }

    lines: List[str]
    with open(path, "r", encoding=encoding, errors="ignore") as f:
        lines = f.readlines()

    truncated = False
    content_lines: List[str]
    if mode == "tail":
        content_lines = lines[-max_lines:]
        truncated = len(lines) > max_lines
    elif mode == "full":
        content_lines = lines
    else:  # head
        content_lines = lines[:max_lines]
        truncated = len(lines) > max_lines

    return {
        "success": True,
        "file_path": path,
        "content": "".join(content_lines),
        "truncated": truncated,
        "line_count": len(lines),
        "mode": mode,
        "max_lines": max_lines,
    }


@mcp.tool()
async def file_read_window(file_path: str,
                           start_line: int,
                           line_count: int = 120,
                           encoding: str = "utf-8") -> Dict[str, Any]:
    """
    Read a specific window/range of lines from a file.
    
    Efficiently reads just a section of a file without loading the entire thing.
    Perfect for navigating large files or examining specific regions of code.
    
    Args:
        file_path: Path to file to read
        start_line: Starting line number (1-indexed)
        line_count: Number of lines to read from start (default: 120)
        encoding: Text encoding (default: utf-8)
    
    Returns:
        Dict[str, Any]: Window of file content with line range information
    """
    path = _norm_path(file_path)

    if start_line < 1:
        start_line = 1
    if not os.path.exists(path):
        return {"success": False, "file_path": path, "error": "File not found"}
    lines: List[str]
    with open(path, "r", encoding=encoding, errors="ignore") as f:
        lines = f.readlines()
    total = len(lines)
    start_idx = min(max(0, start_line - 1), total)
    end_idx = min(total, start_idx + max(0, line_count))
    return {
        "success": True,
        "file_path": path,
        "start_line": start_line,
        "line_count": line_count,
        "total_lines": total,
        "content": "".join(lines[start_idx:end_idx]),
        "truncated": end_idx - start_idx < total,
    }


@mcp.tool()
async def file_read_version(file_path: str,
                            version_number: int,
                            start_line: int = 1,
                            line_count: Optional[int] = 200,
                            encoding: str = "utf-8") -> Dict[str, Any]:
    """
    Read contents from a specific backup version of a file.
    
    Access historical versions created by the automatic backup system.
    Supports windowed reading for large version files.
    
    Args:
        file_path: Path to the file (not the backup - this finds the backup)
        version_number: Which version number to read
        start_line: Starting line in the version (default: 1)
        line_count: Number of lines to read (None = all)
        encoding: Text encoding (default: utf-8)
    
    Returns:
        Dict[str, Any]: Version file content with metadata
    """
    path = _norm_path(file_path)

    versions = get_file_versions(path)
    past = [v for v in versions if v["version"] != "current"]
    target = next((v for v in past if v["version"] == version_number), None)
    if not target:
        return {"success": False, "file_path": path, "error": "Version not found", "version_number": version_number}
    try:
        with open(target["path"], "r", encoding=encoding, errors="ignore") as f:
            lines = f.readlines()
        total = len(lines)
        s = max(0, start_line - 1)
        e = min(total, s + (line_count or total))
        return {
            "success": True,
            "file_path": path,
            "version_number": version_number,
            "start_line": start_line,
            "line_count": (line_count or total),
            "total_lines": total,
            "content": "".join(lines[s:e]),
            "truncated": e - s < total,
        }
    except Exception as e:
        return {"success": False, "file_path": path, "error": str(e), "version_number": version_number}


@mcp.tool()
async def file_read_around(file_path: str,
                           search_text: str,
                           similarity_threshold: float = 0.8,
                           context_lines: int = 30,
                           encoding: str = "utf-8") -> Dict[str, Any]:
    """
    Find text in a file and return surrounding context.
    
    Searches for text (with fuzzy matching) and returns the matching region
    plus surrounding lines. Great for locating code sections without reading
    the entire file.
    
    Args:
        file_path: Path to file to search
        search_text: Text to search for (supports fuzzy matching)
        similarity_threshold: Minimum similarity for fuzzy matches (0.0-1.0)
        context_lines: Number of lines to include before/after match
        encoding: Text encoding (default: utf-8)
    
    Returns:
        Dict[str, Any]: Match location and surrounding content window
    """
    path = _norm_path(file_path)

    if not os.path.exists(path):
        return {"success": False, "file_path": path, "error": "File not found"}
    content = read_file_content(path, encoding)

    # Try exact first
    pos = content.find(search_text)
    strategy = "exact" if pos >= 0 else "fuzzy"
    if pos < 0:
        matches = find_fuzzy_matches(search_text, content, similarity_threshold, ["normalized", "multiline", "single_line", "token"])
        if not matches:
            return {
                "success": False,
                "file_path": path,
                "error": "No matching region found",
                "tip": "Lower similarity_threshold or search a shorter unique snippet.",
            }
        m = matches[0]
        pos = m["start_pos"]
    # Compute line window
    pre = content[:pos]
    line_number = pre.count("\n") + 1
    lines = content.split("\n")
    start_line = max(1, line_number - context_lines)
    end_line = min(len(lines), line_number + context_lines)
    window = "\n".join(lines[start_line - 1:end_line])
    return {
        "success": True,
        "file_path": path,
        "strategy": strategy,
        "line_number": line_number,
        "start_line": start_line,
        "line_count": end_line - start_line + 1,
        "content": window,
    }


# ----------------------------------
# Diff tools (filesystem and text)
# ----------------------------------
@mcp.tool()
async def get_diff_formats() -> Dict[str, Any]:
    """
    List all supported diff/patch format patterns.
    
    Returns information about the various diff formats that file_diff_write
    can parse, including custom safe fences, git-style diffs, and more.
    
    Returns:
        Dict[str, Any]: Available diff formats with patterns and descriptions
    """
    return {
        "success": True,
        "formats": [

            {
                "name": k,
                "pattern": v["pattern"],
                "description": {
                    "custom_safe": "Custom conflict-free delimiters",
                    "toolkami_fenced": "ToolKami style with ```diff fences and filename line",
                    "toolkami_direct": "ToolKami style without fences, filename line",
                    "simple_blocks": "Simple SEARCH/REPLACE blocks",
                    "evolvemcp_style": "EvolveMCP style fenced blocks",
                    "git_style": "Unified diff converted to search/replace",
                }.get(k, ""),
            }
            for k, v in DIFF_PATTERNS.items()
        ],
        "total_patterns": len(DIFF_PATTERNS),
    }


@mcp.tool()
async def file_diff_versions(file_path: str) -> Dict[str, Any]:
    """
    List all backup versions available for a file.
    
    Shows the version history with timestamps, sizes, and version numbers.
    Includes the current file as version "current".
    
    Args:
        file_path: Path to the file to check versions for
    
    Returns:
        Dict[str, Any]: List of all versions with metadata
    """
    path = _norm_path(file_path)

    if not os.path.exists(path):
        return {"success": False, "file_path": path, "error": "File not found"}
    versions = get_file_versions(path)
    current = next((v for v in versions if v["version"] == "current"), None)
    past = [v for v in versions if v["version"] != "current"]
    return {
        "success": True,
        "file_path": path,
        "current_version": current,
        "versions": past,
        "version_count": len(past),
    }


@mcp.tool()
async def file_diff_restore(file_path: str, version_number: int, create_backup: bool = True) -> Dict[str, Any]:
    """
    Restore a file to a previous backup version.
    
    Replaces the current file with an older version from the backup history.
    Optionally creates a backup of the current state before restoring.
    
    Args:
        file_path: Path to the file to restore
        version_number: Which version number to restore to
        create_backup: If True, backup current file before restoring
    
    Returns:
        Dict[str, Any]: Restore operation results
    """
    path = _norm_path(file_path)

    if not os.path.exists(path):
        return {"success": False, "file_path": path, "error": "File not found"}
    backup_info = None
    if create_backup:
        try:
            backup_info = create_file_backup(path, "pre_restore")
        except Exception as e:
            logger.warning("Backup before restore failed: %s", e)
    try:
        result = restore_file_version(path, version_number)
        result.update({"backup_created": backup_info is not None, "backup_info": backup_info})
        return result
    except ValueError as e:
        versions = get_file_versions(path)
        past = [v for v in versions if v["version"] != "current"]
        return {
            "success": False,
            "file_path": path,
            "error": str(e),
            "available_versions": [{"version": v["version"], "date": v["date"]} for v in past],
            "backup_created": backup_info is not None,
            "backup_info": backup_info,
        }


@mcp.tool()
async def text_diff_edit(original_text: str,
                         diff_text: str,
                         similarity_threshold: float = 0.8,
                         allow_partial_matches: bool = True,
                         replace_all: bool = False) -> Dict[str, Any]:
    """
    Apply diff-style edits to text without touching the filesystem.
    
    Pure text manipulation using diff blocks. Great for testing diff patterns
    or processing text that isn't in files yet. Returns both original and
    modified text plus detailed diagnostics.
    
    Args:
        original_text: The text to edit
        diff_text: Diff blocks in any supported format
        similarity_threshold: Minimum similarity for fuzzy matches (0.0-1.0)
        allow_partial_matches: Enable fuzzy matching if exact match fails
        replace_all: Replace all occurrences vs just first match
    
    Returns:
        Dict[str, Any]: Original text, modified text, and detailed edit results
    """
    logger.info("text_diff_edit called; threshold=%.2f", similarity_threshold)

    blocks = extract_diff_blocks(diff_text)
    if not blocks:
        return {
            "success": False,
            "error": "No valid diff blocks found",
            "tip": "Use <<<<<<< SEARCH / ======= / >>>>>>> REPLACE or custom_safe fences.",
            "supported_formats": list(DIFF_PATTERNS.keys()),
            "original_text": original_text,
            "modified_text": original_text,
            "blocks_processed": 0,
            "changes_applied": 0,
        }
    modified, changes, issues = apply_diff_blocks(
        original_text, blocks, similarity_threshold, allow_partial_matches, replace_all
    )
    return {
        "success": changes > 0,
        "original_text": original_text,
        "modified_text": modified,
        "blocks_processed": len(blocks),
        "changes_applied": changes,
        "block_results": issues.get("block_results", []),
        "summary": {
            "total_blocks": len(blocks),
            "successful_blocks": sum(1 for b in issues.get("block_results", []) if b.get("success")),
            "failed_blocks": sum(1 for b in issues.get("block_results", []) if not b.get("success")),
            "similarity_threshold_used": similarity_threshold,
        },
        **({"warnings": issues["warnings"]} if issues.get("warnings") else {}),
    }


@mcp.tool()
async def simple_text_diff(original_text: str, diff_text: str) -> str:
    """
    Apply diff edits and return just the modified text (simplified version).
    
    Streamlined version of text_diff_edit that returns only the modified text
    string instead of full diagnostics. Falls back to original on failure.
    
    Args:
        original_text: Text to edit
        diff_text: Diff blocks to apply
    
    Returns:
        str: Modified text (or original if editing fails)
    """
    res = await text_diff_edit(original_text, diff_text)

    if res.get("success"):
        return str(res.get("modified_text", original_text))
    logger.warning("simple_text_diff failed: %s", res.get("error"))
    return original_text


@mcp.tool()
async def file_diff_write(file_path: str,
                          diff_text: Optional[str] = None,
                          use_direct_mode: bool = False,
                          search_text: Optional[str] = None,
                          replace_text: Optional[str] = None,
                          similarity_threshold: float = 0.8,
                          allow_partial_matches: bool = True,
                          replace_all: bool = True,
                          create_backup: bool = True,
                          change_tag: Optional[str] = None,
                          encoding: str = "utf-8") -> Dict[str, Any]:
    """
    Apply diff-style edits directly to a file with automatic backups.
    
    The main workhorse for file editing. Supports two modes:
    1. Diff mode: Parses diff blocks in various formats and applies them
    2. Direct mode: Simple search/replace operation for single edits
    
    Creates automatic backups before making changes. Supports fuzzy matching
    to handle whitespace variations and minor differences. Can apply multiple
    diff blocks in a single call.
    
    Args:
        file_path: Path to file to edit
        diff_text: Diff blocks in any supported format (use get_diff_formats to see options)
        use_direct_mode: If True, use simple search/replace instead of parsing diff blocks
        search_text: Text to search for (only used in direct mode)
        replace_text: Replacement text (only used in direct mode)
        similarity_threshold: Minimum similarity for fuzzy matches (0.0-1.0, default: 0.8)
        allow_partial_matches: Enable fuzzy matching if exact match fails
        replace_all: Replace all occurrences vs just first match
        create_backup: Create backup before editing
        change_tag: Optional tag to identify this change in backup filename
        encoding: Text encoding (default: utf-8)
    
    Returns:
        Dict[str, Any]: Edit results including changes applied, backup info, and diagnostics
    """
    path = _norm_path(file_path)
    if not os.path.exists(path):
        return {"success": False, "file_path": path, "error": "File not found"}

    backup_info = None
    if create_backup:
        try:
            backup_info = create_file_backup(path, change_tag)
        except Exception as e:
            logger.warning("Backup failed before edit: %s", e)

    try:
        original = read_file_content(path, encoding)

        if use_direct_mode:
            if search_text is None or replace_text is None:
                return {
                    "success": False,
                    "file_path": path,
                    "error": "Direct mode requires search_text and replace_text",
                }
            modified, ok, dbg = apply_diff_edit(
                original, search_text, replace_text,
                similarity_threshold, allow_partial_matches, replace_all,
            )
            if not ok:
                return {
                    "success": False,
                    "file_path": path,
                    "error": "Direct mode replacement failed",
                    "details": dbg,
                    "backup_created": backup_info is not None,
                    "backup_info": backup_info,
                }
            write_file_content(path, modified, encoding)
            st = os.stat(path)
            return {
                "success": True,
                "file_path": path,
                "message": "Direct mode change applied",
                "changes_applied": max(1, int(dbg.get("replaced_count", 1))),
                "method": "direct_mode",
                "size": st.st_size,
                "size_human": _human_size(st.st_size),
                "backup_created": backup_info is not None,
                "backup_info": backup_info,
                "debug_info": dbg,
            }

        # diff_text mode
        if diff_text is None:
            return {
                "success": False,
                "file_path": path,
                "error": "Provide diff_text or set use_direct_mode=true",
                "tip": "Use custom_safe or SEARCH/REPLACE fences, or switch to direct_mode with a small snippet.",
            }
        blocks = extract_diff_blocks(diff_text)
        if not blocks:
            return {
                "success": False,
                "file_path": path,
                "error": "No valid diff blocks found",
                "tip": "Ensure <<<<<<< SEARCH / ======= / >>>>>>> REPLACE blocks or use custom_safe fences.",
                "supported_formats": list(DIFF_PATTERNS.keys()),
                "backup_created": backup_info is not None,
                "backup_info": backup_info,
            }
        modified, changes, issues = apply_diff_blocks(
            original, blocks, similarity_threshold, allow_partial_matches, replace_all
        )
        if changes == 0:
            return {
                "success": False,
                "file_path": path,
                "error": "No changes were applied",
                "details": issues,
                "tip": "Try smaller blocks, lower threshold, or use file_read_around + direct_mode.",
                "changes_applied": 0,
                "diff_blocks_found": len(blocks),
                "backup_created": backup_info is not None,
                "backup_info": backup_info,
            }
        write_file_content(path, modified, encoding)
        st = os.stat(path)
        result: Dict[str, Any] = {
            "success": True,
            "file_path": path,
            "message": f"Applied {changes} change(s)",
            "changes_applied": changes,
            "diff_blocks_found": len(blocks),
            "size": st.st_size,
            "size_human": _human_size(st.st_size),
            "backup_created": backup_info is not None,
            "backup_info": backup_info,
            "details": issues,
        }
        if issues.get("warnings"):
            result["warnings"] = issues["warnings"]
        return result
    except Exception as e:
        logger.error("file_diff_write exception: %s", e, exc_info=True)
        return {"success": False, "file_path": path, "error": f"Unexpected error: {e}"}


# ----------------------------------
# Search tools
# ----------------------------------
@mcp.tool()
async def search_in_file_fuzzy(file_path: str,
                               search_text: str,
                               similarity_threshold: float = 0.8,
                               fuzzy_threshold: float = 0.7,
                               return_content: bool = False,
                               return_fuzzy_below_threshold: bool = False,
                               max_results: int = 10,
                               context_lines: int = 2,
                               encoding: str = "utf-8") -> Dict[str, Any]:
    """
    Search for text in a file with advanced fuzzy matching capabilities.
    
    Performs intelligent search with multiple matching strategies:
    - Exact matching (fastest, highest priority)
    - Normalized whitespace matching
    - Multi-line fuzzy matching for code blocks
    - Single-line similarity matching
    - Token-based matching for reordered content
    
    Returns matches with similarity scores, line numbers, and surrounding context.
    Supports configurable thresholds to control match quality.
    
    Args:
        file_path: Path to file to search
        search_text: Text to search for (supports multi-line)
        similarity_threshold: Minimum similarity for fuzzy matches (0.0-1.0, default: 0.8)
        fuzzy_threshold: Separate threshold for reporting low-quality matches (default: 0.7)
        return_content: Include matched content in exact matches (default: False)
        return_fuzzy_below_threshold: Include content for low-quality fuzzy matches
        max_results: Maximum number of matches to return (default: 10)
        context_lines: Lines of context to include around each match (default: 2)
        encoding: Text encoding (default: utf-8)
    
    Returns:
        Dict[str, Any]: Search results with exact/fuzzy matches, similarity scores, and context
    """
    path = _norm_path(file_path)
    if not os.path.exists(path):
        return {"success": False, "file_path": path, "error": "File not found"}
    content = read_file_content(path, encoding)
    lines = content.split("\n")

    # Exact matches
    exact_matches: List[Dict[str, Any]] = []
    start = 0
    while True:
        pos = content.find(search_text, start)
        if pos == -1:
            break
        line_no = content[:pos].count("\n") + 1
        lstart = max(0, line_no - context_lines - 1)
        lend = min(len(lines), line_no + context_lines)
        ctx = "\n".join(lines[lstart:lend])
        exact_matches.append({
            "line_number": line_no,
            "position": {"start": pos, "end": pos + len(search_text)},
            "context": ctx,
        })
        start = pos + 1
        if len(exact_matches) >= max_results:
            break

    if exact_matches:
        return {
            "success": True,
            "file_path": path,
            "search_text": search_text,
            "exact_matches": exact_matches,
            "fuzzy_matches": [],
            "summary": {"exact_match_count": len(exact_matches), "fuzzy_match_count": 0, "total_matches": len(exact_matches)},
        }

    # Fuzzy
    fuzzy_results = find_fuzzy_matches(search_text, content, similarity_threshold, ["normalized", "multiline", "single_line", "token"])
    fuzzy_matches: List[Dict[str, Any]] = []
    below = 0
    for m in fuzzy_results[:max_results]:
        line_no = content[:m["start_pos"].__int__()].count("\n") + 1
        lstart = max(0, line_no - context_lines - 1)
        lend = min(len(lines), line_no + context_lines)
        ctx = "\n".join(lines[lstart:lend])
        item = {
            "similarity": round(float(m["similarity"]), 3),
            "line_number": line_no,
            "position": {"start": int(m["start_pos"]), "end": int(m["end_pos"])},
            "match_type": m.get("match_type"),
            "context": ctx,
        }
        if m["similarity"] < fuzzy_threshold:
            below += 1
            item["below_threshold"] = True
            item["content"] = m["text"] if return_fuzzy_below_threshold else None
        else:
            item["content"] = m["text"] if return_content else None
        fuzzy_matches.append(item)

    return {
        "success": True,
        "file_path": path,
        "search_text": search_text,
        "exact_matches": [],
        "fuzzy_matches": fuzzy_matches,
        "summary": {
            "exact_match_count": 0,
            "fuzzy_match_count": len(fuzzy_matches),
            "fuzzy_below_threshold_count": below,
            "total_matches": len(fuzzy_matches),
            "highest_similarity": round(float(fuzzy_matches[0]["similarity"]) if fuzzy_matches else 0.0, 3),
        },
    }


@mcp.tool()
async def search_in_file_regex(file_path: str,
                               search_pattern: str,
                               flags: Optional[str] = None,
                               encoding: str = "utf-8") -> Dict[str, Any]:
    """
    Search file using regular expressions with full regex power.
    
    Provides powerful pattern-based searching with support for capture groups,
    lookaheads, character classes, and all standard regex features. Returns
    match positions and captured groups.
    
    Args:
        file_path: Path to file to search
        search_pattern: Regular expression pattern (Python regex syntax)
        flags: Regex flags as string - 'i' for case-insensitive, 'm' for multiline,
               's' for dotall (can combine like 'im')
        encoding: Text encoding (default: utf-8)
    
    Returns:
        Dict[str, Any]: All regex matches with positions, line numbers, and capture groups
    """
    path = _norm_path(file_path)
    if not os.path.exists(path):
        return {"success": False, "file_path": path, "error": "File not found"}

    flag_val = 0
    if flags:
        f = flags.lower()
        flag_val |= re.IGNORECASE if 'i' in f else 0
        flag_val |= re.MULTILINE if 'm' in f else 0
        flag_val |= re.DOTALL if 's' in f else 0

    try:
        content = read_file_content(path, encoding)
        rx = re.compile(search_pattern, flag_val)
        matches: List[Dict[str, Any]] = []
        for mo in rx.finditer(content):
            line_no = content[:mo.start()].count("\n") + 1
            matches.append({
                "span": [mo.start(), mo.end()],
                "line_number": line_no,
                "groups": list(mo.groups()) if mo.groups() else [],
            })
        return {
            "success": True,
            "file_path": path,
            "pattern": search_pattern,
            "flags": flags,
            "matches": matches,
            "summary": {"count": len(matches)},
        }
    except re.error as e:
        return {"success": False, "file_path": path, "error": f"Regex error: {e}"}


# ----------------------------------
# File Writer Tool (simple write/read/version tool)
# ----------------------------------
@mcp.tool()
async def file_writer(
    action: str,
    file_path: str,
    content: Union[str, Dict, List, Any] = None,
    version: str = None,
    create_backup: bool = True,
    encoding: str = "utf-8"
) -> Dict[str, Any]:
    """
    Simple file operations with automatic versioning support.
    
    A straightforward tool for writing, reading, and managing file versions.
    Automatically creates backups before modifications. Supports JSON content
    auto-conversion for structured data storage.
    
    Args:
        action: Operation to perform ('write', 'read', 'list_versions', 'restore')
        file_path: Path to the file to operate on
        content: Content to write (for 'write' action) - auto-converts dicts/lists to JSON
        version: Version number to read or restore (for 'read' and 'restore' actions)
        create_backup: Whether to backup existing file before writing (default: True)
        encoding: Text encoding for file operations (default: utf-8)
    
    Returns:
        Dict[str, Any]: Operation results including success status, file info, and any errors
    """
    path = _norm_path(file_path)
    logger.info("file_writer: action=%s path=%s", action, path)
    
    if action == "write":
        try:
            file_exists = os.path.exists(path)
            backup_info = None
            if file_exists and create_backup:
                backup_info = create_file_backup(path)
            
            # Auto-convert non-string content to JSON
            write_content = content
            if not isinstance(content, str):
                if content is not None:
                    write_content = json.dumps(content, indent=2)
                else:
                    write_content = ""
            
            write_file_content(path, write_content, encoding)
            st = os.stat(path)
            
            return {
                "action": "write",
                "success": True,
                "file_path": path,
                "size": st.st_size,
                "size_human": _human_size(st.st_size),
                "created": not file_exists,
                "updated": file_exists,
                "backup_created": backup_info is not None,
                "backup_info": backup_info
            }
        except Exception as e:
            logger.error("file_writer write error: %s", e)
            return {"action": "write", "success": False, "file_path": path, "error": str(e)}
    
    elif action == "read":
        try:
            if version and version != "current":
                versions = get_file_versions(path)
                version_info = next((v for v in versions if str(v["version"]) == version), None)
                if not version_info:
                    return {"action": "read", "success": False, "file_path": path, "error": f"Version {version} not found"}
                with open(version_info["path"], "r", encoding=encoding) as f:
                    content = f.read()
                return {
                    "action": "read",
                    "success": True,
                    "file_path": path,
                    "version": version,
                    "content": content,
                    "size": version_info["size"],
                    "size_human": version_info["size_human"],
                    "date": version_info["date"]
                }
            
            if not os.path.exists(path):
                return {"action": "read", "success": False, "file_path": path, "error": "File not found"}
            
            content = read_file_content(path, encoding)
            st = os.stat(path)
            return {
                "action": "read",
                "success": True,
                "file_path": path,
                "version": "current",
                "content": content,
                "size": st.st_size,
                "size_human": _human_size(st.st_size),
                "date": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            }
        except Exception as e:
            logger.error("file_writer read error: %s", e)
            return {"action": "read", "success": False, "file_path": path, "error": str(e)}
    
    elif action == "list_versions":
        try:
            versions = get_file_versions(path)
            return {
                "action": "list_versions",
                "success": True,
                "file_path": path,
                "versions": versions,
                "versions_count": len(versions)
            }
        except Exception as e:
            logger.error("file_writer list_versions error: %s", e)
            return {"action": "list_versions", "success": False, "file_path": path, "error": str(e)}
    
    elif action == "restore":
        try:
            versions = get_file_versions(path)
            version_info = next((v for v in versions if str(v["version"]) == version), None)
            if not version_info:
                return {"action": "restore", "success": False, "file_path": path, "error": f"Version {version} not found"}
            
            backup_info = None
            if version != "current" and os.path.exists(path):
                backup_info = create_file_backup(path)
            
            if version != "current":
                shutil.copy2(version_info["path"], path)
            
            st = os.stat(path)
            return {
                "action": "restore",
                "success": True,
                "file_path": path,
                "version": version,
                "size": st.st_size,
                "size_human": _human_size(st.st_size),
                "backup_created": backup_info is not None,
                "backup_info": backup_info
            }
        except Exception as e:
            logger.error("file_writer restore error: %s", e)
            return {"action": "restore", "success": False, "file_path": path, "error": str(e)}
    
    else:
        return {
            "action": action,
            "success": False,
            "file_path": path,
            "error": f"Unknown action: {action}. Valid actions: 'write', 'read', 'list_versions', 'restore'"
        }


# ----------------------------------
# Entrypoint
# ----------------------------------
if __name__ == "__main__":
    try:
        logger.info("Starting file-diff MCP server (stdio)")
        mcp.run(transport='stdio')
    except Exception as e:
        logger.critical("Failed to start MCP server: %s", e, exc_info=True)
        raise


