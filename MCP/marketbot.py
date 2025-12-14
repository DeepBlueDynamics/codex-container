#!/usr/bin/env python3
"""MCP: marketbot

Bridge the MarketBot API into MCP so agents can push/pull competitive intelligence.

Rather than thinking of "competitors" in abstract, the platform tracks specific
companies (the "common name" your team uses internally) plus their recent activities,
alerts, and trending keywords. These tools deliberately surface that naming guidance to
encourage consistent deduplication—always reuse the same canonical company name when
creating a record so downstream dashboards group intelligence correctly.

"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Sequence, Tuple

from mcp.server.fastmcp import FastMCP
from urllib.parse import urlsplit, urlunsplit

mcp = FastMCP("marketbot")

# ============================================================================
# URL State Management (inlined from marketbot_state_lib)
# ============================================================================

# State file for tracking processed URLs
_STATE_FILE = Path(os.environ.get("MARKETBOT_STATE_FILE", "/workspace/.marketbot-processed.json"))

# Default blocked domains
DEFAULT_BLOCKED_DOMAINS: Tuple[str, ...] = (
    "linkedin.com",
    "twitter.com",
    "x.com",
    "facebook.com",
    "instagram.com",
    "reddit.com",
    "businesswire.com",
    "prnewswire.com",
    "marketwatch.com",
    "wsj.com",
    "ft.com",
    "bloomberg.com",
    "glassdoor.com",
    "g2.com",
    "slack.com",
    "teams.microsoft.com",
)


def _ensure_parent() -> None:
    """Ensure the state file's parent directory exists."""
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)


def load_state() -> Dict[str, Any]:
    """Load the URL state from the JSON file."""
    if not _STATE_FILE.exists():
        return {"urls": {}, "last_updated": None}
    try:
        with _STATE_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                return {"urls": {}, "last_updated": None}
            data.setdefault("urls", {})
            return data
    except Exception:
        return {"urls": {}, "last_updated": None}


def save_state(state: Dict[str, Any]) -> None:
    """Save the URL state to the JSON file."""
    _ensure_parent()
    state.setdefault("urls", {})
    state.setdefault("last_updated", iso_now())
    with _STATE_FILE.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
        f.write("\n")


def iso_now() -> str:
    """Return current UTC time as ISO string."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO timestamp string to datetime."""
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)
    except Exception:
        return None


def normalize_url(url: str) -> str:
    """Normalize a URL for comparison."""
    url = (url or "").strip()
    if not url:
        return url
    try:
        parts = urlsplit(url)
        scheme = parts.scheme or "https"
        netloc = parts.netloc.lower()
        path = parts.path.rstrip("/") or "/"
        query = parts.query
        return urlunsplit((scheme, netloc, path, query, ""))
    except Exception:
        return url


def hostname(url: str) -> str:
    """Extract hostname from URL."""
    try:
        return urlsplit(url).netloc.lower()
    except Exception:
        return ""


def is_blocked_domain(url: str, custom_blocklist: Optional[List[str]] = None) -> bool:
    """Check if URL's domain is in the blocklist."""
    host = hostname(url)
    if not host:
        return False
    blocklist = tuple((custom_blocklist or []) + list(DEFAULT_BLOCKED_DOMAINS))
    return any(host == domain or host.endswith(f".{domain}") for domain in blocklist)


