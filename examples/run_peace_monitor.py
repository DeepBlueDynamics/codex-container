#!/usr/bin/env python3
"""
Batch runner: crawl a small set of URLs, optionally expand via SerpAPI, then summarize de-escalation signals.
Assumes the MCP runtime exposes:
- gnosis-crawl.crawl_url
- serpapi-search.google_search_markdown (optional)
- term_graph_tools.filter_urls / sample_urls (if sample_urls exposed)
"""
import json
import os
import urllib.request

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:4000")
PROMPT_PATH = os.path.join(os.path.dirname(__file__), "peace_monitor_prompt.md")

# Seed URLs (replace with official/IGO/reputable news)
SEED_URLS = [
    "https://en.wikipedia.org/wiki/OpenAI",
    "https://www.un.org/en/",
]

def load_prompt():
    with open(PROMPT_PATH, "r", encoding="utf-8") as f:
        return f.read()

def call_completion(prompt):
    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "model": "gpt-5.1-codex-mini",
        "persistent": True,
        "timeout_ms": 300000,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{GATEWAY_URL}/completion",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))

def main():
    prompt = load_prompt()
    # Simple: embed seed URLs and tell the agent to crawl them; tool use is up to the agent.
    seed_block = "\n".join(f"- {u}" for u in SEED_URLS)
    full_prompt = prompt + f"\n\nSeed URLs:\n{seed_block}\n"
    result = call_completion(full_prompt)
    session_id = result.get("gateway_session_id") or result.get("session_id")
    print(f"Session: {session_id}")
    # Print agent content if returned inline
    content = result.get("content") or result.get("message")
    if content:
        print(content)
    else:
        print("Inspect session via /sessions/{id} for full output.")

if __name__ == "__main__":
    main()
