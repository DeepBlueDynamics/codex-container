#!/usr/bin/env python3
"""
Google Calendar MCP Bridge
==========================

Exposes Google Calendar API to AI assistants via MCP, enabling calendar
and event management through natural language.

**FIRST TIME SETUP**: Call `gcal_setup_guide()` for step-by-step instructions!

Available Tools:
  Setup & Configuration:
    - gcal_setup_guide: **START HERE** - Complete setup walkthrough with instructions
    - gcal_status: Quick check of authentication and configuration status
    - gcal_auth_setup: Run OAuth 2.0 authentication flow (console/manual mode)
    - gcal_complete_auth: Complete authentication with authorization code (for containers)

  Calendar Operations:
    - gcal_list_calendars: List all accessible calendars
    - gcal_list_events: List events from a calendar with filtering
    - gcal_create_event: Create a new calendar event
    - gcal_update_event: Update an existing event
    - gcal_delete_event: Delete an event
    - gcal_freebusy: Check free/busy status across calendars

Configuration (one of these methods):
  Option 1 - Environment variables:
    export GOOGLE_CALENDAR_CLIENT_ID='your_client_id'
    export GOOGLE_CALENDAR_CLIENT_SECRET='your_client_secret'

  Option 2 - .gcal.env file (in workspace root):
    GOOGLE_CALENDAR_CLIENT_ID=your_client_id
    GOOGLE_CALENDAR_CLIENT_SECRET=your_client_secret

  Optional:
    GOOGLE_CALENDAR_TOKEN_FILE=.gcal-tokens.json

Quick Start:
  1. Call gcal_setup_guide() to get detailed setup instructions
  2. Follow the steps to create OAuth credentials
  3. Authenticate (two methods):
     Method A (interactive): gcal_auth_setup() - prints URL, prompts for code
     Method B (container-friendly): gcal_auth_setup() → copy auth_url →
                                     open in browser → get code →
                                     gcal_complete_auth(code="...")
  4. Start using calendar tools! Try gcal_list_calendars()

Security Notes:
  - OAuth 2.0 Desktop App credentials required
  - First use requires browser-based Google login
  - Access tokens refresh automatically
  - All credentials stored locally, never transmitted to external servers
  - Tokens stored in .gcal-tokens.json (add to .gitignore)

Example Usage:
  # First time setup
  guide = gcal_setup_guide()
  # ... follow instructions to create credentials ...
  gcal_auth_setup()  # Opens browser for login

  # Daily use
  calendars = gcal_list_calendars()
  events = gcal_list_events(max_results=10)

  gcal_create_event(
      summary="Team Meeting",
      start_time="2025-01-15T14:00:00",
      end_time="2025-01-15T15:00:00",
      attendees=["alice@example.com", "bob@example.com"]
  )
"""

import os
import json
import pickle
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from pathlib import Path

from mcp.server.fastmcp import FastMCP, Context

# Google auth imports (these need to be installed)
try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False


mcp = FastMCP("google-calendar")

# OAuth 2.0 scopes - includes all Google service scopes since same OAuth client is shared
SCOPES = [
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.compose',
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/gmail.labels',
    'https://www.googleapis.com/auth/drive',
    'openid',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile'
]

# Config
GCAL_ENV_FILE = os.path.join(os.getcwd(), ".gcal.env")
DEFAULT_TOKEN_FILE = os.path.join(os.getcwd(), ".gcal-tokens.json")
GCAL_REDIRECT_URI = "http://localhost:8080"


