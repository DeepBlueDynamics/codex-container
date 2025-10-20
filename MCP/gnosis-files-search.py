#!/usr/bin/env python3
"""
MCP: gnosis-files-search

File search and discovery operations - listing, globbing, finding, searching content.
Tools for exploring directory structures and locating files by name or content.
"""

from __future__ import annotations

import sys
import os
import re
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("gnosis-files-search")


@mcp.tool()
async def file_list(
    directory: str,
    pattern: Optional[str] = None,
    recursive: bool = False,
    include_hidden: bool = False
) -> Dict[str, Any]:
    """List files and directories within a specified directory.

    This tool provides a directory listing with optional filtering by glob pattern.
    Returns detailed information about each file including type, size, and modification time.
    Use this to explore directory contents before performing operations.

    Args:
        directory: Path to directory to list. Supports ~ for home directory.
        pattern: Optional glob pattern to filter results (e.g., "*.txt", "test_*.py", "**/*.json"). If not provided, lists all items.
        recursive: If True, searches subdirectories recursively. If False, only lists immediate children (default: False).
        include_hidden: If True, includes hidden files (starting with .). If False, skips them (default: False).

    Returns:
        Dictionary containing:
        - success (bool): Whether the list operation succeeded
        - directory (str): Resolved absolute path of directory that was listed
        - pattern (str): Glob pattern used for filtering, if any
        - recursive (bool): Whether recursive search was used
        - count (int): Number of files/directories found
        - files (list): List of file/directory information dictionaries with:
            - path (str): Absolute path to the file/directory
            - name (str): File/directory name
            - type (str): "file", "directory", or "other"
            - size (int): Size in bytes (0 for directories)
            - modified (float): Last modification timestamp (Unix epoch)
        - error (str): Error message if operation failed

    Example:
        file_list(directory="/workspace")
        file_list(directory="/workspace", pattern="*.py", recursive=True)
        file_list(directory="~/Documents", pattern="report_*.pdf")
    """
    try:
        path = Path(directory).expanduser().resolve()

        if not path.exists():
            return {
                "success": False,
                "error": f"Directory not found: {directory}"
            }

        if not path.is_dir():
            return {
                "success": False,
                "error": f"Not a directory: {directory}"
            }

        # Collect files
        if pattern:
            if recursive:
                files = list(path.rglob(pattern))
            else:
                files = list(path.glob(pattern))
        else:
            if recursive:
                files = [f for f in path.rglob("*")]
            else:
                files = list(path.iterdir())

        # Filter hidden files if requested
        if not include_hidden:
            files = [f for f in files if not f.name.startswith('.')]

        # Sort by name
        files.sort(key=lambda x: x.name)

        # Gather metadata
        results = []
        for f in files:
            try:
                stat = f.stat()
                results.append({
                    "path": str(f),
                    "name": f.name,
                    "type": "file" if f.is_file() else "directory" if f.is_dir() else "other",
                    "size": stat.st_size if f.is_file() else 0,
                    "modified": stat.st_mtime
                })
            except Exception:
                # Skip files we can't stat
                continue

        return {
            "success": True,
            "directory": str(path),
            "pattern": pattern,
            "recursive": recursive,
            "count": len(results),
            "files": results
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to list directory: {str(e)}"
        }


