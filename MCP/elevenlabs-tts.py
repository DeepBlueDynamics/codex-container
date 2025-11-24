#!/usr/bin/env python3
"""
ElevenLabs MCP Bridge
=====================

Exposes ElevenLabs text-to-speech API to AI assistants via MCP.

Tools:
  - elevenlabs_status: Check API key configuration and connection
  - elevenlabs_list_voices: List available voices
  - elevenlabs_get_voice: Get details about a specific voice
  - elevenlabs_text_to_speech: Generate speech from text
  - elevenlabs_list_models: List available TTS models
  - elevenlabs_save_for_playback: Save audio to mounted workspace for host playback

Env/config:
  - ELEVENLABS_API_KEY (required)
  - .elevenlabs.env file in repo root with API key

Setup:
  1. Get API key from https://elevenlabs.io/
  2. Save to .elevenlabs.env:
     ```
     ELEVENLABS_API_KEY=your_api_key_here
     ```
  3. Run elevenlabs_status to verify connection

Notes:
  - API key is required for all operations
  - Prefer saving audio to a file (pass `output_path`) to keep MCP responses small
  - Inline base64 audio is only returned when explicitly requested via `include_audio_base64=True`
  - Pair with the `speaker-bridge` MCP server (`speaker_play`) to trigger
    playback once a file is generated
  - Default voice and model can be configured
"""

import os
import base64
import tempfile
import shutil
import time
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP, Context

# Try importing elevenlabs client
try:
    from elevenlabs.client import ElevenLabs
    from elevenlabs import VoiceSettings
    ELEVENLABS_AVAILABLE = True
except ImportError:
    ELEVENLABS_AVAILABLE = False


mcp = FastMCP("elevenlabs-tts")

# Config
ELEVENLABS_ENV_FILE = os.path.join(os.getcwd(), ".elevenlabs.env")


