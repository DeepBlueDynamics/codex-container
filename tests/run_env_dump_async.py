#!/usr/bin/env python3
"""Call the gateway and ask Codex to dump env + session info via shell."""

import asyncio
import json
import urllib.parse
from typing import Optional

GATEWAY = "http://localhost:4000/completion"
MODEL = "gpt-5.1-codex-mini"
PROMPT = (
    "Run a single shell command that prints the gateway session id and the environment. "
    "Use: printf \"SESSION_ID: %s\\n\" \"$CODEX_SESSION_ID\"; env | sort "
    "and return exactly the command output as plain text. "
    "If the command fails, return a short plain-text error that begins with 'FAILED:' and includes why. "
    "If CODEX_SESSION_ID is empty or unset, say 'SESSION_ID: (empty)'."
)


async def post_completion(session_id: Optional[str] = None) -> dict:
    payload = {
        "messages": [{"role": "user", "content": PROMPT}],
        "model": MODEL,
        "persistent": False,
        "timeout_ms": 60000,
        "return_session_url": True,
    }
    if session_id:
        payload["session_id"] = session_id
    data = json.dumps(payload).encode()
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync_post, data)


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

    res = await post_completion()
    sid = res.get("gateway_session_id") or res.get("session_id")
    cxsid = res.get("codex_session_id")
    status = res.get("status")
    content = res.get("content")
    tool_calls = res.get("tool_calls")
    events = res.get("events")
    session_url = res.get("session_url")

    print(f"[session] session_id={sid} codex_session_id={cxsid} status={status}")
    print(f"[session] content:\n{content}")
    print(f"[session] tool_calls={json.dumps(tool_calls, indent=2)}")
    print(f"[session] events={json.dumps(events, indent=2)}")
    print(f"[session] session_url={session_url}")
    print("-" * 60)

    if sid:
        detail = await get_session_detail(sid, include_events=True, tail=200)
        stdout_tail = detail.get("stdout", {}).get("tail")
        print(f"[session] stdout tail:\n{stdout_tail}")
        ev = detail.get("events")
        if ev:
            print(f"[session] detail/events ({len(ev)}):")
            print(json.dumps(ev, indent=2))
        else:
            print("[session] detail/events: none")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
