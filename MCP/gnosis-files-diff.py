#!/usr/bin/env python3
"""
MCP: gnosis-files-diff

File comparison, backup, and version control operations.
Tools for comparing files, creating backups, and managing file versions.
"""

from __future__ import annotations

import sys
import os
import shutil
import difflib
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("gnosis-files-diff")


def _get_versions_dir(file_path: Path) -> Path:
    """Get the versions directory for a file."""
    parent = file_path.parent
    versions_dir = parent / f".{file_path.name}_versions"
    return versions_dir


@mcp.tool()
async def file_diff(
    file1: str,
    file2: str,
    context_lines: int = 3,
    format: str = "unified"
) -> Dict[str, Any]:
    """Compare two text files and show differences.

    This tool compares the contents of two files and generates a diff showing what
    has changed between them. Useful for reviewing changes, comparing backups, or
    understanding file modifications.

    Args:
        file1: Path to first file (often the original or older version). Supports ~ for home directory.
        file2: Path to second file (often the modified or newer version). Supports ~ for home directory.
        context_lines: Number of unchanged lines to show around each change for context (default: 3).
        format: Diff format to use. Options: "unified" (patch-style), "ndiff" (line-by-line with markers) (default: "unified").

    Returns:
        Dictionary containing:
        - success (bool): Whether the diff operation succeeded
        - file1 (str): Resolved absolute path to first file
        - file2 (str): Resolved absolute path to second file
        - identical (bool): True if files have identical content
        - diff (str): Multi-line string showing differences (empty if identical)
        - added_lines (int): Count of lines added in file2
        - removed_lines (int): Count of lines removed from file1
        - error (str): Error message if operation failed

    Example:
        file_diff(file1="/workspace/config.old.json", file2="/workspace/config.json")
        file_diff(file1="~/draft.txt", file2="~/final.txt", context_lines=5, format="ndiff")
    """
    try:
        path1 = Path(file1).expanduser().resolve()
        path2 = Path(file2).expanduser().resolve()

        if not path1.exists():
            return {
                "success": False,
                "error": f"First file not found: {file1}"
            }

        if not path2.exists():
            return {
                "success": False,
                "error": f"Second file not found: {file2}"
            }

        if not path1.is_file() or not path2.is_file():
            return {
                "success": False,
                "error": "Both paths must be files"
            }

        # Read files
        lines1 = path1.read_text(encoding='utf-8', errors='ignore').splitlines(keepends=True)
        lines2 = path2.read_text(encoding='utf-8', errors='ignore').splitlines(keepends=True)

        # Check if identical
        identical = lines1 == lines2

        # Generate diff
        if identical:
            diff_str = ""
            added = 0
            removed = 0
        else:
            if format == "ndiff":
                diff_lines = list(difflib.ndiff(lines1, lines2))
                diff_str = "".join(diff_lines)
                added = sum(1 for line in diff_lines if line.startswith('+ '))
                removed = sum(1 for line in diff_lines if line.startswith('- '))
            else:  # unified
                diff_lines = list(difflib.unified_diff(
                    lines1, lines2,
                    fromfile=str(path1),
                    tofile=str(path2),
                    n=context_lines
                ))
                diff_str = "".join(diff_lines)
                added = sum(1 for line in diff_lines if line.startswith('+') and not line.startswith('+++'))
                removed = sum(1 for line in diff_lines if line.startswith('-') and not line.startswith('---'))

        return {
            "success": True,
            "file1": str(path1),
            "file2": str(path2),
            "identical": identical,
            "diff": diff_str,
            "added_lines": added,
            "removed_lines": removed
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to diff files: {str(e)}"
        }


