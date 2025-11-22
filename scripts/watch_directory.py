#!/usr/bin/env python3
"""Simple watcher that triggers Codex runs when new files appear."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

DEFAULT_TEMPLATE = (
    "New artifact detected at {path}. Provide a short summary and suggest next steps."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", required=True, help="Directory to watch")
    parser.add_argument(
        "--pattern",
        dest="patterns",
        action="append",
        default=None,
        help="Glob pattern to match (repeatable; default: *).",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="Polling interval in seconds (default: 5)",
    )
    parser.add_argument(
        "--template",
        default=DEFAULT_TEMPLATE,
        help="Prompt template. Supports {path}, {name}, {stem} placeholders.",
    )
    parser.add_argument(
        "--include-content",
        action="store_true",
        help="Embed text file content into the prompt (UTF-8, up to --content-bytes).",
    )
    parser.add_argument(
        "--content-bytes",
        type=int,
        default=65536,
        help="Maximum bytes to read when embedding content (default: 65536).",
    )
    parser.add_argument(
        "--codex-script",
        required=True,
        help="Absolute path to codex_container.sh",
    )
    parser.add_argument(
        "--workspace",
        help="Workspace path to mount for Codex (defaults to watch directory).",
    )
    parser.add_argument(
        "--json-mode",
        choices=["none", "legacy", "experimental"],
        default="none",
    )
    parser.add_argument(
        "--codex-arg",
        dest="codex_args",
        action="append",
        help="Additional --codex-arg forwarded to codex_container.sh",
    )
    parser.add_argument(
        "--exec-arg",
        dest="exec_args",
        action="append",
        help="Additional --exec-arg forwarded to codex_container.sh",
    )
    parser.add_argument(
        "--debounce",
        type=float,
        default=2.0,
        help="Minimum seconds between triggers for the same file (default: 2)",
    )
    parser.add_argument(
        "--state-file",
        help="Optional path to persist seen files between restarts",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run once over unseen files then exit",
    )
    return parser


def load_seen(state_file: Optional[Path]) -> Dict[str, float]:
    if not state_file or not state_file.exists():
        return {}
    try:
        with state_file.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
            if isinstance(data, dict):
                return {str(k): float(v) for k, v in data.items()}
    except Exception:
        return {}
    return {}


def save_seen(state_file: Optional[Path], seen: Dict[str, float]) -> None:
    if not state_file:
        return
    try:
        with state_file.open("w", encoding="utf-8") as fh:
            json.dump(seen, fh, indent=2)
    except Exception:
        pass


def read_content(path: Path, limit: int) -> Optional[str]:
    try:
        data = path.read_bytes()[:limit]
        return data.decode("utf-8", errors="replace")
    except Exception:
        return None


def generate_prompt(template: str, path: Path, include_content: bool, limit: int) -> str:
    prompt = template.format(path=str(path), name=path.name, stem=path.stem)
    if include_content:
        content = read_content(path, limit)
        if content:
            prompt = f"{prompt}\n\n--- File Content (first {limit} bytes) ---\n{content}"
    return prompt


def run_codex(
    codex_script: Path,
    workspace: Path,
    prompt: str,
    json_mode: str,
    codex_args: Iterable[str],
    exec_args: Iterable[str],
) -> int:
    cmd: List[str] = [str(codex_script), "--exec", "--workspace", str(workspace)]
    if json_mode == "legacy":
        cmd.append("--json")
    elif json_mode == "experimental":
        cmd.append("--json-e")
    for arg in codex_args:
        cmd.extend(["--codex-arg", arg])
    for arg in exec_args:
        cmd.extend(["--exec-arg", arg])
    cmd.append("--")
    cmd.append(prompt)
    proc = subprocess.run(cmd)
    return proc.returncode


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    watch_dir = Path(args.path).expanduser().resolve()
    if not watch_dir.is_dir():
        parser.error(f"Watch path '{watch_dir}' is not a directory")

    patterns = args.patterns or ["*"]
    state_file = Path(args.state_file).expanduser().resolve() if args.state_file else None
    seen = load_seen(state_file)

    codex_script = Path(args.codex_script).expanduser().resolve()
    if not codex_script.exists():
        parser.error("codex_container.sh not found")

    workspace = Path(args.workspace).expanduser().resolve() if args.workspace else watch_dir

    def scan_once() -> List[Path]:
        matches: Set[Path] = set()
        for pattern in patterns:
            matches.update(watch_dir.glob(pattern))
        return sorted(matches, key=lambda p: p.stat().st_mtime)

    try:
        while True:
            now = time.time()
    for path in scan_once():
        mtime = path.stat().st_mtime
        key = str(path)
        last_trigger = seen.get(key)
                if last_trigger and mtime <= last_trigger:
                    continue
                if last_trigger and now - last_trigger < args.debounce:
                    continue
                print(f"[watch] Detected change: {path}")
                prompt = generate_prompt(
                    args.template, path, args.include_content, args.content_bytes
                )
                exit_code = run_codex(
                    codex_script,
                    workspace,
                    prompt,
                    args.json_mode,
                    args.codex_args or [],
                    args.exec_args or [],
                )
                seen[key] = time.time()
                save_seen(state_file, seen)
                if exit_code != 0:
                    print(f"Codex command exited with {exit_code}", file=sys.stderr)
            if args.once:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("Stopping watcher.")

    save_seen(state_file, seen)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