@mcp.tool()
async def file_find_by_name(
    directory: str,
    name_pattern: str,
    case_sensitive: bool = False,
    max_results: int = 100
) -> Dict[str, Any]:
    """Find files by name pattern within a directory tree.

    This tool recursively searches for files whose names match a given pattern.
    Supports wildcards (* and ?) and optional case-insensitive matching. Use this
    when you know part of a filename but not its exact location.

    Args:
        directory: Root directory to start search from. Supports ~ for home directory.
        name_pattern: Pattern to match filenames against. Supports wildcards: * (any characters) and ? (single character).
        case_sensitive: If True, pattern matching is case-sensitive. If False, ignores case (default: False).
        max_results: Maximum number of results to return, to prevent overwhelming output (default: 100).

    Returns:
        Dictionary containing:
        - success (bool): Whether the find operation succeeded
        - directory (str): Resolved absolute path where search started
        - pattern (str): Name pattern that was searched for
        - case_sensitive (bool): Whether case-sensitive matching was used
        - count (int): Number of matching files found (up to max_results)
        - files (list): List of matching file paths (strings)
        - truncated (bool): True if more results exist beyond max_results
        - error (str): Error message if operation failed

    Example:
        file_find_by_name(directory="/workspace", name_pattern="*config*.json")
        file_find_by_name(directory="~/Projects", name_pattern="test_*.py", case_sensitive=True)
        file_find_by_name(directory="/var/log", name_pattern="*.log", max_results=50)
    """
    try:
        path = Path(directory).expanduser().resolve()

        if not path.exists():
            return {
                "success": False,
                "error": f"Directory not found: {directory}"
            }

        if not path.is_dir():
            return {
                "success": False,
                "error": f"Not a directory: {directory}"
            }

        # Convert glob pattern to regex for case-insensitive matching
        if case_sensitive:
            matches = list(path.rglob(name_pattern))
        else:
            # Case-insensitive: manually check each file
            matches = []
            pattern_lower = name_pattern.lower()
            for f in path.rglob("*"):
                if f.is_file():
                    # Simple glob-like matching (case-insensitive)
                    import fnmatch
                    if fnmatch.fnmatch(f.name.lower(), pattern_lower):
                        matches.append(f)

        # Sort by path
        matches.sort(key=lambda x: str(x))

        # Limit results
        truncated = len(matches) > max_results
        matches = matches[:max_results]

        return {
            "success": True,
            "directory": str(path),
            "pattern": name_pattern,
            "case_sensitive": case_sensitive,
            "count": len(matches),
            "files": [str(f) for f in matches],
            "truncated": truncated
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to find files: {str(e)}"
        }


@mcp.tool()
async def file_search_content(
    directory: str,
    search_text: str,
    file_pattern: Optional[str] = "*.txt",
    case_sensitive: bool = False,
    max_results: int = 50
) -> Dict[str, Any]:
    """Search for text content within files in a directory tree.

    This tool performs a grep-like search, finding files that contain the specified text.
    Returns matching files with context about where matches were found. Use this to locate
    files containing specific strings, error messages, or code patterns.

    Args:
        directory: Root directory to start search from. Supports ~ for home directory.
        search_text: Text string to search for within file contents.
        file_pattern: Glob pattern to filter which files to search (default: "*.txt"). Use "*" for all files.
        case_sensitive: If True, search is case-sensitive. If False, ignores case (default: False).
        max_results: Maximum number of matching files to return (default: 50).

    Returns:
        Dictionary containing:
        - success (bool): Whether the search operation succeeded
        - directory (str): Resolved absolute path where search started
        - search_text (str): Text that was searched for
        - file_pattern (str): Pattern used to filter files
        - case_sensitive (bool): Whether case-sensitive matching was used
        - count (int): Number of files containing matches (up to max_results)
        - matches (list): List of match information dictionaries with:
            - file (str): Path to file containing match
            - line_count (int): Number of lines containing the search text
            - first_line_num (int): Line number of first match
            - preview (str): Preview of first matching line (truncated to 200 chars)
        - truncated (bool): True if more results exist beyond max_results
        - error (str): Error message if operation failed

    Example:
        file_search_content(directory="/workspace", search_text="TODO", file_pattern="*.py")
        file_search_content(directory="~/logs", search_text="ERROR", file_pattern="*.log", max_results=20)
        file_search_content(directory="/workspace", search_text="function main", case_sensitive=True)
    """
    try:
        path = Path(directory).expanduser().resolve()

        if not path.exists():
            return {
                "success": False,
                "error": f"Directory not found: {directory}"
            }

        if not path.is_dir():
            return {
                "success": False,
                "error": f"Not a directory: {directory}"
            }

        # Find files matching pattern
        files = list(path.rglob(file_pattern))

        # Search each file
        search_lower = search_text.lower() if not case_sensitive else search_text
        matches = []

        for f in files:
            if not f.is_file():
                continue

            try:
                # Try to read as text
                content = f.read_text(encoding='utf-8', errors='ignore')
                lines = content.splitlines()

                # Search for text
                matching_lines = []
                for line_num, line in enumerate(lines, start=1):
                    line_to_search = line if case_sensitive else line.lower()
                    if search_lower in line_to_search:
                        matching_lines.append((line_num, line))

                if matching_lines:
                    first_line_num, first_line = matching_lines[0]
                    preview = first_line.strip()[:200]
                    if len(first_line.strip()) > 200:
                        preview += "..."

                    matches.append({
                        "file": str(f),
                        "line_count": len(matching_lines),
                        "first_line_num": first_line_num,
                        "preview": preview
                    })

                    if len(matches) >= max_results:
                        break

            except Exception:
                # Skip files we can't read
                continue

        truncated = len(matches) >= max_results

        return {
            "success": True,
            "directory": str(path),
            "search_text": search_text,
            "file_pattern": file_pattern,
            "case_sensitive": case_sensitive,
            "count": len(matches),
            "matches": matches,
            "truncated": truncated
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to search content: {str(e)}"
        }


