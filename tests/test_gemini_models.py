"""Quick check that a configured Gemini API key can list generation models.

Run with: python -m pytest tests/test_gemini_models.py -q

Notes:
- Requires GOOGLE_API_KEY in the environment or .gemini.env alongside the repo.
- Fails with a clear message if no generation-capable models are returned.
"""

from __future__ import annotations

import json
import os
import urllib.request


def load_api_key() -> str:
    key = os.environ.get("GOOGLE_API_KEY")
    if key:
        return key.strip()
    # fallback to .gemini.env in cwd
    env_path = os.path.join(os.getcwd(), ".gemini.env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("GOOGLE_API_KEY="):
                    return line.split("=", 1)[1].strip()
    raise RuntimeError("GOOGLE_API_KEY not set and .gemini.env not found")


def fetch_models(key: str):
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}"
    with urllib.request.urlopen(url) as resp:  # type: ignore
        data = json.load(resp)
    return data.get("models", [])


def test_gemini_models_present():
    key = load_api_key()
    models = fetch_models(key)
    gen_models = [
        m for m in models
        if "generation" in m.get("supportedGenerationMethods", [])
    ]
    if not gen_models:
        raise AssertionError(
            "No generation-capable models returned. Key may be embeddings-only. "
            "Check Gemini access in Google AI Studio/Cloud and retry."
        )

    # Basic sanity: print a few for pytest -q output when verbose
    for m in gen_models[:5]:
        print("gen model:", m.get("name"))


if __name__ == "__main__":
    test_gemini_models_present()
