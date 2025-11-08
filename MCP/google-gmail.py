#!/usr/bin/env python3
"""
Google Gmail MCP Bridge
=======================

Exposes Gmail API to AI assistants via MCP, enabling email management
through natural language.

Tools:
  - gmail_status: Check authentication and configuration status
  - gmail_auth_setup: Initialize OAuth 2.0 authentication flow
  - gmail_list_messages: List emails with filtering
  - gmail_get_message: Get full email content
  - gmail_send: Send a new email
  - gmail_reply: Reply to an email
  - gmail_search: Search emails by query
  - gmail_create_draft: Create a draft email
  - gmail_delete: Move email to trash
  - gmail_mark_read: Mark email as read
  - gmail_mark_unread: Mark email as unread
  - gmail_add_label: Add label to email
  - gmail_remove_label: Remove label from email
  - gmail_list_labels: List all available labels

Env/config:
  - GOOGLE_GMAIL_CLIENT_ID     (required for OAuth)
  - GOOGLE_GMAIL_CLIENT_SECRET (required for OAuth)
  - GOOGLE_GMAIL_TOKEN_FILE    (default: .gmail-tokens.json)
  - .gmail.env file in repo root with credentials

Setup:
  1. Create OAuth 2.0 Desktop App credentials in Google Cloud Console
  2. Enable Gmail API
  3. Save client_id and client_secret to .gmail.env or environment
  4. Run gmail_auth_setup to authenticate (opens browser)
  5. Tokens are saved locally for future use

Notes:
  - First use requires browser-based OAuth consent
  - Tokens refresh automatically
  - All credentials stay local, never transmitted to external servers
  - Uses the same OAuth client as Google Calendar (can share credentials)
"""

import os
import json
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
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
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False


mcp = FastMCP("google-gmail")

# OAuth 2.0 scopes - includes all Google service scopes since same OAuth client is shared
SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.compose',
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/gmail.labels',
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/drive',
    'openid',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile'
]

# Config
GMAIL_ENV_FILE = os.path.join(os.getcwd(), ".gmail.env")
DEFAULT_TOKEN_FILE = os.path.join(os.getcwd(), ".gmail-tokens.json")
GMAIL_REDIRECT_URI = "http://localhost:8080"


