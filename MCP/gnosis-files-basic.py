#!/usr/bin/env python3
"""
MCP: gnosis-files-basic

Core file operations - read, write, stat, copy, move, delete.
Fast and lightweight operations for everyday file manipulation.
"""

from __future__ import annotations

import sys
import os
import shutil
from pathlib import Path
from typing import Dict, Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("gnosis-files-basic")


@mcp.tool()
async def file_read(file_path: str, encoding: str = "utf-8") -> Dict[str, Any]:
    """Read the complete contents of a text file.

    This tool reads an entire file into memory and returns its contents as a string.
    Use this for reading configuration files, source code, logs, or any text-based files.

    Args:
        file_path: Absolute or relative path to the file to read. Supports ~ for home directory.
        encoding: Character encoding to use (default: utf-8). Common alternatives: ascii, latin-1, utf-16.

    Returns:
        Dictionary containing:
        - success (bool): Whether the read operation succeeded
        - content (str): Full file contents if successful
        - file_path (str): Resolved absolute path to the file
        - size (int): File size in bytes
        - lines (int): Number of lines in the file
        - error (str): Error message if operation failed

    Example:
        file_read(file_path="/workspace/config.json")
        file_read(file_path="~/Documents/notes.txt", encoding="utf-8")
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

        content = path.read_text(encoding=encoding)

        return {
            "success": True,
            "file_path": str(path),
            "content": content,
            "size": path.stat().st_size,
            "lines": len(content.splitlines())
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to read file: {str(e)}"
        }


@mcp.tool()
async def file_write(
    file_path: str,
    content: str,
    encoding: str = "utf-8",
    create_dirs: bool = True
) -> Dict[str, Any]:
    """Write text content to a file, creating or overwriting it.

    This tool writes the provided content to a file. If the file exists, it will be
    completely replaced. If parent directories don't exist, they can be created automatically.

    Args:
        file_path: Path where the file should be written. Supports ~ for home directory.
        content: Text content to write to the file.
        encoding: Character encoding to use (default: utf-8). Common alternatives: ascii, latin-1, utf-16.
        create_dirs: If True, creates parent directories if they don't exist (default: True).

    Returns:
        Dictionary containing:
        - success (bool): Whether the write operation succeeded
        - file_path (str): Resolved absolute path where file was written
        - size (int): Size of written file in bytes
        - lines (int): Number of lines written
        - error (str): Error message if operation failed

    Example:
        file_write(file_path="/workspace/output.txt", content="Hello World")
        file_write(file_path="~/logs/app.log", content="Log entry\n", create_dirs=True)
    """
    try:
        path = Path(file_path).expanduser().resolve()

        if create_dirs:
            path.parent.mkdir(parents=True, exist_ok=True)

        path.write_text(content, encoding=encoding)

        return {
            "success": True,
            "file_path": str(path),
            "size": path.stat().st_size,
            "lines": len(content.splitlines())
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to write file: {str(e)}"
        }


@mcp.tool()
async def file_stat(file_path: str) -> Dict[str, Any]:
    """Get detailed metadata and statistics for a file or directory.

    This tool retrieves comprehensive information about a filesystem path including
    size, timestamps, permissions, and type. Use this to check file properties before
    performing operations or to gather file information for reporting.

    Args:
        file_path: Path to file or directory to inspect. Supports ~ for home directory.

    Returns:
        Dictionary containing:
        - success (bool): Whether the stat operation succeeded
        - path (str): Resolved absolute path
        - type (str): "file", "directory", or "other"
        - size (int): Size in bytes (0 for directories)
        - modified (float): Last modification timestamp (Unix epoch)
        - created (float): Creation timestamp (Unix epoch)
        - exists (bool): Whether the path exists
        - readable (bool): Whether the path is readable
        - writable (bool): Whether the path is writable
        - error (str): Error message if operation failed

    Example:
        file_stat(file_path="/workspace/data.csv")
        file_stat(file_path="~/Downloads")
    """
    try:
        path = Path(file_path).expanduser().resolve()

        if not path.exists():
            return {
                "success": False,
                "error": f"Path not found: {file_path}"
            }

        stat = path.stat()

        return {
            "success": True,
            "path": str(path),
            "type": "file" if path.is_file() else "directory" if path.is_dir() else "other",
            "size": stat.st_size,
            "modified": stat.st_mtime,
            "created": stat.st_ctime,
            "exists": True,
            "readable": os.access(path, os.R_OK),
            "writable": os.access(path, os.W_OK)
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to stat path: {str(e)}"
        }


@mcp.tool()
async def file_exists(file_path: str) -> Dict[str, Any]:
    """Check whether a file or directory exists at the specified path.

    This is a quick way to test for the existence of a path without retrieving
    full metadata. Use this before attempting operations that require a file to exist,
    or to verify that a path was created successfully.

    Args:
        file_path: Path to check for existence. Supports ~ for home directory.

    Returns:
        Dictionary containing:
        - success (bool): Whether the check operation succeeded (always True unless path is invalid)
        - path (str): Resolved absolute path that was checked
        - exists (bool): True if the path exists, False otherwise
        - is_file (bool): True if path exists and is a file
        - is_directory (bool): True if path exists and is a directory
        - error (str): Error message if operation failed

    Example:
        file_exists(file_path="/workspace/config.json")
        file_exists(file_path="~/Documents/report.pdf")
    """
    try:
        path = Path(file_path).expanduser().resolve()

        exists = path.exists()
        is_file = path.is_file() if exists else False
        is_dir = path.is_dir() if exists else False

        return {
            "success": True,
            "path": str(path),
            "exists": exists,
            "is_file": is_file,
            "is_directory": is_dir
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to check path: {str(e)}"
        }


@mcp.tool()
async def file_delete(file_path: str, recursive: bool = False) -> Dict[str, Any]:
    """Delete a file or directory from the filesystem.

    This tool permanently removes files or directories. For directories, use recursive=True
    to delete all contents. Use with caution as this operation cannot be undone.

    Args:
        file_path: Path to file or directory to delete. Supports ~ for home directory.
        recursive: If True, deletes directories and all their contents. Required for non-empty directories (default: False).

    Returns:
        Dictionary containing:
        - success (bool): Whether the delete operation succeeded
        - path (str): Resolved absolute path that was deleted
        - type (str): What was deleted - "file", "directory", or "not_found"
        - error (str): Error message if operation failed

    Example:
        file_delete(file_path="/workspace/temp.txt")
        file_delete(file_path="/workspace/temp_dir", recursive=True)

    Warning:
        This operation is permanent and cannot be undone. Consider backing up important files before deletion.
    """
    try:
        path = Path(file_path).expanduser().resolve()

        if not path.exists():
            return {
                "success": False,
                "path": str(path),
                "type": "not_found",
                "error": f"Path does not exist: {file_path}"
            }

        path_type = "file" if path.is_file() else "directory"

        if path.is_file():
            path.unlink()
        elif path.is_dir():
            if recursive:
                shutil.rmtree(path)
            else:
                path.rmdir()  # Only works for empty directories

        return {
            "success": True,
            "path": str(path),
            "type": path_type,
            "message": f"Deleted {path_type}: {path}"
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to delete: {str(e)}"
        }


@mcp.tool()
async def file_copy(source: str, destination: str, overwrite: bool = False) -> Dict[str, Any]:
    """Copy a file or directory to a new location.

    This tool creates a complete copy of a file or directory tree at the destination path.
    For directories, all contents are copied recursively. Metadata like timestamps are preserved.

    Args:
        source: Path to the file or directory to copy. Supports ~ for home directory.
        destination: Path where the copy should be created. Supports ~ for home directory.
        overwrite: If True, replaces destination if it exists. If False, fails if destination exists (default: False).

    Returns:
        Dictionary containing:
        - success (bool): Whether the copy operation succeeded
        - source (str): Resolved absolute source path
        - destination (str): Resolved absolute destination path
        - type (str): What was copied - "file" or "directory"
        - size (int): Size in bytes of copied file (0 for directories)
        - error (str): Error message if operation failed

    Example:
        file_copy(source="/workspace/data.csv", destination="/workspace/backup/data.csv")
        file_copy(source="~/Documents/project", destination="~/Backup/project", overwrite=True)
    """
    try:
        src_path = Path(source).expanduser().resolve()
        dst_path = Path(destination).expanduser().resolve()

        if not src_path.exists():
            return {
                "success": False,
                "error": f"Source does not exist: {source}"
            }

        if dst_path.exists() and not overwrite:
            return {
                "success": False,
                "error": f"Destination already exists: {destination} (use overwrite=True to replace)"
            }

        # Create parent directories if needed
        dst_path.parent.mkdir(parents=True, exist_ok=True)

        if src_path.is_file():
            shutil.copy2(src_path, dst_path)
            size = dst_path.stat().st_size
            path_type = "file"
        else:
            if dst_path.exists():
                shutil.rmtree(dst_path)
            shutil.copytree(src_path, dst_path)
            size = 0
            path_type = "directory"

        return {
            "success": True,
            "source": str(src_path),
            "destination": str(dst_path),
            "type": path_type,
            "size": size
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to copy: {str(e)}"
        }


@mcp.tool()
async def file_move(source: str, destination: str, overwrite: bool = False) -> Dict[str, Any]:
    """Move or rename a file or directory to a new location.

    This tool relocates a file or directory, effectively renaming it if the destination
    is in the same directory, or moving it if the destination is in a different directory.
    The source is removed after successful move.

    Args:
        source: Path to the file or directory to move. Supports ~ for home directory.
        destination: New path for the file or directory. Supports ~ for home directory.
        overwrite: If True, replaces destination if it exists. If False, fails if destination exists (default: False).

    Returns:
        Dictionary containing:
        - success (bool): Whether the move operation succeeded
        - source (str): Original absolute path (no longer exists after move)
        - destination (str): New absolute path where file/directory now exists
        - type (str): What was moved - "file" or "directory"
        - error (str): Error message if operation failed

    Example:
        file_move(source="/workspace/draft.txt", destination="/workspace/final.txt")
        file_move(source="~/Downloads/file.pdf", destination="~/Documents/file.pdf", overwrite=True)
    """
    try:
        src_path = Path(source).expanduser().resolve()
        dst_path = Path(destination).expanduser().resolve()

        if not src_path.exists():
            return {
                "success": False,
                "error": f"Source does not exist: {source}"
            }

        if dst_path.exists() and not overwrite:
            return {
                "success": False,
                "error": f"Destination already exists: {destination} (use overwrite=True to replace)"
            }

        path_type = "file" if src_path.is_file() else "directory"

        # Create parent directories if needed
        dst_path.parent.mkdir(parents=True, exist_ok=True)

        # Remove destination if overwriting
        if dst_path.exists() and overwrite:
            if dst_path.is_file():
                dst_path.unlink()
            else:
                shutil.rmtree(dst_path)

        shutil.move(str(src_path), str(dst_path))

        return {
            "success": True,
            "source": str(src_path),
            "destination": str(dst_path),
            "type": path_type
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to move: {str(e)}"
        }


if __name__ == "__main__":
    print("[gnosis-files-basic] Starting core file operations MCP server", file=sys.stderr, flush=True)
    mcp.run()
