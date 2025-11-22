#!/usr/bin/env python3
"""
Google Drive MCP Bridge
=======================

Exposes Google Drive API to AI assistants via MCP, enabling file and folder
management through natural language.

Tools:
  - gdrive_status: Check authentication and configuration status
  - gdrive_auth_setup: Initialize OAuth 2.0 authentication flow
  - gdrive_list_files: List files and folders
  - gdrive_get_file: Get file metadata
  - gdrive_download: Download file content
  - gdrive_upload: Upload a new file
  - gdrive_create_folder: Create a new folder
  - gdrive_move: Move file to different folder
  - gdrive_copy: Copy a file
  - gdrive_delete: Delete file (move to trash)
  - gdrive_search: Search files by query
  - gdrive_share: Share file/folder with user
  - gdrive_get_permissions: Get sharing permissions
  - gdrive_export: Export Google Docs to different format

Env/config:
  - GOOGLE_DRIVE_CLIENT_ID     (required for OAuth)
  - GOOGLE_DRIVE_CLIENT_SECRET (required for OAuth)
  - GOOGLE_DRIVE_TOKEN_FILE    (default: .gdrive-tokens.json)
  - .gdrive.env file in repo root with credentials

Setup:
  1. Create OAuth 2.0 Desktop App credentials in Google Cloud Console
  2. Enable Google Drive API
  3. Save client_id and client_secret to .gdrive.env or environment
  4. Run gdrive_auth_setup to authenticate (opens browser)
  5. Tokens are saved locally for future use

Notes:
  - First use requires browser-based OAuth consent
  - Tokens refresh automatically
  - All credentials stay local, never transmitted to external servers
  - Can use same OAuth credentials as Calendar/Gmail
"""

import os
import io
from typing import Any, Dict, List, Optional
from pathlib import Path

from mcp.server.fastmcp import FastMCP, Context

# Google auth imports
try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload, MediaIoBaseUpload
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False


mcp = FastMCP("google-drive")

# OAuth 2.0 scopes - includes all Google service scopes since same OAuth client is shared
SCOPES = [
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.compose',
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/gmail.labels',
    'openid',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile'
]

# Config
GDRIVE_ENV_FILE = os.path.join(os.getcwd(), ".gdrive.env")
DEFAULT_TOKEN_FILE = os.path.join(os.getcwd(), ".gdrive-tokens.json")
GDRIVE_REDIRECT_URI = "http://localhost:8080"

# MIME types for export
EXPORT_MIMETYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "odt": "application/vnd.oasis.opendocument.text",
    "pdf": "application/pdf",
    "txt": "text/plain",
    "html": "text/html",
    "epub": "application/epub+zip",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "ods": "application/vnd.oasis.opendocument.spreadsheet",
    "csv": "text/csv",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def _get_config() -> Dict[str, Optional[str]]:
    """Get configuration from environment or .gdrive.env file."""
    config = {
        "client_id": os.environ.get("GOOGLE_DRIVE_CLIENT_ID"),
        "client_secret": os.environ.get("GOOGLE_DRIVE_CLIENT_SECRET"),
        "token_file": os.environ.get("GOOGLE_DRIVE_TOKEN_FILE", DEFAULT_TOKEN_FILE),
    }

    # Try loading from .gdrive.env if not in environment
    if not config["client_id"] or not config["client_secret"]:
        try:
            if os.path.exists(GDRIVE_ENV_FILE):
                with open(GDRIVE_ENV_FILE, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            key, value = line.split("=", 1)
                            key = key.strip()
                            value = value.strip().strip('"').strip("'")
                            if key == "GOOGLE_DRIVE_CLIENT_ID":
                                config["client_id"] = value
                            elif key == "GOOGLE_DRIVE_CLIENT_SECRET":
                                config["client_secret"] = value
                            elif key == "GOOGLE_DRIVE_TOKEN_FILE":
                                config["token_file"] = value
        except Exception:
            pass

    return config


def _get_credentials() -> Optional[Credentials]:
    """Load saved credentials or return None."""
    config = _get_config()
    token_file = config["token_file"]

    if not os.path.exists(token_file):
        return None

    try:
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)

        # Refresh if expired
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            # Save refreshed credentials
            with open(token_file, 'w') as token:
                token.write(creds.to_json())

        return creds if creds and creds.valid else None
    except Exception:
        return None


