#!/usr/bin/env python3
"""Spin up two gateway sessions concurrently, ask each to run a crawl, log full responses."""

import asyncio
import json
import urllib.parse
from typing import Optional

GATEWAY = "http://localhost:4000/completion"
MODEL = "gpt-5.1-codex-mini"
PROMPT = (
    "Use the MCP tool gnosis-crawl::crawl_url to fetch https://example.com . "
    "Return a short JSON object with keys: url, title (if present), and preview "
    "(first 120 chars of extracted text). If the crawl tool fails, return "
    "json with error and status fields describing what happened."
)

async def post_completion(session_id: Optional[str] = None) -> dict:
    payload = {
        "messages": [{"role": "user", "content": PROMPT}],
        "model": MODEL,
        # Force non-worker path so we get tool_calls/events inline.
        "persistent": False,
        "timeout_ms": 60000,
        "return_session_url": True,
    }
    if session_id:
        payload["session_id"] = session_id
    data = json.dumps(payload).encode()
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        _sync_post,
        data,
    )

def _sync_post(data: bytes) -> dict:
    import urllib.request
    import urllib.error

    req = urllib.request.Request(
        GATEWAY,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            body = resp.read().decode("utf-8")
            try:
                return json.loads(body)
            except Exception:
                return {"raw": body}
    except urllib.error.HTTPError as e:
        # Handle 429 Too Many Requests and other HTTP errors
        body = e.read().decode("utf-8") if e.fp else ""
        try:
            err_data = json.loads(body)
            return {"status": "rejected", "http_code": e.code, **err_data}
        except Exception:
            return {"status": "rejected", "http_code": e.code, "error": str(e)}
    except Exception as e:
        return {"status": "error", "error": str(e)}


async def get_session_detail(session_id: str, include_events: bool = True, tail: int = 200) -> dict:
    url = f"http://localhost:4000/sessions/{urllib.parse.quote(session_id)}"
    params = []
    if include_events:
        params.append("include_events=1")
    if tail:
        params.append(f"tail={tail}")
    if params:
        url = f"{url}?{'&'.join(params)}"
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync_get, url)


def _sync_get(url: str) -> dict:
    import urllib.request

    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8")
        try:
            return json.loads(body)
        except Exception:
            return {"raw": body}


async def main():
    print(f"[check] gateway={GATEWAY}")
    print(f"[check] prompt={PROMPT}")
    # Launch two sessions concurrently
    results = await asyncio.gather(
        post_completion(),
        post_completion(),
    )
    for idx, res in enumerate(results, 1):
        sid = res.get("gateway_session_id") or res.get("session_id")
        cxsid = res.get("codex_session_id")
        status = res.get("status")
        content = res.get("content")
        tool_calls = res.get("tool_calls")
        events = res.get("events")
        session_url = res.get("session_url")
        print(f"[session {idx}] session_id={sid} codex_session_id={cxsid} status={status}")
        print(f"[session {idx}] content={content}")
        print(f"[session {idx}] tool_calls={json.dumps(tool_calls, indent=2)}")
        print(f"[session {idx}] events={json.dumps(events, indent=2)}")
        print(f"[session {idx}] session_url={session_url}")
        print("-" * 60)
    # Fetch session tails to see what actually ran
    for idx, res in enumerate(results, 1):
        sid = res.get("gateway_session_id") or res.get("session_id")
        if not sid:
            continue
        detail = await get_session_detail(sid, include_events=True, tail=120)
        print(f"[session {idx}] detail/stdout tail:\\n{detail.get('stdout', {}).get('tail')}")
        ev = detail.get("events")
        if ev:
            print(f"[session {idx}] detail/events ({len(ev)}):")
            print(json.dumps(ev, indent=2))
        else:
            print(f"[session {idx}] detail/events: none")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
