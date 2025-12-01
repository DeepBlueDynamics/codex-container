#!/usr/bin/env python3
"""
Example: Crawl Hacker News and summarize AI stories.

Robust client that handles:
- Connection timeouts gracefully
- Falls back to session polling if initial request hangs
- Reconnects and continues monitoring
- Shows progress during long-running tasks
- Logs all API calls and saves results to hn_top.json
"""

import json
import time
import socket
import urllib.request
import urllib.error
import os
from datetime import datetime
from typing import Dict, Any, Optional, Tuple

GATEWAY_URL = "http://localhost:4000"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "hn_top.json")
LOG_FILE = os.path.join(SCRIPT_DIR, "hn_api_log.txt")


def log_api(method: str, url: str, status: str, response_preview: str = ""):
    """Log API calls to file and console."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] {method} {url} -> {status}"
    if response_preview:
        log_line += f" | {response_preview[:100]}"
    print(f"    API: {method} {url} -> {status}")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(log_line + "\n")

# The prompt for our multi-page crawl and summarize task
CRAWL_PROMPT = """
You have access to gnosis-crawl MCP tools. Complete these tasks:

IMPORTANT: Only use the crawl_url tool. Do NOT use raw_html.

1. CRAWL HN FRONT PAGE (3 pages):
   - Use crawl_url to fetch https://news.ycombinator.com/
   - Use crawl_url to fetch https://news.ycombinator.com/?p=2
   - Use crawl_url to fetch https://news.ycombinator.com/?p=3

2. CRAWL HN NEWEST (2 pages):
   - Use crawl_url to fetch https://news.ycombinator.com/newest
   - Use crawl_url to fetch https://news.ycombinator.com/newest?next=<id>&n=31 (get the next link from first page)

3. ANALYZE:
   - From all crawled pages, identify stories related to AI, ML, LLMs, or machine learning
   - Note the title, points, and comment count for each

4. SUMMARIZE:
   - Create a brief summary of the AI/ML landscape on HN today
   - List the top 5 AI-related stories by points
   - Note any interesting trends or discussions

Return your report in markdown format wrapped in ```markdown and ``` markers:

