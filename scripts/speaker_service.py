#!/usr/bin/env python3
"""Host-side speaker bridge for Codex audio playback.

This service listens on a localhost HTTP port and plays any audio file
referenced in the request. It is designed to be launched by
``scripts/codex_container.ps1 -Speaker`` so that MCP tools inside the container
can simply POST a relative filename once an MP3 has been written to the shared
voice outbox volume.

Supported POST payloads for ``/play``:
    1. JSON body with ``{"relative_path": "clip.mp3"}`` (preferred).
    2. JSON body with ``{"path": "C:/.../clip.mp3"}`` (must live inside the
       configured outbox).
    3. Raw ``application/octet-stream`` data with optional ``X-Filename`` header.
       The service saves the bytes under the outbox before playing them.

The server responds to ``GET /health`` for readiness checks.
The ``/browser`` endpoint accepts JSON payloads such as
``{"action": "open", "url": "https://example.com"}`` and launches Google Chrome
on the host (best-effort auto-detection with optional overrides).
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import pathlib
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import wave
from urllib.parse import urlparse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from typing import Optional


LOGGER = logging.getLogger("speaker")


class AudioPlaybackError(RuntimeError):
    """Raised when no playback backend succeeds."""


class AudioPlayer:
    """Simple best-effort audio playback wrapper."""

    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger
        self.ffplay = shutil.which("ffplay")
        self.afplay = shutil.which("afplay")
        self.cvlc = shutil.which("cvlc") or shutil.which("vlc")
        self.powershell = shutil.which("powershell") or shutil.which("pwsh")
        self.force_backend = os.environ.get("SPEAKER_FORCE_BACKEND")

        if self.force_backend:
            self.logger.info("Forcing backend: %s", self.force_backend)
            self._reorder_backends()

    def _reorder_backends(self) -> None:
        backends = {
            "ffplay": ("ffplay",),
            "afplay": ("afplay",),
            "vlc": ("cvlc", "vlc"),
            "powershell": ("powershell", "pwsh"),
        }
        desired = self.force_backend.lower()
        if desired in backends:
            for key, names in backends.items():
                if key == "ffplay":
                    self.ffplay = None
                elif key == "afplay":
                    self.afplay = None
                elif key == "vlc":
                    self.cvlc = None
                elif key == "powershell":
                    self.powershell = None
            for name in backends[desired]:
                found = shutil.which(name)
                if desired == "ffplay":
                    self.ffplay = found
                elif desired == "afplay":
                    self.afplay = found
                elif desired == "vlc":
                    self.cvlc = found
                elif desired == "powershell":
                    self.powershell = found
        else:
            self.logger.warning("Unknown SPEAKER_FORCE_BACKEND=%s", self.force_backend)

    def play(self, path: pathlib.Path) -> None:
        path = path.resolve()
        self.logger.info("Playing %s", path)
        if self.ffplay:
            if self._run([self.ffplay, "-autoexit", "-nodisp", "-loglevel", "error", str(path)]):
                self.logger.info("Using ffplay backend")
                return
        if self.afplay:
            if self._run([self.afplay, str(path)]):
                self.logger.info("Using afplay backend")
                return
        if self.cvlc:
            if self._run([self.cvlc, "--play-and-exit", "--no-video", str(path)]):
                self.logger.info("Using VLC backend")
                return
        if os.name == "nt" and self.powershell:
            ps_script = (
                "Add-Type -AssemblyName presentationCore; "
                "$player = New-Object System.Windows.Media.MediaPlayer; "
                f"$player.Open([Uri]'file:///{path.as_posix()}'); "
                "$player.Volume = 1.0; "
                "$player.Play(); "
                "while ($player.NaturalDuration.HasTimeSpan -eq $false) { Start-Sleep -Milliseconds 100 }; "
                "while ($player.Position -lt $player.NaturalDuration.TimeSpan) { Start-Sleep -Milliseconds 200 }; "
                "$player.Stop();"
            )
            if self._run([self.powershell, "-NoProfile", "-Command", ps_script]):
                self.logger.info("Using PowerShell MediaPlayer backend")
                return

        raise AudioPlaybackError("No audio backend succeeded; install ffmpeg/ffplay for best results.")

    def _run(self, cmd: list[str]) -> bool:
        try:
            subprocess.run(cmd, check=True)
            return True
        except (OSError, subprocess.CalledProcessError) as exc:
            self.logger.debug("Playback backend failed: %s", exc)
            return False


class BrowserController:
    """Basic helper for launching Google Chrome with specific URLs."""

    def __init__(self, logger: logging.Logger, explicit_path: Optional[str] = None) -> None:
        self.logger = logger
        self.chrome_path = self._resolve_chrome(explicit_path)

    @property
    def available(self) -> bool:
        return bool(self.chrome_path)

    def _resolve_chrome(self, explicit_path: Optional[str]) -> Optional[str]:
        candidates: list[str] = []
        if explicit_path:
            candidates.append(explicit_path)

        env_path = os.environ.get("CHROME_PATH")
        if env_path:
            candidates.append(env_path)

        if os.name == "nt":
            roots = [
                os.environ.get("PROGRAMFILES"),
                os.environ.get("PROGRAMFILES(X86)"),
                os.environ.get("LOCALAPPDATA"),
            ]
            for root in roots:
                if not root:
                    continue
                candidates.append(os.path.join(root, "Google", "Chrome", "Application", "chrome.exe"))
        elif sys.platform == "darwin":
            candidates.append("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        else:
            candidates.extend(["google-chrome", "chrome", "chromium-browser", "chromium"])

        for candidate in candidates:
            resolved = self._expand_candidate(candidate)
            if resolved:
                self.logger.info("Chrome binary detected at %s", resolved)
                return resolved

        self.logger.warning(
            "Chrome binary not found; browser endpoint disabled. Provide --chrome or set CHROME_PATH."
        )
        return None

    def _expand_candidate(self, candidate: str) -> Optional[str]:
        candidate_path = pathlib.Path(candidate).expanduser()
        if candidate_path.is_absolute():
            return str(candidate_path) if candidate_path.exists() else None
        return shutil.which(candidate)

    def open_url(self, url: str, new_window: bool = False) -> str:
        if not self.chrome_path:
            raise FileNotFoundError("Chrome executable not available; set --chrome or CHROME_PATH")

        normalized = self._normalize_url(url)
        cmd = [self.chrome_path]
        cmd.append("--new-window" if new_window else "--new-tab")
        cmd.append(normalized)
        self.logger.info("Launching Chrome with %s", normalized)
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # noqa: S603,S607
        return normalized

    def _normalize_url(self, url: str) -> str:
        candidate = (url or "").strip()
        if not candidate:
            raise ValueError("URL is required for browser requests")

        parsed = urlparse(candidate)
        if not parsed.scheme:
            candidate = f"https://{candidate}"
        return candidate


class SpeakerRequestHandler(BaseHTTPRequestHandler):
    server_version = "CodexSpeaker/1.0"

    # Silence the default stdout logging; route through logging module instead.
    def log_message(self, fmt: str, *args: object) -> None:  # type: ignore[override]
        LOGGER.info("%s - %s", self.address_string(), fmt % args)

    def do_GET(self) -> None:  # type: ignore[override]
        if self.path == "/health":
            self._send_json({"status": "ok"})
        else:
            self.send_error(404, "Not found")

    def do_POST(self) -> None:  # type: ignore[override]
        LOGGER.info("Incoming %s request from %s", self.path, self.client_address[0])
        try:
            payload = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        except ValueError:
            self.send_error(400, "Invalid Content-Length")
            return

        content_type = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()

        if self.path == "/play":
            self._handle_play(payload, content_type)
        elif self.path == "/browser":
            self._handle_browser(payload, content_type)
        else:
            self.send_error(404, "Unknown endpoint")

    def _handle_play(self, payload: bytes, content_type: str) -> None:
        delete_after = False
        target_path: Optional[pathlib.Path] = None

        try:
            if content_type == "application/json":
                target_path = self._resolve_from_json(payload)
            else:
                target_path, delete_after = self._save_binary(payload)

            if not target_path:
                raise ValueError("Unable to determine target audio file")

            self.server.player.play(target_path)  # type: ignore[attr-defined]

            if delete_after and target_path.exists():
                target_path.unlink()

            self._send_json({"success": True, "path": str(target_path)})
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.exception("Playback failed: %s", exc)
            self.send_error(500, explain=str(exc))

    def _handle_browser(self, payload: bytes, content_type: str) -> None:
        if content_type != "application/json":
            self.send_error(415, "Browser endpoint requires application/json")
            return

        try:
            data = json.loads(payload.decode("utf-8")) if payload else {}
        except json.JSONDecodeError as exc:
            self.send_error(400, f"Invalid JSON payload: {exc}")
            return

        action = (data.get("action") or "open").lower()
        if action != "open":
            self.send_error(400, "Unsupported browser action; currently only 'open' is allowed")
            return

        controller: Optional[BrowserController] = getattr(self.server, "browser", None)  # type: ignore[attr-defined]
        if not controller or not controller.available:
            self.send_error(503, "Browser control unavailable; ensure Chrome is installed and detected")
            return

        url = data.get("url")
        new_window = bool(data.get("new_window", False))

        try:
            normalized = controller.open_url(url, new_window=new_window)
            self._send_json({"success": True, "action": action, "url": normalized, "new_window": new_window})
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.exception("Browser request failed: %s", exc)
            self.send_error(500, explain=str(exc))

    def _resolve_from_json(self, payload: bytes) -> pathlib.Path:
        try:
            data = json.loads(payload.decode("utf-8")) if payload else {}
        except json.JSONDecodeError as exc:  # pragma: no cover
            raise ValueError(f"Invalid JSON payload: {exc}") from exc

        candidate = data.get("relative_path") or data.get("path") or data.get("filename")
        if not candidate:
            raise ValueError("JSON payload must include 'relative_path' or 'path'")

        candidate_path = pathlib.Path(candidate)
        if not candidate_path.is_absolute():
            candidate_path = (self.server.outbox / candidate_path).resolve()  # type: ignore[attr-defined]

        return self._ensure_within_outbox(candidate_path)

    def _save_binary(self, payload: bytes) -> tuple[pathlib.Path, bool]:
        if not payload:
            raise ValueError("Binary request body is empty")

        filename = self.headers.get("X-Filename") or f"upload_{int(time.time() * 1000)}.mp3"
        filename = pathlib.Path(filename).name  # strip directories
        destination = (self.server.outbox / filename).resolve()  # type: ignore[attr-defined]
        destination = self._ensure_within_outbox(destination)

        with open(destination, "wb") as fh:
            fh.write(payload)

        return destination, True

    def _ensure_within_outbox(self, path: pathlib.Path) -> pathlib.Path:
        path = path.resolve()
        outbox = self.server.outbox.resolve()  # type: ignore[attr-defined]
        try:
            path.relative_to(outbox)
        except ValueError as exc:
            raise ValueError("Path must reside inside the configured voice outbox") from exc
        return path

    def _send_json(self, data: dict[str, object]) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        LOGGER.info("Completed %s request", self.path)


def _write_test_tone(target: pathlib.Path, duration: float = 0.5, freq: float = 660.0, sample_rate: int = 44100) -> None:
    frame_count = int(sample_rate * duration)
    with wave.open(str(target), "w") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        frames = bytearray()
        for i in range(frame_count):
            value = int(32767 * math.sin(2 * math.pi * freq * (i / sample_rate)))
            frames.extend(struct.pack("<h", value))
        wav_file.writeframes(frames)


def _run_startup_test(server: ThreadingHTTPServer) -> None:
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            temp_path = pathlib.Path(tmp.name)
        _write_test_tone(temp_path)
        LOGGER.info("Playing startup test tone to verify speaker output")
        server.player.play(temp_path)  # type: ignore[attr-defined]
    except Exception as exc:  # pragma: no cover - best-effort diagnostic
        LOGGER.warning("Startup audio test failed: %s", exc)
    finally:
        try:
            temp_path.unlink()
        except Exception:
            pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Codex speaker bridge service")
    parser.add_argument("--port", type=int, default=8777, help="Port to bind (default: 8777)")
    parser.add_argument("--bind", default="127.0.0.1", help="Host/IP to bind (default: 127.0.0.1; set to 0.0.0.0 for Docker access)")
    parser.add_argument("--outbox", required=True, help="Directory containing shared voice MP3s")
    parser.add_argument("--log", default=None, help="Optional log file path")
    parser.add_argument("--startup-test", action="store_true", help="Play a short tone after startup")
    parser.add_argument("--chrome", default=None, help="Optional explicit path to the Chrome executable")
    return parser.parse_args()


def configure_logging(log_path: Optional[str]) -> None:
    handlers = [logging.StreamHandler(sys.stdout)]
    if log_path:
        log_dir = os.path.dirname(log_path)
        if log_dir and not os.path.isdir(log_dir):
            os.makedirs(log_dir, exist_ok=True)
        handlers.append(logging.FileHandler(log_path, encoding="utf-8"))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=handlers,
    )


def main() -> None:
    args = parse_args()
    configure_logging(args.log)

    outbox = pathlib.Path(args.outbox).expanduser().resolve()
    outbox.mkdir(parents=True, exist_ok=True)

    server = ThreadingHTTPServer((args.bind, args.port), SpeakerRequestHandler)
    server.outbox = outbox  # type: ignore[attr-defined]
    server.player = AudioPlayer(LOGGER)  # type: ignore[attr-defined]
    server.browser = BrowserController(LOGGER, args.chrome)  # type: ignore[attr-defined]

    LOGGER.info("Speaker service ready on http://%s:%s (outbox=%s)", args.bind, args.port, outbox)
    if args.startup_test:
        threading.Thread(target=_run_startup_test, args=(server,), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("Speaker service interrupted; shutting down")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
