#!/usr/bin/env python3
"""MCP: slackbot

Interact with Gnosis Slackbot API to send messages, images, and files to Slack channels.
Allows Alpha India and other agents to communicate maritime intelligence via Slack.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import sys
from pathlib import Path
from typing import Dict, Optional
from urllib import request as _urlrequest
from urllib.parse import urljoin

from mcp.server.fastmcp import FastMCP

# Setup logging
log_dir = Path("/workspace/.mcp-logs")
log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / "slackbot.log"),
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("slackbot")

mcp = FastMCP("slackbot")

# Service URL - can be overridden via environment variable
DEFAULT_API_URL = "http://localhost:8765"
API_URL = os.getenv("SLACKBOT_API_URL", DEFAULT_API_URL)


@mcp.tool()
def slack_send_message(
    channel: str,
    text: str,
    thread_ts: Optional[str] = None
) -> Dict:
    """Send a text message to a Slack channel.

    Args:
        channel: Channel ID or name (e.g., C1234567890 or #general)
        text: Message text to send
        thread_ts: Optional thread timestamp to reply in thread

    Returns:
        Dictionary with success status and response from Slack API
    """
    logger.info(f"Sending message to {channel}")

    payload = {
        "channel": channel,
        "text": text
    }
    if thread_ts:
        payload["thread_ts"] = thread_ts

    url = urljoin(API_URL, "/send")
    req = _urlrequest.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST'
    )

    with _urlrequest.urlopen(req, timeout=30) as response:
        result = json.loads(response.read().decode('utf-8'))
        logger.info(f"Message sent successfully to {channel}")
        return result


@mcp.tool()
def slack_send_image(
    channel: str,
    image_path: str,
    text: Optional[str] = None
) -> Dict:
    """Send an image to a Slack channel.

    Args:
        channel: Channel ID or name
        image_path: Path to the image file (container path)
        text: Optional caption for the image

    Returns:
        Dictionary with success status and response from Slack API
    """
    image_file = Path(image_path)
    if not image_file.exists():
        error_msg = f"Image file not found: {image_path}"
        logger.error(error_msg)
        return {"error": error_msg, "success": False}

    logger.info(f"Sending image {image_file.name} to {channel}")

    # Prepare multipart form data
    import uuid
    boundary = f"----WebKitFormBoundary{uuid.uuid4().hex[:16]}"
    body_parts = []

    # Add channel field
    body_parts.append(f'--{boundary}\r\n')
    body_parts.append('Content-Disposition: form-data; name="channel"\r\n\r\n')
    body_parts.append(f'{channel}\r\n')

    # Add text field if provided
    if text:
        body_parts.append(f'--{boundary}\r\n')
        body_parts.append('Content-Disposition: form-data; name="text"\r\n\r\n')
        body_parts.append(f'{text}\r\n')

    # Add image field
    body_parts.append(f'--{boundary}\r\n')
    body_parts.append(f'Content-Disposition: form-data; name="image"; filename="{image_file.name}"\r\n')
    body_parts.append('Content-Type: image/png\r\n\r\n')

    # Combine text parts
    body = ''.join(body_parts).encode('utf-8')

    # Add image data
    with open(image_file, 'rb') as f:
        body += f.read()

    # Add closing boundary
    body += f'\r\n--{boundary}--\r\n'.encode('utf-8')

    url = urljoin(API_URL, "/send-with-image")
    req = _urlrequest.Request(
        url,
        data=body,
        headers={'Content-Type': f'multipart/form-data; boundary={boundary}'},
        method='POST'
    )

    with _urlrequest.urlopen(req, timeout=60) as response:
        result = json.loads(response.read().decode('utf-8'))
        logger.info(f"Image sent successfully to {channel}")
        return result


@mcp.tool()
def slack_upload_file(
    channel: str,
    file_path: str,
    title: Optional[str] = None,
    comment: Optional[str] = None
) -> Dict:
    """Upload a file to Slack.

    Args:
        channel: Channel ID
        file_path: Path to the file to upload
        title: Optional file title
        comment: Optional comment to include with file

    Returns:
        Dictionary with success status and response from Slack API
    """
    file = Path(file_path)
    if not file.exists():
        error_msg = f"File not found: {file_path}"
        logger.error(error_msg)
        return {"error": error_msg, "success": False}

    logger.info(f"Uploading file {file.name} to {channel}")

    # Read file and encode as base64
    with open(file, 'rb') as f:
        content_base64 = base64.b64encode(f.read()).decode('utf-8')

    payload = {
        "channel": channel,
        "filename": file.name,
        "content_base64": content_base64
    }
    if title:
        payload["title"] = title
    if comment:
        payload["initial_comment"] = comment

    url = urljoin(API_URL, "/upload")
    req = _urlrequest.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST'
    )

    with _urlrequest.urlopen(req, timeout=60) as response:
        result = json.loads(response.read().decode('utf-8'))
        logger.info(f"File uploaded successfully to {channel}")
        return result


@mcp.tool()
def slack_get_user(user_id: str) -> Dict:
    """Get information about a Slack user.

    Args:
        user_id: User ID (e.g., U1234567890)

    Returns:
        Dictionary with user information
    """
    logger.info(f"Getting user info for {user_id}")

    url = urljoin(API_URL, f"/user/{user_id}")
    req = _urlrequest.Request(url, method='GET')

    with _urlrequest.urlopen(req, timeout=30) as response:
        result = json.loads(response.read().decode('utf-8'))
        return result


@mcp.tool()
def slack_get_channel(channel_id: str) -> Dict:
    """Get information about a Slack channel.

    Args:
        channel_id: Channel ID (e.g., C1234567890)

    Returns:
        Dictionary with channel information
    """
    logger.info(f"Getting channel info for {channel_id}")

    url = urljoin(API_URL, f"/channel/{channel_id}")
    req = _urlrequest.Request(url, method='GET')

    with _urlrequest.urlopen(req, timeout=30) as response:
        result = json.loads(response.read().decode('utf-8'))
        return result


if __name__ == "__main__":
    mcp.run()