```markdown
# HN AI/ML Report

## Crawl Summary
- Pages crawled: X
- Total stories found: X
- AI stories found: X

## Top 5 AI Stories
1. **Title** - X points, X comments (front/newest)
2. ...

## Trends
Brief analysis of AI trends on HN today.

## All AI Stories
| Title | Points | Comments | Source |
|-------|--------|----------|--------|
| ... | ... | ... | ... |
```
"""


def safe_request(url: str, data: bytes = None, method: str = "GET",
                 timeout: int = 30, retries: int = 3, log: bool = True) -> Tuple[Optional[Dict], Optional[str]]:
    """
    Make an HTTP request with retries and proper error handling.

    Returns: (response_dict, error_string)
    """
    headers = {"Content-Type": "application/json"} if data else {}

    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8")
                result = json.loads(body)
                if log:
                    preview = body[:80].replace('\n', ' ')
                    log_api(method, url, f"200 OK", preview)
                return result, None
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8") if e.fp else ""
            if log:
                log_api(method, url, f"HTTP {e.code}")
            try:
                return json.loads(body), None  # Some errors return valid JSON
            except:
                return None, f"HTTP {e.code}: {body[:200]}"
        except urllib.error.URLError as e:
            if log and attempt == retries - 1:
                log_api(method, url, f"URLError: {e.reason}")
            if attempt < retries - 1:
                time.sleep(2 ** attempt)  # Exponential backoff
                continue
            return None, f"Connection error: {e.reason}"
        except socket.timeout:
            if log and attempt == retries - 1:
                log_api(method, url, "Timeout")
            if attempt < retries - 1:
                time.sleep(1)
                continue
            return None, "Socket timeout"
        except Exception as e:
            if log:
                log_api(method, url, f"Error: {e}")
            return None, str(e)

    return None, "Max retries exceeded"


def check_gateway() -> Tuple[bool, Dict]:
    """Check if gateway is available."""
    result, err = safe_request(f"{GATEWAY_URL}/status", timeout=10)
    if err:
        return False, {"error": err}
    return True, result


def list_sessions(limit: int = 10) -> Dict[str, Any]:
    """GET /sessions - List recent sessions."""
    result, err = safe_request(f"{GATEWAY_URL}/sessions?limit={limit}", timeout=15)
    return result if result else {"error": err}


def get_session(session_id: str, include_events: bool = False, tail: int = 200) -> Dict[str, Any]:
    """GET /sessions/:id - Get session details."""
    params = []
    if include_events:
        params.append("include_events=1")
    if tail:
        params.append(f"tail={tail}")

    url = f"{GATEWAY_URL}/sessions/{session_id}"
    if params:
        url += "?" + "&".join(params)

    result, err = safe_request(url, timeout=15)
    return result if result else {"error": err}


def find_active_session() -> Optional[str]:
    """Look for any running session."""
    sessions = list_sessions(limit=10)
    if "sessions" in sessions:
        for s in sessions["sessions"]:
            status = s.get("status", "")
            if status in ("running", "starting"):
                return s.get("session_id")
    return None


def start_task_async(prompt: str, model: str = "gpt-5.1-codex-mini") -> Tuple[Optional[str], Optional[str]]:
    """
    Start a task and return session_id as soon as possible.

    Strategy:
    1. Send request with short socket timeout
    2. If it completes, great - return session_id
    3. If it times out, check /sessions for a running session
    4. Return (session_id, error) tuple
    """
    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "model": model,
        "persistent": True,
        "timeout_ms": 300000,  # 5 min task timeout
        "return_session_url": True,
    }

    data = json.dumps(payload).encode("utf-8")

    # Try with a short timeout first - we just want to see if it starts
    print("    Sending request to gateway...")

    try:
        req = urllib.request.Request(
            f"{GATEWAY_URL}/completion",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        # Short timeout - if task starts quickly, we get result
        # If not, we'll poll for it
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            session_id = result.get("gateway_session_id") or result.get("session_id")
            return session_id, None
    except socket.timeout:
        pass  # Expected for long tasks
    except urllib.error.URLError as e:
        if "timed out" not in str(e.reason).lower():
            return None, str(e.reason)
    except Exception as e:
        return None, str(e)

    # Request timed out - check if session was created
    print("    Request still processing, checking for session...")
    time.sleep(2)

    session_id = find_active_session()
    if session_id:
        return session_id, None

    # Wait a bit more and try again
    for i in range(5):
        time.sleep(3)
        session_id = find_active_session()
        if session_id:
            return session_id, None
        print(f"    Still waiting for session to appear... ({i+1}/5)")

    return None, "Could not find session after starting task"


def poll_session(session_id: str, poll_interval: int = 5, max_wait: int = 600) -> Dict[str, Any]:
    """
    Poll a session until it completes.

    Shows progress updates and handles connection issues gracefully.
    """
    start = time.time()
    last_status = None
    last_event_count = 0
    consecutive_errors = 0

    while time.time() - start < max_wait:
        detail = get_session(session_id, include_events=False, tail=50)

        if "error" in detail:
            consecutive_errors += 1
            if consecutive_errors > 5:
                print(f"    Too many errors, stopping poll")
                return detail
            print(f"    Connection error, retrying... ({consecutive_errors}/5)")
            time.sleep(poll_interval)
            continue

        consecutive_errors = 0
        status = detail.get("status", "unknown")
        elapsed = int(time.time() - start)

        # Show status changes
        if status != last_status:
            print(f"    [{elapsed:3d}s] Status: {status}")
            last_status = status

        # Show stdout progress if available
        stdout_info = detail.get("stdout", {})
        if stdout_info.get("tail"):
            lines = stdout_info["tail"].strip().split("\n")
            # Show last meaningful line
            for line in reversed(lines):
                line = line.strip()
                if line and not line.startswith("{") and len(line) < 100:
                    print(f"    [{elapsed:3d}s] > {line[:70]}")
                    break

        # Check if done
        if status in ("idle", "completed", "error", "timeout"):
            # Get full details with large tail to capture output
            return get_session(session_id, include_events=True, tail=5000)

        time.sleep(poll_interval)

    return {"error": "Polling timed out", "session_id": session_id}


def extract_result(session: Dict[str, Any]) -> Optional[str]:
    """Extract the final agent response from session."""
    import re

    def find_markdown_block(text: str) -> Optional[str]:
        """Find markdown content between ```markdown and ``` markers."""
        # Look for ```markdown ... ``` block
        match = re.search(r'```markdown\s*(.*?)\s*```', text, re.DOTALL)
        if match:
            return match.group(1).strip()
        # Also try generic ``` blocks that contain our report headers
        for match in re.finditer(r'```\s*(.*?)\s*```', text, re.DOTALL):
            content = match.group(1)
            if '# HN' in content or '## Crawl Summary' in content or '## Top' in content:
                return content.strip()
        return None

    # First try events - look for agent_message with markdown
    events = session.get("events", [])
    for event in reversed(events):
        if event.get("type") == "item.completed":
            item = event.get("item", {})
            if item.get("type") == "agent_message":
                text = item.get("text", "")
                # Check if it contains markdown block
                md = find_markdown_block(text)
                if md:
                    return md
                # If no markdown markers but has report content, return as-is
                if '# HN' in text or '## Crawl' in text or '## Top' in text:
                    return text

    # Try content field directly
    content = session.get("content", "")
    if content:
        md = find_markdown_block(content)
        if md:
            return md
        if '# HN' in content or '## Crawl' in content or '## Top' in content:
            return content

    # Parse stdout for markdown output
    stdout = session.get("stdout", {}).get("tail", "")
    if stdout:
        # Look for markdown block in stdout
        md = find_markdown_block(stdout)
        if md:
            return md

        # Look for agent_message text in JSON events and extract markdown from it
        for match in re.finditer(r'"type"\s*:\s*"agent_message"[^}]*"text"\s*:\s*"([^"]*(?:\\.[^"]*)*)"', stdout):
            text = match.group(1)
            # Unescape JSON string
            text = text.replace('\\n', '\n').replace('\\"', '"').replace('\\\\', '\\')
            md = find_markdown_block(text)
            if md:
                return md
            if '# HN' in text or '## Crawl' in text or '## Top' in text:
                return text

    return None


def count_tool_calls(session: Dict[str, Any]) -> Dict[str, int]:
    """Count tool calls by type."""
    events = session.get("events", [])
    counts = {}

    for event in events:
        if event.get("type") == "item.completed":
            item = event.get("item", {})
            if item.get("type") == "mcp_tool_call":
                tool = f"{item.get('server', '?')}::{item.get('tool', '?')}"
                counts[tool] = counts.get(tool, 0) + 1

    return counts


def save_results(session_id: str, result: Dict[str, Any], content: Optional[str]):
    """Save full session result and extracted content to hn_top.json."""
    output = {
        "session_id": session_id,
        "timestamp": datetime.now().isoformat(),
        "status": result.get("status"),
        "content": content,
        "tool_calls": count_tool_calls(result),
        "stdout_tail": result.get("stdout", {}).get("tail", "")[-2000:],
        "events_count": len(result.get("events", [])),
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print(f"\n    Results saved to: {OUTPUT_FILE}")


def main():
    print("=" * 70)
    print("HN CRAWL & SUMMARIZE - Robust Gateway Client")
    print("=" * 70)
    print(f"Log file: {LOG_FILE}")
    print(f"Output file: {OUTPUT_FILE}")

    # Clear log file
    with open(LOG_FILE, "w") as f:
        f.write(f"=== HN Crawl Run {datetime.now().isoformat()} ===\n")

    # Step 1: Check gateway
    print("\n[1] Checking gateway...")
    ok, status = check_gateway()
    if not ok:
        print(f"    ERROR: {status.get('error')}")
        print("    Is the gateway running? Try: .\\scripts\\codex_container.ps1 -Serve")
        return

    concurrency = status.get("concurrency", {})
    print(f"    Gateway OK - {concurrency.get('available', '?')}/{concurrency.get('max', '?')} slots available")

    # Step 2: Check for existing running session
    print("\n[2] Checking for existing sessions...")
    existing = find_active_session()
    if existing:
        print(f"    Found running session: {existing}")
        print("    Resuming monitoring...")
        session_id = existing
    else:
        print("    No active sessions, starting new task...")

        # Step 3: Start the task
        print("\n[3] Starting HN crawl task...")
        session_id, err = start_task_async(CRAWL_PROMPT)

        if err:
            print(f"    ERROR: {err}")
            return

        print(f"    Session ID: {session_id}")

    # Step 4: Poll for completion
    print(f"\n[4] Monitoring session (may take 2-5 minutes)...")
    print("-" * 50)

    result = poll_session(session_id, poll_interval=5, max_wait=600)

    print("-" * 50)

    if "error" in result:
        print(f"\n    ERROR: {result['error']}")
        print(f"    Check session manually: curl {GATEWAY_URL}/sessions/{session_id}")
        return

    # Step 5: Show results
    print(f"\n[5] RESULTS")
    print("=" * 70)

    status = result.get("status", "unknown")
    print(f"Status: {status}")

    # Tool call summary
    tool_counts = count_tool_calls(result)
    if tool_counts:
        print(f"\nTool calls:")
        for tool, count in sorted(tool_counts.items()):
            print(f"  {tool}: {count}")

    # Final content
    content = extract_result(result)

    # Save results to file
    save_results(session_id, result, content)

    if content:
        print(f"\n{'=' * 70}")
        print("AGENT RESPONSE:")
        print("=" * 70)
        print(content)
    else:
        print("\nNo structured agent response found.")
        print("Showing raw stdout output:\n")

        # Show full stdout
        stdout = result.get("stdout", {}).get("tail", "")
        if stdout:
            # Try to find and pretty-print any JSON in the output
            lines = stdout.strip().split('\n')
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                # Skip internal event JSON
                if '"type":' in line and ('"item.' in line or '"turn.' in line or '"thread.' in line):
                    continue
                # Try to pretty-print JSON lines
                if line.startswith('{'):
                    try:
                        parsed = json.loads(line)
                        print(json.dumps(parsed, indent=2))
                        continue
                    except:
                        pass
                print(line)

    print("\n" + "=" * 70)
    print("Done!")


if __name__ == "__main__":
    main()
