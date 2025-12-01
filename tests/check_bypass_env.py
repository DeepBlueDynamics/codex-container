#!/usr/bin/env python3
import json
import sys
import time
import urllib.request
from typing import Optional, Tuple

GATEWAY_URL = "http://localhost:4000/completion"


def send(prompt: str, session_id: Optional[str] = None, persistent: bool = True) -> Tuple[int, str, dict]:
    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "model": "gpt-5.1-codex-mini",
        "timeout_ms": 60000,
        "persistent": persistent,
    }
    if session_id:
        payload["session_id"] = session_id
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        GATEWAY_URL, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        body = resp.read().decode("utf-8")
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = {}
        return resp.status, body, parsed


def main():
    prompt = (
        "Run `echo CODEX_UNSAFE_ALLOW_NO_SANDBOX=$CODEX_UNSAFE_ALLOW_NO_SANDBOX` in a shell. "
        "Return only the exact line of output (no JSON, no markup). "
        "If you cannot run a shell, return exactly `CODEX_UNSAFE_ALLOW_NO_SANDBOX=<unknown>`."
    )
    print(f"[check] prompt: {prompt}")
    print("[check] sending first request (persistent session)...")
    status, body, parsed = send(prompt, persistent=True)
    print(f"[check] status={status}\n{body}\n")
    if parsed.get("content") is not None:
        print(f"[check] content field: {parsed.get('content')}")
    else:
        print("[check] no content field present")
    print("[check] parsed response (pretty):")
    print(json.dumps(parsed, indent=2))

    gateway_session_id = parsed.get("gateway_session_id") or parsed.get("session_id")
    codex_session_id = parsed.get("codex_session_id")
    print(f"[check] captured gateway_session_id={gateway_session_id}, codex_session_id={codex_session_id}")
    if not gateway_session_id:
        print("[check] no session id returned; cannot resume")
        sys.exit(1)

    print("[check] waiting 30s then sending follow-up on same session...")
    time.sleep(30)
    follow_prompt = (
        "Run `echo CODEX_UNSAFE_ALLOW_NO_SANDBOX=$CODEX_UNSAFE_ALLOW_NO_SANDBOX` in a shell. "
        "Return only the exact line of output (no JSON, no markup). "
        "If you cannot run a shell, return exactly `CODEX_UNSAFE_ALLOW_NO_SANDBOX=<unknown>`."
    )
    status2, body2, parsed2 = send(follow_prompt, session_id=gateway_session_id, persistent=True)
    print(f"[check] follow-up status={status2}\n{body2}\n")
    if parsed2.get("content") is not None:
        print(f"[check] follow-up content field: {parsed2.get('content')}")
    else:
        print("[check] follow-up: no content field present")
    print("[check] follow-up parsed response (pretty):")
    print(json.dumps(parsed2, indent=2))

    if parsed2.get("gateway_session_id") and parsed2.get("gateway_session_id") != gateway_session_id:
        print(
            f"[check] WARNING: follow-up returned different session_id {parsed2.get('gateway_session_id')}"
        )


if __name__ == "__main__":
    main()