@mcp.tool()
async def file_backup(file_path: str, backup_dir: Optional[str] = None) -> Dict[str, Any]:
    """Create a timestamped backup copy of a file.

    This tool creates a backup copy of a file with a timestamp in the filename,
    allowing you to preserve versions before making changes. Backups are stored
    either in a specified directory or in a hidden versions folder next to the original.

    Args:
        file_path: Path to file to backup. Supports ~ for home directory.
        backup_dir: Optional directory to store backup. If not provided, creates a hidden .{filename}_versions/ directory next to the original file.

    Returns:
        Dictionary containing:
        - success (bool): Whether the backup operation succeeded
        - original (str): Resolved absolute path to original file
        - backup (str): Absolute path where backup was created
        - backup_name (str): Name of the backup file
        - size (int): Size of backed up file in bytes
        - timestamp (str): ISO timestamp when backup was created
        - error (str): Error message if operation failed

    Example:
        file_backup(file_path="/workspace/config.json")
        file_backup(file_path="~/important.txt", backup_dir="~/backups")
    """
    try:
        path = Path(file_path).expanduser().resolve()

        if not path.exists():
            return {
                "success": False,
                "error": f"File not found: {file_path}"
            }

        if not path.is_file():
            return {
                "success": False,
                "error": f"Not a file: {file_path}"
            }

        # Determine backup location
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{path.stem}_{timestamp}{path.suffix}"

        if backup_dir:
            backup_path = Path(backup_dir).expanduser().resolve()
            backup_path.mkdir(parents=True, exist_ok=True)
        else:
            backup_path = _get_versions_dir(path)
            backup_path.mkdir(parents=True, exist_ok=True)

        backup_file = backup_path / backup_name

        # Create backup
        shutil.copy2(path, backup_file)

        return {
            "success": True,
            "original": str(path),
            "backup": str(backup_file),
            "backup_name": backup_name,
            "size": backup_file.stat().st_size,
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to create backup: {str(e)}"
        }


@mcp.tool()
async def file_list_versions(file_path: str) -> Dict[str, Any]:
    """List all available backup versions of a file.

    This tool shows all timestamped backups that have been created for a file using
    the file_backup tool. Returns version information sorted by creation time, allowing
    you to see the history of changes and select a version to restore.

    Args:
        file_path: Path to the original file. Supports ~ for home directory.

    Returns:
        Dictionary containing:
        - success (bool): Whether the list operation succeeded
        - file_path (str): Resolved absolute path to original file
        - versions_dir (str): Directory where versions are stored
        - count (int): Number of backup versions available
        - versions (list): List of version information dictionaries with:
            - path (str): Absolute path to backup file
            - name (str): Backup filename
            - size (int): File size in bytes
            - modified (float): Modification timestamp (Unix epoch)
            - modified_iso (str): Human-readable ISO timestamp
            - age_hours (float): How many hours ago this backup was created
        - error (str): Error message if operation failed

    Example:
        file_list_versions(file_path="/workspace/config.json")
        file_list_versions(file_path="~/Documents/report.docx")
    """
    try:
        path = Path(file_path).expanduser().resolve()
        versions_dir = _get_versions_dir(path)

        if not versions_dir.exists():
            return {
                "success": True,
                "file_path": str(path),
                "versions_dir": str(versions_dir),
                "count": 0,
                "versions": [],
                "message": "No versions directory found (no backups created yet)"
            }

        # Find all backup files
        pattern = f"{path.stem}_*{path.suffix}"
        backup_files = list(versions_dir.glob(pattern))

        # Gather version information
        versions = []
        now = datetime.now().timestamp()

        for backup in backup_files:
            try:
                stat = backup.stat()
                mod_dt = datetime.fromtimestamp(stat.st_mtime)
                age_hours = (now - stat.st_mtime) / 3600

                versions.append({
                    "path": str(backup),
                    "name": backup.name,
                    "size": stat.st_size,
                    "modified": stat.st_mtime,
                    "modified_iso": mod_dt.isoformat(),
                    "age_hours": round(age_hours, 2)
                })
            except Exception:
                continue

        # Sort by modification time (newest first)
        versions.sort(key=lambda x: x["modified"], reverse=True)

        return {
            "success": True,
            "file_path": str(path),
            "versions_dir": str(versions_dir),
            "count": len(versions),
            "versions": versions
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to list versions: {str(e)}"
        }


