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
from urllib.error import URLError
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
_API_URL_CACHE: Optional[str] = None


def _probe_health(base_url: str) -> bool:
    """Return True if the Slackbot /health endpoint responds."""
    health_endpoint = urljoin(base_url.rstrip("/") + "/", "health")
    with _urlrequest.urlopen(health_endpoint, timeout=2):
        return True


def _resolve_api_url() -> str:
    """Determine the API endpoint that should be used."""
    env_url = os.getenv("SLACKBOT_API_URL")
    candidates = []
    if env_url:
        candidates.append(env_url)
    candidates.extend([
        "http://gnosis-slackbot:8765",
        "http://host.docker.internal:8765",
        DEFAULT_API_URL,
    ])

    for url in candidates:
        try:
            if _probe_health(url):
                logger.info(f"Slackbot MCP using API endpoint: {url}")
                return url
        except URLError as exc:
            logger.debug(f"Slackbot MCP probe failed for {url}: {exc}")
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"Slackbot MCP probe error for {url}: {exc}", exc_info=True)

    fallback = candidates[-1]
    logger.warning(f"Slackbot MCP falling back to default endpoint: {fallback}")
    return fallback


def _get_api_url() -> str:
    """Return a reachable API URL, re-resolving if connectivity drops."""
    global _API_URL_CACHE  # noqa: PLW0603

    if _API_URL_CACHE:
        try:
            if _probe_health(_API_URL_CACHE):
                return _API_URL_CACHE
        except Exception:  # noqa: BLE001
            logger.info("Slackbot MCP cached endpoint is unavailable; re-resolving.")
            _API_URL_CACHE = None

    _API_URL_CACHE = _resolve_api_url()
    return _API_URL_CACHE


@mcp.tool()
def slack_send_message(
    channel: str,
    text: str,
    thread_ts: Optional[str] = None
) -> Dict:
    """Send a text message to a Slack channel."""
    logger.info(f"Sending message to {channel}")

    payload = {
        "channel": channel,
        "text": text
    }
    if thread_ts:
        payload["thread_ts"] = thread_ts

    api_url = _get_api_url()
    url = urljoin(api_url, "/send")
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
    """Send an image to a Slack channel."""
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

    api_url = _get_api_url()
    url = urljoin(api_url, "/send-with-image")
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
    """Upload a file to Slack."""
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

    api_url = _get_api_url()
    url = urljoin(api_url, "/upload")
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
    """Get information about a Slack user."""
    logger.info(f"Getting user info for {user_id}")

    api_url = _get_api_url()
    url = urljoin(api_url, f"/user/{user_id}")
    req = _urlrequest.Request(url, method='GET')

    with _urlrequest.urlopen(req, timeout=30) as response:
        result = json.loads(response.read().decode('utf-8'))
        return result


@mcp.tool()
def slack_get_channel(channel_id: str) -> Dict:
    """Get information about a Slack channel."""
    logger.info(f"Getting channel info for {channel_id}")

    api_url = _get_api_url()
    url = urljoin(api_url, f"/channel/{channel_id}")
    req = _urlrequest.Request(url, method='GET')

    with _urlrequest.urlopen(req, timeout=30) as response:
        result = json.loads(response.read().decode('utf-8'))
        return result


if __name__ == "__main__":
    mcp.run()