def iter_state_urls(state: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    """Iterate over URLs in state, returning (url, payload) tuples."""
    items = []
    for url, payload in state.get("urls", {}).items():
        if isinstance(payload, dict):
            items.append((url, payload))
        else:
            items.append((url, {"timestamp": payload}))
    return items

# ============================================================================
# MarketBot API Configuration
# ============================================================================

# Configuration mirrors the ProductBotAI deployment exposed via ngrok.
# CRITICAL FIX: Use host.docker.internal instead of localhost for Docker containers
# Inside Docker, localhost refers to the container itself, not the host machine
_DOCKER_HOST = os.getenv("DOCKER_HOST_ALIAS", "host.docker.internal")
_DEFAULT_BASE_URL = f"http://{_DOCKER_HOST}:3000/api/marketbot"
def _read_env_file() -> Dict[str, str]:
    """Load environment variables from session-specific .env file.
    
    ⭐ SESSION-ISOLATED ARCHITECTURE:
    - Each Codex session has its own env file at: /opt/codex-home/sessions/{CODEX_SESSION_ID}/.env
    - This ensures different teams with different API keys are properly isolated
    - No legacy workspace paths are used to prevent credential conflicts
    """

    candidates: Sequence[Path] = []
    
    # ⭐ CRITICAL: Only use session-specific env file
    # This ensures each Codex session uses its own isolated credentials
    # Multiple teams can run concurrently without credential conflicts
    # Session directory structure matches SessionStore: /opt/codex-home/sessions/gateway/session-{sessionId}
    session_id = os.getenv("CODEX_SESSION_ID")
    if not session_id:
        print(f"[marketbot] ⚠️ CODEX_SESSION_ID not set - cannot load session-specific env file", file=sys.stderr)
        return {}
    
    # Try gateway session directory first (matches SessionStore structure)
    session_env_gateway = Path("/opt/codex-home/sessions/gateway") / f"session-{session_id}" / ".env"
    candidates.append(session_env_gateway)
    print(f"[marketbot] Looking for session-specific env file (gateway): {session_env_gateway}", file=sys.stderr)
    
    # Fallback to direct session ID path (for backward compatibility)
    session_env_direct = Path("/opt/codex-home/sessions") / session_id / ".env"
    candidates.append(session_env_direct)
    print(f"[marketbot] Looking for session-specific env file (direct): {session_env_direct}", file=sys.stderr)
    
    # Allow explicit override via MARKETBOT_ENV_FILE (for testing/debugging only)
    explicit_path = os.getenv("MARKETBOT_ENV_FILE", "")
    if explicit_path:
        print(f"[marketbot] ⚠️ MARKETBOT_ENV_FILE override set: {explicit_path} (testing mode)", file=sys.stderr)
        candidates.append(Path(explicit_path))

    values: Dict[str, str] = {}
    for candidate in candidates:
        if not candidate or not candidate.is_file():
            if candidate:
                print(f"[marketbot] Env file not found: {candidate}", file=sys.stderr)
            continue
        
        print(f"[marketbot] ✅ Loading env file: {candidate}", file=sys.stderr)
        try:
            for raw_line in candidate.read_text().splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                # Remove quotes from value if present (handles both single and double quotes)
                # This handles: KEY="value", KEY='value', KEY=value, KEY="value with spaces"
                value = value.strip()
                # Remove outer quotes if present (both single and double)
                if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
                    value = value[1:-1]
                values.setdefault(key.strip(), value)
            
            if values:
                print(f"[marketbot] ✅ Loaded {len(values)} env vars from {candidate}", file=sys.stderr)
                print(f"[marketbot] Loaded keys: {', '.join(sorted(values.keys()))}", file=sys.stderr)
                break
        except Exception as e:
            print(f"[marketbot] ⚠️ Error reading env file {candidate}: {e}", file=sys.stderr)
            continue
    
    if not values:
        print(f"[marketbot] ⚠️ No env file found in any candidate location", file=sys.stderr)
    
    return values


# ⭐ CRITICAL: Session-scoped cache to prevent env var leakage between sessions
# Key: session_id, Value: {env_values: dict, mtime: float, path: Path}
# This ensures each session has isolated credentials
_env_file_cache: Dict[str, Dict[str, Any]] = {}

def _load_env_vars_from_file() -> Dict[str, str]:
    """Load env file WITHOUT setting os.environ.
    
    ⚠️ CRITICAL: We do NOT set os.environ because this MCP server is a SINGLE
    long-lived process that handles multiple Codex sessions concurrently.
    Setting os.environ would cause env vars to leak between sessions!
    
    Instead, we:
    1. Read directly from session-specific file
    2. Use session-scoped cache (keyed by session ID)
    3. Return values without modifying global process environment
    
    ⭐ CRITICAL: Reloads if file was modified after initial load (handles race conditions
    where env file is written after MCP server starts).
    
    ⚠️ SESSION ID RESOLUTION:
    - First tries os.getenv("CODEX_SESSION_ID") (might be passed via MCP protocol)
    - If not found, this is a CRITICAL ERROR - we cannot know which session file to read
    - This will cause the function to return empty dict, which will trigger errors
    - This is INTENTIONAL - we'd rather fail than use wrong credentials
    """
    global _env_file_cache
    
    # ⭐ CRITICAL: Get current session ID
    # This MUST be available to know which session's env file to read
    session_id = os.getenv("CODEX_SESSION_ID")
    if not session_id:
        print(f"[marketbot] ❌ CRITICAL: No CODEX_SESSION_ID in process environment!", file=sys.stderr)
        print(f"[marketbot] ❌ Cannot determine which session's env file to read", file=sys.stderr)
        print(f"[marketbot] ❌ This will cause authentication failures to prevent cross-team data leakage", file=sys.stderr)
        print(f"[marketbot] ❌ CODEX_SESSION_ID must be passed via MCP protocol context or process environment", file=sys.stderr)
        return {}
    
    current_env_path = Path("/opt/codex-home/sessions/gateway") / f"session-{session_id}" / ".env"
    
    # Check if we have a cached version for this session
    if session_id in _env_file_cache:
        cached = _env_file_cache[session_id]
        cached_path = cached.get("path")
        cached_mtime = cached.get("mtime")
        
        # If path changed, clear cache for this session
        if cached_path != current_env_path:
            print(f"[marketbot] ⚠️ Session {session_id} env path changed, clearing cache", file=sys.stderr)
            del _env_file_cache[session_id]
        elif current_env_path.is_file():
            # Check if file was modified
            try:
                current_mtime = current_env_path.stat().st_mtime
                if cached_mtime is not None and current_mtime <= cached_mtime:
                    # File unchanged, return cached values
                    print(f"[marketbot] ✅ Using cached env for session {session_id}", file=sys.stderr)
                    return cached.get("env_values", {})
                else:
                    print(f"[marketbot] ⚠️ Env file modified for session {session_id}, reloading...", file=sys.stderr)
            except OSError as e:
                print(f"[marketbot] ⚠️ Error checking env file mtime: {e}, forcing reload", file=sys.stderr)
    
    # Load env file for this session
    print(f"[marketbot] 📂 Loading env file for session {session_id}: {current_env_path}", file=sys.stderr)
    env_values = _read_env_file()
    
    # Store in session-scoped cache (NOT in os.environ!)
    if current_env_path.is_file():
        try:
            mtime = current_env_path.stat().st_mtime
        except OSError:
            mtime = None
    else:
        mtime = None
    
    _env_file_cache[session_id] = {
        "env_values": env_values,
        "mtime": mtime,
        "path": current_env_path,
    }
    
    print(f"[marketbot] ✅ Loaded {len(env_values)} env vars for session {session_id} (NOT set in os.environ to prevent leakage)", file=sys.stderr)
    return env_values

def _resolve_setting(name: str, default: Optional[str] = None) -> Optional[str]:
    """Return env value from session-specific file ONLY.
    
    ⭐ CRITICAL: This MCP server is a SINGLE long-lived process handling multiple sessions.
    We MUST NEVER use os.getenv() for MARKETBOT_* variables because:
    1. The MCP server process has its own environment (not the Codex session's environment)
    2. os.getenv() will return values from the MCP server's process, which could be from a previous session
    3. This causes cross-team data leakage (the exact problem we're fixing)
    
    ⭐ SOLUTION: ALWAYS read from session-specific file based on CODEX_SESSION_ID.
    The file is written by Codex Gateway for each session and contains the correct credentials.
    
    For MARKETBOT_* variables: ALWAYS read from file (never os.getenv())
    For CODEX_SESSION_ID: Try os.getenv() first (if passed via MCP context), then file
    """

    # ⭐ CRITICAL FIX: For MARKETBOT_* variables, NEVER use os.getenv()
    # The MCP server is a separate process from Codex sessions, so os.getenv() will
    # return values from the MCP server's process environment, not the current session.
    # This causes cross-team data leakage when multiple sessions run concurrently.
    if name.startswith("MARKETBOT_") or name.startswith("PRODUCTBOT_"):
        # ⭐ ALWAYS read from session-specific file for MARKETBOT_* variables
        print(f"[_resolve_setting] 🔒 MARKETBOT_* variable - reading from session-specific file only (never os.getenv())", file=sys.stderr)
        env_values = _load_env_vars_from_file()
        file_value = env_values.get(name)
        
        if file_value:
            print(f"[_resolve_setting] ✅ Found {name} in session-specific env file (length: {len(file_value)})", file=sys.stderr)
            return file_value
        
        print(f"[_resolve_setting] ❌ {name} not found in session-specific file", file=sys.stderr)
        return default
    
    # For non-MARKETBOT variables (like CODEX_SESSION_ID, CODEX_JOB_ID), try process env first
    # These might be passed via MCP protocol context
    value = os.getenv(name)
    if value:
        print(f"[_resolve_setting] ✅ Found {name} in process environment (length: {len(value)})", file=sys.stderr)
        return value
    
    # Fallback to file for non-MARKETBOT variables
    print(f"[_resolve_setting] ⚠️ {name} not in process environment, reading from session-specific file...", file=sys.stderr)
    env_values = _load_env_vars_from_file()
    file_value = env_values.get(name)
    
    if file_value:
        print(f"[_resolve_setting] ✅ Found {name} in session-specific env file (length: {len(file_value)})", file=sys.stderr)
        return file_value
    
    print(f"[_resolve_setting] ❌ {name} not found in process environment or session-specific file", file=sys.stderr)
    return default


class MarketBotError(RuntimeError):
    """Raised when the MarketBot API returns an error."""


def _debug_info() -> Dict[str, Optional[str]]:
    """Return non-sensitive context for tool responses."""

    api_key = _resolve_setting("MARKETBOT_API_KEY", "")
    suffix: Optional[str] = api_key[-4:] if api_key else None
    return {
        "base_url": _resolve_setting("MARKETBOT_API_URL", _DEFAULT_BASE_URL),
        "team_id": _resolve_setting("MARKETBOT_TEAM_ID", ""),
        "api_key_suffix": suffix,
    }


# ============================================================================
# Event Publishing (New Event-Driven Architecture)
# ============================================================================

def _publish_event(event_type: str, payload: dict) -> Dict[str, Any]:
    """Publish event to ProductBot via RabbitMQ event queue.
    
    ⭐ NEW: Event-driven architecture - publishes events instead of direct HTTP calls.
    This ensures atomic data creation and status updates.
    """
    try:
        # Try to get job ID from environment or from payload
        job_id = os.getenv("CODEX_JOB_ID") or payload.get("jobId")
        team_id = _resolve_setting("MARKETBOT_TEAM_ID")
        
        if not job_id:
            # If no job ID, try to get from session ID (fallback)
            session_id = os.getenv("CODEX_SESSION_ID")
            if session_id:
                # Extract job ID from session if possible, or use session ID as fallback
                job_id = session_id
            else:
                raise MarketBotError("CODEX_JOB_ID or CODEX_SESSION_ID must be set to publish events")
        
        if not team_id:
            raise MarketBotError("MARKETBOT_TEAM_ID must be set to publish events")
        
        event = {
            "type": event_type,
            "jobId": str(job_id),  # Ensure it's a string
            "teamId": team_id,
            "timestamp": iso_now(),
            **payload
        }
        
        # Publish to event endpoint (which publishes to RabbitMQ)
        result = _request("POST", "/events", body=event)
        
        if not result.get("success"):
            raise MarketBotError(f"Failed to publish event: {result.get('error')}")
        
        return result
    except Exception as err:
        # ⭐ FALLBACK: If event publishing fails, log but don't fail the operation
        print(f"[marketbot] ⚠️ Failed to publish {event_type} event: {err}", file=sys.stderr)
        return {"success": False, "error": str(err)}


# Heartbeat tracking for progress updates
_last_heartbeat_time = None
_heartbeat_interval_seconds = 120  # 2 minutes

def _maybe_send_heartbeat(current_step: str = "processing", message: str = None):
    """Send heartbeat if enough time has passed."""
    global _last_heartbeat_time
    
    now = datetime.now(timezone.utc)
    if _last_heartbeat_time is None or (now - _last_heartbeat_time).total_seconds() >= _heartbeat_interval_seconds:
        try:
            _publish_event("PROGRESS_UPDATE", {
                "progress": {
                    "currentStep": current_step,
                    "message": message,
                }
            })
            _last_heartbeat_time = now
        except Exception as err:
            # Don't fail on heartbeat errors
            print(f"[marketbot] ⚠️ Heartbeat failed: {err}", file=sys.stderr)


def _with_next_actions(resp: Dict[str, Any], actions: Optional[Sequence[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Ensure every response carries next_actions (default: empty list)."""

    if actions is None:
        actions = []
    if isinstance(resp, dict) and "next_actions" not in resp:
        resp["next_actions"] = list(actions)
    return resp


def _request(
    method: str,
    path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    body: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Make an HTTP request to the MarketBot API.
    
    ⭐ CRITICAL: Uses session-specific environment variables.
    - Reads from process environment (set by Codex Gateway) or session-specific .env file
    - Each Codex session MUST have its own isolated credentials
    - CODEX_SESSION_ID must be set to load session-specific env file
    """

    # ⭐ CRITICAL: Get session ID first to verify session isolation
    session_id = os.getenv("CODEX_SESSION_ID")
    api_key = _resolve_setting("MARKETBOT_API_KEY")
    team_id = _resolve_setting("MARKETBOT_TEAM_ID")
    base_url = (_resolve_setting("MARKETBOT_API_URL", _DEFAULT_BASE_URL) or _DEFAULT_BASE_URL).rstrip("/")

    # ⭐ DEBUG: Log environment variable values (masked for security)
    print(f"[_request] ========== REQUEST DEBUG INFO ==========", file=sys.stderr)
    print(f"[_request] ⭐ SESSION ISOLATION CHECK:", file=sys.stderr)
    print(f"[_request]   CODEX_SESSION_ID: {'✅ SET' if session_id else '❌ MISSING'} ({session_id if session_id else 'N/A'})", file=sys.stderr)
    if session_id:
        session_env_path = Path("/opt/codex-home/sessions/gateway") / f"session-{session_id}" / ".env"
        print(f"[_request]   Session env file: {session_env_path} ({'✅ EXISTS' if session_env_path.is_file() else '❌ NOT FOUND'})", file=sys.stderr)
        # ⭐ CRITICAL: Verify we're reading from the correct session file
        if session_env_path.is_file():
            # Read file to verify it contains the team ID we're using
            try:
                with session_env_path.open("r") as f:
                    file_content = f.read()
                    if team_id and f'MARKETBOT_TEAM_ID="{team_id}"' in file_content:
                        print(f"[_request]   ✅ Verified: Team ID {team_id} matches session file", file=sys.stderr)
                    elif team_id:
                        print(f"[_request]   ⚠️ WARNING: Team ID {team_id} not found in session file!", file=sys.stderr)
                        print(f"[_request]   ⚠️ This could indicate session isolation failure!", file=sys.stderr)
            except Exception as e:
                print(f"[_request]   ⚠️ Could not verify session file contents: {e}", file=sys.stderr)
    print(f"[_request] MARKETBOT_API_URL (raw): {base_url}", file=sys.stderr)
    print(f"[_request] MARKETBOT_TEAM_ID: {team_id}", file=sys.stderr)
    print(f"[_request] MARKETBOT_API_KEY: {'SET' if api_key else 'MISSING'} (length: {len(api_key) if api_key else 0})", file=sys.stderr)
    if api_key:
        print(f"[_request] MARKETBOT_API_KEY (masked): {api_key[:10]}...{api_key[-4:] if len(api_key) > 14 else '***'}", file=sys.stderr)
    print(f"[_request] Request path: {path}", file=sys.stderr)
    print(f"[_request] Request method: {method}", file=sys.stderr)

    if not api_key:
        raise MarketBotError("MARKETBOT_API_KEY is not set (must be in session-specific env file: /opt/codex-home/sessions/{CODEX_SESSION_ID}/.env)")
    if not team_id:
        raise MarketBotError("MARKETBOT_TEAM_ID is not set (must be in session-specific env file: /opt/codex-home/sessions/{CODEX_SESSION_ID}/.env)")

    # CRITICAL FIX: Automatically replace localhost with host.docker.internal for Docker containers
    # This allows Codex container to reach the ProductBot API running on the host machine
    if "localhost" in base_url or "127.0.0.1" in base_url:
        original_url = base_url
        base_url = base_url.replace("localhost", _DOCKER_HOST).replace("127.0.0.1", _DOCKER_HOST)
        print(f"[_request] ⚠️ Found localhost in base_url, replacing with {_DOCKER_HOST}", file=sys.stderr)
        print(f"[_request] ✅ Updated base_url from {original_url} to {base_url}", file=sys.stderr)

    base = base_url or _DEFAULT_BASE_URL
    
    # ⭐ CRITICAL: Handle path construction
    # Paths in marketbot.py are relative (e.g., "/competitors", "/products/batch")
    # Base URL should be: http://host.docker.internal:3000/api/marketbot
    # So "/competitors" becomes: http://host.docker.internal:3000/api/marketbot/competitors
    # But if user wants http://host.docker.internal:3000/competitors, base should be without /api/marketbot
    
    # Check if path already includes /api/marketbot
    if path.startswith("/api/marketbot"):
        # Path is already full, extract base domain
        if "/api/marketbot" in base:
            base_domain = base.split("/api/marketbot")[0].rstrip("/")
            url = f"{base_domain}{path}"
        else:
            url = f"{base.rstrip('/')}{path}"
    else:
        # Normal path construction - append to base
        url = f"{base.rstrip('/')}/{path.lstrip('/')}"
    
    print(f"[_request] ========== URL CONSTRUCTION ==========", file=sys.stderr)
    print(f"[_request] Base URL: {base}", file=sys.stderr)
    print(f"[_request] Path: {path}", file=sys.stderr)
    print(f"[_request] Final URL: {url}", file=sys.stderr)
    print(f"[_request] =====================================", file=sys.stderr)
    if params:
        query_params = {k: v for k, v in params.items() if v is not None}
        if query_params:
            query = urllib.parse.urlencode(query_params)
            url = f"{url}?{query}"

    data = None
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {api_key}",
        "X-API-Key": api_key,
        "X-Team-Id": team_id,
    }
    if "ngrok" in base:
        headers["ngrok-skip-browser-warning"] = "true"
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    # Log the request details
    print(f"[_request] Making {method} request to: {url}", file=sys.stderr)
    if body:
        body_preview = json.dumps(body) if isinstance(body, dict) else str(body)
        if len(body_preview) > 500:
            body_preview = body_preview[:500] + "... (truncated)"
        print(f"[_request] Request body preview: {body_preview}", file=sys.stderr)
    print(f"[_request] Headers: X-Team-Id={team_id}, X-API-Key={'present' if api_key else 'missing'}", file=sys.stderr)

    req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # type: ignore[no-untyped-call]
            payload = resp.read().decode("utf-8")
            print(f"[_request] Response status: {resp.status}", file=sys.stderr)
            print(f"[_request] Response preview: {payload[:200]}...", file=sys.stderr)
            if resp.status >= 400:
                raise MarketBotError(payload)
            parsed = json.loads(payload)
            print(f"[_request] ✅ Request succeeded: success={parsed.get('success', 'unknown')}", file=sys.stderr)
            return parsed
    except urllib.error.HTTPError as exc:  # type: ignore[attr-defined]
        detail = exc.read().decode("utf-8")
        print(f"[_request] ❌ HTTP Error {exc.code}: {detail}", file=sys.stderr)
        raise MarketBotError(f"HTTP {exc.code}: {detail}") from exc
    except Exception as e:
        print(f"[_request] ❌ Request failed with exception: {e}", file=sys.stderr)
        import traceback
        print(f"[_request] Traceback: {traceback.format_exc()}", file=sys.stderr)
        raise


@mcp.tool()
async def marketbot_ping() -> Dict[str, Any]:
    """Ping the MarketBot API and report the base URL in use.

    Returns the resolved base URL and health check response (or error).
    """
    try:
        response = _request("GET", "/health")
        if isinstance(response, dict):
            response.setdefault("base_url", _resolve_setting("MARKETBOT_API_URL", _DEFAULT_BASE_URL))
            response.setdefault("debug", _debug_info())
        else:
            response = {"success": True, "data": response, "debug": _debug_info()}
        return _with_next_actions(response)
    except Exception as err:
        return _with_next_actions(
            {
                "success": False,
                "base_url": _resolve_setting("MARKETBOT_API_URL", _DEFAULT_BASE_URL),
                "debug": _debug_info(),
                "error": str(err),
            }
        )


@mcp.tool()
async def marketbot_health() -> Dict[str, Any]:
    """Return the MarketBot API health check.

    Use this first if requests fail—it confirms the MCP process can reach the
    ProductBotAI MarketBot service. Override MARKETBOT_API_URL if you're not on
    the default localhost/ngrok tunnel.
    """
    try:
        response = _request("GET", "/health")
        if isinstance(response, dict):
            response.setdefault("base_url", _resolve_setting("MARKETBOT_API_URL", _DEFAULT_BASE_URL))
            response.setdefault("debug", _debug_info())
        else:
            response = {"success": True, "data": response, "debug": _debug_info()}
        return _with_next_actions(response)
    except Exception as err:
        return _with_next_actions(
            {
                "success": False,
                "error": str(err),
                "base_url": _resolve_setting("MARKETBOT_API_URL", _DEFAULT_BASE_URL),
                "debug": _debug_info(),
            }
        )


@mcp.tool()
async def list_competitors(
    name: Optional[str] = None,
    industry: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> Dict[str, Any]:
    """List known companies (a.k.a. competitors) with optional filters.

    Args:
        name: Filter companies by name (partial match supported).
        industry: Filter companies by industry tag.
        status: Filter by lifecycle (active, monitoring, inactive).
        limit/offset: Paginate through large result sets.

    Reminder: each entry represents a single company with a canonical "common name".
    Reuse that name when creating activities to avoid duplicates.
    """
    try:
        params = {
            "name": name,
            "industry": industry,
            "status": status,
            "limit": limit,
            "offset": offset,
        }
        payload = _request("GET", "/competitors", params=params)
        payload.setdefault("debug", _debug_info())
        return _with_next_actions(payload)
    except Exception as err:
        return _with_next_actions({"success": False, "error": str(err), "debug": _debug_info()})


@mcp.tool()
async def create_competitor(
    name: str,
    website: str,
    industry: str,
    status: str = "active",
    logo_url: Optional[str] = None,
    summary: Optional[str] = None,
    competes_with_ids: Optional[Sequence[str]] = None,
    # New fields for Phase 1 extraction (optional for backward compatibility)
    overview: Optional[str] = None,
    tags: Optional[Sequence[str]] = None,
    founded_year: Optional[int] = None,
    employee_count: Optional[str] = None,
    headquarters: Optional[str] = None,
    funding: Optional[str] = None,
    revenue: Optional[str] = None,
    social_links: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Create a company record used across MarketBot dashboards.

    Args:
        name: Canonical common name (e.g., "Splunk" or "Microsoft Sentinel").
        website: Primary marketing site.
        industry: Free-form grouping used for dashboard filters.
        status: "active", "monitoring", etc.
        logo_url/summary: Optional embellishments for richer cards.
        competes_with_ids: Optional list of other competitor IDs this company overlaps with.
        overview: Detailed company description (2-3 paragraphs).
        tags: Array of tags/categories (e.g., ["customer-research", "product-management"]).
        founded_year: Year company was founded (integer).
        employee_count: Employee count range (e.g., "50-100", "1000+").
        headquarters: Headquarters location (e.g., "San Francisco, CA").
        funding: Funding information (e.g., "Series A", "$10M Series A").
        revenue: Revenue information (e.g., "$50M ARR").
        social_links: Dictionary with keys: linkedin, twitter, github, facebook.

    Always reuse the same `name` (common name) so deduplication is effortless. If the
    company already exists, `list_competitors` can help you find the canonical slug.
    """
    try:
        body = {
            "name": name,
            "website": website,
            "industry": industry,
            "status": status,
            "logo_url": logo_url,
            "summary": summary,
            "competes_with_ids": list(competes_with_ids) if competes_with_ids else None,
            # New expanded fields
            "overview": overview,
            "tags": list(tags) if tags else None,
            "founded_year": founded_year,
            "employee_count": employee_count,
            "headquarters": headquarters,
            "funding": funding,
            "revenue": revenue,
            "social_links": social_links,
        }
        payload = _request("POST", "/competitors", body=body)
        payload.setdefault("debug", _debug_info())
        return _with_next_actions(payload)
    except Exception as err:
        return _with_next_actions({"success": False, "error": str(err), "debug": _debug_info()})


@mcp.tool()
async def get_competitor_detail(competitor_id: str) -> Dict[str, Any]:
    """Fetch one company plus up to five recent activities.

    Args:
        competitor_id: The `id` returned from `list_competitors` / `create_competitor`.

    Returns the metadata block plus `recent_activities` for storyboarded cards.
    """
    try:
        payload = _request("GET", f"/competitors/{competitor_id}")
        payload.setdefault("debug", _debug_info())
        return _with_next_actions(payload)
    except Exception as err:
        return _with_next_actions({"success": False, "error": str(err), "debug": _debug_info()})


@mcp.tool()
async def update_competitor(
    competitor_id: str,
    name: Optional[str] = None,
    website: Optional[str] = None,
    industry: Optional[str] = None,
    status: Optional[str] = None,
    logo_url: Optional[str] = None,
    summary: Optional[str] = None,
    overview: Optional[str] = None,
    tags: Optional[Sequence[str]] = None,
    founded_year: Optional[int] = None,
    employee_count: Optional[str] = None,
    headquarters: Optional[str] = None,
    funding: Optional[str] = None,
    revenue: Optional[str] = None,
    social_links: Optional[Dict[str, Optional[str]]] = None,
    job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Update an existing competitor record with comprehensive data.

    ⭐ NEW: Publishes event to RabbitMQ instead of direct HTTP call.
    This ensures atomic data creation and status updates.

    This function is used after Phase 1 extraction to enrich competitor data
    with information extracted from website content via Freeplay templates.

    Args:
        competitor_id: ID of the competitor to update (required).
        name/website/industry/status: Basic competitor fields.
        logo_url/summary: Existing optional fields.
        overview: Detailed company description (2-3 paragraphs).
        tags: Array of tags/categories (e.g., ["customer-research", "product-management"]).
        founded_year: Year company was founded (integer).
        employee_count: Employee count range (e.g., "50-100", "1000+").
        headquarters: Headquarters location (e.g., "San Francisco, CA").
        funding: Funding information (e.g., "Series A", "$10M Series A").
        revenue: Revenue information (e.g., "$50M ARR").
        social_links: Dictionary with keys: linkedin, twitter, github, facebook.

    Returns the updated competitor record.
    """
    try:
        # Log request details for debugging
        print(f"[update_competitor] ========== UPDATE COMPETITOR ==========", file=sys.stderr)
        print(f"[update_competitor] Competitor ID: {competitor_id}", file=sys.stderr)
        fields_map = {
            'name': name,
            'website': website,
            'industry': industry,
            'status': status,
            'overview': overview,
            'tags': tags,
            'founded_year': founded_year,
        }
        print(f"[update_competitor] Fields to update: {[k for k, v in fields_map.items() if v is not None]}", file=sys.stderr)
        print(f"[update_competitor] MARKETBOT_API_URL: {_resolve_setting('MARKETBOT_API_URL', 'NOT SET')}", file=sys.stderr)
        print(f"[update_competitor] ========================================", file=sys.stderr)
        
        body: Dict[str, Any] = {}

        # Basic fields
        if name is not None:
            body["name"] = name
        if website is not None:
            body["website"] = website
        if industry is not None:
            body["industry"] = industry
        if status is not None:
            body["status"] = status
        if logo_url is not None:
            body["logo_url"] = logo_url
        if summary is not None:
            body["summary"] = summary

        # New expanded fields
        if overview is not None:
            body["overview"] = overview
        if tags is not None:
            body["tags"] = list(tags)
        if founded_year is not None:
            body["founded_year"] = founded_year
        if employee_count is not None:
            body["employee_count"] = employee_count
        if headquarters is not None:
            body["headquarters"] = headquarters
        if funding is not None:
            body["funding"] = funding
        if revenue is not None:
            body["revenue"] = revenue
        if social_links is not None:
            body["social_links"] = social_links

        # ⭐ NEW: Publish event
        event_result = _publish_event("COMPETITOR_UPDATED", {
            "competitorId": competitor_id,
            "competitorData": {
                "name": name,
                "website": website,
                "industry": industry,
                "status": status,
                "logo_url": logo_url,
                "summary": summary,
                "overview": overview,
                "tags": list(tags) if tags else None,
                "founded_year": founded_year,
                "employee_count": employee_count,
                "headquarters": headquarters,
                "funding": funding,
                "revenue": revenue,
                "social_links": social_links,
            },
        })
        
        if event_result.get("success"):
            return {
                "success": True,
                "message": "Competitor update event published successfully",
                "debug": _debug_info()
            }
        else:
            # ⭐ FALLBACK: Try HTTP call
            print(f"[marketbot] ⚠️ Event publishing failed, falling back to HTTP call", file=sys.stderr)
            if job_id:
                body["job_id"] = job_id
            payload = _request("PATCH", f"/competitors/{competitor_id}", body=body)
            payload.setdefault("debug", _debug_info())
            return payload
            
    except Exception as err:
        return {"success": False, "error": str(err), "debug": _debug_info()}


# ============================================================================
# Product Management Functions
# ============================================================================

@mcp.tool()
async def create_product(
    name: str,
    description: str,
    value_prop: Optional[str] = None,
    tagline: Optional[str] = None,
    markets: Optional[Sequence[str]] = None,
    benefits: Optional[str] = None,
    pricing: Optional[str] = None,
    url: Optional[str] = None,
    competitor_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a product record for a competitor.

    Used in Phase 2 extraction to store products extracted from competitor websites.

    Args:
        name: Product name (required).
        description: Product description, 2-4 sentences (required).
        value_prop: Core value proposition.
        tagline: Product tagline or slogan.
        markets: Target market segments (e.g., ["B2B", "Enterprise", "SMB"]).
        benefits: Key benefits or advantages.
        pricing: Pricing information (e.g., "Starting at $25/user/month").
        url: Product-specific URL (e.g., "/products/crm").
        competitor_id: ID of the competitor this product belongs to. If not provided, will use MARKETBOT_COMPETITOR_ID from environment.

    Returns the created product record with ID.
    """
    try:
        # Use provided competitor_id or fall back to environment variable
        actual_competitor_id = competitor_id or _resolve_setting("MARKETBOT_COMPETITOR_ID")
        if not actual_competitor_id:
            raise MarketBotError("competitor_id is required (provide as argument or set MARKETBOT_COMPETITOR_ID env var)")
        
        body = {
            "competitor_id": actual_competitor_id,
            "name": name,
            "description": description,
            "value_prop": value_prop,
            "tagline": tagline,
            "markets": list(markets) if markets else [],
            "benefits": benefits,
            "pricing": pricing,
            "url": url,
        }
        payload = _request("POST", "/products", body=body)
        payload.setdefault("debug", _debug_info())
        return payload
    except Exception as err:
        return {"success": False, "error": str(err), "debug": _debug_info()}


@mcp.tool()
async def list_products(
    competitor_id: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> Dict[str, Any]:
    """List products, optionally filtered by competitor.

    Args:
        competitor_id: Filter to products for a specific competitor.
        limit/offset: Pagination controls.

    Returns a list of products with their associated features and personas.
    """
    try:
        params = {
            "competitor_id": competitor_id,
            "limit": limit,
            "offset": offset,
        }
        payload = _request("GET", "/products", params=params)
        payload.setdefault("debug", _debug_info())
        return payload
    except Exception as err:
        return {"success": False, "error": str(err), "debug": _debug_info()}


@mcp.tool()
async def get_product_detail(product_id: str) -> Dict[str, Any]:
    """Fetch detailed information about a product including features and personas.

    Args:
        product_id: The product ID.

    Returns product details with associated features and personas.
    """
    try:
        payload = _request("GET", f"/products/{product_id}")
        payload.setdefault("debug", _debug_info())
        return payload
    except Exception as err:
        return {"success": False, "error": str(err), "debug": _debug_info()}


# ============================================================================
# Feature Management Functions
# ============================================================================

@mcp.tool()
async def create_feature(
    competitor_id: str,
    name: str,
    description: Optional[str] = None,
    category: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a feature record for a competitor.

    Features can be associated with multiple products via junction tables.
    Used in Phase 2 extraction.

    Args:
        competitor_id: ID of the competitor this feature belongs to (required).
        name: Feature name (required).
        description: What the feature does and how it works.
        category: Feature category (e.g., "AI", "Analytics", "Security", "Collaboration").

    Returns the created feature record with ID.
    """
    try:
        body = {
            "competitor_id": competitor_id,
            "name": name,
            "description": description,
            "category": category,
        }
        payload = _request("POST", "/features", body=body)
        payload.setdefault("debug", _debug_info())
        return payload
    except Exception as err:
        return {"success": False, "error": str(err), "debug": _debug_info()}


@mcp.tool()
async def list_features(
    competitor_id: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> Dict[str, Any]:
    """List features, optionally filtered by competitor or category.

    Args:
        competitor_id: Filter to features for a specific competitor.
        category: Filter by feature category.
        limit/offset: Pagination controls.

    Returns a list of features.
    """
    try:
        params = {
            "competitor_id": competitor_id,
            "category": category,
            "limit": limit,
            "offset": offset,
        }
        payload = _request("GET", "/features", params=params)
        payload.setdefault("debug", _debug_info())
        return payload
    except Exception as err:
        return {"success": False, "error": str(err), "debug": _debug_info()}


# ============================================================================
# Persona Management Functions
# ============================================================================

@mcp.tool()
async def create_persona(
    competitor_id: str,
    name: str,
    description: str,
    goals: Optional[Sequence[str]] = None,
    pain_points: Optional[Sequence[str]] = None,
    responsibilities: Optional[Sequence[str]] = None,
    role_level: Optional[str] = None,
    department: Optional[str] = None,
    decision_making_authority: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a persona record for a competitor.

    Personas can be associated with multiple products via junction tables.
    Used in Phase 2 extraction. Each persona should be unique per competitor.

    Args:
        competitor_id: ID of the competitor this persona belongs to (required).
        name: Persona name (e.g., "Product Manager", "Security Manager") (required).
        description: Detailed description of who this persona is and their role (required).
        goals: Primary objectives (e.g., ["Make data-driven decisions", "Improve security"]).
        pain_points: Challenges and frustrations.
        responsibilities: Key duties.
        role_level: Organizational level (e.g., "Individual Contributor", "Manager", "Director").
        department: Functional area (e.g., "Product", "Security", "IT").
        decision_making_authority: Level of authority (e.g., "High", "Medium", "Low").

    Returns the created persona record with ID.
    """
    try:
        body = {
            "competitor_id": competitor_id,
            "name": name,
            "description": description,
            "goals": list(goals) if goals else [],
            "pain_points": list(pain_points) if pain_points else [],
            "responsibilities": list(responsibilities) if responsibilities else [],
            "role_level": role_level,
            "department": department,
            "decision_making_authority": decision_making_authority,
        }
        payload = _request("POST", "/personas", body=body)
        payload.setdefault("debug", _debug_info())
        return payload
    except Exception as err:
        return {"success": False, "error": str(err), "debug": _debug_info()}


@mcp.tool()
async def list_personas(
    competitor_id: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> Dict[str, Any]:
    """List personas, optionally filtered by competitor.

    Args:
        competitor_id: Filter to personas for a specific competitor.
        limit/offset: Pagination controls.

    Returns a list of personas.
    """
    try:
        params = {
            "competitor_id": competitor_id,
            "limit": limit,
            "offset": offset,
        }
        payload = _request("GET", "/personas", params=params)
        payload.setdefault("debug", _debug_info())
        return payload
    except Exception as err:
        return {"success": False, "error": str(err), "debug": _debug_info()}


# ============================================================================
# Junction Table Functions (Product-Feature, Product-Persona)
# ============================================================================

@mcp.tool()
async def link_product_feature(
    product_id: str,
    feature_id: str,
) -> Dict[str, Any]:
    """Link a feature to a product (many-to-many relationship).

    Used after creating products and features to establish relationships.

    Args:
        product_id: ID of the product.
        feature_id: ID of the feature.

    Returns success status.
    """
    try:
        body = {
            "product_id": product_id,
            "feature_id": feature_id,
        }
        payload = _request("POST", "/products/features", body=body)
        payload.setdefault("debug", _debug_info())
        return payload
    except Exception as err:
        return {"success": False, "error": str(err), "debug": _debug_info()}


@mcp.tool()
async def link_product_persona(
    product_id: str,
    persona_id: str,
) -> Dict[str, Any]:
    """Link a persona to a product (many-to-many relationship).

    Used after creating products and personas to establish relationships.

    Args:
        product_id: ID of the product.
        persona_id: ID of the persona.

    Returns success status.
    """
    try:
        body = {
            "product_id": product_id,
            "persona_id": persona_id,
        }
        payload = _request("POST", "/products/personas", body=body)
        payload.setdefault("debug", _debug_info())
        return payload
    except Exception as err:
        return {"success": False, "error": str(err), "debug": _debug_info()}


# ============================================================================
# Batch Operations
# ============================================================================

@mcp.tool()
async def create_products_batch(
    products: Sequence[Dict[str, Any]],
    competitor_id: Optional[str] = None,
    job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create multiple products for a competitor in a single request.

    ⭐ NEW: Publishes event to RabbitMQ instead of direct HTTP call.
    This ensures atomic data creation and status updates.

    Args:
        products: Array of product objects, each with:
            - name (required)
            - description (required)
            - value_prop, tagline, markets, benefits, pricing, url (optional)
            - features: array of feature objects (optional, will be created and linked)
            - personas: array of persona objects (optional, will be created and linked)
        competitor_id: ID of the competitor. If not provided, will use MARKETBOT_COMPETITOR_ID from environment.
        job_id: Optional job ID for status reporting.

    Returns success status and product count.
    """
    try:
        # Use provided competitor_id or fall back to environment variable
        actual_competitor_id = competitor_id or _resolve_setting("MARKETBOT_COMPETITOR_ID")
        if not actual_competitor_id:
            raise MarketBotError("competitor_id is required (provide as argument or set MARKETBOT_COMPETITOR_ID env var)")
        
        # Validate products array is not empty
        products_list = list(products) if products else []
        if not products_list or len(products_list) == 0:
            raise MarketBotError("products array cannot be empty. Provide at least one product with 'name' and 'description' fields.")
        
        # Log request details for debugging
        print(f"[create_products_batch] ========== CREATE PRODUCTS BATCH ==========", file=sys.stderr)
        print(f"[create_products_batch] Competitor ID: {actual_competitor_id}", file=sys.stderr)
        print(f"[create_products_batch] Products count: {len(products_list)}", file=sys.stderr)
        print(f"[create_products_batch] Product names: {[p.get('name', 'N/A') for p in products_list[:5]]}", file=sys.stderr)
        print(f"[create_products_batch] MARKETBOT_API_URL: {_resolve_setting('MARKETBOT_API_URL', 'NOT SET')}", file=sys.stderr)
        print(f"[create_products_batch] ==========================================", file=sys.stderr)
        
        # ⭐ NEW: Publish event instead of HTTP call
        event_result = _publish_event("PRODUCTS_CREATED", {
            "competitorId": actual_competitor_id,
            "products": products_list,
        })
        
        if event_result.get("success"):
            return {
                "success": True,
                "message": f"Products event published successfully",
                "products_count": len(products_list),
                "debug": _debug_info()
            }
        else:
            # ⭐ FALLBACK: Try HTTP call if event publishing fails
            print(f"[marketbot] ⚠️ Event publishing failed, falling back to HTTP call", file=sys.stderr)
            body = {
                "competitor_id": actual_competitor_id,
                "products": products_list,
            }
            if job_id:
                body["job_id"] = job_id
            payload = _request("POST", "/products/batch", body=body)
            payload.setdefault("debug", _debug_info())
            return payload
            
    except Exception as err:
        return {"success": False, "error": str(err), "debug": _debug_info()}


# ============================================================================
# Activity Management Functions
# ============================================================================

@mcp.tool()
async def list_activities(
    competitor_id: Optional[str] = None,
    category: Optional[str] = None,
    time_range_days: Optional[int] = None,
    search: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> Dict[str, Any]:
    """List or search activities tied to tracked companies.

    Args:
        competitor_id: Filter to a single company.
        category: e.g., Product, Pricing, Funding, News.
        time_range_days: quick lookback filtering.
        search: semantic search term (uses Chroma similarity).
        limit/offset: Pagination controls.
    """
    try:
        params = {
            "competitor_id": competitor_id,
            "category": category,
            "time_range_days": time_range_days,
            "search": search,
            "limit": limit,
            "offset": offset,
        }
        payload = _request("GET", "/activities", params=params)
        payload.setdefault("debug", _debug_info())
        return _with_next_actions(payload)
    except Exception as err:
        return _with_next_actions({"success": False, "error": str(err), "debug": _debug_info()})


@mcp.tool()
async def create_activity(
    title: str,
    description: Optional[str] = None,
    category: str = "News",
    source_url: Optional[str] = None,
    source_type: Optional[str] = None,
    detected_at: Optional[str] = None,
    published_at: Optional[str] = None,
    confidence_score: Optional[float] = None,
    is_verified: bool = False,
    competitor_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Append a competitive intel activity (product launch, pricing move, etc.).

    Args:
        title/description: Short headline plus supporting blurb.
        category: Product, Pricing, Funding, News, etc.
        source_url/source_type: Where the intel came from.
        detected_at/published_at: ISO timestamps (optional; omit if unknown).
        confidence_score/is_verified: Confidence bookkeeping.
        competitor_id: ID of the company record. If not provided, will use MARKETBOT_COMPETITOR_ID from environment.

    Tip: omit `detected_at` unless you have a precise timestamp—MarketBot will fill in
    the current time, avoiding malformed values.
    """
    try:
        # Use provided competitor_id or fall back to environment variable
        actual_competitor_id = competitor_id or _resolve_setting("MARKETBOT_COMPETITOR_ID")
        if not actual_competitor_id:
            raise MarketBotError("competitor_id is required (provide as argument or set MARKETBOT_COMPETITOR_ID env var)")
        
        body = {
            "competitor_id": actual_competitor_id,
            "title": title,
            "description": description,
            "category": category,
            "source_url": source_url,
            "source_type": source_type,
            "detected_at": detected_at,
            "published_at": published_at,
            "confidence_score": confidence_score,
            "is_verified": is_verified,
        }
        payload = _request("POST", "/activities", body=body)
        payload.setdefault("debug", _debug_info())
        return _with_next_actions(payload)
    except Exception as err:
        return _with_next_actions({"success": False, "error": str(err), "debug": _debug_info()})


@mcp.tool()
async def create_activities_batch(
    activities: Sequence[Dict[str, Any]],
    competitor_id: Optional[str] = None,
    job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create multiple activities for a competitor in a single request.

    ⭐ NEW: Publishes event to RabbitMQ instead of direct HTTP call.
    This ensures atomic data creation and status updates.

    Args:
        activities: Array of activity objects, each with:
            - title (required)
            - description (optional)
            - category (required): Product, Pricing, Funding, News, etc.
            - source_url, source_type (optional)
            - published_at (optional): ISO timestamp
            - confidence_score (optional): 0.0 to 1.0
            - tags (optional): Array of strings
        competitor_id: ID of the competitor. If not provided, will use MARKETBOT_COMPETITOR_ID from environment.
        job_id: Optional job ID for status reporting.

    Returns success status and activity count.
    """
    try:
        actual_competitor_id = competitor_id or _resolve_setting("MARKETBOT_COMPETITOR_ID")
        if not actual_competitor_id:
            raise MarketBotError("competitor_id is required")
        
        activities_list = list(activities) if activities else []
        if not activities_list or len(activities_list) == 0:
            raise MarketBotError("activities array cannot be empty")
        
        # Log request details for debugging
        print(f"[create_activities_batch] ========== CREATE ACTIVITIES BATCH ==========", file=sys.stderr)
        print(f"[create_activities_batch] Competitor ID: {actual_competitor_id}", file=sys.stderr)
        print(f"[create_activities_batch] Activities count: {len(activities_list)}", file=sys.stderr)
        print(f"[create_activities_batch] Activity titles: {[a.get('title', 'N/A') for a in activities_list[:5]]}", file=sys.stderr)
        print(f"[create_activities_batch] MARKETBOT_API_URL: {_resolve_setting('MARKETBOT_API_URL', 'NOT SET')}", file=sys.stderr)
        print(f"[create_activities_batch] ============================================", file=sys.stderr)
        
        # ⭐ NEW: Publish event
        event_result = _publish_event("ACTIVITIES_CREATED", {
            "competitorId": actual_competitor_id,
            "activities": activities_list,
        })
        
        if event_result.get("success"):
            return {
                "success": True,
                "message": f"Activities event published successfully",
                "activities_count": len(activities_list),
                "debug": _debug_info()
            }
        else:
            # ⭐ FALLBACK: Try HTTP call
            print(f"[marketbot] ⚠️ Event publishing failed, falling back to HTTP call", file=sys.stderr)
            body = {
                "competitor_id": actual_competitor_id,
                "activities": activities_list,
            }
            if job_id:
                body["job_id"] = job_id
            payload = _request("POST", "/activities/batch", body=body)
            payload.setdefault("debug", _debug_info())
            return payload
            
    except Exception as err:
        return {"success": False, "error": str(err), "debug": _debug_info()}


@mcp.tool()
async def list_trends(limit: int = 10) -> Dict[str, Any]:
    """Return trending keywords extracted from all competitor activities.

    Args:
        limit: Number of ranked keywords to fetch (default 10).
    """
    try:
        payload = _request("GET", "/trends", params={"limit": limit})
        payload.setdefault("debug", _debug_info())
        return _with_next_actions(payload)
    except Exception as err:
        return _with_next_actions({"success": False, "error": str(err), "debug": _debug_info()})


@mcp.tool()
async def recompute_trends(top_n: int = 25, lookback_days: int = 180) -> Dict[str, Any]:
    """Recompute trending keywords from activities and return the updated list.

    Args:
        top_n: Number of keywords to keep (1–50; default 25).
        lookback_days: Only consider activities in this recent window (default 180).

    Notes:
        - Calls POST /api/trends/recompute under the hood.
        - After recompute, GET /api/trends will reflect the new rankings.
    """
    try:
        body = {"top_n": top_n, "lookback_days": lookback_days}
        payload = _request("POST", "/trends", body=body)
        payload.setdefault("debug", _debug_info())
        return _with_next_actions(payload)
    except Exception as err:
        return _with_next_actions({"success": False, "error": str(err), "debug": _debug_info()})


@mcp.tool()
async def list_alerts(unread_only: bool = False) -> Dict[str, Any]:
    """List alert records (optionally unread only).

    Args:
        unread_only: True to fetch only unread alerts (UI badge scenario).
    """
    try:
        params = {"unread_only": str(bool(unread_only)).lower()}
        payload = _request("GET", "/alerts", params=params)
        payload.setdefault("debug", _debug_info())
        return _with_next_actions(payload)
    except Exception as err:
        return _with_next_actions({"success": False, "error": str(err), "debug": _debug_info()})


@mcp.tool()
async def update_alert(alert_id: str, is_read: bool = True) -> Dict[str, Any]:
    """Mark an alert read/unread."""
    try:
        body = {"is_read": is_read}
        payload = _request("PATCH", f"/alerts/{alert_id}", body=body)
        payload.setdefault("debug", _debug_info())
        return _with_next_actions(payload)
    except Exception as err:
        return _with_next_actions({"success": False, "error": str(err), "debug": _debug_info()})


@mcp.tool()
async def get_processed_urls(
    limit: int = 200,
    since_hours: Optional[int] = None,
) -> Dict[str, Any]:
    """Return recent processed URLs from the local state file."""
    state = load_state()
    entries = iter_state_urls(state)

    if since_hours is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max(0, since_hours))
        entries = [
            (url, payload)
            for url, payload in entries
            if parse_timestamp(payload.get("timestamp")) and parse_timestamp(payload.get("timestamp")) >= cutoff
        ]

    # Sort newest first
    entries.sort(
        key=lambda pair: parse_timestamp(pair[1].get("timestamp")) or datetime.fromtimestamp(0, tz=timezone.utc),
        reverse=True,
    )

    limited = entries[: max(1, limit)]
    return {
        "success": True,
        "count": len(limited),
        "last_updated": state.get("last_updated"),
        "items": [
            {
                "url": url,
                "timestamp": payload.get("timestamp"),
                "metadata": {k: v for k, v in payload.items() if k != "timestamp"},
            }
            for url, payload in limited
        ],
    }


@mcp.tool()
async def filter_processed_urls(
    urls: List[str],
    lookback_hours: int = 24,
    block_domains: Optional[List[str]] = None,
    normalize: bool = True,
) -> Dict[str, Any]:
    """Filter out URLs already processed recently or on the block list."""
    incoming = [u for u in urls if isinstance(u, str) and u.strip()]
    if not incoming:
        return {
            "success": True,
            "incoming": len(urls),
            "filtered_urls": [],
            "skipped": {"state_recent": [], "blocked_domains": [], "invalid": urls},
        }

    state = load_state()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(0, lookback_hours))
    blocked = block_domains or []
    state_entries = iter_state_urls(state)

    recent_norms = {
        normalize_url(url): payload
        for url, payload in state_entries
        if parse_timestamp(payload.get("timestamp")) and parse_timestamp(payload.get("timestamp")) >= cutoff
    }

    filtered: List[str] = []
    skipped_state: List[str] = []
    skipped_blocked: List[str] = []
    skipped_invalid: List[str] = []

    for raw_url in incoming:
        if not raw_url:
            skipped_invalid.append(raw_url)
            continue

        norm = normalize_url(raw_url) if normalize else raw_url
        if is_blocked_domain(norm, blocked):
            skipped_blocked.append(raw_url)
            continue
        if norm in recent_norms:
            skipped_state.append(raw_url)
            continue
        if raw_url not in filtered:
            filtered.append(raw_url)

    return {
        "success": True,
        "incoming": len(urls),
        "filtered_urls": filtered,
        "skipped": {
            "state_recent": skipped_state,
            "blocked_domains": skipped_blocked,
            "invalid": skipped_invalid,
        },
        "lookback_hours": lookback_hours,
        "block_domains": blocked or list(DEFAULT_BLOCKED_DOMAINS),
    }


@mcp.tool()
async def report_progress(
    current_step: str,
    message: Optional[str] = None,
    urls_processed: Optional[int] = None,
    total_urls: Optional[int] = None,
) -> Dict[str, Any]:
    """Report progress to prevent false stuck detection.
    
    Call this every 2 minutes during extraction to update activity timestamp.
    
    Args:
        current_step: Description of current step (e.g., "crawling website", "extracting products")
        message: Optional progress message
        urls_processed: Number of URLs processed so far
        total_urls: Total URLs to process
    """
    try:
        _maybe_send_heartbeat(current_step, message)
        
        # Also send explicit progress update
        event_result = _publish_event("PROGRESS_UPDATE", {
            "progress": {
                "currentStep": current_step,
                "urlsProcessed": urls_processed,
                "totalUrls": total_urls,
                "message": message,
            }
        })
        
        return {
            "success": event_result.get("success", False),
            "message": "Progress reported",
            "debug": _debug_info()
        }
    except Exception as err:
        return {"success": False, "error": str(err), "debug": _debug_info()}


@mcp.tool()
async def report_error(
    message: str,
    error_type: str = "TRANSIENT",
    code: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Report error with context for proper classification.
    
    Args:
        message: Error message
        error_type: 'TRANSIENT' or 'PERMANENT'
        code: Optional error code
        context: Optional additional context
    """
    try:
        import traceback
        stack_trace = traceback.format_exc()
        
        event_result = _publish_event("ERROR_REPORTED", {
            "error": {
                "message": message,
                "type": error_type,
                "code": code,
                "stackTrace": stack_trace,
                "context": context or {},
            }
        })
        
        return {
            "success": event_result.get("success", False),
            "message": "Error reported",
            "debug": _debug_info()
        }
    except Exception as err:
        return {"success": False, "error": str(err), "debug": _debug_info()}


@mcp.tool()
async def mark_urls_processed(
    entries: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Mark URLs as processed with optional metadata.

    This function:
    1. Stores URLs locally in .marketbot-processed.json (for backward compatibility)
    2. Stores URLs in Productbot database via API endpoint (for knowledge base)

    Args:
        entries: List of URL entry objects, each with:
            - url (required): The URL that was processed
            - timestamp (optional): ISO timestamp (defaults to current time)
            - competitor_id (required): ID of the competitor this URL belongs to
            - source (optional): "initial_scrape", "alert_job", "manual" (defaults to "initial_scrape")
            - category (optional): "Initial", "Product", "Pricing", "Funding", "News" (defaults to "Initial")
            - activity_id (optional): ID of activity if URL resulted in an activity

    Returns:
        Success status with count of URLs stored in database
    """
    if not isinstance(entries, list):
        return {"success": False, "error": "entries must be a list of objects"}

    # 1. Store locally (backward compatibility)
    state = load_state()
    urls_state = state.setdefault("urls", {})
    local_updated = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        url = entry.get("url")
        if not isinstance(url, str) or not url.strip():
            continue
        timestamp = entry.get("timestamp")
        if not timestamp:
            timestamp = iso_now()
        metadata = {k: v for k, v in entry.items() if k not in {"url", "timestamp"}}
        payload: Dict[str, Any] = {"timestamp": timestamp}
        if metadata:
            payload.update(metadata)
        urls_state[url] = payload
        local_updated += 1

    if local_updated > 0:
        state["last_updated"] = iso_now()
        save_state(state)

    # 2. Store in Productbot database via API
    db_result = {"success": False, "updated": 0}
    try:
        # Prepare entries for API (ensure all required fields are present)
        api_entries = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            url = entry.get("url")
            if not isinstance(url, str) or not url.strip():
                continue
            if not entry.get("competitor_id"):
                # Skip entries without competitor_id (can't store in DB without it)
                continue

            api_entry = {
                "url": url,
                "competitor_id": entry.get("competitor_id"),
                "timestamp": entry.get("timestamp") or iso_now(),
                "source": entry.get("source", "initial_scrape"),
                "category": entry.get("category", "Initial"),
            }
            if entry.get("activity_id"):
                api_entry["activity_id"] = entry.get("activity_id")

            api_entries.append(api_entry)

        if api_entries:
            print(f"[mark_urls_processed] Preparing to call API with {len(api_entries)} entries", file=sys.stderr)
            print(f"[mark_urls_processed] API entries preview: {api_entries[:2]}", file=sys.stderr)
            db_result = _request("POST", "/processed-urls", body={"entries": api_entries})
            print(f"[mark_urls_processed] API call result: success={db_result.get('success')}, updated={db_result.get('data', {}).get('updated', 0)}", file=sys.stderr)
            db_result.setdefault("debug", _debug_info())
        else:
            print(f"[mark_urls_processed] ⚠️ No API entries to send (all entries filtered out)", file=sys.stderr)
    except Exception as err:
        # Don't fail the whole operation if API call fails - local storage succeeded
        print(f"[mark_urls_processed] ❌ API call failed: {err}", file=sys.stderr)
        import traceback
        print(f"[mark_urls_processed] Traceback: {traceback.format_exc()}", file=sys.stderr)
        db_result = {
            "success": False,
            "error": str(err),
            "debug": _debug_info(),
        }

    # Return combined result
    return {
        "success": True,
        "updated": db_result.get("data", {}).get("updated", 0) if db_result.get("success") else 0,
        "total_urls": db_result.get("data", {}).get("total_urls", 0) if db_result.get("success") else len(urls_state),
        "local_storage": {
            "updated": local_updated,
            "total_urls": len(urls_state),
        },
        "database_storage": db_result,
    }


@mcp.tool()
async def get_processed_urls_local(
    limit: int = 200,
    since_hours: Optional[int] = None,
) -> Dict[str, Any]:
    """Return processed URLs from the shared /workspace/.marketbot-processed.json state file."""
    state = load_state()
    entries = iter_state_urls(state)
    if since_hours is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max(0, since_hours))
        entries = [
            (url, payload)
            for url, payload in entries
            if parse_timestamp(payload.get("timestamp")) and parse_timestamp(payload.get("timestamp")) >= cutoff
        ]

    entries.sort(
        key=lambda pair: parse_timestamp(pair[1].get("timestamp")) or datetime.fromtimestamp(0, tz=timezone.utc),
        reverse=True,
    )

    limited = entries[: max(1, limit)]
    return {
        "success": True,
        "count": len(limited),
        "last_updated": state.get("last_updated"),
        "items": [
            {
                "url": url,
                "timestamp": payload.get("timestamp"),
                "metadata": {k: v for k, v in payload.items() if k != "timestamp"},
            }
            for url, payload in limited
        ],
    }


if __name__ == "__main__":
    # ⭐ SIMPLIFIED: Just verify env vars are available (they should already be in process environment)
    # Codex Gateway passes env vars directly to the process via spawn(), so they're already in os.environ
    print(f"[marketbot] ========== MODULE INITIALIZATION ==========", file=sys.stderr)
    
    # Check critical variables in process environment
    api_key = os.getenv("MARKETBOT_API_KEY")
    team_id = os.getenv("MARKETBOT_TEAM_ID")
    job_id = os.getenv("CODEX_JOB_ID")
    session_id = os.getenv("CODEX_SESSION_ID")
    api_url = os.getenv("MARKETBOT_API_URL")
    competitor_id = os.getenv("MARKETBOT_COMPETITOR_ID")
    
    print(f"[marketbot] Process Environment Check:", file=sys.stderr)
    print(f"[marketbot]   MARKETBOT_API_KEY: {'✅ SET' if api_key else '❌ MISSING'} ({len(api_key) if api_key else 0} chars)", file=sys.stderr)
    if api_key:
        print(f"[marketbot]   MARKETBOT_API_KEY (masked): {api_key[:10]}...{api_key[-4:] if len(api_key) > 14 else '***'}", file=sys.stderr)
    print(f"[marketbot]   MARKETBOT_TEAM_ID: {'✅ SET' if team_id else '❌ MISSING'}", file=sys.stderr)
    print(f"[marketbot]   MARKETBOT_API_URL: {'✅ SET' if api_url else '❌ MISSING'} ({api_url if api_url else 'N/A'})", file=sys.stderr)
    print(f"[marketbot]   CODEX_JOB_ID: {'✅ SET' if job_id else '❌ MISSING'} ({job_id if job_id else 'N/A'})", file=sys.stderr)
    print(f"[marketbot]   CODEX_SESSION_ID: {'✅ SET' if session_id else '❌ MISSING'} ({session_id if session_id else 'N/A'})", file=sys.stderr)
    print(f"[marketbot]   MARKETBOT_COMPETITOR_ID: {'✅ SET' if competitor_id else '❌ MISSING'} ({competitor_id if competitor_id else 'N/A'})", file=sys.stderr)
    
    # If critical vars are missing, try loading from file as fallback
    # ⚠️ NOTE: We read from file but DON'T set os.environ to prevent leakage
    if not api_key or not team_id:
        print(f"[marketbot] ⚠️ Critical env vars missing in process environment, attempting file fallback...", file=sys.stderr)
        try:
            env_values = _load_env_vars_from_file()
            if env_values:
                print(f"[marketbot] ✅ Loaded {len(env_values)} vars from session-specific file (NOT set in os.environ)", file=sys.stderr)
                # Get values from file (not from os.environ since we don't set it)
                api_key = env_values.get("MARKETBOT_API_KEY") or api_key
                team_id = env_values.get("MARKETBOT_TEAM_ID") or team_id
                print(f"[marketbot] After file load - API_KEY: {'✅ SET' if api_key else '❌ MISSING'}, TEAM_ID: {'✅ SET' if team_id else '❌ MISSING'}", file=sys.stderr)
        except Exception as e:
            print(f"[marketbot] ❌ File fallback failed: {e}", file=sys.stderr)
            import traceback
            print(f"[marketbot] Traceback: {traceback.format_exc()}", file=sys.stderr)
    
    print(f"[marketbot] ==========================================", file=sys.stderr)
    
    # Match other MCP tools: run the server over stdio for the Codex harness.
    mcp.run(transport="stdio")
