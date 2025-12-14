#!/usr/bin/env python3
import argparse
import json
import os
import readline  # noqa: F401 - history support on POSIX shells
import sys
from datetime import datetime
from typing import List

import requests


DEFAULT_TIMEOUT_MS = 300_000  # 5 minutes
DISPLAY_MODES = {"full", "compact"}
DEBUG_KEYS = ["gateway_session_id", "codex_session_id", "model", "usage", "tool_calls", "events"]
WATCH_KEYS_DEFAULT: List[str] = []


def timestamp():
    """Return current timestamp in ISO format."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log_with_timestamp(message, prefix="[codex-repl]"):
    """Print a message with timestamp prefix."""
    print(f"{prefix} [{timestamp()}] {message}")


def pretty(obj):
    return json.dumps(obj, indent=2, ensure_ascii=False)


def print_debug_keys(result, watch_keys: List[str]):
    """Print common debug keys if present."""
    out = []
    for k in DEBUG_KEYS:
        if k in result:
            v = result.get(k)
            if k == "events" and isinstance(v, list):
                out.append(f"{k}: {len(v)} event(s)")
            else:
                out.append(f"{k}: {v}")
    for k in watch_keys:
        if k in result and k not in DEBUG_KEYS:
            v = result.get(k)
            if k == "events" and isinstance(v, list):
                out.append(f"{k}: {len(v)} event(s)")
            else:
                out.append(f"{k}: {v}")
    if out:
        print("=== DEBUG KEYS ===")
        for line in out:
            print(line)
        print("==================")


def print_compact_events(events: List[dict]):
    """Print reasoning/agent messages and command_execution outputs in compact form."""
    messages = []
    cmd_outputs = []
    for ev in events or []:
        if not isinstance(ev, dict):
            continue
        item = ev.get("item", {}) if isinstance(ev.get("item"), dict) else {}
        if ev.get("type") == "item.completed" and item.get("type") == "reasoning":
            text = item.get("text")
            if text:
                messages.append(f"[reasoning] {text}")
        if ev.get("type") == "item.completed" and item.get("type") == "agent_message":
            text = item.get("text")
            if text:
                messages.append(f"[agent] {text}")
        if ev.get("type") in {"item.started", "item.completed"} and item.get("type") == "command_execution":
            out = item.get("aggregated_output") or ""
            if out:
                if len(out) > 800:
                    out = out[:800] + "...(truncated)"
                cmd_outputs.append(out)
    if messages:
        print("=== COMPACT EVENTS ===")
        for m in messages:
            print(m)
        print("======================")
    if cmd_outputs:
        print("=== COMMAND OUTPUT ===")
        for co in cmd_outputs:
            print(co)
            print("----------------------")
        print("======================")


def extract_trigger_ids(events):
    """Extract trigger IDs from events array."""
    trigger_ids = []
    if not isinstance(events, list):
        return trigger_ids

    for event in events:
        if not isinstance(event, dict):
            continue
        item = event.get("item", {}) if isinstance(event.get("item"), dict) else {}
        if event.get("type") == "item.completed" and item.get("type") == "mcp_tool_call" and item.get("tool") == "create_trigger":
            result = item.get("result", {})
            if isinstance(result, dict) and "content" in result:
                for content_item in result["content"]:
                    if content_item.get("type") != "text":
                        continue
                    try:
                        data = json.loads(content_item["text"])
                        if "trigger" in data and "id" in data["trigger"]:
                            trigger_ids.append(
                                {
                                    "id": data["trigger"]["id"],
                                    "title": data["trigger"].get("title", "Unknown"),
                                    "tags": data["trigger"].get("tags", []),
                                }
                            )
                    except Exception:
                        continue
    return trigger_ids


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


def print_help(base, timeout_ms, pinned_session, display_mode):
    help_text = f"""
Connected to {base}
Commands:
  run <prompt>                → POST /completion (timeout={timeout_ms/1000:.0f}s)
  list                        → GET /sessions
  show <id>                   → GET /sessions/:id (tail=200)
  show <id> events            → include events
  show <id> triggers          → include events + extract trigger IDs
  watch <key1> <key2> ...     → set extra keys to display in compact mode (clear with `watch clear`)
  search <id> <phrase> [--f]  → search session text, add --f for fuzzy
  prompt <id> <text>          → resume Codex session with new text
  use <id>                    → pin a gateway session for future runs
  timeout <seconds>           → change default run timeout
  mode <full|compact>         → toggle display mode (compact shows reasoning/agent messages only)
  watch <keys...>             → set extra keys to display in compact mode (e.g., watch usage model); use 'watch clear' to reset
  clear                       → clear the console
  help                        → show this message
  exit | quit                 → leave console
