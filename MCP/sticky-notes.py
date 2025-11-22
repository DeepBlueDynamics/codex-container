#!/usr/bin/env python3
"""MCP: sticky-notes

Desktop sticky notes integration for Codex agents.
Allows reading, creating, updating, and managing sticky notes via TCP API.

The sticky notes app must be running on localhost:47822 for this to work.
"""

from __future__ import annotations

import json
import logging
import random
import socket
import struct
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from mcp.server.fastmcp import FastMCP

# Setup logging
log_dir = Path("/workspace/.mcp-logs")
log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / "sticky-notes.log"),
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("sticky-notes")

mcp = FastMCP("sticky-notes")

# Constants
STICKY_TCP_PORT = 47822
STICKY_CHECK_PORT = 47821


def send_tcp_command(command: Dict[str, Any], port: int = STICKY_TCP_PORT) -> Dict[str, Any]:
    """Send a command to the sticky notes TCP server and get response."""
    try:
        # Create socket connection
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)  # 5 second timeout
        sock.connect(('host.docker.internal', port))  # Use Docker host gateway

        # Serialize command to JSON
        command_data = json.dumps(command).encode('utf-8')
        command_length = struct.pack('!I', len(command_data))

        # Send command length then command data
        sock.sendall(command_length + command_data)

        # Receive response length
        response_length_data = sock.recv(4)
        if not response_length_data:
            return {"success": False, "error": "No response from server"}

        response_length = struct.unpack('!I', response_length_data)[0]

        # Receive response data
        response_data = b''
        while len(response_data) < response_length:
            chunk = sock.recv(response_length - len(response_data))
            if not chunk:
                break
            response_data += chunk

        sock.close()

        # Parse JSON response
        response = json.loads(response_data.decode('utf-8'))
        return response

    except socket.timeout:
        return {"success": False, "error": "Sticky notes server timeout (is the app running?)"}
    except ConnectionRefusedError:
        return {"success": False, "error": "Sticky notes server not running (start the sticky notes app)"}
    except Exception as e:
        logger.error(f"TCP communication error: {e}")
        return {"success": False, "error": f"TCP error: {str(e)}"}


