#!/usr/bin/env python3
"""
Quick Gemini image generation test (no external deps).

Usage:
  GOOGLE_API_KEY=... python3 tests/gemini_image_generate.py "your prompt"

Optional env:
  MODEL=gemini-2.5-flash-image      (default)
  OUTPUT=./temp/gemini_test.png     (default)
  COUNT=1                           (1-4)

The script calls :generateContent, extracts inline image bytes, and writes to OUTPUT.
If image-gen isn't enabled for the key/region, you'll get an error body/status.
"""

import os
import sys
import json
import base64
import pathlib
import urllib.request
import urllib.error
import mimetypes


def get_api_key() -> str:
    key = os.environ.get("GOOGLE_API_KEY")
    if key:
        return key
    env_path = pathlib.Path(".gemini.env")
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and line.startswith("GOOGLE_API_KEY="):
                return line.split("=", 1)[1].strip()
    return ""


def main():
    if len(sys.argv) < 2:
        print("Usage: GOOGLE_API_KEY=... python3 tests/gemini_image_generate.py prompt words here")
        sys.exit(1)

    api_key = get_api_key()
    if not api_key:
        print("GOOGLE_API_KEY is required (or .gemini.env with GOOGLE_API_KEY=...)")
        sys.exit(1)

    # Allow optional image path as last arg if it exists
    maybe_image = None
    if len(sys.argv) > 2 and pathlib.Path(sys.argv[-1]).exists():
        maybe_image = pathlib.Path(sys.argv[-1])
        prompt = " ".join(sys.argv[1:-1]).strip()
    else:
        prompt = " ".join(sys.argv[1:]).strip()
    if not prompt:
        print("Prompt cannot be empty")
        sys.exit(1)
    model = os.environ.get("MODEL", "gemini-2.5-flash-image")
    output = pathlib.Path(os.environ.get("OUTPUT", "./temp/gemini_test.png"))
    count = max(1, min(int(os.environ.get("COUNT", "1")), 4))

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    parts = [{"text": prompt}]
    if maybe_image:
        with open(maybe_image, "rb") as f:
            img_bytes = f.read()
        mime, _ = mimetypes.guess_type(str(maybe_image))
        mime = mime or "application/octet-stream"
        parts.append({"inlineData": {"mimeType": mime, "data": base64.b64encode(img_bytes).decode("utf-8")}})

    payload = {
        "contents": [{"role": "user", "parts": parts}],
    }
    if count and count > 1:
        payload["candidate_count"] = max(1, min(count, 4))

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            resp_text = resp.read().decode("utf-8")
            status = resp.getcode()
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        try:
            err_json = json.loads(err_body)
        except Exception:
            err_json = err_body
        print(json.dumps({"status": e.code, "error": err_json}, indent=2))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"status": "error", "error": str(e)}, indent=2))
        sys.exit(1)

    try:
        data = json.loads(resp_text)
    except Exception as e:
        print(json.dumps({"status": "error", "error": f"json_parse_error: {e}", "raw": resp_text}, indent=2))
        sys.exit(1)

    if status != 200:
        print(json.dumps({"status": status, "error": data}, indent=2))
        sys.exit(1)

    candidates = data.get("candidates") or []
    if not candidates:
        print(json.dumps({"status": "error", "error": "no candidates in response", "raw": data}, indent=2))
        sys.exit(1)

    first = candidates[0] if isinstance(candidates[0], dict) else None
    parts = None
    if first:
        parts = first.get("content", {}).get("parts")
        if not parts and isinstance(first.get("content"), list):
            parts = first.get("content")
    img_b64 = None
    if parts:
        for p in parts:
            if isinstance(p, dict) and "inlineData" in p and p["inlineData"].get("data"):
                img_b64 = p["inlineData"]["data"]
                break
            if isinstance(p, dict) and p.get("inline_data", {}).get("data"):
                img_b64 = p["inline_data"]["data"]
                break
    if not img_b64:
        print(json.dumps({"status": "error", "error": "no image bytes in response", "raw": first}, indent=2))
        sys.exit(1)

    raw = base64.b64decode(img_b64)
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "wb") as f:
        f.write(raw)

    print(json.dumps(
        {
            "status": "ok",
            "model": model,
            "saved_to": str(output),
            "bytes": len(raw),
        },
        indent=2,
    ))


if __name__ == "__main__":
    main()
