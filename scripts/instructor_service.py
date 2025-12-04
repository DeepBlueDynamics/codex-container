#!/usr/bin/env python3
"""
Instructor XL embedding service (GPU-aware).

Endpoints:
- POST /embed  body: {"texts": [...], "instruction": "...", "normalize": true}
- GET  /health

Caps: max 64 texts/request, basic size checks. Loads model once, prefers GPU.
"""

import json
import asyncio
import os
import sys
from typing import List

import aiohttp
from aiohttp import web

try:
    from InstructorEmbedding import INSTRUCTOR
except Exception as e:
    print(f"FATAL: InstructorEmbedding not available: {e}", file=sys.stderr, flush=True)
    raise

SERVICE_PORT = int(os.environ.get("INSTRUCTOR_PORT", "8787"))
MODEL_NAME = os.environ.get("INSTRUCTOR_MODEL", "hkunlp/instructor-xl")
MAX_TEXTS = int(os.environ.get("MAX_TEXTS", "64"))
MAX_CHARS = int(os.environ.get("MAX_CHARS", "8000"))

MODEL = None
DEVICE = "cpu"
MODEL_LOADING = False


async def load_model():
    global MODEL, DEVICE, MODEL_LOADING
    MODEL_LOADING = True
    try:
        import torch
        DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        DEVICE = "cpu"
    print(f"🔄 Loading Instructor model: {MODEL_NAME} on {DEVICE.upper()}", file=sys.stderr, flush=True)
    try:
        MODEL = INSTRUCTOR(MODEL_NAME)
        print(f"✅ Model ready: {MODEL_NAME} on {DEVICE.upper()}", file=sys.stderr, flush=True)
    except Exception as e:
        print(f"❌ Model load failed: {e}", file=sys.stderr, flush=True)
        MODEL = None
    MODEL_LOADING = False


async def handle_health(request):
    return web.json_response({
        "status": "ok",
        "model": MODEL_NAME,
        "device": DEVICE,
        "loaded": MODEL is not None,
        "loading": MODEL_LOADING,
        "max_texts": MAX_TEXTS,
        "max_chars": MAX_CHARS,
    })


def _validate_payload(data: dict) -> List[str]:
    if not isinstance(data, dict):
        raise ValueError("Body must be JSON object")
    texts = data.get("texts")
    if not isinstance(texts, list) or not all(isinstance(t, str) for t in texts):
        raise ValueError("Field 'texts' must be a list of strings")
    if len(texts) == 0:
        raise ValueError("Field 'texts' must not be empty")
    if len(texts) > MAX_TEXTS:
        raise ValueError(f"Too many texts (max {MAX_TEXTS})")
    for t in texts:
        if len(t) > MAX_CHARS:
            raise ValueError(f"Text too long (>{MAX_CHARS} chars)")
    return texts


async def handle_embed(request):
    if MODEL is None:
        status = 503 if MODEL_LOADING else 500
        msg = "Model is loading" if MODEL_LOADING else "Model not loaded"
        return web.json_response({"error": msg}, status=status)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    try:
        texts = _validate_payload(body)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)

    instruction = body.get("instruction") or "Represent the text for clustering"
    normalize = bool(body.get("normalize", True))

    pairs = [[instruction, t] for t in texts]

    try:
        vectors = MODEL.encode(pairs, normalize_embeddings=normalize)
        # Ensure JSON serializable
        embeddings = [v.tolist() for v in vectors]
    except Exception as e:
        print(f"❌ Embedding error: {e}", file=sys.stderr, flush=True)
        return web.json_response({"error": f"Embedding failed: {e}"}, status=500)

    return web.json_response({
        "model": MODEL_NAME,
        "device": DEVICE,
        "count": len(embeddings),
        "dim": len(embeddings[0]) if embeddings else 0,
        "embeddings": embeddings,
    })


async def on_startup(app):
    try:
        await load_model()
    except Exception as e:
        print(f"❌ Startup load failed: {e}", file=sys.stderr, flush=True)
        raise


def main():
    app = web.Application(client_max_size=8 * 1024 * 1024)  # 8MB limit
    app.router.add_post("/embed", handle_embed)
    app.router.add_get("/health", handle_health)
    app.on_startup.append(on_startup)

    print("=" * 60, file=sys.stderr, flush=True)
    print("INSTRUCTOR SERVICE STARTING", file=sys.stderr, flush=True)
    print(f"Port: {SERVICE_PORT}", file=sys.stderr, flush=True)
    print(f"Model: {MODEL_NAME}", file=sys.stderr, flush=True)
    print("=" * 60, file=sys.stderr, flush=True)

    web.run_app(app, host="0.0.0.0", port=SERVICE_PORT)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"FATAL: service failed to start: {e}", file=sys.stderr, flush=True)
        raise
