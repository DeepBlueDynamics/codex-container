#!/usr/bin/env python3
"""Quick standalone speaker tester that mimics the bridge playback command."""

import argparse
import logging
import shutil
import subprocess
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)

BACKENDS = ["ffplay", "powershell", "cvlc", "vlc", "afplay"]


def find_backend(name: str) -> str | None:
    tool = shutil.which(name)
    if tool:
        logging.info("Detected backend %s at %s", name, tool)
    return tool


def play_with_ffplay(path: Path, volume: float) -> bool:
    cmd = ["ffplay", "-autoexit", "-nodisp", "-loglevel", "error", "-af", f"volume={volume}", str(path)]
    return run_cmd(cmd)


def run_cmd(cmd: list[str]) -> bool:
    logging.info("Running: %s", " ".join(cmd))
    try:
        subprocess.run(cmd, check=True)
        return True
    except subprocess.CalledProcessError as exc:
        logging.error("Command failed: %s", exc)
        return False
    except FileNotFoundError:
        logging.warning("Backend missing: %s", cmd[0])
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Play a file via one of the speaker backends")
    parser.add_argument("path", type=Path, nargs="?", default=Path("voice-outbox/elevenlabs_detection.mp3"))
    parser.add_argument("--volume", type=float, default=0.5)
    parser.add_argument("--force", choices=["ffplay", "powershell", "cvlc", "afplay"], help="Force backend")
    args = parser.parse_args()

    target = args.path.expanduser()
    if not target.is_absolute():
        target = Path.cwd() / target
    target = target.resolve()

    if not target.exists():
        logging.error("File not found: %s", target)
        sys.exit(1)

    logging.info("Playing %s", target)

    volume = max(0.0, min(1.0, args.volume))

    if args.force:
        backend = find_backend(args.force)
        if backend:
            run_cmd([backend, *([] if args.force == "ffplay" else []), str(target)])
        sys.exit(0)

    if find_backend("ffplay") and play_with_ffplay(target, volume):
        return

    for backend in ["cvlc", "vlc", "afplay", "powershell"]:
        binary = find_backend(backend)
        if not binary:
            continue
        if backend in ("cvlc", "vlc"):
            if run_cmd([binary, "--play-and-exit", "--no-video", "--gain", str(volume), str(target)]):
                return
        elif backend == "afplay":
            if run_cmd([binary, "-v", str(volume), str(target)]):
                return
        else:
            ps_script = (
                "Add-Type -AssemblyName presentationCore;"
                f"$player = New-Object System.Windows.Media.MediaPlayer;"
                f"$player.Open([Uri]'file:///{target.as_posix()}');$player.Volume={volume};$player.Play();"
                "while ($player.NaturalDuration.HasTimeSpan -eq $false) { Start-Sleep -Milliseconds 100 };"
                "while ($player.Position -lt $player.NaturalDuration.TimeSpan) { Start-Sleep -Milliseconds 200 };"
                "$player.Stop();"
            )
            if run_cmd([binary, "-NoProfile", "-Command", ps_script]):
                return

    logging.error("All playback backends failed. Try installing ffplay or restarting the speaker bridge.")
    sys.exit(1)


if __name__ == "__main__":
    main()
