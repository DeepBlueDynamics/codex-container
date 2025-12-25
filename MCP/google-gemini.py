#!/usr/bin/env python3
"""
MCP server: Google Gemini API (text/multimodal) with simple API key auth.

Tools
- gemini_status: check API key presence and model access
- gemini_list_models: list generation-capable models
- gemini_chat: single-call text/multimodal generation
- set_gemini_key: capture/persist API key (like SerpAPI helper)
- gemini_chat_stream (optional): streaming variant (not implemented here; add if needed)

Auth
- Set GOOGLE_API_KEY in the environment (e.g., .env or shell export) OR use set_gemini_key to set/persist a key locally (.gemini.env).
- Obtain a key from Google AI Studio / Cloud Console with Gemini API enabled.

Defaults
- model: gemini-3-pro-preview (if available; caller can override to e.g. gemini-2.5-flash)
- temperature clamped to [0, 1]; max_tokens clamped (default 2048, hard cap 4096)

Notes
- This is API-key only (no OAuth). Fails fast if key missing/invalid.
- Dependency: google-generativeai

Setup flow for users
1) Get a Gemini API key: visit Google AI Studio (https://aistudio.google.com/) or Google Cloud Console and create/copy an API key with Gemini access.
2) Install dependency in the MCP venv: pip install google-generativeai
3) Set env: export GOOGLE_API_KEY=your_key_here (or call set_gemini_key, persist=True to write .gemini.env)
4) Restart MCP servers/container so the tool loads (if using env). If set via set_gemini_key in-memory, restart not required for current process.
5) Verify: call gemini_status; then gemini_chat with your prompt.
"""

from __future__ import annotations

import os
import base64
import json
from typing import Any, Dict, List, Optional, Tuple

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("google-gemini")

# Default model; caller can override (do not prefix with "models/"; SDK does that)
DEFAULT_MODEL = "gemini-3-pro-preview"
MAX_TOKENS_HARD_CAP = 4096
GEMINI_ENV_FILE = os.path.join(os.getcwd(), ".gemini.env")

# Lazy import to avoid startup failure if dependency is missing.
genai = None


