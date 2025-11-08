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
  - Generated audio is returned as base64-encoded data
  - Default voice and model can be configured
"""

import os
import base64
import subprocess
import tempfile
from typing import Any, Dict, List, Optional
from pathlib import Path

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
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Generate speech from text using ElevenLabs.

    Args:
        text: Text to convert to speech (required)
        voice_id: ElevenLabs voice ID (default: Rachel)
        output_path: Path to save audio file (optional, saves to /tmp if in container)
        model_id: TTS model to use (default: eleven_monolingual_v1)
        stability: Voice stability (0.0-1.0, default: 0.5)
        similarity_boost: Voice similarity (0.0-1.0, default: 0.75)
        ctx: MCP context (optional)

    Returns:
        Dictionary containing:
            - success: bool
            - output_path: str (if saved to file)
            - audio_base64: str (base64-encoded audio data)
            - size_bytes: int
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

        # Save to file if path provided
        saved_path = None
        if output_path:
            with open(output_path, "wb") as f:
                f.write(audio_data)
            saved_path = output_path

        return {
            "success": True,
            "output_path": saved_path,
            "audio_base64": base64.b64encode(audio_data).decode('utf-8'),
            "size_bytes": len(audio_data),
            "voice_id": voice_id,
            "model_id": model_id
        }

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
    audio_base64: str,
    filename: Optional[str] = None,
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Save base64 audio to mounted workspace for playback on host machine.

    Since the container has no audio hardware, this saves audio to /workspace
    which is mounted to the host. The host can then play the file.

    Args:
        audio_base64: Base64-encoded audio data to save (required)
        filename: Optional filename (default: elevenlabs_TIMESTAMP.mp3)
        ctx: MCP context (optional)

    Returns:
        Dictionary containing:
            - success: bool
            - container_path: str - Path inside container
            - host_path_hint: str - Likely path on host machine
            - message: str - Instructions for playback
    """
    try:
        import time

        # Decode audio data
        audio_data = base64.b64decode(audio_base64)

        # Generate filename if not provided
        if not filename:
            timestamp = int(time.time())
            filename = f"elevenlabs_{timestamp}.mp3"

        # Ensure .mp3 extension
        if not filename.endswith('.mp3'):
            filename += '.mp3'

        # Save to workspace (mounted to host)
        workspace_path = "/workspace"
        output_path = os.path.join(workspace_path, filename)

        with open(output_path, "wb") as f:
            f.write(audio_data)

        return {
            "success": True,
            "container_path": output_path,
            "filename": filename,
            "size_bytes": len(audio_data),
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