def _get_service():
    """Get authenticated Drive service or raise error."""
    if not GOOGLE_AVAILABLE:
        raise ImportError(
            "Google Drive libraries not installed. "
            "Run: pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client"
        )

    creds = _get_credentials()
    if not creds:
        raise ValueError(
            "Not authenticated. Run gdrive_auth_setup first to authenticate with Google."
        )

    return build('drive', 'v3', credentials=creds)


def _format_file_info(file: Dict[str, Any]) -> Dict[str, Any]:
    """Format file metadata for response."""
    return {
        "id": file.get("id"),
        "name": file.get("name"),
        "mime_type": file.get("mimeType"),
        "size": file.get("size"),
        "created_time": file.get("createdTime"),
        "modified_time": file.get("modifiedTime"),
        "web_view_link": file.get("webViewLink"),
        "parents": file.get("parents", []),
        "trashed": file.get("trashed", False),
        "starred": file.get("starred", False),
        "shared": file.get("shared", False),
    }


@mcp.tool()
async def gdrive_status(ctx: Context = None) -> Dict[str, Any]:
    """
    Check Google Drive authentication and configuration status.

    Use this to verify your OAuth credentials are configured and valid
    before attempting Drive operations.

    Args:
        ctx: MCP context (optional)

    Returns:
        Dictionary containing:
            - success: bool - Always True
            - google_libs_installed: bool - Whether required libraries are available
            - client_id_present: bool - Whether OAuth client ID is configured
            - client_secret_present: bool - Whether OAuth client secret is configured
            - token_file: str - Path to token storage file
            - authenticated: bool - Whether valid tokens exist
            - credentials_valid: bool - Whether credentials are currently valid
    """
    config = _get_config()
    creds = _get_credentials() if GOOGLE_AVAILABLE else None

    return {
        "success": True,
        "google_libs_installed": GOOGLE_AVAILABLE,
        "client_id_present": bool(config["client_id"]),
        "client_secret_present": bool(config["client_secret"]),
        "token_file": config["token_file"],
        "authenticated": creds is not None,
        "credentials_valid": creds.valid if creds else False,
    }


