#!/usr/bin/env python3
import json
import urllib.request
from typing import List

GATEWAY = "http://localhost:4000"


def http_get(url: str):
    req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8")
        return resp.status, body


def list_sessions() -> List[str]:
    status, body = http_get(f"{GATEWAY}/sessions")
    print(f"[list] status={status}\n{body}\n")
    try:
        parsed = json.loads(body)
        sessions = parsed.get("sessions", [])
        return [s.get("session_id") for s in sessions if s.get("session_id")]
    except Exception as e:
        print(f"[list] failed to parse JSON: {e}")
        return []


def dump_session(session_id: str):
    url = f"{GATEWAY}/sessions/{session_id}?include_events=1&include_stderr=1&tail=200"
    status, body = http_get(url)
    print(f"[detail] session={session_id} status={status}")
    try:
        parsed = json.loads(body)
    except Exception:
        print(body)
        return
    # Pretty print key parts
    meta_keys = [
        "session_id","codex_session_id","status","model","created_at","updated_at","last_activity_at","runs"
    ]
    meta = {k: parsed.get(k) for k in meta_keys}
    print("[detail] meta:")
    print(json.dumps(meta, indent=2))
    stdout = parsed.get("stdout", {})
    stderr = parsed.get("stderr", {})
    events = parsed.get("events", [])
    print(f"[detail] stdout tail:\n{stdout.get('tail','')}")
    if stderr:
        print(f"[detail] stderr tail:\n{stderr.get('tail','')}")
    print(f"[detail] events count={len(events)}")
    if events:
        print("[detail] last event:")
        print(json.dumps(events[-1], indent=2))
    print("-- end detail --\n")


def main():
    sessions = list_sessions()
    if not sessions:
        print("[main] no sessions returned")
        return
    for sid in sessions:
        dump_session(sid)


if __name__ == "__main__":
    main()