def _get_config() -> Dict[str, Optional[str]]:
    """Get configuration from environment or .gcal.env file."""
    config = {
        "client_id": os.environ.get("GOOGLE_CALENDAR_CLIENT_ID"),
        "client_secret": os.environ.get("GOOGLE_CALENDAR_CLIENT_SECRET"),
        "token_file": os.environ.get("GOOGLE_CALENDAR_TOKEN_FILE", DEFAULT_TOKEN_FILE),
    }

    # Try loading from .gcal.env if not in environment
    if not config["client_id"] or not config["client_secret"]:
        try:
            if os.path.exists(GCAL_ENV_FILE):
                with open(GCAL_ENV_FILE, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            key, value = line.split("=", 1)
                            key = key.strip()
                            value = value.strip().strip('"').strip("'")
                            if key == "GOOGLE_CALENDAR_CLIENT_ID":
                                config["client_id"] = value
                            elif key == "GOOGLE_CALENDAR_CLIENT_SECRET":
                                config["client_secret"] = value
                            elif key == "GOOGLE_CALENDAR_TOKEN_FILE":
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
    """Get authenticated Calendar service or raise error."""
    if not GOOGLE_AVAILABLE:
        raise ImportError(
            "Google Calendar libraries not installed. "
            "Run: pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client"
        )

    creds = _get_credentials()
    if not creds:
        raise ValueError(
            "Not authenticated. Run gcal_auth_setup first to authenticate with Google."
        )

    return build('calendar', 'v3', credentials=creds)


@mcp.tool()
async def gcal_setup_guide(ctx: Context = None) -> Dict[str, Any]:
    """
    Get step-by-step instructions for setting up Google Calendar integration.

    **CALL THIS FIRST** if you've never used Google Calendar tools before.
    This provides a complete setup guide with links and examples.

    Returns:
        Dictionary containing:
            - success: bool - Always True
            - setup_complete: bool - Whether setup is already done
            - current_status: dict - Current configuration state
            - steps: list - Ordered setup steps with instructions
            - next_action: str - What to do next

    Example:
        ```python
        guide = await gcal_setup_guide()
        print(guide["steps"])  # Follow the instructions
        ```
    """
    config = _get_config()
    creds = _get_credentials() if GOOGLE_AVAILABLE else None

    status = {
        "libs_installed": GOOGLE_AVAILABLE,
        "client_id_set": bool(config["client_id"]),
        "client_secret_set": bool(config["client_secret"]),
        "authenticated": creds is not None and creds.valid if creds else False,
    }

    setup_complete = all(status.values())

    steps = [
        {
            "step": 1,
            "title": "Install Python libraries (if needed)",
            "done": status["libs_installed"],
            "command": "pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client",
            "description": "Install required Google API client libraries"
        },
        {
            "step": 2,
            "title": "Create OAuth 2.0 credentials in Google Cloud Console",
            "done": False,  # We can't auto-detect this
            "instructions": [
                "1. Go to https://console.cloud.google.com/",
                "2. Create a new project or select existing one",
                "3. Go to 'APIs & Services' → 'Library'",
                "4. Search for 'Google Calendar API' and click 'Enable'",
                "5. Go to 'APIs & Services' → 'Credentials'",
                "6. Click 'Create Credentials' → 'OAuth client ID'",
                "7. If prompted, configure consent screen (External/Internal, add app name)",
                "8. Application type: 'Desktop app'",
                "9. Name it something like 'Codex Calendar Integration'",
                "10. IMPORTANT: Ensure 'http://localhost:8080/' is in Authorized redirect URIs",
                "11. Click 'Create' and note the Client ID and Client Secret"
            ],
            "link": "https://console.cloud.google.com/apis/credentials",
            "note": "Desktop app type should include http://localhost:8080/ by default, but verify it's present"
        },
        {
            "step": 3,
            "title": "Configure credentials in environment",
            "done": status["client_id_set"] and status["client_secret_set"],
            "options": [
                {
                    "method": "Environment variables",
                    "commands": [
                        "export GOOGLE_CALENDAR_CLIENT_ID='your_client_id_here'",
                        "export GOOGLE_CALENDAR_CLIENT_SECRET='your_client_secret_here'"
                    ]
                },
                {
                    "method": "Create .gcal.env file",
                    "file_path": GCAL_ENV_FILE,
                    "content_example": "GOOGLE_CALENDAR_CLIENT_ID=your_client_id_here\nGOOGLE_CALENDAR_CLIENT_SECRET=your_client_secret_here"
                }
            ],
            "description": "Store your OAuth credentials securely"
        },
        {
            "step": 4,
            "title": "Run authentication flow",
            "done": status["authenticated"],
            "command": "await gcal_auth_setup()",
            "description": "Opens browser for Google login. Tokens saved to .gcal-tokens.json"
        }
    ]

    # Determine next action
    if setup_complete:
        next_action = "Setup complete! Use gcal_list_calendars() to get started."
    elif not status["libs_installed"]:
        next_action = f"Install libraries: pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client"
    elif not status["client_id_set"] or not status["client_secret_set"]:
        next_action = "Create OAuth credentials in Google Cloud Console and configure them (see step 2-3)"
    elif not status["authenticated"]:
        next_action = "Run: await gcal_auth_setup() to authenticate"
    else:
        next_action = "Ready to use!"

    return {
        "success": True,
        "setup_complete": setup_complete,
        "current_status": status,
        "steps": steps,
        "next_action": next_action,
        "google_cloud_console": "https://console.cloud.google.com/",
        "env_file_location": GCAL_ENV_FILE
    }


@mcp.tool()
async def gcal_status(ctx: Context = None) -> Dict[str, Any]:
    """
    Check Google Calendar authentication and configuration status.

    **QUICK CHECK**: Use this to verify setup before calendar operations.
    For detailed setup instructions, call gcal_setup_guide() first.

    Returns:
        Dictionary containing:
            - success: bool - Always True
            - google_libs_installed: bool - Whether required libraries are available
            - client_id_present: bool - Whether OAuth client ID is configured
            - client_secret_present: bool - Whether OAuth client secret is configured
            - token_file: str - Path to token storage file
            - authenticated: bool - Whether valid tokens exist
            - credentials_valid: bool - Whether credentials are currently valid
            - ready_to_use: bool - Whether all setup is complete
            - next_step: str - What to do if not ready

    Example:
        ```python
        status = await gcal_status()
        if not status["ready_to_use"]:
            print(status["next_step"])
            guide = await gcal_setup_guide()
        ```
    """
    config = _get_config()
    creds = _get_credentials() if GOOGLE_AVAILABLE else None

    libs_ok = GOOGLE_AVAILABLE
    client_id_ok = bool(config["client_id"])
    client_secret_ok = bool(config["client_secret"])
    auth_ok = creds is not None and (creds.valid if creds else False)

    ready = libs_ok and client_id_ok and client_secret_ok and auth_ok

    # Determine next step
    if not libs_ok:
        next_step = "Install libraries: pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client"
    elif not client_id_ok or not client_secret_ok:
        next_step = "Configure OAuth credentials. Run: await gcal_setup_guide() for instructions"
    elif not auth_ok:
        next_step = "Authenticate with Google. Run: await gcal_auth_setup()"
    else:
        next_step = "Ready! Try: await gcal_list_calendars()"

    return {
        "success": True,
        "google_libs_installed": libs_ok,
        "client_id_present": client_id_ok,
        "client_secret_present": client_secret_ok,
        "token_file": config["token_file"],
        "authenticated": auth_ok,
        "credentials_valid": creds.valid if creds else False,
        "ready_to_use": ready,
        "next_step": next_step
    }


@mcp.tool()
async def gcal_auth_setup(
    force_reauth: bool = False,
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Initialize OAuth 2.0 authentication flow for Google Calendar.

    **FIRST TIME SETUP**: This will open a browser window for you to log in to Google
    and grant calendar access. After authentication, tokens are saved locally for future use.

    **PREREQUISITES**:
    1. Create OAuth 2.0 credentials in Google Cloud Console (Desktop App type)
    2. Enable Google Calendar API
    3. Set GOOGLE_CALENDAR_CLIENT_ID and GOOGLE_CALENDAR_CLIENT_SECRET in environment
       or save to .gcal.env file in this format:
       ```
       GOOGLE_CALENDAR_CLIENT_ID=your_client_id
       GOOGLE_CALENDAR_CLIENT_SECRET=your_client_secret
       ```

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
            "error": "Google Calendar libraries not installed",
            "install_command": "pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client"
        }

    config = _get_config()

    # Check for required config
    missing = []
    if not config["client_id"]:
        missing.append("GOOGLE_CALENDAR_CLIENT_ID")
    if not config["client_secret"]:
        missing.append("GOOGLE_CALENDAR_CLIENT_SECRET")

    if missing:
        return {
            "success": False,
            "error": "Missing OAuth configuration",
            "missing_config": missing,
            "hint": f"Set these in environment or create {GCAL_ENV_FILE}"
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
        redirect_uri = GCAL_REDIRECT_URI

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
                "6. Run gcal_complete_auth(authorization_code='PASTE_CODE_HERE')."
            ],
            "message": "Authorization URL generated. Complete login in browser, then call gcal_complete_auth with the returned code."
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Authentication failed: {str(e)}"
        }