def check_sticky_app_running() -> bool:
    """Check if sticky notes app is running by trying to connect to its port."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(('host.docker.internal', STICKY_CHECK_PORT))
        sock.close()
        return result == 0
    except:
        return False


@mcp.tool()
async def list_active_notes() -> Dict[str, Any]:
    """List all currently active (visible) sticky notes.

    Returns:
        Dictionary with list of active notes and their details.

    Example:
        {
            "success": true,
            "count": 3,
            "notes": [
                {"note_id": "abc123", "text": "Meeting at 2pm", "color": "yellow"},
                ...
            ]
        }
    """
    logger.info("Listing active sticky notes")

    try:
        command = {"type": "list_active"}
        result = send_tcp_command(command)

        if result.get("success"):
            logger.info(f"Found {result.get('count', 0)} active notes")
        else:
            logger.error(f"Failed to list active notes: {result.get('error')}")

        return result

    except Exception as e:
        logger.error(f"Error listing active notes: {e}")
        return {"success": False, "error": str(e)}


@mcp.tool()
async def list_saved_notes() -> Dict[str, Any]:
    """List all saved (closed/hidden) sticky notes.

    Returns:
        Dictionary with list of saved notes and their details.
    """
    logger.info("Listing saved sticky notes")

    try:
        command = {"type": "list_saved"}
        result = send_tcp_command(command)

        if result.get("success"):
            logger.info(f"Found {result.get('count', 0)} saved notes")
        else:
            logger.error(f"Failed to list saved notes: {result.get('error')}")

        return result

    except Exception as e:
        logger.error(f"Error listing saved notes: {e}")
        return {"success": False, "error": str(e)}


@mcp.tool()
async def search_notes(
    query: str,
    search_saved: bool = True,
    min_similarity: float = 0.5,
    max_results: int = 10,
    search_names: bool = True
) -> Dict[str, Any]:
    """Search for sticky notes by content or name.

    Args:
        query: Search query string
        search_saved: Whether to search saved notes (default: True)
        min_similarity: Minimum similarity threshold 0.0-1.0 (default: 0.5)
        max_results: Maximum number of results (default: 10)
        search_names: Whether to search note names (default: True)

    Returns:
        Dictionary with search results filtered by similarity.
    """
    logger.info(f"Searching notes for: '{query}' (min_similarity: {min_similarity})")

    try:
        command = {
            "type": "search",
            "query": query,
            "search_saved": search_saved,
            "min_similarity": min_similarity,
            "max_results": max_results,
            "search_names": search_names
        }
        result = send_tcp_command(command)

        if result.get("success"):
            # Apply client-side filtering if server doesn't support parameters
            if "matches" in result:
                filtered_matches = []
                for match in result["matches"]:
                    if match.get("similarity", 1.0) >= min_similarity:
                        filtered_matches.append(match)
                    if len(filtered_matches) >= max_results:
                        break

                result["matches"] = filtered_matches
                result["count"] = len(filtered_matches)

            logger.info(f"Found {result.get('count', 0)} matches")
        else:
            logger.error(f"Search failed: {result.get('error')}")

        return result

    except Exception as e:
        logger.error(f"Error searching notes: {e}")
        return {"success": False, "error": str(e)}


@mcp.tool()
async def read_note(note_id: str) -> Dict[str, Any]:
    """Read the full content of a specific sticky note.

    Args:
        note_id: ID or name of the note to read

    Returns:
        Dictionary with note content and metadata.
    """
    logger.info(f"Reading sticky note: {note_id}")

    try:
        command = {
            "type": "read_note",
            "note_id": note_id
        }
        result = send_tcp_command(command)

        if result.get("success"):
            logger.info(f"Successfully read note: {note_id}")
        else:
            logger.warning(f"Note not found: {note_id}")

        return result

    except Exception as e:
        logger.error(f"Error reading note {note_id}: {e}")
        return {"success": False, "error": str(e)}


@mcp.tool()
async def create_note(
    text: str,
    x: Optional[int] = None,
    y: Optional[int] = None,
    color: Optional[str] = None
) -> Dict[str, Any]:
    """Create a new sticky note with the specified content.

    Args:
        text: Content for the new note
        x: X position (optional, uses random if not specified)
        y: Y position (optional, uses random if not specified)
        color: Note color (optional, cycles through defaults)

    Returns:
        Dictionary with new note details or error.
    """
    logger.info(f"Creating new sticky note: {text[:50]}...")

    try:
        command = {
            "type": "create_note",
            "text": text,
            "x": x,
            "y": y,
            "color": color
        }

        result = send_tcp_command(command)
        if result.get("success"):
            logger.info(f"Created note: {result.get('note_id')}")
        else:
            logger.error(f"Failed to create note: {result.get('error')}")

        return result

    except Exception as e:
        logger.error(f"Error creating note: {e}")
        return {"success": False, "error": str(e)}


@mcp.tool()
async def open_note(
    note_id: str,
    x: Optional[int] = None,
    y: Optional[int] = None
) -> Dict[str, Any]:
    """Open/activate a saved sticky note, making it visible.

    Args:
        note_id: ID or name of the saved note to open
        x: X position (optional, uses last position if available)
        y: Y position (optional, uses last position if available)

    Returns:
        Dictionary with operation result.
    """
    logger.info(f"Opening saved sticky note: {note_id}")

    try:
        command = {
            "type": "open_note",
            "note_id": note_id,
            "x": x,
            "y": y
        }

        result = send_tcp_command(command)
        if result.get("success"):
            logger.info(f"Opened note: {note_id}")
        else:
            logger.error(f"Failed to open note: {result.get('error')}")

        return result

    except Exception as e:
        logger.error(f"Error opening note {note_id}: {e}")
        return {"success": False, "error": str(e)}


@mcp.tool()
async def update_note(note_id: str, text: str) -> Dict[str, Any]:
    """Update the content of an existing sticky note.

    Args:
        note_id: ID or name of the note to update
        text: New content for the note

    Returns:
        Dictionary with operation result.
    """
    logger.info(f"Updating sticky note: {note_id}")

    try:
        command = {
            "type": "update_note",
            "note_id": note_id,
            "text": text
        }

        result = send_tcp_command(command)
        if result.get("success"):
            logger.info(f"Updated note: {note_id}")
        else:
            logger.error(f"Failed to update note: {result.get('error')}")

        return result

    except Exception as e:
        logger.error(f"Error updating note {note_id}: {e}")
        return {"success": False, "error": str(e)}


@mcp.tool()
async def delete_note(note_id: str) -> Dict[str, Any]:
    """Delete a sticky note completely (removes from active and saved storage).

    Args:
        note_id: ID or name of the note to delete

    Returns:
        Dictionary with operation result.
    """
    logger.info(f"Deleting sticky note: {note_id}")

    try:
        command = {
            "type": "delete_note",
            "note_id": note_id
        }

        result = send_tcp_command(command)
        if result.get("success"):
            logger.info(f"Deleted note: {note_id}")
        else:
            logger.error(f"Failed to delete note: {result.get('error')}")

        return result

    except Exception as e:
        logger.error(f"Error deleting note {note_id}: {e}")
        return {"success": False, "error": str(e)}


@mcp.tool()
async def find_note_by_name(note_name: str) -> Dict[str, Any]:
    """Find a sticky note by its exact name/ID.

    Args:
        note_name: Exact name or ID of the note to find

    Returns:
        Dictionary with note details if found.
    """
    logger.info(f"Finding sticky note by name: {note_name}")

    try:
        # First try to read it directly
        read_result = await read_note(note_name)
        if read_result.get("success"):
            return read_result

        # If not found, search with high similarity threshold
        search_result = await search_notes(
            note_name,
            search_saved=True,
            min_similarity=0.95,
            max_results=5,
            search_names=True
        )

        if search_result.get("success") and search_result.get("count", 0) > 0:
            # Look for exact name matches
            for match in search_result.get("matches", []):
                if match.get("note_id") == note_name or match.get("note_name") == note_name:
                    return await read_note(match.get("note_id"))

            # Return best match if no exact match
            best_match = search_result.get("matches", [])[0]
            return await read_note(best_match.get("note_id"))

        return {"success": False, "error": f"Note '{note_name}' not found"}

    except Exception as e:
        logger.error(f"Error finding note by name {note_name}: {e}")
        return {"success": False, "error": str(e)}


@mcp.tool()
async def sticky_status() -> Dict[str, Any]:
    """Get status information about the sticky notes system.

    Returns:
        Dictionary with system status and statistics.
    """
    logger.info("Getting sticky notes system status")

    try:
        command = {"type": "status"}
        result = send_tcp_command(command)

        if result.get("success"):
            logger.info("Status check complete via TCP")
            return result
        else:
            # Fallback status if TCP fails
            app_running = check_sticky_app_running()
            return {
                "success": True,
                "app_running": app_running,
                "tcp_available": False,
                "message": "Limited status - TCP communication failed",
                "last_check": datetime.now().isoformat()
            }

    except Exception as e:
        logger.error(f"Error getting status: {e}")
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    logger.info("Starting Sticky Notes MCP server")
    mcp.run()
