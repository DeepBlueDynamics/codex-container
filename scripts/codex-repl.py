#!/usr/bin/env python3
import argparse
import json
import os
import readline  # noqa: F401 - history support on POSIX shells
import sys

import requests


DEFAULT_TIMEOUT_MS = 300_000  # 5 minutes


def pretty(obj):
    return json.dumps(obj, indent=2, ensure_ascii=False)


def post_completion(base_url, prompt, timeout_ms, session_id=None):
    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "timeout_ms": timeout_ms,
        "persistent": True,
    }
    if session_id:
        payload["session_id"] = session_id
    resp = requests.post(
        f"{base_url}/completion",
        json=payload,
        timeout=(timeout_ms / 1000) + 5,
    )
    resp.raise_for_status()
    return resp.json()


def get_sessions(base_url):
    resp = requests.get(f"{base_url}/sessions", timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_session_detail(base_url, session_id, tail=200, include_events=False):
    params = {"tail": tail}
    if include_events:
        params["include_events"] = "true"
    resp = requests.get(
        f"{base_url}/sessions/{session_id}",
        params=params,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def search_session(base_url, session_id, query, fuzzy=False):
    params = {"q": query}
    if fuzzy:
        params["fuzzy"] = "true"
    resp = requests.get(
        f"{base_url}/sessions/{session_id}/search",
        params=params,
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def resume_prompt(base_url, session_id, prompt, timeout_ms):
    payload = {"prompt": prompt, "timeout_ms": timeout_ms}
    resp = requests.post(
        f"{base_url}/sessions/{session_id}/prompt",
        json=payload,
        timeout=(timeout_ms / 1000) + 5,
    )
    resp.raise_for_status()
    return resp.json()


def print_help(base, timeout_ms, pinned_session):
    help_text = f"""
Connected to {base}
Commands:
  run <prompt>                → POST /completion (timeout={timeout_ms/1000:.0f}s)
  list                        → GET /sessions
  show <id>                   → GET /sessions/:id (tail=200)
  show <id> events            → include events
  search <id> <phrase> [--f]  → search session text, add --f for fuzzy
  prompt <id> <text>          → resume Codex session with new text
  use <id>                    → pin a gateway session for future runs
  timeout <seconds>           → change default run timeout
  clear                       → clear the console
  help                        → show this message
  exit | quit                 → leave console
Pinned session: {pinned_session or "(none)"}
Persistent workers auto-start whenever you run/prompt; adjust run duration with the `timeout` command.
"""
    print(help_text.strip())


def main():
    parser = argparse.ArgumentParser(description="Interact with Codex gateway")
    parser.add_argument(
        "base_url",
        nargs="?",
        default="http://localhost:4000",
        help="Gateway base URL",
    )
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    current_session = None
    current_timeout_ms = DEFAULT_TIMEOUT_MS

    print_help(base, current_timeout_ms, current_session)

    while True:
        try:
            line = input("codex> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not line:
            continue
        if line.lower() in {"exit", "quit"}:
            break
        lower = line.lower()
        if lower == "help":
            print_help(base, current_timeout_ms, current_session)
            continue
        if lower == "clear":
            os.system("cls" if os.name == "nt" else "clear")
            continue

        cmd, *rest = line.split(" ", 1)
        remainder = rest[0] if rest else ""

        try:
            if cmd == "run":
                if not remainder:
                    print("Usage: run <prompt>")
                    continue
                result = post_completion(base, remainder, current_timeout_ms, session_id=current_session)
                print(pretty(result))
                gateway_session = result.get("gateway_session_id") or result.get("session_id")
                if gateway_session:
                    current_session = gateway_session
                    print(f"→ gateway_session_id: {gateway_session}")
                model_info = result.get("model")
                usage_info = result.get("usage")
                if model_info:
                    print(f"→ model: {model_info}")
                if usage_info is not None:
                    print(f"→ usage: {usage_info}")
            elif cmd == "list":
                result = get_sessions(base)
                print(pretty(result))
            elif cmd == "show":
                if not remainder:
                    print("Usage: show <session-id> [events]")
                    continue
                session_id, _, flag = remainder.partition(" ")
                include_events = flag.strip().lower() == "events"
                result = get_session_detail(base, session_id, include_events=include_events)
                print(pretty(result))
                runs = result.get("runs") or []
                for run in runs:
                    usage = run.get("usage")
                    if usage:
                        print(
                            f"→ run {run['run_id']} usage: "
                            f"{usage.get('input_tokens')} in / "
                            f"{usage.get('output_tokens')} out "
                            f"(total {usage.get('total_tokens')})"
                        )
            elif cmd == "search":
                if not remainder:
                    print("Usage: search <session-id> <phrase> [--f]")
                    continue
                parts = remainder.split(" ")
                if len(parts) < 2:
                    print("Usage: search <session-id> <phrase> [--f]")
                    continue
                session_id = parts[0]
                fuzzy = "--f" in parts[1:]
                phrase_parts = [p for p in parts[1:] if p != "--f"]
                phrase = " ".join(phrase_parts)
                if not phrase:
                    print("Usage: search <session-id> <phrase> [--f]")
                    continue
                result = search_session(base, session_id, phrase, fuzzy=fuzzy)
                print(pretty(result))
            elif cmd == "prompt":
                if not remainder:
                    print("Usage: prompt <session-id> <text>")
                    continue
                session_id, _, prompt_text = remainder.partition(" ")
                if not prompt_text:
                    print("Usage: prompt <session-id> <text>")
                    continue
                result = resume_prompt(base, session_id, prompt_text, current_timeout_ms)
                print(pretty(result))
            elif cmd == "use":
                if not remainder:
                    print("Usage: use <session-id>")
                    continue
                current_session = remainder.strip()
                print(f"Pinned session set to {current_session}")
            elif cmd == "timeout":
                if not remainder:
                    print("Usage: timeout <seconds>")
                    continue
                try:
                    seconds = float(remainder.strip())
                    if seconds <= 0:
                        raise ValueError
                except ValueError:
                    print("Timeout must be a positive number of seconds")
                    continue
                current_timeout_ms = int(seconds * 1000)
                print(f"Timeout updated to {seconds:.1f}s")
            else:
                print("Unknown command. Type 'help' for instructions.")
        except requests.HTTPError as err:
            print(f"HTTP error {err.response.status_code}: {err.response.text}")
        except requests.RequestException as err:
            print(f"Request failed: {err}")
        except Exception as err:
            print(f"Error: {err}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(1)
