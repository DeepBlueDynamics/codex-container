#!/usr/bin/env python3
"""
Run 10 gateway crawl requests with proper backoff for long-running Codex sessions.

Each Codex session takes 30-120 seconds (persistent=False means we wait for completion).
With max 3 concurrent slots, we expect ~4 batches = 2-8 minutes total.

Retry strategy: Wait 15 seconds between retries.
"""

import asyncio
import json
import time
import random
import urllib.parse
import urllib.request
import urllib.error
from typing import Optional, Dict, Any, List

GATEWAY = "http://localhost:4000/completion"
MODEL = "gpt-5.1-codex-mini"
PROMPT = (
    "Use the MCP tool gnosis-crawl::crawl_url to fetch https://example.com . "
    "Return a short JSON object with keys: url, title (if present), and preview "
    "(first 120 chars of extracted text). If the crawl tool fails, return "
    "json with error and status fields describing what happened."
)
NUM_REQUESTS = 10

# Retry config - 15 second waits between retries
MAX_RETRIES = 20
RETRY_DELAY = 15.0  # seconds between retries


def sync_post(request_id: int) -> Dict[str, Any]:
    """
    Send a completion request, retrying on 429 with 15-second backoff.

    persistent=False means this blocks until Codex completes (30-120 seconds).
    """
    payload = {
        "messages": [{"role": "user", "content": PROMPT}],
        "model": MODEL,
        "persistent": False,  # BLOCKING - waits for Codex to finish
        "timeout_ms": 180000,  # 3 minute timeout per attempt
        "return_session_url": True,
    }
    data = json.dumps(payload).encode()

    for attempt in range(MAX_RETRIES):
        req = urllib.request.Request(
            GATEWAY,
            data=data,
            headers={"Content-Type": "application/json"},
        )
        try:
            print(f"  [req {request_id}] attempt {attempt + 1}/{MAX_RETRIES} - sending request...")
            start = time.time()
            with urllib.request.urlopen(req, timeout=200) as resp:
                elapsed = time.time() - start
                body = resp.read().decode("utf-8")
                try:
                    result = json.loads(body)
                    result["request_id"] = request_id
                    result["attempts"] = attempt + 1
                    result["elapsed_seconds"] = round(elapsed, 1)
                    print(f"  [req {request_id}] SUCCESS after {elapsed:.1f}s (attempt {attempt + 1})")
                    return result
                except Exception:
                    return {"request_id": request_id, "raw": body, "attempts": attempt + 1}

        except urllib.error.HTTPError as e:
            if e.code == 429:
                # Server at capacity - wait and retry
                jitter = random.uniform(0, 5)
                wait = RETRY_DELAY + jitter
                print(f"  [req {request_id}] 429 at capacity - waiting {wait:.0f}s before retry...")
                time.sleep(wait)
                continue
            # Other HTTP errors - don't retry
            body = e.read().decode("utf-8") if e.fp else ""
            print(f"  [req {request_id}] HTTP {e.code} error")
            try:
                err_data = json.loads(body)
                return {"request_id": request_id, "status": "http_error", "http_code": e.code, **err_data}
            except Exception:
                return {"request_id": request_id, "status": "http_error", "http_code": e.code, "error": str(e)}

        except urllib.error.URLError as e:
            print(f"  [req {request_id}] connection error: {e.reason}")
            return {"request_id": request_id, "status": "connection_error", "error": str(e.reason)}

        except Exception as e:
            print(f"  [req {request_id}] error: {e}")
            return {"request_id": request_id, "status": "error", "error": str(e)}

    # Exhausted retries
    print(f"  [req {request_id}] EXHAUSTED after {MAX_RETRIES} attempts")
    return {"request_id": request_id, "status": "exhausted", "error": f"Failed after {MAX_RETRIES} retries"}


async def run_request(request_id: int) -> Dict[str, Any]:
    """Run a single request in a thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, sync_post, request_id)


async def main():
    print("=" * 70)
    print("GATEWAY CRAWL TEST - 10 CONCURRENT REQUESTS")
    print("=" * 70)
    print(f"Gateway: {GATEWAY}")
    print(f"Model: {MODEL}")
    print(f"Requests: {NUM_REQUESTS}")
    print(f"Mode: persistent=False (BLOCKING - each request waits for Codex)")
    print(f"Retry: {MAX_RETRIES} attempts, {RETRY_DELAY}s between retries")
    print()
    print("NOTE: Each Codex session takes 30-120 seconds.")
    print("      With 3 concurrent slots, expect 2-8 minutes total.")
    print("=" * 70)
    print()

    start_time = time.time()

    # Launch all requests concurrently
    # They'll queue up via 429 retries as slots become available
    tasks = [run_request(i + 1) for i in range(NUM_REQUESTS)]
    results = await asyncio.gather(*tasks)

    elapsed = time.time() - start_time

    print()
    print("=" * 70)
    print("RESULTS")
    print("=" * 70)

    success_count = 0
    for res in results:
        rid = res.get("request_id", "?")
        status = res.get("status", "unknown")
        attempts = res.get("attempts", "?")
        elapsed_s = res.get("elapsed_seconds", "?")
        session_id = res.get("gateway_session_id") or res.get("session_id") or "none"
        content = res.get("content", "")

        if status == "completed" or session_id != "none":
            success_count += 1
            print(f"[{rid}] ✓ session={session_id[:12]}... attempts={attempts} time={elapsed_s}s")
            if content:
                preview = content[:100].replace('\n', ' ')
                print(f"     content: {preview}...")
        else:
            print(f"[{rid}] ✗ status={status} attempts={attempts}")
            if res.get("error"):
                print(f"     error: {res['error'][:80]}")

    print()
    print(f"Total: {success_count}/{NUM_REQUESTS} succeeded in {elapsed:.1f}s")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