def _get_config() -> Dict[str, Optional[str]]:
    """Get configuration from environment or .gmail.env file."""
    config = {
        "client_id": os.environ.get("GOOGLE_GMAIL_CLIENT_ID"),
        "client_secret": os.environ.get("GOOGLE_GMAIL_CLIENT_SECRET"),
        "token_file": os.environ.get("GOOGLE_GMAIL_TOKEN_FILE", DEFAULT_TOKEN_FILE),
    }

    # Try loading from .gmail.env if not in environment
    if not config["client_id"] or not config["client_secret"]:
        try:
            if os.path.exists(GMAIL_ENV_FILE):
                with open(GMAIL_ENV_FILE, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            key, value = line.split("=", 1)
                            key = key.strip()
                            value = value.strip().strip('"').strip("'")
                            if key == "GOOGLE_GMAIL_CLIENT_ID":
                                config["client_id"] = value
                            elif key == "GOOGLE_GMAIL_CLIENT_SECRET":
                                config["client_secret"] = value
                            elif key == "GOOGLE_GMAIL_TOKEN_FILE":
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
    """Get authenticated Gmail service or raise error."""
    if not GOOGLE_AVAILABLE:
        raise ImportError(
            "Google Gmail libraries not installed. "
            "Run: pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client"
        )

    creds = _get_credentials()
    if not creds:
        raise ValueError(
            "Not authenticated. Run gmail_auth_setup first to authenticate with Google."
        )

    return build('gmail', 'v1', credentials=creds)


def _parse_headers(headers: List[Dict[str, str]]) -> Dict[str, str]:
    """Parse message headers into a dictionary."""
    result = {}
    for header in headers:
        name = header.get("name", "").lower()
        value = header.get("value", "")
        result[name] = value
    return result


def _decode_message_part(part: Dict[str, Any]) -> str:
    """Decode a message part body."""
    data = part.get("body", {}).get("data", "")
    if data:
        return base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
    return ""


def _extract_message_body(payload: Dict[str, Any]) -> Dict[str, str]:
    """Extract text and HTML body from message payload."""
    result = {"text": "", "html": ""}

    mime_type = payload.get("mimeType", "")

    if mime_type == "text/plain":
        result["text"] = _decode_message_part(payload)
    elif mime_type == "text/html":
        result["html"] = _decode_message_part(payload)
    elif mime_type.startswith("multipart/"):
        parts = payload.get("parts", [])
        for part in parts:
            part_mime = part.get("mimeType", "")
            if part_mime == "text/plain":
                result["text"] = _decode_message_part(part)
            elif part_mime == "text/html":
                result["html"] = _decode_message_part(part)
            elif part_mime.startswith("multipart/"):
                # Recursive for nested multipart
                nested = _extract_message_body(part)
                if not result["text"] and nested["text"]:
                    result["text"] = nested["text"]
                if not result["html"] and nested["html"]:
                    result["html"] = nested["html"]

    return result


@mcp.tool()
async def gmail_status(ctx: Context = None) -> Dict[str, Any]:
    """
    Check Google Gmail authentication and configuration status.

    Use this to verify your OAuth credentials are configured and valid
    before attempting Gmail operations.

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
async def gmail_auth_setup(
    force_reauth: bool = False,
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Initialize OAuth 2.0 authentication flow for Gmail.

    **FIRST TIME SETUP**: This will open a browser window for you to log in to Google
    and grant Gmail access. After authentication, tokens are saved locally for future use.

    **PREREQUISITES**:
    1. Create OAuth 2.0 credentials in Google Cloud Console (Desktop App type)
    2. Enable Gmail API
    3. Set GOOGLE_GMAIL_CLIENT_ID and GOOGLE_GMAIL_CLIENT_SECRET in environment
       or save to .gmail.env file in this format:
       ```
       GOOGLE_GMAIL_CLIENT_ID=your_client_id
       GOOGLE_GMAIL_CLIENT_SECRET=your_client_secret
       ```

    **NOTE**: You can use the same OAuth credentials as Google Calendar if you've already set that up.

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
            "error": "Google Gmail libraries not installed",
            "install_command": "pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client"
        }

    config = _get_config()

    # Check for required config
    missing = []
    if not config["client_id"]:
        missing.append("GOOGLE_GMAIL_CLIENT_ID")
    if not config["client_secret"]:
        missing.append("GOOGLE_GMAIL_CLIENT_SECRET")

    if missing:
        return {
            "success": False,
            "error": "Missing OAuth configuration",
            "missing_config": missing,
            "hint": f"Set these in environment or create {GMAIL_ENV_FILE}"
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
        redirect_uri = GMAIL_REDIRECT_URI

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
                "6. Run gmail_complete_auth(authorization_code='PASTE_CODE_HERE')."
            ],
            "message": "Authorization URL generated. Complete login in browser, then call gmail_complete_auth with the returned code."
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Authentication failed: {str(e)}"
        }


@mcp.tool()
async def gmail_complete_auth(
    authorization_code: str,
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Complete OAuth authentication using an authorization code.

    **USE THIS** when gmail_auth_setup() returns an auth_url but can't accept input interactively.

    Workflow:
    1. Call gmail_auth_setup() - it returns auth_url
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
            "error": "Google Gmail libraries not installed"
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
        flow.redirect_uri = GMAIL_REDIRECT_URI

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
            "message": "Successfully authenticated! Gmail tokens saved for future use."
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to exchange authorization code: {str(e)}. Make sure the code is valid and hasn't expired."
        }


@mcp.tool()
async def gmail_list_messages(
    max_results: int = 10,
    query: Optional[str] = None,
    label_ids: Optional[List[str]] = None,
    include_spam_trash: bool = False,
    ctx: Context = None
) -> Dict[str, Any]:
    """
    List email messages with optional filtering.

    **DEFAULT USE CASE**: Get recent messages from inbox.

    **QUERY SYNTAX**: Use Gmail search operators:
    - "from:user@example.com" - From specific sender
    - "subject:meeting" - Subject contains text
    - "is:unread" - Unread messages
    - "has:attachment" - Has attachments
    - "after:2025/01/01" - After date
    - "label:important" - Has label

    **LABEL IDS**: Common labels include:
    - "INBOX" - Inbox
    - "UNREAD" - Unread messages
    - "SENT" - Sent messages
    - "DRAFT" - Drafts
    - "SPAM" - Spam folder
    - "TRASH" - Trash

    **AUTHENTICATION**: Requires gmail_auth_setup to be run first.

    Args:
        max_results: Maximum number of messages to return (1-500, default: 10)
        query: Gmail search query (default: none, returns all messages)
        label_ids: List of label IDs to filter by (default: none)
        include_spam_trash: If True, include spam and trash folders (default: False)
        ctx: MCP context (optional)

    Returns:
        Dictionary containing:
            - success: bool - Whether the operation succeeded
            - messages: list - List of message summaries, each containing:
                - id: str - Message ID
                - thread_id: str - Thread ID
                - snippet: str - Short preview of message body
                - from: str - Sender email
                - to: str - Recipient email(s)
                - subject: str - Email subject
                - date: str - Date/time received
                - labels: list - Label IDs applied to message
            - count: int - Number of messages returned
            - result_size_estimate: int - Total messages matching query
            OR on error:
            - success: bool - False
            - error: str - Error message
    """
    try:
        service = _get_service()

        # Build query parameters
        params = {
            "userId": "me",
            "maxResults": max(1, min(int(max_results), 500)),
            "includeSpamTrash": include_spam_trash,
        }

        if query:
            params["q"] = query
        if label_ids:
            params["labelIds"] = label_ids

        result = service.users().messages().list(**params).execute()
        messages = result.get('messages', [])

        # Get full message details for each
        detailed_messages = []
        for msg in messages:
            try:
                full_msg = service.users().messages().get(
                    userId="me",
                    id=msg['id'],
                    format='metadata',
                    metadataHeaders=['From', 'To', 'Subject', 'Date']
                ).execute()

                headers = _parse_headers(full_msg.get('payload', {}).get('headers', []))

                detailed_messages.append({
                    "id": full_msg.get("id"),
                    "thread_id": full_msg.get("threadId"),
                    "snippet": full_msg.get("snippet", ""),
                    "from": headers.get("from", ""),
                    "to": headers.get("to", ""),
                    "subject": headers.get("subject", ""),
                    "date": headers.get("date", ""),
                    "labels": full_msg.get("labelIds", []),
                })
            except Exception:
                # Skip messages that can't be fetched
                continue

        return {
            "success": True,
            "messages": detailed_messages,
            "count": len(detailed_messages),
            "result_size_estimate": result.get("resultSizeEstimate", 0)
        }

    except ValueError as e:
        return {"success": False, "error": str(e)}
    except HttpError as e:
        return {"success": False, "error": f"Gmail API error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def gmail_get_message(
    message_id: str,
    format: str = "full",
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Get full content of a specific email message.

    **FORMAT OPTIONS**:
    - "full" - Complete message with body (default)
    - "metadata" - Headers only, no body
    - "minimal" - Only ID and labels

    **AUTHENTICATION**: Requires gmail_auth_setup to be run first.

    Args:
        message_id: ID of the message to retrieve (required)
        format: Response format (default: "full")
                Options: "full", "metadata", "minimal"
        ctx: MCP context (optional)

    Returns:
        Dictionary containing:
            - success: bool - Whether the operation succeeded
            - id: str - Message ID
            - thread_id: str - Thread ID
            - from: str - Sender email
            - to: str - Recipient email(s)
            - subject: str - Email subject
            - date: str - Date/time received
            - body_text: str - Plain text body (if format="full")
            - body_html: str - HTML body (if format="full")
            - snippet: str - Short preview
            - labels: list - Label IDs applied to message
            - size_estimate: int - Message size in bytes
            OR on error:
            - success: bool - False
            - error: str - Error message
    """
    try:
        service = _get_service()

        message = service.users().messages().get(
            userId="me",
            id=message_id,
            format=format
        ).execute()

        headers = _parse_headers(message.get('payload', {}).get('headers', []))

        result = {
            "success": True,
            "id": message.get("id"),
            "thread_id": message.get("threadId"),
            "from": headers.get("from", ""),
            "to": headers.get("to", ""),
            "subject": headers.get("subject", ""),
            "date": headers.get("date", ""),
            "snippet": message.get("snippet", ""),
            "labels": message.get("labelIds", []),
            "size_estimate": message.get("sizeEstimate", 0),
        }

        # Extract body if format is full
        if format == "full":
            body = _extract_message_body(message.get('payload', {}))
            result["body_text"] = body.get("text", "")
            result["body_html"] = body.get("html", "")

        return result

    except ValueError as e:
        return {"success": False, "error": str(e)}
    except HttpError as e:
        return {"success": False, "error": f"Gmail API error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def gmail_send(
    to: str,
    subject: str,
    body: str,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
    html: bool = False,
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Send a new email message.

    **DEFAULT USE CASE**: Send plain text email to one recipient.

    **HTML EMAILS**: Set html=True to send HTML formatted emails.

    **MULTIPLE RECIPIENTS**: Use comma-separated emails for to/cc/bcc fields.

    **AUTHENTICATION**: Requires gmail_auth_setup to be run first.

    Args:
        to: Recipient email address(es) (required)
            Example: "user@example.com" or "user1@example.com,user2@example.com"
        subject: Email subject line (required)
        body: Email body content (required)
        cc: CC recipient email address(es) (default: none)
        bcc: BCC recipient email address(es) (default: none)
        html: If True, body is treated as HTML (default: False for plain text)
        ctx: MCP context (optional)

    Returns:
        Dictionary containing:
            - success: bool - Whether the email was sent
            - id: str - ID of the sent message
            - thread_id: str - Thread ID
            - label_ids: list - Labels applied to sent message
            OR on error:
            - success: bool - False
            - error: str - Error message
    """
    try:
        service = _get_service()

        # Create message
        if html:
            message = MIMEText(body, 'html')
        else:
            message = MIMEText(body, 'plain')

        message['To'] = to
        message['Subject'] = subject
        if cc:
            message['Cc'] = cc
        if bcc:
            message['Bcc'] = bcc

        # Encode message
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')

        # Send message
        sent_message = service.users().messages().send(
            userId="me",
            body={'raw': raw_message}
        ).execute()

        return {
            "success": True,
            "id": sent_message.get("id"),
            "thread_id": sent_message.get("threadId"),
            "label_ids": sent_message.get("labelIds", []),
        }

    except ValueError as e:
        return {"success": False, "error": str(e)}
    except HttpError as e:
        return {"success": False, "error": f"Gmail API error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def gmail_reply(
    message_id: str,
    body: str,
    html: bool = False,
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Reply to an existing email message.

    Automatically uses the original sender as recipient and keeps the same subject
    with "Re:" prefix. Maintains the email thread.

    **AUTHENTICATION**: Requires gmail_auth_setup to be run first.

    Args:
        message_id: ID of the message to reply to (required)
        body: Reply body content (required)
        html: If True, body is treated as HTML (default: False for plain text)
        ctx: MCP context (optional)

    Returns:
        Dictionary containing:
            - success: bool - Whether the reply was sent
            - id: str - ID of the reply message
            - thread_id: str - Thread ID (same as original)
            - label_ids: list - Labels applied to reply
            OR on error:
            - success: bool - False
            - error: str - Error message
    """
    try:
        service = _get_service()

        # Get original message to extract headers
        original = service.users().messages().get(
            userId="me",
            id=message_id,
            format='metadata',
            metadataHeaders=['From', 'To', 'Subject', 'Message-ID']
        ).execute()

        headers = _parse_headers(original.get('payload', {}).get('headers', []))
        thread_id = original.get('threadId')

        # Create reply message
        if html:
            message = MIMEText(body, 'html')
        else:
            message = MIMEText(body, 'plain')

        # Set headers for reply
        message['To'] = headers.get('from', '')
        subject = headers.get('subject', '')
        if not subject.startswith('Re:'):
            subject = f"Re: {subject}"
        message['Subject'] = subject

        # Add In-Reply-To and References headers for threading
        message_id_header = headers.get('message-id', '')
        if message_id_header:
            message['In-Reply-To'] = message_id_header
            message['References'] = message_id_header

        # Encode and send
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')

        sent_message = service.users().messages().send(
            userId="me",
            body={
                'raw': raw_message,
                'threadId': thread_id
            }
        ).execute()

        return {
            "success": True,
            "id": sent_message.get("id"),
            "thread_id": sent_message.get("threadId"),
            "label_ids": sent_message.get("labelIds", []),
        }

    except ValueError as e:
        return {"success": False, "error": str(e)}
    except HttpError as e:
        return {"success": False, "error": f"Gmail API error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def gmail_search(
    query: str,
    max_results: int = 50,
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Search emails using Gmail search query syntax.

    **QUERY SYNTAX**: Use Gmail search operators:
    - "from:user@example.com" - From specific sender
    - "to:user@example.com" - To specific recipient
    - "subject:meeting" - Subject contains text
    - "is:unread" - Unread messages
    - "is:starred" - Starred messages
    - "has:attachment" - Has attachments
    - "after:2025/01/01" - After date
    - "before:2025/12/31" - Before date
    - "larger:10M" - Larger than size
    - "label:important" - Has label
    - Combine with AND, OR, NOT operators

    **AUTHENTICATION**: Requires gmail_auth_setup to be run first.

    Args:
        query: Gmail search query (required)
               Example: "from:boss@company.com subject:urgent is:unread"
        max_results: Maximum number of results (1-500, default: 50)
        ctx: MCP context (optional)

    Returns:
        Dictionary containing:
            - success: bool - Whether the search succeeded
            - messages: list - List of matching messages (same format as gmail_list_messages)
            - count: int - Number of messages returned
            - query: str - The search query used
            OR on error:
            - success: bool - False
            - error: str - Error message
    """
    return await gmail_list_messages(
        max_results=max_results,
        query=query,
        ctx=ctx
    )


@mcp.tool()
async def gmail_create_draft(
    to: str,
    subject: str,
    body: str,
    cc: Optional[str] = None,
    bcc: Optional[str] = None,
    html: bool = False,
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Create a draft email (not sent).

    Use this to prepare emails for later review and sending.

    **AUTHENTICATION**: Requires gmail_auth_setup to be run first.

    Args:
        to: Recipient email address(es) (required)
        subject: Email subject line (required)
        body: Email body content (required)
        cc: CC recipient email address(es) (default: none)
        bcc: BCC recipient email address(es) (default: none)
        html: If True, body is treated as HTML (default: False)
        ctx: MCP context (optional)

    Returns:
        Dictionary containing:
            - success: bool - Whether the draft was created
            - id: str - Draft ID
            - message: dict - Message details including:
                - id: str - Message ID
                - thread_id: str - Thread ID
            OR on error:
            - success: bool - False
            - error: str - Error message
    """
    try:
        service = _get_service()

        # Create message
        if html:
            message = MIMEText(body, 'html')
        else:
            message = MIMEText(body, 'plain')

        message['To'] = to
        message['Subject'] = subject
        if cc:
            message['Cc'] = cc
        if bcc:
            message['Bcc'] = bcc

        # Encode message
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')

        # Create draft
        draft = service.users().drafts().create(
            userId="me",
            body={
                'message': {
                    'raw': raw_message
                }
            }
        ).execute()

        return {
            "success": True,
            "id": draft.get("id"),
            "message": draft.get("message", {}),
        }

    except ValueError as e:
        return {"success": False, "error": str(e)}
    except HttpError as e:
        return {"success": False, "error": f"Gmail API error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def gmail_delete(
    message_id: str,
    permanent: bool = False,
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Delete or trash an email message.

    **DEFAULT**: Moves message to Trash (recoverable for 30 days).

    **PERMANENT**: Set permanent=True to permanently delete (cannot be undone).

    **AUTHENTICATION**: Requires gmail_auth_setup to be run first.

    Args:
        message_id: ID of the message to delete (required)
        permanent: If True, permanently delete; if False, move to trash (default: False)
        ctx: MCP context (optional)

    Returns:
        Dictionary containing:
            - success: bool - Whether the message was deleted
            - message_id: str - ID of the deleted message
            - action: str - "trashed" or "permanently_deleted"
            OR on error:
            - success: bool - False
            - error: str - Error message
    """
    try:
        service = _get_service()

        if permanent:
            service.users().messages().delete(
                userId="me",
                id=message_id
            ).execute()
            action = "permanently_deleted"
        else:
            service.users().messages().trash(
                userId="me",
                id=message_id
            ).execute()
            action = "trashed"

        return {
            "success": True,
            "message_id": message_id,
            "action": action,
        }

    except ValueError as e:
        return {"success": False, "error": str(e)}
    except HttpError as e:
        return {"success": False, "error": f"Gmail API error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def gmail_mark_read(
    message_id: str,
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Mark an email message as read.

    **AUTHENTICATION**: Requires gmail_auth_setup to be run first.

    Args:
        message_id: ID of the message to mark as read (required)
        ctx: MCP context (optional)

    Returns:
        Dictionary containing:
            - success: bool - Whether the message was marked as read
            - message_id: str - ID of the message
            - labels: list - Updated label IDs
            OR on error:
            - success: bool - False
            - error: str - Error message
    """
    try:
        service = _get_service()

        message = service.users().messages().modify(
            userId="me",
            id=message_id,
            body={'removeLabelIds': ['UNREAD']}
        ).execute()

        return {
            "success": True,
            "message_id": message_id,
            "labels": message.get("labelIds", []),
        }

    except ValueError as e:
        return {"success": False, "error": str(e)}
    except HttpError as e:
        return {"success": False, "error": f"Gmail API error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def gmail_mark_unread(
    message_id: str,
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Mark an email message as unread.

    **AUTHENTICATION**: Requires gmail_auth_setup to be run first.

    Args:
        message_id: ID of the message to mark as unread (required)
        ctx: MCP context (optional)

    Returns:
        Dictionary containing:
            - success: bool - Whether the message was marked as unread
            - message_id: str - ID of the message
            - labels: list - Updated label IDs
            OR on error:
            - success: bool - False
            - error: str - Error message
    """
    try:
        service = _get_service()

        message = service.users().messages().modify(
            userId="me",
            id=message_id,
            body={'addLabelIds': ['UNREAD']}
        ).execute()

        return {
            "success": True,
            "message_id": message_id,
            "labels": message.get("labelIds", []),
        }

    except ValueError as e:
        return {"success": False, "error": str(e)}
    except HttpError as e:
        return {"success": False, "error": f"Gmail API error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def gmail_add_label(
    message_id: str,
    label_id: str,
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Add a label to an email message.

    **COMMON LABELS**:
    - "STARRED" - Star the message
    - "IMPORTANT" - Mark as important
    - Custom label IDs from gmail_list_labels

    **AUTHENTICATION**: Requires gmail_auth_setup to be run first.

    Args:
        message_id: ID of the message (required)
        label_id: Label ID to add (required)
        ctx: MCP context (optional)

    Returns:
        Dictionary containing:
            - success: bool - Whether the label was added
            - message_id: str - ID of the message
            - labels: list - Updated label IDs
            OR on error:
            - success: bool - False
            - error: str - Error message
    """
    try:
        service = _get_service()

        message = service.users().messages().modify(
            userId="me",
            id=message_id,
            body={'addLabelIds': [label_id]}
        ).execute()

        return {
            "success": True,
            "message_id": message_id,
            "labels": message.get("labelIds", []),
        }

    except ValueError as e:
        return {"success": False, "error": str(e)}
    except HttpError as e:
        return {"success": False, "error": f"Gmail API error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def gmail_remove_label(
    message_id: str,
    label_id: str,
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Remove a label from an email message.

    **AUTHENTICATION**: Requires gmail_auth_setup to be run first.

    Args:
        message_id: ID of the message (required)
        label_id: Label ID to remove (required)
        ctx: MCP context (optional)

    Returns:
        Dictionary containing:
            - success: bool - Whether the label was removed
            - message_id: str - ID of the message
            - labels: list - Updated label IDs
            OR on error:
            - success: bool - False
            - error: str - Error message
    """
    try:
        service = _get_service()

        message = service.users().messages().modify(
            userId="me",
            id=message_id,
            body={'removeLabelIds': [label_id]}
        ).execute()

        return {
            "success": True,
            "message_id": message_id,
            "labels": message.get("labelIds", []),
        }

    except ValueError as e:
        return {"success": False, "error": str(e)}
    except HttpError as e:
        return {"success": False, "error": f"Gmail API error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def gmail_list_labels(ctx: Context = None) -> Dict[str, Any]:
    """
    List all available Gmail labels (folders).

    Returns both system labels (INBOX, SENT, etc.) and user-created labels.

    **AUTHENTICATION**: Requires gmail_auth_setup to be run first.

    Args:
        ctx: MCP context (optional)

    Returns:
        Dictionary containing:
            - success: bool - Whether the operation succeeded
            - labels: list - List of label objects, each containing:
                - id: str - Label ID (use for other operations)
                - name: str - Label display name
                - type: str - "system" or "user"
                - message_list_visibility: str - Visibility setting
                - label_list_visibility: str - Whether shown in label list
            - count: int - Number of labels
            OR on error:
            - success: bool - False
            - error: str - Error message
    """
    try:
        service = _get_service()

        result = service.users().labels().list(userId="me").execute()
        labels = result.get('labels', [])

        formatted_labels = []
        for label in labels:
            formatted_labels.append({
                "id": label.get("id"),
                "name": label.get("name"),
                "type": label.get("type"),
                "message_list_visibility": label.get("messageListVisibility"),
                "label_list_visibility": label.get("labelListVisibility"),
            })

        return {
            "success": True,
            "labels": formatted_labels,
            "count": len(formatted_labels)
        }

    except ValueError as e:
        return {"success": False, "error": str(e)}
    except HttpError as e:
        return {"success": False, "error": f"Gmail API error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    mcp.run(transport="stdio")
