#!/usr/bin/env python3
"""
Example: Release/Change Intelligence with bounded crawling and a term-graph-driven prompt.

This mirrors the HN example flow: send a single prompt to the gateway, let the
agent call MCP tools (gnosis-crawl + SerpAPI) under strict caps, and poll until
completion. Results are saved to release_intel.json.
"""

import json
import os
import socket
import time
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:4000")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "release_intel.json")
LOG_FILE = os.path.join(SCRIPT_DIR, "release_intel_log.txt")

# Edit this seed list to your target product/repo.
SEED_URLS = """
- https://example.com/docs/changelog
- https://example.com/blog
- https://github.com/org/repo/releases
"""

RELEASE_INTEL_PROMPT = f"""
You are an agent with access to gnosis-crawl and SerpAPI tools.

Objective: release/change intelligence (features, breaking changes, pricing/licensing, deprecations).

Use ONLY these tools:
- crawl_url (gnosis-crawl) with markdown_extraction=enhanced.
- google_search_markdown (SerpAPI wrapper) with small result counts.
Do NOT call raw_html. Skip screenshots/assets.

Guardrails:
- SerpAPI: num <= 12, do NOT set fetch_pages_top_k. If SerpAPI unavailable, skip search and note it.
- Filtering: allowlist official docs/blog/changelog and github.com/org/repo; dedupe; max 3 URLs per domain; max 20 total; depth = 0.
- Crawl: timeout ~15s, response <= 1.5MB, no binaries; stop if queue > 25; per-domain delay ~1s; backoff on 429/5xx.

Workflow:
1) Seed crawl (depth 0/1) of:
{SEED_URLS}
2) Extract text and build a small term graph (top 300 terms, window=5, edges<=3000). Use it to propose <=15 focused queries.
3) Run google_search_markdown with those queries (num<=12), then filter URLs with the allowlist + caps above.
4) Crawl ONLY the filtered URLs with crawl_url using the crawl settings above.
5) Update the term graph with new docs. Surface change signals: new features, breaking changes, pricing/licensing shifts, deprecations, ecosystem impacts.
6) Return markdown:

```markdown
# Release / Change Intelligence
## Summary
- Seeds crawled: X
- URLs crawled (post-filter): X
- Queries used: [...]

## Notable Changes
- Bullet list of concrete changes with source URLs.

## Risks / Unknowns
- Items needing follow-up.

## Next URLs to Approve
- If more than caps, list top candidates (not crawled).
```
"""


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def safe_request(url: str, data: bytes = None, method: str = "GET",
                 timeout: int = 30) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    headers = {"Content-Type": "application/json"} if data else {}
    try:
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body), None
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8") if e.fp else ""
        try:
            return json.loads(body), None
        except Exception:
            return None, f"HTTP {e.code}: {body[:200]}"
    except urllib.error.URLError as e:
        return None, f"URLError: {e.reason}"
    except socket.timeout:
        return None, "Timeout"
    except Exception as e:
        return None, str(e)


def check_gateway() -> Tuple[bool, Dict[str, Any]]:
    result, err = safe_request(f"{GATEWAY_URL}/status", timeout=10)
    if err:
        return False, {"error": err}
    return True, result


def start_task(prompt: str, model: str = "gpt-5.1-codex-mini") -> Tuple[Optional[str], Optional[str]]:
    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "model": model,
        "persistent": True,
        "timeout_ms": 300_000,
        "return_session_url": True,
    }
    data = json.dumps(payload).encode("utf-8")
    result, err = safe_request(f"{GATEWAY_URL}/completion", data=data, method="POST", timeout=60)
    if err:
        return None, err
    session_id = result.get("gateway_session_id") or result.get("session_id")
    if not session_id:
        return None, "No session_id in response"
    return session_id, None


def get_session(session_id: str, include_events: bool = False, tail: int = 4000) -> Dict[str, Any]:
    params = []
    if include_events:
        params.append("include_events=1")
    if tail:
        params.append(f"tail={tail}")
    url = f"{GATEWAY_URL}/sessions/{session_id}"
    if params:
        url += "?" + "&".join(params)
    result, err = safe_request(url, timeout=20)
    return result if result else {"error": err}


def poll_session(session_id: str, poll_interval: int = 5, max_wait: int = 600) -> Dict[str, Any]:
    start = time.time()
    last_status = None
    while time.time() - start < max_wait:
        detail = get_session(session_id, include_events=False, tail=200)
        status = detail.get("status", "unknown")
        if status != last_status:
            log(f"Session {session_id} status: {status}")
            last_status = status
        if status in ("idle", "completed", "error", "timeout"):
            return get_session(session_id, include_events=True, tail=4000)
        time.sleep(poll_interval)
    return {"error": "Polling timed out", "session_id": session_id}


def extract_result(session: Dict[str, Any]) -> Optional[str]:
    def find_markdown(text: str) -> Optional[str]:
        import re
        m = re.search(r"```markdown\s*(.*?)\s*```", text, re.DOTALL)
        if m:
            return m.group(1).strip()
        m = re.search(r"```\s*(.*?)\s*```", text, re.DOTALL)
        if m:
            return m.group(1).strip()
        return None

    events = session.get("events", [])
    for ev in reversed(events):
        if ev.get("type") == "item.completed":
            item = ev.get("item", {})
            if item.get("type") == "agent_message":
                txt = item.get("text", "")
                md = find_markdown(txt)
                if md:
                    return md
                if txt:
                    return txt
    content = session.get("content", "")
    if content:
        md = find_markdown(content)
        return md or content
    stdout = session.get("stdout", {}).get("tail", "")
    if stdout:
        md = find_markdown(stdout)
        return md or stdout
    return None


def save_results(session_id: str, session: Dict[str, Any], content: Optional[str]) -> None:
    out = {
        "session_id": session_id,
        "timestamp": datetime.now().isoformat(),
        "status": session.get("status"),
        "content": content,
        "tool_calls": len([e for e in session.get("events", []) if e.get("type") == "item.completed" and e.get("item", {}).get("type") == "mcp_tool_call"]),
        "stdout_tail": session.get("stdout", {}).get("tail", "")[-2000:],
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    log(f"Saved results to {OUTPUT_FILE}")


def main():
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write(f"=== Release Intel Run {datetime.now().isoformat()} ===\n")

    log(f"Gateway: {GATEWAY_URL}")
    ok, status = check_gateway()
    if not ok:
        log(f"Gateway error: {status.get('error')}")
        log("Is the gateway running? Try: ./scripts/codex_container.sh --serve")
        return

    log("Starting release/change intelligence task...")
    session_id, err = start_task(RELEASE_INTEL_PROMPT)
    if err:
        log(f"Start error: {err}")
        return
    log(f"Session: {session_id}")

    result = poll_session(session_id, poll_interval=5, max_wait=900)
    if "error" in result:
        log(f"Task error: {result['error']}")
        return

    content = extract_result(result)
    save_results(session_id, result, content)

    print("\n--- AGENT RESPONSE ---\n")
    if content:
        print(content)
    else:
        print("(No structured response found; see stdout_tail in JSON.)")


if __name__ == "__main__":
    main()