Pinned session: {pinned_session or "(none)"}
Display mode: {display_mode}
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
    watch_keys: List[str] = WATCH_KEYS_DEFAULT.copy()
    current_display_mode = "full"

    print_help(base, current_timeout_ms, current_session, current_display_mode)

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
            print_help(base, current_timeout_ms, current_session, current_display_mode)
            continue
        if lower == "clear":
            os.system("cls" if os.name == "nt" else "clear")
            continue

        cmd, *rest = line.split(" ", 1)
        remainder = rest[0] if rest else ""

        try:
            if cmd == "run":
                if not remainder:
                    log_with_timestamp("Usage: run <prompt>")
                    continue
                log_with_timestamp(f"🚀 Starting job: {remainder[:80]}..." if len(remainder) > 80 else f"🚀 Starting job: {remainder}")
                result = post_completion(base, remainder, current_timeout_ms, session_id=current_session)
                log_with_timestamp("✅ Job completed")
                if current_display_mode == "compact":
                    print("=== COMPACT RUN SUMMARY ===")
                    print_compact_events(result.get("events", []))
                    print("===========================")
                else:
                    print(pretty(result))
                print_debug_keys(result, watch_keys)
                gateway_session = result.get("gateway_session_id") or result.get("session_id")
                if gateway_session:
                    current_session = gateway_session
                    log_with_timestamp(f"📌 Pinned session set to {gateway_session}")
                    log_with_timestamp(f"→ gateway_session_id: {gateway_session}")
                model_info = result.get("model")
                usage_info = result.get("usage")
                if model_info:
                    print(f"→ model: {model_info}")
                if usage_info is not None:
                    print(f"→ usage: {usage_info}")
            elif cmd == "list":
                log_with_timestamp("📋 Fetching sessions list...")
                result = get_sessions(base)
                log_with_timestamp(f"✅ Found {len(result.get('sessions', []))} session(s)")
                print(pretty(result))
            elif cmd == "show":
                if not remainder:
                    log_with_timestamp("Usage: show <session-id> [events|triggers]")
                    continue
                session_id, _, flag = remainder.partition(" ")
                flag_lower = flag.strip().lower()
                include_events = flag_lower in {"events", "triggers"}
                log_with_timestamp(f"📄 Fetching session {session_id}..." + (f" (with {flag_lower})" if flag_lower else ""))
                result = get_session_detail(base, session_id, include_events=include_events)
                log_with_timestamp("✅ Session data retrieved")

                if flag_lower == "triggers":
                    events = result.get("events", [])
                    trigger_ids = extract_trigger_ids(events)
                    if trigger_ids:
                        print("\n📋 Trigger IDs found in this session:")
                        for trigger in trigger_ids:
                            print(f"  ID: {trigger['id']}")
                            print(f"  Title: {trigger['title']}")
                            if trigger["tags"]:
                                print(f"  Tags: {', '.join(trigger['tags'])}")
                            print()
                    else:
                        print("\n⚠️  No trigger IDs found in events")
                    print("\n--- Full session data ---")

                if current_display_mode == "compact" and include_events:
                    print_compact_events(result.get("events", []))
                else:
                    print(pretty(result))
                print_debug_keys(result, watch_keys)
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
                    log_with_timestamp("Usage: prompt <session-id> <text>")
                    continue
                session_id, _, prompt_text = remainder.partition(" ")
                if not prompt_text:
                    log_with_timestamp("Usage: prompt <session-id> <text>")
                    continue
                log_with_timestamp(f"📝 Resuming session {session_id}: {prompt_text[:80]}..." if len(prompt_text) > 80 else f"📝 Resuming session {session_id}: {prompt_text}")
                result = resume_prompt(base, session_id, prompt_text, current_timeout_ms)
                log_with_timestamp("✅ Prompt completed")
                print(pretty(result))
            elif cmd == "use":
                if not remainder:
                    log_with_timestamp("Usage: use <session-id>")
                    continue
                current_session = remainder.strip()
                log_with_timestamp(f"📌 Pinned session set to {current_session}")
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
            elif cmd == "mode":
                choice = remainder.strip().lower()
                if choice not in DISPLAY_MODES:
                    print("Usage: mode <full|compact>")
                    continue
                current_display_mode = choice
                log_with_timestamp(f"Display mode set to {current_display_mode}")
            elif cmd == "watch":
                if not remainder:
                    print("Usage: watch <key1> <key2> ... | watch clear")
                    continue
                if remainder.strip().lower() == "clear":
                    watch_keys = []
                    log_with_timestamp("Watch keys cleared")
                    continue
                parts = remainder.split()
                watch_keys = parts
                log_with_timestamp(f"Watch keys set to: {', '.join(watch_keys)}")
            else:
                print("Unknown command. Type 'help' for instructions.")
        except requests.HTTPError as err:
            log_with_timestamp(f"❌ HTTP error {err.response.status_code}: {err.response.text}", prefix="[codex-repl]")
        except requests.RequestException as err:
            log_with_timestamp(f"❌ Request failed: {err}", prefix="[codex-repl]")
        except Exception as err:
            log_with_timestamp(f"❌ Error: {err}", prefix="[codex-repl]")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(1)