@mcp.tool()
async def file_tree(
    directory: str,
    max_depth: int = 3,
    include_hidden: bool = False
) -> Dict[str, Any]:
    """Display directory structure as a tree.

    This tool generates a hierarchical tree view of a directory structure, similar to
    the Unix 'tree' command. Use this to visualize folder organization and quickly
    understand project structure.

    Args:
        directory: Root directory to display tree for. Supports ~ for home directory.
        max_depth: Maximum depth of subdirectories to traverse (default: 3). Use higher values for deeper trees.
        include_hidden: If True, includes hidden files/dirs (starting with .). If False, skips them (default: False).

    Returns:
        Dictionary containing:
        - success (bool): Whether the tree operation succeeded
        - directory (str): Resolved absolute path of root directory
        - max_depth (int): Maximum depth that was traversed
        - tree (str): Multi-line string representation of directory tree
        - file_count (int): Total number of files in tree
        - dir_count (int): Total number of directories in tree
        - error (str): Error message if operation failed

    Example:
        file_tree(directory="/workspace")
        file_tree(directory="~/Projects/myapp", max_depth=5, include_hidden=True)
    """
    try:
        path = Path(directory).expanduser().resolve()

        if not path.exists():
            return {
                "success": False,
                "error": f"Directory not found: {directory}"
            }

        if not path.is_dir():
            return {
                "success": False,
                "error": f"Not a directory: {directory}"
            }

        file_count = 0
        dir_count = 0
        tree_lines = [str(path)]

        def build_tree(current_path: Path, prefix: str = "", depth: int = 0):
            nonlocal file_count, dir_count

            if depth >= max_depth:
                return

            try:
                items = sorted(current_path.iterdir(), key=lambda x: (not x.is_dir(), x.name))

                # Filter hidden if requested
                if not include_hidden:
                    items = [item for item in items if not item.name.startswith('.')]

                for i, item in enumerate(items):
                    is_last = i == len(items) - 1
                    connector = "└── " if is_last else "├── "
                    tree_lines.append(f"{prefix}{connector}{item.name}")

                    if item.is_dir():
                        dir_count += 1
                        extension = "    " if is_last else "│   "
                        build_tree(item, prefix + extension, depth + 1)
                    else:
                        file_count += 1

            except PermissionError:
                tree_lines.append(f"{prefix}    [Permission Denied]")

        build_tree(path)
        tree_str = "\n".join(tree_lines)

        return {
            "success": True,
            "directory": str(path),
            "max_depth": max_depth,
            "tree": tree_str,
            "file_count": file_count,
            "dir_count": dir_count
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to build tree: {str(e)}"
        }