def _get_config() -> Dict[str, Optional[str]]:
    """Get configuration from environment or .elevenlabs.env file."""
    config = {
        "api_key": os.environ.get("ELEVENLABS_API_KEY"),
    }

    # Try loading from .elevenlabs.env if not in environment
    if not config["api_key"]:
        try:
            if os.path.exists(ELEVENLABS_ENV_FILE):
                with open(ELEVENLABS_ENV_FILE, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            key, value = line.split("=", 1)
                            key = key.strip()
                            value = value.strip().strip('"').strip("'")
                            if key == "ELEVENLABS_API_KEY":
                                config["api_key"] = value
        except Exception:
            pass

    return config


def _get_client():
    """Get authenticated ElevenLabs client or raise error."""
    if not ELEVENLABS_AVAILABLE:
        raise ImportError(
            "ElevenLabs library not installed. "
            "Run: pip install elevenlabs"
        )

    config = _get_config()
    if not config["api_key"]:
        raise ValueError(
            "ELEVENLABS_API_KEY not configured. "
            f"Set in environment or create {ELEVENLABS_ENV_FILE}"
        )

    return ElevenLabs(api_key=config["api_key"])


def _default_output_path(requested_path: Optional[str]) -> tuple[str, bool, str]:
    """Resolve the path where audio should be written."""

    if requested_path:
        directory = os.path.dirname(os.path.realpath(requested_path)) or os.getcwd()
        return requested_path, False, directory

    outbox = os.environ.get("VOICE_OUTBOX_CONTAINER_PATH") or os.path.join(os.getcwd(), "voice-outbox")
    outbox = os.path.realpath(outbox)
    os.makedirs(outbox, exist_ok=True)
    filename = f"elevenlabs_{int(time.time())}.mp3"
    return os.path.join(outbox, filename), False, outbox


@mcp.tool()
async def elevenlabs_status(ctx: Context = None) -> Dict[str, Any]:
    """
    Check ElevenLabs API configuration and connection status.

    Returns:
        Dictionary containing:
            - success: bool
            - library_installed: bool
            - api_key_present: bool
            - ready_to_use: bool
            - message: str
    """
    config = _get_config()

    library_ok = ELEVENLABS_AVAILABLE
    api_key_ok = bool(config["api_key"])

    # Try to connect if configured
    connection_ok = False
    if library_ok and api_key_ok:
        try:
            client = _get_client()
            # Simple test call
            voices = client.voices.get_all()
            connection_ok = True
        except Exception as e:
            return {
                "success": False,
                "library_installed": library_ok,
                "api_key_present": api_key_ok,
                "connection_ok": False,
                "ready_to_use": False,
                "error": f"Connection test failed: {str(e)}"
            }

    ready = library_ok and api_key_ok and connection_ok

    if not library_ok:
        message = "Install library: pip install elevenlabs"
    elif not api_key_ok:
        message = f"Configure API key in {ELEVENLABS_ENV_FILE}"
    elif connection_ok:
        message = "Ready! ElevenLabs API connected."
    else:
        message = "Configuration incomplete"

    return {
        "success": True,
        "library_installed": library_ok,
        "api_key_present": api_key_ok,
        "connection_ok": connection_ok,
        "ready_to_use": ready,
        "message": message
    }


@mcp.tool()
async def elevenlabs_list_voices(ctx: Context = None) -> Dict[str, Any]:
    """
    List all available ElevenLabs voices.

    Returns:
        Dictionary containing:
            - success: bool
            - voices: list of voice objects with id, name, category, description
            - count: int
    """
    try:
        client = _get_client()
        response = client.voices.get_all()

        voices = []
        for voice in response.voices:
            voices.append({
                "voice_id": voice.voice_id,
                "name": voice.name,
                "category": voice.category if hasattr(voice, 'category') else None,
                "description": voice.description if hasattr(voice, 'description') else None,
                "labels": voice.labels if hasattr(voice, 'labels') else {}
            })

        return {
            "success": True,
            "voices": voices,
            "count": len(voices)
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
async def elevenlabs_get_voice(
    voice_id: str,
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Get detailed information about a specific voice.

    Args:
        voice_id: ElevenLabs voice ID
        ctx: MCP context (optional)

    Returns:
        Dictionary containing:
            - success: bool
            - voice: voice object with full details
    """
    try:
        client = _get_client()
        voice = client.voices.get(voice_id=voice_id)

        return {
            "success": True,
            "voice": {
                "voice_id": voice.voice_id,
                "name": voice.name,
                "category": voice.category if hasattr(voice, 'category') else None,
                "description": voice.description if hasattr(voice, 'description') else None,
                "labels": voice.labels if hasattr(voice, 'labels') else {},
                "settings": {
                    "stability": voice.settings.stability if hasattr(voice, 'settings') else None,
                    "similarity_boost": voice.settings.similarity_boost if hasattr(voice, 'settings') else None,
                }
            }
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
async def elevenlabs_text_to_speech(
    text: str,
    voice_id: str = "21m00Tcm4TlvDq8ikWAM",  # Default: Rachel
    output_path: Optional[str] = None,
    model_id: str = "eleven_monolingual_v1",
    stability: float = 0.5,
    similarity_boost: float = 0.75,
    include_audio_base64: bool = False,
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Generate speech from text using ElevenLabs.

    Args:
        text: Text to convert to speech (required)
        voice_id: ElevenLabs voice ID (default: Rachel)
        output_path: Path to save audio file. Strongly recommended so downstream
            agents can reference a filename instead of huge payloads. Defaults to a
            workspace temp file when omitted.
        model_id: TTS model to use (default: eleven_monolingual_v1)
        stability: Voice stability (0.0-1.0, default: 0.5)
        similarity_boost: Voice similarity (0.0-1.0, default: 0.75)
        include_audio_base64: Set True only if you explicitly need inline audio
            data. Defaults to False to avoid megabyte-scale MCP responses.
        ctx: MCP context (optional)

    Returns:
        Dictionary containing:
            - success: bool
            - output_path: str (always saved to file)
            - audio_base64: str (only when include_audio_base64=True)
            - size_bytes: int
            - relative_path: str (when saved inside voice-outbox; pass to speaker_play)
    """
    try:
        client = _get_client()

        # Generate audio using v2 API
        audio_generator = client.text_to_speech.convert(
            text=text,
            voice_id=voice_id,
            model_id=model_id,
            voice_settings=VoiceSettings(
                stability=stability,
                similarity_boost=similarity_boost
            )
        )

        # Collect audio chunks
        audio_data = b"".join(audio_generator)

        # Always write audio to disk so callers can fetch it without inline blobs
        saved_path, created_temp_file, outbox_root = _default_output_path(output_path)

        with open(saved_path, "wb") as f:
            f.write(audio_data)

        response: Dict[str, Any] = {
            "success": True,
            "output_path": saved_path,
            "size_bytes": len(audio_data),
            "voice_id": voice_id,
            "model_id": model_id
        }

        relative_path: Optional[str] = None
        try:
            base_real = os.path.realpath(outbox_root)
            saved_real = os.path.realpath(saved_path)
            relative_path = os.path.relpath(saved_real, base_real)
        except Exception:
            relative_path = None

        if relative_path:
            response["relative_path"] = os.path.split(relative_path)[-1]
            response["filename"] = response["relative_path"]

        if include_audio_base64:
            response["audio_base64"] = base64.b64encode(audio_data).decode('utf-8')

        if created_temp_file and not include_audio_base64:
            response["message"] = (
                "Audio saved to a workspace temp file. Pass output_path or set "
                "include_audio_base64=True if you need inline audio next time."
            )
        else:
            hint = "Use speaker_play(relative_path='{}') to replay via the speaker bridge.".format(relative_path) if relative_path else "Use speaker_play to stream this file to the speaker bridge."
            response.setdefault("message", hint)

        return response

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
async def elevenlabs_list_models(ctx: Context = None) -> Dict[str, Any]:
    """
    List all available ElevenLabs TTS models.

    Returns:
        Dictionary containing:
            - success: bool
            - models: list of model objects
            - count: int
    """
    try:
        client = _get_client()
        response = client.models.get_all()

        models = []
        for model in response:
            models.append({
                "model_id": model.model_id,
                "name": model.name,
                "description": model.description if hasattr(model, 'description') else None,
                "languages": model.languages if hasattr(model, 'languages') else []
            })

        return {
            "success": True,
            "models": models,
            "count": len(models)
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
async def elevenlabs_save_for_playback(
    audio_base64: Optional[str] = None,
    filename: Optional[str] = None,
    audio_path: Optional[str] = None,
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Save audio to the mounted workspace for playback on the host machine.

    Since the container has no audio hardware, this writes files to /workspace
    which is mounted to the host. Provide either inline base64 data (set
    `include_audio_base64=True` when generating audio) or a path to an existing
    file previously written by the TTS tool.

    Args:
        audio_base64: Base64-encoded audio data to save.
        filename: Optional filename (default: elevenlabs_TIMESTAMP.mp3)
        audio_path: Optional source path to copy instead of base64
        ctx: MCP context (optional)

    Returns:
        Dictionary containing:
            - success: bool
            - container_path: str - Path inside container
            - filename: str - Saved filename
            - size_bytes: int
            - host_path_hint: str - Likely path on host machine
            - message: str - Instructions for playback
            - playback_instructions: list[str] - Example commands
    """
    try:
        import time

        if not audio_base64 and not audio_path:
            return {
                "success": False,
                "error": "Provide audio_base64 or audio_path when calling elevenlabs_save_for_playback"
            }

        if audio_path and not os.path.exists(audio_path):
            return {
                "success": False,
                "error": f"audio_path not found: {audio_path}"
            }

        if not filename:
            timestamp = int(time.time())
            filename = f"elevenlabs_{timestamp}.mp3"

        if not filename.endswith('.mp3'):
            filename += '.mp3'

        workspace_path = "/workspace"
        output_path = os.path.join(workspace_path, filename)

        if audio_base64:
            audio_data = base64.b64decode(audio_base64)
            with open(output_path, "wb") as f:
                f.write(audio_data)
        else:
            shutil.copy(audio_path, output_path)
            with open(output_path, "rb") as f:
                audio_data = f.read()

        size_bytes = len(audio_data)

        return {
            "success": True,
            "container_path": output_path,
            "filename": filename,
            "size_bytes": size_bytes,
            "host_path_hint": f"C:\\Users\\kord\\Code\\gnosis\\codex-container\\{filename}",
            "message": f"Audio saved to {output_path}. Play on host with: ffplay {filename} or open in your media player.",
            "playback_instructions": [
                f"From host terminal: ffplay {filename}",
                f"Or double-click: {filename}",
                f"Or use Windows Media Player / VLC"
            ]
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


if __name__ == "__main__":
    mcp.run()