@mcp.tool()
async def gdrive_auth_setup(
    force_reauth: bool = False,
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Initialize OAuth 2.0 authentication flow for Google Drive.

    **FIRST TIME SETUP**: This will open a browser window for you to log in to Google
    and grant Drive access. After authentication, tokens are saved locally for future use.

    **PREREQUISITES**:
    1. Create OAuth 2.0 credentials in Google Cloud Console (Desktop App type)
    2. Enable Google Drive API
    3. Set GOOGLE_DRIVE_CLIENT_ID and GOOGLE_DRIVE_CLIENT_SECRET in environment
       or save to .gdrive.env file in this format:
       ```
       GOOGLE_DRIVE_CLIENT_ID=your_client_id
       GOOGLE_DRIVE_CLIENT_SECRET=your_client_secret
       ```

    **NOTE**: You can use the same OAuth credentials as Calendar/Gmail if you've already set those up.

    Args:
        force_reauth: If True, force re-authentication even if tokens exist (default: False)
        ctx: MCP context (optional)

    Returns:
        Dictionary containing:
            - success: bool - Whether authentication succeeded
            - authenticated: bool - Whether valid credentials now exist
            - token_file: str - Path where tokens were saved
            - message: str - Human-readable status message
            OR on error:
            - success: bool - False
            - error: str - Error message
            - missing_config: list - List of missing configuration items
    """
    if not GOOGLE_AVAILABLE:
        return {
            "success": False,
            "error": "Google Drive libraries not installed",
            "install_command": "pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client"
        }

    config = _get_config()

    # Check for required config
    missing = []
    if not config["client_id"]:
        missing.append("GOOGLE_DRIVE_CLIENT_ID")
    if not config["client_secret"]:
        missing.append("GOOGLE_DRIVE_CLIENT_SECRET")

    if missing:
        return {
            "success": False,
            "error": "Missing OAuth configuration",
            "missing_config": missing,
            "hint": f"Set these in environment or create {GDRIVE_ENV_FILE}"
        }

    token_file = config["token_file"]

    # Check if already authenticated
    if not force_reauth:
        creds = _get_credentials()
        if creds and creds.valid:
            return {
                "success": True,
                "authenticated": True,
                "token_file": token_file,
                "message": "Already authenticated. Use force_reauth=True to re-authenticate."
            }

    try:
        redirect_uri = GDRIVE_REDIRECT_URI

        # Create credentials dict for OAuth flow
        client_config = {
            "installed": {
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        }

        flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
        flow.redirect_uri = redirect_uri

        # Always return manual auth instructions so user can complete in browser
        auth_url, _ = flow.authorization_url(
            access_type="offline",
            prompt="consent"
        )

        return {
            "success": True,
            "manual_auth_required": True,
            "auth_url": auth_url,
            "instructions": [
                "1. Open the auth_url in your own browser.",
                "2. Complete Google login and grant access.",
                "3. After approval, Google redirects to http://localhost:8080 (may show connection error - that's OK).",
                "4. Copy the ENTIRE URL from your browser's address bar.",
                "5. Extract the code parameter: look for '?code=XXXXXX' or '&code=XXXXXX'.",
                "6. Run gdrive_complete_auth(authorization_code='PASTE_CODE_HERE')."
            ],
            "message": "Authorization URL generated. Complete login in browser, then call gdrive_complete_auth with the returned code."
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Authentication failed: {str(e)}"
        }


@mcp.tool()
async def gdrive_complete_auth(
    authorization_code: str,
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Complete OAuth authentication using an authorization code.

    **USE THIS** when gdrive_auth_setup() returns an auth_url but can't accept input interactively.

    Workflow:
    1. Call gdrive_auth_setup() - it returns auth_url
    2. Open auth_url in your browser
    3. Complete Google login and authorization
    4. Google redirects to http://localhost:8080/?code=...
    5. Copy the code value from the URL
    6. Call this tool with that code

    Args:
        authorization_code: The authorization code from Google OAuth flow (required)
        ctx: MCP context (optional)

    Returns:
        Dictionary containing:
            - success: bool - Whether authentication completed
            - authenticated: bool - Whether valid credentials now exist
            - token_file: str - Path where tokens were saved
            - message: str - Success message
        OR on error:
            - success: bool - False
            - error: str - Error description
    """
    if not GOOGLE_AVAILABLE:
        return {
            "success": False,
            "error": "Google Drive libraries not installed"
        }

    config = _get_config()
    if not config["client_id"] or not config["client_secret"]:
        return {
            "success": False,
            "error": "Missing OAuth configuration (client_id or client_secret)"
        }

    token_file = config["token_file"]

    try:
        # Create credentials dict for OAuth flow
        client_config = {
            "installed": {
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        }

        flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
        flow.redirect_uri = GDRIVE_REDIRECT_URI

        # Exchange authorization code for credentials
        flow.fetch_token(code=authorization_code)
        creds = flow.credentials

        # Save credentials
        with open(token_file, 'w') as token:
            token.write(creds.to_json())

        return {
            "success": True,
            "authenticated": True,
            "token_file": token_file,
            "message": "Successfully authenticated! Google Drive tokens saved for future use."
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to exchange authorization code: {str(e)}. Make sure the code is valid and hasn't expired."
        }


@mcp.tool()
async def gdrive_list_files(
    folder_id: Optional[str] = None,
    max_results: int = 100,
    order_by: str = "modifiedTime desc",
    query: Optional[str] = None,
    ctx: Context = None
) -> Dict[str, Any]:
    """
    List files and folders in Google Drive.

    **DEFAULT USE CASE**: List recent files from your entire Drive.

    **FOLDER FILTERING**: Provide folder_id to list contents of a specific folder.
    Use "root" for the root folder of My Drive.

    **QUERY SYNTAX**: Use Drive query operators:
    - "name contains 'report'" - File name contains text
    - "mimeType = 'application/pdf'" - Files of specific type
    - "trashed = false" - Not in trash
    - "starred = true" - Starred files
    - "'parent_folder_id' in parents" - Files in specific folder

    **AUTHENTICATION**: Requires gdrive_auth_setup to be run first.

    Args:
        folder_id: ID of folder to list (default: None for all files)
        max_results: Maximum number of files to return (1-1000, default: 100)
        order_by: Sort order (default: "modifiedTime desc")
                  Options: "modifiedTime", "createdTime", "name", "folder"
                  Add " desc" for descending order
        query: Drive query string for filtering (default: none)
        ctx: MCP context (optional)

    Returns:
        Dictionary containing:
            - success: bool - Whether the operation succeeded
            - files: list - List of file objects, each containing:
                - id: str - File ID
                - name: str - File/folder name
                - mime_type: str - MIME type
                - size: str - File size in bytes (folders have no size)
                - created_time: str - When file was created
                - modified_time: str - When file was last modified
                - web_view_link: str - Link to view in browser
                - parents: list - Parent folder IDs
                - trashed: bool - Whether in trash
                - starred: bool - Whether starred
                - shared: bool - Whether shared with others
            - count: int - Number of files returned
            OR on error:
            - success: bool - False
            - error: str - Error message
    """
    try:
        service = _get_service()

        # Build query
        q_parts = []
        if folder_id:
            q_parts.append(f"'{folder_id}' in parents")
        if query:
            q_parts.append(query)
        q_parts.append("trashed = false")

        query_str = " and ".join(q_parts)

        # List files
        results = service.files().list(
            q=query_str,
            pageSize=max(1, min(int(max_results), 1000)),
            orderBy=order_by,
            fields="files(id, name, mimeType, size, createdTime, modifiedTime, webViewLink, parents, trashed, starred, shared)"
        ).execute()

        files = results.get('files', [])
        formatted_files = [_format_file_info(f) for f in files]

        return {
            "success": True,
            "files": formatted_files,
            "count": len(formatted_files)
        }

    except ValueError as e:
        return {"success": False, "error": str(e)}
    except HttpError as e:
        return {"success": False, "error": f"Drive API error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def gdrive_get_file(
    file_id: str,
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Get metadata for a specific file or folder.

    **AUTHENTICATION**: Requires gdrive_auth_setup to be run first.

    Args:
        file_id: ID of the file/folder (required)
                 Use "root" for the root folder of My Drive
        ctx: MCP context (optional)

    Returns:
        Dictionary containing:
            - success: bool - Whether the operation succeeded
            - file: dict - File metadata (same format as gdrive_list_files items)
            OR on error:
            - success: bool - False
            - error: str - Error message
    """
    try:
        service = _get_service()

        file = service.files().get(
            fileId=file_id,
            fields="id, name, mimeType, size, createdTime, modifiedTime, webViewLink, parents, trashed, starred, shared"
        ).execute()

        return {
            "success": True,
            "file": _format_file_info(file)
        }

    except ValueError as e:
        return {"success": False, "error": str(e)}
    except HttpError as e:
        return {"success": False, "error": f"Drive API error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def gdrive_download(
    file_id: str,
    output_path: str,
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Download a file from Google Drive to local filesystem.

    **NOTE**: Cannot download Google Docs formats directly. Use gdrive_export for
    Google Docs, Sheets, Slides, etc.

    **AUTHENTICATION**: Requires gdrive_auth_setup to be run first.

    Args:
        file_id: ID of the file to download (required)
        output_path: Local file path where to save (required)
        ctx: MCP context (optional)

    Returns:
        Dictionary containing:
            - success: bool - Whether the download succeeded
            - file_id: str - ID of downloaded file
            - output_path: str - Where file was saved
            - size: int - File size in bytes
            OR on error:
            - success: bool - False
            - error: str - Error message
    """
    try:
        service = _get_service()

        # Get file metadata first
        file_meta = service.files().get(fileId=file_id, fields="name,mimeType,size").execute()

        # Check if it's a Google Docs format
        if file_meta.get('mimeType', '').startswith('application/vnd.google-apps.'):
            return {
                "success": False,
                "error": "Cannot download Google Docs formats directly. Use gdrive_export instead.",
                "mime_type": file_meta.get('mimeType')
            }

        # Download file
        request = service.files().get_media(fileId=file_id)
        fh = io.FileIO(output_path, 'wb')
        downloader = MediaIoBaseDownload(fh, request)

        done = False
        while not done:
            status, done = downloader.next_chunk()

        fh.close()

        return {
            "success": True,
            "file_id": file_id,
            "output_path": output_path,
            "size": int(file_meta.get('size', 0))
        }

    except ValueError as e:
        return {"success": False, "error": str(e)}
    except HttpError as e:
        return {"success": False, "error": f"Drive API error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def gdrive_upload(
    file_path: str,
    name: Optional[str] = None,
    parent_folder_id: Optional[str] = None,
    mime_type: Optional[str] = None,
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Upload a file to Google Drive.

    **DEFAULT USE CASE**: Upload file to root of My Drive with original filename.

    **AUTHENTICATION**: Requires gdrive_auth_setup to be run first.

    Args:
        file_path: Local path to file to upload (required)
        name: Name for file in Drive (default: original filename)
        parent_folder_id: ID of parent folder (default: root of My Drive)
        mime_type: MIME type of file (default: auto-detected)
        ctx: MCP context (optional)

    Returns:
        Dictionary containing:
            - success: bool - Whether the upload succeeded
            - id: str - ID of uploaded file
            - name: str - Name of file in Drive
            - web_view_link: str - Link to view in browser
            - size: str - File size in bytes
            OR on error:
            - success: bool - False
            - error: str - Error message
    """
    try:
        service = _get_service()

        # Prepare file metadata
        if not name:
            name = os.path.basename(file_path)

        file_metadata = {'name': name}
        if parent_folder_id:
            file_metadata['parents'] = [parent_folder_id]

        # Create media upload
        media = MediaFileUpload(file_path, mimetype=mime_type, resumable=True)

        # Upload file
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, name, webViewLink, size'
        ).execute()

        return {
            "success": True,
            "id": file.get('id'),
            "name": file.get('name'),
            "web_view_link": file.get('webViewLink'),
            "size": file.get('size')
        }

    except ValueError as e:
        return {"success": False, "error": str(e)}
    except HttpError as e:
        return {"success": False, "error": f"Drive API error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def gdrive_create_folder(
    name: str,
    parent_folder_id: Optional[str] = None,
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Create a new folder in Google Drive.

    **AUTHENTICATION**: Requires gdrive_auth_setup to be run first.

    Args:
        name: Name for the new folder (required)
        parent_folder_id: ID of parent folder (default: root of My Drive)
        ctx: MCP context (optional)

    Returns:
        Dictionary containing:
            - success: bool - Whether the folder was created
            - id: str - ID of new folder
            - name: str - Folder name
            - web_view_link: str - Link to view in browser
            OR on error:
            - success: bool - False
            - error: str - Error message
    """
    try:
        service = _get_service()

        file_metadata = {
            'name': name,
            'mimeType': 'application/vnd.google-apps.folder'
        }

        if parent_folder_id:
            file_metadata['parents'] = [parent_folder_id]

        folder = service.files().create(
            body=file_metadata,
            fields='id, name, webViewLink'
        ).execute()

        return {
            "success": True,
            "id": folder.get('id'),
            "name": folder.get('name'),
            "web_view_link": folder.get('webViewLink')
        }

    except ValueError as e:
        return {"success": False, "error": str(e)}
    except HttpError as e:
        return {"success": False, "error": f"Drive API error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def gdrive_move(
    file_id: str,
    new_parent_folder_id: str,
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Move a file or folder to a different parent folder.

    **AUTHENTICATION**: Requires gdrive_auth_setup to be run first.

    Args:
        file_id: ID of file/folder to move (required)
        new_parent_folder_id: ID of destination folder (required)
        ctx: MCP context (optional)

    Returns:
        Dictionary containing:
            - success: bool - Whether the move succeeded
            - id: str - File ID
            - name: str - File name
            - parents: list - New parent folder IDs
            OR on error:
            - success: bool - False
            - error: str - Error message
    """
    try:
        service = _get_service()

        # Get current parents
        file = service.files().get(fileId=file_id, fields='parents, name').execute()
        previous_parents = ",".join(file.get('parents', []))

        # Move file
        file = service.files().update(
            fileId=file_id,
            addParents=new_parent_folder_id,
            removeParents=previous_parents,
            fields='id, name, parents'
        ).execute()

        return {
            "success": True,
            "id": file.get('id'),
            "name": file.get('name'),
            "parents": file.get('parents', [])
        }

    except ValueError as e:
        return {"success": False, "error": str(e)}
    except HttpError as e:
        return {"success": False, "error": f"Drive API error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def gdrive_copy(
    file_id: str,
    new_name: Optional[str] = None,
    parent_folder_id: Optional[str] = None,
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Create a copy of a file.

    **AUTHENTICATION**: Requires gdrive_auth_setup to be run first.

    Args:
        file_id: ID of file to copy (required)
        new_name: Name for the copy (default: "Copy of [original name]")
        parent_folder_id: ID of folder for copy (default: same as original)
        ctx: MCP context (optional)

    Returns:
        Dictionary containing:
            - success: bool - Whether the copy succeeded
            - id: str - ID of new copy
            - name: str - Name of copy
            - web_view_link: str - Link to view in browser
            OR on error:
            - success: bool - False
            - error: str - Error message
    """
    try:
        service = _get_service()

        body = {}
        if new_name:
            body['name'] = new_name
        if parent_folder_id:
            body['parents'] = [parent_folder_id]

        copy = service.files().copy(
            fileId=file_id,
            body=body,
            fields='id, name, webViewLink'
        ).execute()

        return {
            "success": True,
            "id": copy.get('id'),
            "name": copy.get('name'),
            "web_view_link": copy.get('webViewLink')
        }

    except ValueError as e:
        return {"success": False, "error": str(e)}
    except HttpError as e:
        return {"success": False, "error": f"Drive API error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def gdrive_delete(
    file_id: str,
    permanent: bool = False,
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Delete a file or folder.

    **DEFAULT**: Moves to trash (recoverable for 30 days).

    **PERMANENT**: Set permanent=True to permanently delete (cannot be undone).

    **AUTHENTICATION**: Requires gdrive_auth_setup to be run first.

    Args:
        file_id: ID of file/folder to delete (required)
        permanent: If True, permanently delete; if False, move to trash (default: False)
        ctx: MCP context (optional)

    Returns:
        Dictionary containing:
            - success: bool - Whether the delete succeeded
            - file_id: str - ID of deleted file
            - action: str - "trashed" or "permanently_deleted"
            OR on error:
            - success: bool - False
            - error: str - Error message
    """
    try:
        service = _get_service()

        if permanent:
            service.files().delete(fileId=file_id).execute()
            action = "permanently_deleted"
        else:
            service.files().update(
                fileId=file_id,
                body={'trashed': True}
            ).execute()
            action = "trashed"

        return {
            "success": True,
            "file_id": file_id,
            "action": action
        }

    except ValueError as e:
        return {"success": False, "error": str(e)}
    except HttpError as e:
        return {"success": False, "error": f"Drive API error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def gdrive_search(
    query: str,
    max_results: int = 50,
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Search for files using Drive query syntax.

    **QUERY SYNTAX**: Use Drive search operators:
    - "name contains 'report'" - File name contains text
    - "fullText contains 'keyword'" - Search file content
    - "mimeType = 'application/pdf'" - Files of specific type
    - "modifiedTime > '2025-01-01T00:00:00'" - Modified after date
    - "trashed = false" - Not in trash
    - "'parent_id' in parents" - In specific folder

    **COMMON MIME TYPES**:
    - PDF: "application/pdf"
    - Word: "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    - Excel: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    - Folder: "application/vnd.google-apps.folder"

    **AUTHENTICATION**: Requires gdrive_auth_setup to be run first.

    Args:
        query: Drive query string (required)
        max_results: Maximum number of results (1-1000, default: 50)
        ctx: MCP context (optional)

    Returns:
        Dictionary containing:
            - success: bool - Whether the search succeeded
            - files: list - List of matching files (same format as gdrive_list_files)
            - count: int - Number of files found
            - query: str - The query used
            OR on error:
            - success: bool - False
            - error: str - Error message
    """
    return await gdrive_list_files(
        max_results=max_results,
        query=query,
        ctx=ctx
    )


@mcp.tool()
async def gdrive_share(
    file_id: str,
    email: str,
    role: str = "reader",
    send_notification: bool = True,
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Share a file or folder with a user.

    **ROLES**:
    - "reader" - Can view only (default)
    - "writer" - Can edit
    - "commenter" - Can comment but not edit
    - "owner" - Transfer ownership (use with caution)

    **AUTHENTICATION**: Requires gdrive_auth_setup to be run first.

    Args:
        file_id: ID of file/folder to share (required)
        email: Email address of user to share with (required)
        role: Permission role (default: "reader")
        send_notification: Send email notification to user (default: True)
        ctx: MCP context (optional)

    Returns:
        Dictionary containing:
            - success: bool - Whether sharing succeeded
            - permission_id: str - ID of created permission
            - email: str - Email address shared with
            - role: str - Permission role granted
            OR on error:
            - success: bool - False
            - error: str - Error message
    """
    try:
        service = _get_service()

        permission = {
            'type': 'user',
            'role': role,
            'emailAddress': email
        }

        result = service.permissions().create(
            fileId=file_id,
            body=permission,
            sendNotificationEmail=send_notification,
            fields='id'
        ).execute()

        return {
            "success": True,
            "permission_id": result.get('id'),
            "email": email,
            "role": role
        }

    except ValueError as e:
        return {"success": False, "error": str(e)}
    except HttpError as e:
        return {"success": False, "error": f"Drive API error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def gdrive_get_permissions(
    file_id: str,
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Get sharing permissions for a file or folder.

    **AUTHENTICATION**: Requires gdrive_auth_setup to be run first.

    Args:
        file_id: ID of file/folder (required)
        ctx: MCP context (optional)

    Returns:
        Dictionary containing:
            - success: bool - Whether the operation succeeded
            - permissions: list - List of permission objects, each containing:
                - id: str - Permission ID
                - type: str - "user", "group", "domain", or "anyone"
                - role: str - "owner", "writer", "commenter", or "reader"
                - email_address: str - Email (for user/group types)
                - display_name: str - Display name
            - count: int - Number of permissions
            OR on error:
            - success: bool - False
            - error: str - Error message
    """
    try:
        service = _get_service()

        result = service.permissions().list(
            fileId=file_id,
            fields='permissions(id, type, role, emailAddress, displayName)'
        ).execute()

        permissions = result.get('permissions', [])

        formatted_permissions = []
        for perm in permissions:
            formatted_permissions.append({
                "id": perm.get('id'),
                "type": perm.get('type'),
                "role": perm.get('role'),
                "email_address": perm.get('emailAddress'),
                "display_name": perm.get('displayName')
            })

        return {
            "success": True,
            "permissions": formatted_permissions,
            "count": len(formatted_permissions)
        }

    except ValueError as e:
        return {"success": False, "error": str(e)}
    except HttpError as e:
        return {"success": False, "error": f"Drive API error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def gdrive_export(
    file_id: str,
    output_path: str,
    export_format: str = "pdf",
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Export a Google Docs format file to another format.

    Use this for Google Docs, Sheets, Slides, etc. For regular files, use gdrive_download.

    **EXPORT FORMATS**:
    - Google Docs → "pdf", "docx", "odt", "txt", "html", "epub"
    - Google Sheets → "pdf", "xlsx", "ods", "csv"
    - Google Slides → "pdf", "pptx"

    **AUTHENTICATION**: Requires gdrive_auth_setup to be run first.

    Args:
        file_id: ID of Google Docs file to export (required)
        output_path: Local path where to save exported file (required)
        export_format: Format to export as (default: "pdf")
        ctx: MCP context (optional)

    Returns:
        Dictionary containing:
            - success: bool - Whether the export succeeded
            - file_id: str - ID of exported file
            - output_path: str - Where file was saved
            - format: str - Export format used
            OR on error:
            - success: bool - False
            - error: str - Error message
    """
    try:
        service = _get_service()

        # Get MIME type for export format
        mime_type = EXPORT_MIMETYPES.get(export_format.lower())
        if not mime_type:
            return {
                "success": False,
                "error": f"Unsupported export format: {export_format}",
                "supported_formats": list(EXPORT_MIMETYPES.keys())
            }

        # Export file
        request = service.files().export_media(
            fileId=file_id,
            mimeType=mime_type
        )

        fh = io.FileIO(output_path, 'wb')
        downloader = MediaIoBaseDownload(fh, request)

        done = False
        while not done:
            status, done = downloader.next_chunk()

        fh.close()

        return {
            "success": True,
            "file_id": file_id,
            "output_path": output_path,
            "format": export_format
        }

    except ValueError as e:
        return {"success": False, "error": str(e)}
    except HttpError as e:
        return {"success": False, "error": f"Drive API error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    mcp.run(transport="stdio")