@mcp.tool()
async def gcal_complete_auth(
    authorization_code: str,
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Complete OAuth authentication using an authorization code.

    **USE THIS** when gcal_auth_setup() returns an auth_url but can't accept input interactively.

    Workflow:
    1. Call gcal_auth_setup() - it returns auth_url
    2. Open auth_url in your browser
    3. Complete Google login and authorization
    4. Google displays authorization code
    5. Call this tool with that code

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
            - error: str - Error message

    Example:
        ```python
        # Step 1: Start auth and get URL
        result = await gcal_auth_setup()
        auth_url = result["auth_url"]

        # Step 2: User opens URL in browser, gets code like "4/0AbC...XYZ"

        # Step 3: Complete auth with code
        await gcal_complete_auth(authorization_code="4/0AbC...XYZ")
        ```
    """
    if not GOOGLE_AVAILABLE:
        return {
            "success": False,
            "error": "Google Calendar libraries not installed"
        }

    config = _get_config()

    # Check for required config
    if not config["client_id"] or not config["client_secret"]:
        return {
            "success": False,
            "error": "OAuth credentials not configured. Run gcal_setup_guide() first."
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
        flow.redirect_uri = GCAL_REDIRECT_URI

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
            "message": "Successfully authenticated! Tokens saved for future use."
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to exchange authorization code: {str(e)}. Make sure the code is valid and hasn't expired."
        }


@mcp.tool()
async def gcal_list_calendars(ctx: Context = None) -> Dict[str, Any]:
    """
    List all calendars accessible to the authenticated user.

    Returns both owned calendars and calendars shared with the user.
    Each calendar includes its ID, which is needed for other operations.

    **AUTHENTICATION**: Requires gcal_auth_setup to be run first.

    Args:
        ctx: MCP context (optional)

    Returns:
        Dictionary containing:
            - success: bool - Whether the operation succeeded
            - calendars: list - List of calendar objects, each containing:
                - id: str - Calendar ID (use this for other operations)
                - summary: str - Calendar name/title
                - primary: bool - Whether this is the user's primary calendar
                - access_role: str - User's access level (owner, writer, reader)
                - time_zone: str - Calendar timezone
                - description: str - Calendar description (optional)
            - count: int - Number of calendars found
            OR on error:
            - success: bool - False
            - error: str - Error message
    """
    try:
        service = _get_service()

        calendar_list = service.calendarList().list().execute()
        calendars = calendar_list.get('items', [])

        result_calendars = []
        for cal in calendars:
            result_calendars.append({
                "id": cal.get("id"),
                "summary": cal.get("summary"),
                "primary": cal.get("primary", False),
                "access_role": cal.get("accessRole"),
                "time_zone": cal.get("timeZone"),
                "description": cal.get("description", ""),
            })

        return {
            "success": True,
            "calendars": result_calendars,
            "count": len(result_calendars)
        }

    except ValueError as e:
        return {"success": False, "error": str(e)}
    except HttpError as e:
        return {"success": False, "error": f"Google API error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def gcal_list_events(
    calendar_id: str = "primary",
    max_results: int = 10,
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
    query: Optional[str] = None,
    ctx: Context = None
) -> Dict[str, Any]:
    """
    List events from a calendar with optional filtering.

    **DEFAULT USE CASE**: Get upcoming events from your primary calendar.

    **TIME FILTERING**: Use ISO 8601 format for time_min/time_max:
    - "2025-01-15T00:00:00Z" (UTC)
    - "2025-01-15T09:00:00-08:00" (with timezone)
    If not specified, defaults to now for time_min.

    **AUTHENTICATION**: Requires gcal_auth_setup to be run first.

    Args:
        calendar_id: Calendar ID to list events from (default: "primary" for user's main calendar)
        max_results: Maximum number of events to return (1-2500, default: 10)
        time_min: Lower bound for event start time in ISO 8601 format (default: now)
        time_max: Upper bound for event start time in ISO 8601 format (default: none)
        query: Text search query to filter events (default: none)
        ctx: MCP context (optional)

    Returns:
        Dictionary containing:
            - success: bool - Whether the operation succeeded
            - events: list - List of event objects, each containing:
                - id: str - Event ID (use for updates/deletes)
                - summary: str - Event title
                - start: dict - Start time (dateTime or date)
                - end: dict - End time (dateTime or date)
                - description: str - Event description (optional)
                - location: str - Event location (optional)
                - attendees: list - List of attendee emails (optional)
                - html_link: str - Link to view event in Google Calendar
                - status: str - Event status (confirmed, tentative, cancelled)
                - created: str - When event was created
                - updated: str - When event was last modified
            - count: int - Number of events returned
            - time_min: str - Start of time range queried
            - time_max: str - End of time range queried (if specified)
            OR on error:
            - success: bool - False
            - error: str - Error message
    """
    try:
        service = _get_service()

        # Default time_min to now if not specified
        if not time_min:
            time_min = datetime.utcnow().isoformat() + 'Z'

        # Build query parameters
        params = {
            "calendarId": calendar_id,
            "timeMin": time_min,
            "maxResults": max(1, min(int(max_results), 2500)),
            "singleEvents": True,
            "orderBy": "startTime",
        }

        if time_max:
            params["timeMax"] = time_max
        if query:
            params["q"] = query

        events_result = service.events().list(**params).execute()
        events = events_result.get('items', [])

        result_events = []
        for event in events:
            result_events.append({
                "id": event.get("id"),
                "summary": event.get("summary", "(No title)"),
                "start": event.get("start"),
                "end": event.get("end"),
                "description": event.get("description", ""),
                "location": event.get("location", ""),
                "attendees": [a.get("email") for a in event.get("attendees", [])],
                "html_link": event.get("htmlLink"),
                "status": event.get("status"),
                "created": event.get("created"),
                "updated": event.get("updated"),
            })

        result = {
            "success": True,
            "events": result_events,
            "count": len(result_events),
            "time_min": time_min,
        }

        if time_max:
            result["time_max"] = time_max

        return result

    except ValueError as e:
        return {"success": False, "error": str(e)}
    except HttpError as e:
        return {"success": False, "error": f"Google API error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def gcal_create_event(
    summary: str,
    start_time: str,
    end_time: str,
    calendar_id: str = "primary",
    description: Optional[str] = None,
    location: Optional[str] = None,
    attendees: Optional[List[str]] = None,
    time_zone: str = "UTC",
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Create a new calendar event.

    **TIME FORMAT**: Use ISO 8601 format for start_time and end_time:
    - DateTime: "2025-01-15T14:00:00" (uses time_zone parameter)
    - All-day: "2025-01-15" (date only)

    **ATTENDEES**: Provide a list of email addresses. Invitations will be sent automatically.

    **AUTHENTICATION**: Requires gcal_auth_setup to be run first.

    Args:
        summary: Event title/name (required)
        start_time: Event start in ISO 8601 format (required)
        end_time: Event end in ISO 8601 format (required)
        calendar_id: Calendar to create event in (default: "primary")
        description: Event description/notes (default: none)
        location: Event location (default: none)
        attendees: List of attendee email addresses (default: none)
        time_zone: Timezone for the event (default: "UTC")
                   Examples: "America/Los_Angeles", "Europe/London", "Asia/Tokyo"
        ctx: MCP context (optional)

    Returns:
        Dictionary containing:
            - success: bool - Whether the event was created
            - event_id: str - ID of the created event
            - html_link: str - Link to view event in Google Calendar
            - summary: str - Event title
            - start: dict - Start time
            - end: dict - End time
            - created: str - When event was created
            OR on error:
            - success: bool - False
            - error: str - Error message
    """
    try:
        service = _get_service()

        # Build event object
        event = {
            "summary": summary,
        }

        # Handle start/end times (detect if all-day by checking for time component)
        if "T" in start_time:
            event["start"] = {"dateTime": start_time, "timeZone": time_zone}
        else:
            event["start"] = {"date": start_time}

        if "T" in end_time:
            event["end"] = {"dateTime": end_time, "timeZone": time_zone}
        else:
            event["end"] = {"date": end_time}

        # Optional fields
        if description:
            event["description"] = description
        if location:
            event["location"] = location
        if attendees:
            event["attendees"] = [{"email": email} for email in attendees]

        # Create event
        created_event = service.events().insert(
            calendarId=calendar_id,
            body=event
        ).execute()

        return {
            "success": True,
            "event_id": created_event.get("id"),
            "html_link": created_event.get("htmlLink"),
            "summary": created_event.get("summary"),
            "start": created_event.get("start"),
            "end": created_event.get("end"),
            "created": created_event.get("created"),
        }

    except ValueError as e:
        return {"success": False, "error": str(e)}
    except HttpError as e:
        return {"success": False, "error": f"Google API error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def gcal_update_event(
    event_id: str,
    calendar_id: str = "primary",
    summary: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    description: Optional[str] = None,
    location: Optional[str] = None,
    attendees: Optional[List[str]] = None,
    time_zone: str = "UTC",
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Update an existing calendar event.

    Only specified fields will be updated. Unspecified fields remain unchanged.

    **TIME FORMAT**: Use ISO 8601 format for start_time and end_time:
    - DateTime: "2025-01-15T14:00:00" (uses time_zone parameter)
    - All-day: "2025-01-15" (date only)

    **AUTHENTICATION**: Requires gcal_auth_setup to be run first.

    Args:
        event_id: ID of the event to update (required)
        calendar_id: Calendar containing the event (default: "primary")
        summary: New event title (default: unchanged)
        start_time: New start time in ISO 8601 format (default: unchanged)
        end_time: New end time in ISO 8601 format (default: unchanged)
        description: New description (default: unchanged)
        location: New location (default: unchanged)
        attendees: New list of attendee emails (default: unchanged)
        time_zone: Timezone for new times (default: "UTC")
        ctx: MCP context (optional)

    Returns:
        Dictionary containing:
            - success: bool - Whether the event was updated
            - event_id: str - ID of the updated event
            - html_link: str - Link to view event in Google Calendar
            - summary: str - Updated event title
            - start: dict - Updated start time
            - end: dict - Updated end time
            - updated: str - When event was last modified
            OR on error:
            - success: bool - False
            - error: str - Error message
    """
    try:
        service = _get_service()

        # Get existing event
        event = service.events().get(
            calendarId=calendar_id,
            eventId=event_id
        ).execute()

        # Update fields that were provided
        if summary is not None:
            event["summary"] = summary

        if start_time is not None:
            if "T" in start_time:
                event["start"] = {"dateTime": start_time, "timeZone": time_zone}
            else:
                event["start"] = {"date": start_time}

        if end_time is not None:
            if "T" in end_time:
                event["end"] = {"dateTime": end_time, "timeZone": time_zone}
            else:
                event["end"] = {"date": end_time}

        if description is not None:
            event["description"] = description

        if location is not None:
            event["location"] = location

        if attendees is not None:
            event["attendees"] = [{"email": email} for email in attendees]

        # Update event
        updated_event = service.events().update(
            calendarId=calendar_id,
            eventId=event_id,
            body=event
        ).execute()

        return {
            "success": True,
            "event_id": updated_event.get("id"),
            "html_link": updated_event.get("htmlLink"),
            "summary": updated_event.get("summary"),
            "start": updated_event.get("start"),
            "end": updated_event.get("end"),
            "updated": updated_event.get("updated"),
        }

    except ValueError as e:
        return {"success": False, "error": str(e)}
    except HttpError as e:
        return {"success": False, "error": f"Google API error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def gcal_delete_event(
    event_id: str,
    calendar_id: str = "primary",
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Delete a calendar event.

    **WARNING**: This permanently deletes the event. This action cannot be undone.

    **AUTHENTICATION**: Requires gcal_auth_setup to be run first.

    Args:
        event_id: ID of the event to delete (required)
        calendar_id: Calendar containing the event (default: "primary")
        ctx: MCP context (optional)

    Returns:
        Dictionary containing:
            - success: bool - Whether the event was deleted
            - event_id: str - ID of the deleted event
            - message: str - Confirmation message
            OR on error:
            - success: bool - False
            - error: str - Error message
    """
    try:
        service = _get_service()

        service.events().delete(
            calendarId=calendar_id,
            eventId=event_id
        ).execute()

        return {
            "success": True,
            "event_id": event_id,
            "message": "Event deleted successfully"
        }

    except ValueError as e:
        return {"success": False, "error": str(e)}
    except HttpError as e:
        return {"success": False, "error": f"Google API error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def gcal_freebusy(
    calendar_ids: List[str],
    time_min: str,
    time_max: str,
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Check free/busy status for one or more calendars within a time range.

    Useful for finding available meeting times or checking conflicts across multiple calendars.

    **TIME FORMAT**: Use ISO 8601 format for time boundaries:
    - "2025-01-15T09:00:00Z" (UTC)
    - "2025-01-15T09:00:00-08:00" (with timezone)

    **AUTHENTICATION**: Requires gcal_auth_setup to be run first.

    Args:
        calendar_ids: List of calendar IDs to check (use ["primary"] for main calendar)
        time_min: Start of time range in ISO 8601 format (required)
        time_max: End of time range in ISO 8601 format (required)
        ctx: MCP context (optional)

    Returns:
        Dictionary containing:
            - success: bool - Whether the query succeeded
            - calendars: dict - Free/busy info keyed by calendar ID, each containing:
                - busy: list - List of busy time blocks, each with:
                    - start: str - Busy period start time
                    - end: str - Busy period end time
                - errors: list - Any errors for this calendar
            - time_min: str - Start of queried time range
            - time_max: str - End of queried time range
            OR on error:
            - success: bool - False
            - error: str - Error message
    """
    try:
        service = _get_service()

        body = {
            "timeMin": time_min,
            "timeMax": time_max,
            "items": [{"id": cal_id} for cal_id in calendar_ids]
        }

        freebusy_result = service.freebusy().query(body=body).execute()

        calendars = {}
        for cal_id, cal_data in freebusy_result.get("calendars", {}).items():
            calendars[cal_id] = {
                "busy": cal_data.get("busy", []),
                "errors": cal_data.get("errors", [])
            }

        return {
            "success": True,
            "calendars": calendars,
            "time_min": time_min,
            "time_max": time_max
        }

    except ValueError as e:
        return {"success": False, "error": str(e)}
    except HttpError as e:
        return {"success": False, "error": f"Google API error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    mcp.run(transport="stdio")