@mcp.tool()
async def file_find_recent(
    directory: str,
    hours: int = 24,
    file_pattern: Optional[str] = None,
    max_results: int = 50
) -> Dict[str, Any]:
    """Find files modified within a specified time period.

    This tool searches for recently modified files, useful for finding new logs,
    recent changes, or files created/updated during a specific timeframe. Returns
    files sorted by modification time (most recent first).

    Args:
        directory: Root directory to search. Supports ~ for home directory.
        hours: Look for files modified within this many hours ago (default: 24).
        file_pattern: Optional glob pattern to filter files (e.g., "*.log", "*.py"). If not provided, searches all files.
        max_results: Maximum number of results to return, sorted by most recent (default: 50).

    Returns:
        Dictionary containing:
        - success (bool): Whether the search operation succeeded
        - directory (str): Resolved absolute path where search started
        - hours (int): Time window in hours that was searched
        - file_pattern (str): Pattern used to filter files, if any
        - cutoff_time (str): ISO timestamp of oldest modification time included
        - count (int): Number of matching files found (up to max_results)
        - files (list): List of file information dictionaries with:
            - path (str): Absolute path to the file
            - name (str): File name
            - modified (float): Modification timestamp (Unix epoch)
            - modified_iso (str): Human-readable ISO timestamp
            - size (int): File size in bytes
            - hours_ago (float): How many hours ago file was modified
        - truncated (bool): True if more results exist beyond max_results
        - error (str): Error message if operation failed

    Example:
        file_find_recent(directory="/var/log", hours=1, file_pattern="*.log")
        file_find_recent(directory="/workspace", hours=48, max_results=100)
        file_find_recent(directory="~/Documents", hours=168, file_pattern="*.docx")  # Last week
    """
    try:
        path = Path(directory).expanduser().resolve()

        if not path.exists():
            return {
                "success": False,
                "error": f"Directory not found: {directory}"
            }

        if not path.is_dir():
            return {
                "success": False,
                "error": f"Not a directory: {directory}"
            }

        # Calculate cutoff time
        cutoff = datetime.now().timestamp() - (hours * 3600)
        cutoff_dt = datetime.fromtimestamp(cutoff)

        # Find files
        if file_pattern:
            files = list(path.rglob(file_pattern))
        else:
            files = list(path.rglob("*"))

        # Filter by modification time and gather metadata
        recent_files = []
        for f in files:
            if not f.is_file():
                continue

            try:
                stat = f.stat()
                if stat.st_mtime >= cutoff:
                    mod_dt = datetime.fromtimestamp(stat.st_mtime)
                    hours_ago = (datetime.now().timestamp() - stat.st_mtime) / 3600

                    recent_files.append({
                        "path": str(f),
                        "name": f.name,
                        "modified": stat.st_mtime,
                        "modified_iso": mod_dt.isoformat(),
                        "size": stat.st_size,
                        "hours_ago": round(hours_ago, 2)
                    })
            except Exception:
                continue

        # Sort by modification time (most recent first)
        recent_files.sort(key=lambda x: x["modified"], reverse=True)

        # Limit results
        truncated = len(recent_files) > max_results
        recent_files = recent_files[:max_results]

        return {
            "success": True,
            "directory": str(path),
            "hours": hours,
            "file_pattern": file_pattern,
            "cutoff_time": cutoff_dt.isoformat(),
            "count": len(recent_files),
            "files": recent_files,
            "truncated": truncated
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to find recent files: {str(e)}"
        }


if __name__ == "__main__":
    print("[gnosis-files-search] Starting file search and discovery MCP server", file=sys.stderr, flush=True)
    mcp.run()