def _extract_key_from_text(text: str) -> Optional[str]:
    """Parse a plausible API key from arbitrary text (similar to SerpAPI helper)."""
    if not text:
        return None
    raw = text.strip()
    # Common assignment forms
    for prefix in ("GOOGLE_API_KEY=", "google_api_key=", "api_key=", "key="):
        if prefix in raw:
            candidate = raw.split(prefix, 1)[1].strip().strip('"').strip("'")
            if candidate:
                return candidate
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if "GOOGLE_API_KEY=" in line:
            return line.split("GOOGLE_API_KEY=", 1)[1].strip().strip('"').strip("'")
        if line.lower().startswith("google_api_key="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    # Fallback: choose the longest plausible token
    tokens: List[str] = []
    current: List[str] = []
    for ch in raw:
        if ch.isalnum() or ch in ("-", "_"):
            current.append(ch)
        else:
            if current:
                tokens.append("".join(current))
                current = []
    if current:
        tokens.append("".join(current))
    candidates = [t for t in tokens if 20 <= len(t) <= 120]
    if not candidates:
        return None
    candidates.sort(key=len, reverse=True)
    return candidates[0]


def _write_gemini_env_file(key: str) -> Tuple[bool, Optional[str]]:
    try:
        with open(GEMINI_ENV_FILE, "w", encoding="utf-8") as f:
            f.write(f"GOOGLE_API_KEY={key}\n")
        return True, None
    except Exception as e:  # pragma: no cover - filesystem errors
        return False, str(e)


def _get_gemini_key() -> Optional[str]:
    key = os.environ.get("GOOGLE_API_KEY")
    if key:
        return key.strip()
    try:
        if os.path.exists(GEMINI_ENV_FILE):
            with open(GEMINI_ENV_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.startswith("GOOGLE_API_KEY="):
                        return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return None


def _configure() -> Dict[str, Any]:
    global genai
    if genai is None:
        try:
            import google.generativeai as _genai  # type: ignore
            genai = _genai
        except Exception as e:  # pragma: no cover - dependency missing
            raise RuntimeError("google-generativeai not installed in MCP venv. Install with: pip install google-generativeai") from e

    api_key = _get_gemini_key() or ""
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not set. Obtain a Gemini API key from Google AI Studio/Cloud Console or call set_gemini_key().")
    os.environ["GOOGLE_API_KEY"] = api_key  # ensure downstream access
    # Default to base host; SDK adds the versioned path (e.g., /v1beta/models).
    base_endpoint = os.environ.get("GEMINI_API_ENDPOINT", "https://generativelanguage.googleapis.com")
    genai.configure(
        api_key=api_key,
        transport="rest",
        client_options={"api_endpoint": base_endpoint},
    )
    return {"api_key_present": True, "key_last4": api_key[-4:]}


@mcp.tool()
def gemini_status() -> Dict[str, Any]:
    """Report whether GOOGLE_API_KEY is set and whether model listing works."""
    try:
        _configure()
        models = [
            m.name
            for m in genai.list_models()
            if any("generate" in method.lower() for method in getattr(m, "supported_generation_methods", []))
        ]
        return {
            "api_key_present": True,
            "model_count": len(models),
            "models_sample": models[:10],
            "message": "OK"
        }
    except Exception as e:  # pragma: no cover - runtime/SDK errors
        return {"api_key_present": False, "error": str(e)}


@mcp.tool()
def set_gemini_key(text: str, persist: bool = False) -> Dict[str, Any]:
    """Extract and set the Gemini API key from pasted text.

    - Parses common forms (e.g., "GOOGLE_API_KEY=..." or raw token)
    - Sets the key in-memory for this process
    - If persist=True, writes to a local .gemini.env file alongside the workspace
    """
    if not text:
        return {"success": False, "error": "No text provided"}
    key = _extract_key_from_text(text)
    if not key:
        return {"success": False, "error": "No valid key found in text"}

    os.environ["GOOGLE_API_KEY"] = key
    result: Dict[str, Any] = {
        "success": True,
        "set_in_memory": True,
        "key_last4": key[-4:],
        "persisted": False,
        "source": "env",
    }
    if persist:
        ok, err = _write_gemini_env_file(key)
        result["persisted"] = bool(ok)
        if not ok:
            result["persist_error"] = err
        else:
            result["source"] = ".gemini.env"
    return result


@mcp.tool()
def gemini_list_models() -> Dict[str, Any]:
    """List generation-capable models for this API key."""
    _configure()
    models = [
        {
            "name": m.name,
            "input_token_limit": getattr(m, "input_token_limit", None),
            "output_token_limit": getattr(m, "output_token_limit", None),
        }
        for m in genai.list_models()
        if any("generate" in method.lower() for method in getattr(m, "supported_generation_methods", []))
    ]
    return {"models": models, "count": len(models)}


@mcp.tool()
def gemini_chat(
    prompt: str,
    system: str = "",
    model: str = DEFAULT_MODEL,
    temperature: float = 0.3,
    max_tokens: int = 2048,
) -> Dict[str, Any]:
    """Single-call text (and light multimodal) generation."""
    if not prompt or not prompt.strip():
        return {"error": "empty_prompt"}

    temperature = max(0.0, min(1.0, temperature))
    max_tokens = min(max_tokens, MAX_TOKENS_HARD_CAP)

    _configure()
    # Join system + user messages into a simple conversation string
    msgs: List[str] = []
    if system:
        msgs.append(f"system: {system.strip()}")
    msgs.append(f"user: {prompt.strip()}")
    final_prompt = "\n".join(msgs)

    gmodel = genai.GenerativeModel(model)
    resp = gmodel.generate_content(
        final_prompt,
        generation_config={
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        },
    )
    # Some SDK responses use .text, others .candidates; prefer .text if present.
    text = getattr(resp, "text", None)
    if text is None and getattr(resp, "candidates", None):
        cand = resp.candidates[0]
        text = getattr(cand, "content", None) or getattr(cand, "text", None)

    return {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "text": text,
    }


@mcp.tool()
async def gemini_generate_image(
    prompt: str,
    model: str = "gemini-2.5-flash-image",
    sample_count: int = 1,
    output_path: str = "temp/nano_banana.png",
    input_image_path: str = "",
) -> Dict[str, Any]:
    """
    Generate an image via Gemini image-capable model and save to output_path.

    Uses the :generateContent endpoint with responseMimeType=image/png.
    Requires GOOGLE_API_KEY in env or .gemini.env.
    """
    if not prompt or not prompt.strip():
        return {"success": False, "error": "empty_prompt"}
    api_key = _get_gemini_key()
    if not api_key:
        return {"success": False, "error": "GOOGLE_API_KEY not set"}

    import aiohttp  # type: ignore
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Try generateContent for image models (non-prefixed model name, per SDK examples)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    parts = [{"text": prompt}]
    if input_image_path:
        try:
            with open(input_image_path, "rb") as f:
                img_bytes = f.read()
            import mimetypes  # lazy import
            mime, _ = mimetypes.guess_type(input_image_path)
            mime = mime or "application/octet-stream"
            parts.append({"inlineData": {"mimeType": mime, "data": base64.b64encode(img_bytes).decode("utf-8")}})
        except Exception as e:
            return {"success": False, "error": f"failed to read input_image_path: {e}"}

    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"responseMimeType": "image/png"},
    }
    if sample_count and sample_count > 1:
        payload["candidate_count"] = max(1, min(sample_count, 4))

    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            headers={
                "x-goog-api-key": api_key,
                "Content-Type": "application/json",
            },
            json=payload,
        ) as resp:
            body_text = await resp.text()
            if resp.status != 200:
                try:
                    err_json = json.loads(body_text)
                except Exception:
                    err_json = body_text
                return {"success": False, "status": resp.status, "error": err_json}
            try:
                data = json.loads(body_text)
            except Exception as e:
                return {"success": False, "status": resp.status, "error": f"json_parse_error: {e}", "raw": body_text}

    # Extract inline image data from candidates
    candidates = data.get("candidates") or []
    if not candidates:
        return {"success": False, "error": "no candidates in response", "raw": data}

    first = candidates[0]
    parts = first.get("content", {}).get("parts") or first.get("content", []) or []
    img_b64 = None
    for p in parts:
        if isinstance(p, dict) and "inlineData" in p and p["inlineData"].get("data"):
            img_b64 = p["inlineData"]["data"]
            break
        if isinstance(p, dict) and p.get("inline_data", {}).get("data"):
            img_b64 = p["inline_data"]["data"]
            break
    if not img_b64:
        # Some models return text-only; surface any text for debugging.
        text_fallback = None
        for p in parts:
            if isinstance(p, dict) and p.get("text"):
                text_fallback = p.get("text")
                break
        return {
            "success": False,
            "error": "no inlineData image bytes in response",
            "text": text_fallback,
            "raw": data,
        }

    try:
        raw = base64.b64decode(img_b64)
        output_path_dir = os.path.dirname(output_path)
        if output_path_dir:
            os.makedirs(output_path_dir, exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(raw)
        return {
            "success": True,
            "model": model,
            "output_path": output_path,
            "bytes": len(raw),
        }
    except Exception as e:  # pragma: no cover
        return {"success": False, "error": f"decode_error: {e}", "raw": str(e)}


if __name__ == "__main__":
    mcp.run()