@mcp.tool()
async def file_restore(
    file_path: str,
    version_name: str,
    create_backup: bool = True
) -> Dict[str, Any]:
    """Restore a file from a previous backup version.

    This tool replaces the current file with a specified backup version. Optionally
    creates a backup of the current file before restoring, so you can undo the restore
    if needed. Use file_list_versions to see available versions first.

    Args:
        file_path: Path to the file to restore. Supports ~ for home directory.
        version_name: Name of the backup file to restore from (e.g., "config_20231215_143022.json").
        create_backup: If True, backs up current file before restoring. Recommended to prevent data loss (default: True).

    Returns:
        Dictionary containing:
        - success (bool): Whether the restore operation succeeded
        - file_path (str): Resolved absolute path to restored file
        - restored_from (str): Path to the backup version that was restored
        - backup_of_current (str): Path where current version was backed up before restore (if create_backup=True)
        - size (int): Size of restored file in bytes
        - error (str): Error message if operation failed

    Example:
        file_restore(file_path="/workspace/config.json", version_name="config_20231215_143022.json")
        file_restore(file_path="~/report.txt", version_name="report_20231220_090000.txt", create_backup=False)

    Warning:
        If create_backup=False, the current file contents will be permanently lost.
    """
    try:
        path = Path(file_path).expanduser().resolve()
        versions_dir = _get_versions_dir(path)
        restore_from = versions_dir / version_name

        if not restore_from.exists():
            return {
                "success": False,
                "error": f"Version not found: {version_name} in {versions_dir}"
            }

        if not restore_from.is_file():
            return {
                "success": False,
                "error": f"Version is not a file: {version_name}"
            }

        result = {
            "success": True,
            "file_path": str(path),
            "restored_from": str(restore_from)
        }

        # Backup current file if requested and it exists
        if create_backup and path.exists():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"{path.stem}_pre_restore_{timestamp}{path.suffix}"
            backup_file = versions_dir / backup_name
            shutil.copy2(path, backup_file)
            result["backup_of_current"] = str(backup_file)

        # Restore from backup
        shutil.copy2(restore_from, path)
        result["size"] = path.stat().st_size

        return result

    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to restore file: {str(e)}"
        }


@mcp.tool()
async def file_patch(
    file_path: str,
    search_text: str,
    replace_text: str,
    create_backup: bool = True,
    max_replacements: int = -1
) -> Dict[str, Any]:
    """Apply a simple search-and-replace patch to a file.

    This tool modifies a file by replacing all occurrences of a search string with
    replacement text. Optionally creates a backup before making changes. Use this for
    simple text replacements across entire files.

    Args:
        file_path: Path to file to patch. Supports ~ for home directory.
        search_text: Text string to search for and replace.
        replace_text: Text string to insert in place of search_text.
        create_backup: If True, creates a backup before patching (default: True).
        max_replacements: Maximum number of replacements to make. Use -1 for unlimited (default: -1).

    Returns:
        Dictionary containing:
        - success (bool): Whether the patch operation succeeded
        - file_path (str): Resolved absolute path to patched file
        - backup (str): Path to backup file (if create_backup=True)
        - replacements (int): Number of times search_text was replaced
        - size_before (int): File size before patching (bytes)
        - size_after (int): File size after patching (bytes)
        - error (str): Error message if operation failed

    Example:
        file_patch(file_path="/workspace/config.json", search_text="localhost", replace_text="production.example.com")
        file_patch(file_path="~/script.sh", search_text="/old/path", replace_text="/new/path", create_backup=True)
        file_patch(file_path="/workspace/file.txt", search_text="TODO", replace_text="DONE", max_replacements=5)

    Warning:
        This performs literal string replacement, not regex. All occurrences will be replaced.
    """
    try:
        path = Path(file_path).expanduser().resolve()

        if not path.exists():
            return {
                "success": False,
                "error": f"File not found: {file_path}"
            }

        if not path.is_file():
            return {
                "success": False,
                "error": f"Not a file: {file_path}"
            }

        size_before = path.stat().st_size

        # Create backup if requested
        backup_path = None
        if create_backup:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            versions_dir = _get_versions_dir(path)
            versions_dir.mkdir(parents=True, exist_ok=True)
            backup_name = f"{path.stem}_pre_patch_{timestamp}{path.suffix}"
            backup_path = versions_dir / backup_name
            shutil.copy2(path, backup_path)

        # Read file
        content = path.read_text(encoding='utf-8')

        # Apply replacements
        if max_replacements == -1:
            new_content = content.replace(search_text, replace_text)
            replacements = content.count(search_text)
        else:
            replacements = 0
            new_content = content
            for _ in range(max_replacements):
                if search_text in new_content:
                    new_content = new_content.replace(search_text, replace_text, 1)
                    replacements += 1
                else:
                    break

        # Write back
        path.write_text(new_content, encoding='utf-8')
        size_after = path.stat().st_size

        result = {
            "success": True,
            "file_path": str(path),
            "replacements": replacements,
            "size_before": size_before,
            "size_after": size_after
        }

        if backup_path:
            result["backup"] = str(backup_path)

        return result

    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to patch file: {str(e)}"
        }


if __name__ == "__main__":
    print("[gnosis-files-diff] Starting file diff and version control MCP server", file=sys.stderr, flush=True)
    mcp.run()
