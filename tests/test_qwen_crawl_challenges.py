#!/usr/bin/env python3
"""
Test qwen3:8b with gnosis-crawl tool challenges.
Tests the model's ability to map natural language to crawl tool calls.
"""

import json
import requests
from typing import Dict, Any, List

OLLAMA_URL = "http://localhost:11434"
MODEL = "qwen3:8b"

# Define gnosis-crawl tools based on MCP/gnosis-crawl.py
CRAWL_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "crawl_url",
            "description": "Crawl a single URL and extract clean markdown content. Fetches web pages through Wraith API, handles JavaScript rendering, content extraction, and markdown conversion.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Target URL to crawl (e.g., https://example.com)"
                    },
                    "take_screenshot": {
                        "type": "boolean",
                        "description": "If True, capture a full-page screenshot",
                        "default": False
                    },
                    "javascript_enabled": {
                        "type": "boolean",
                        "description": "If True, execute JavaScript before extracting content",
                        "default": False
                    },
                    "markdown_extraction": {
                        "type": "string",
                        "description": "Extraction mode - 'enhanced' applies content pruning",
                        "enum": ["enhanced", "basic"],
                        "default": "enhanced"
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Request timeout in seconds (minimum 5)",
                        "default": 30
                    }
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "crawl_batch",
            "description": "Crawl multiple URLs in a single batch operation. Processes multiple URLs with options for async processing and automatic collation. Max 50 URLs per batch.",
            "parameters": {
                "type": "object",
                "properties": {
                    "urls": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of URLs to crawl (max 50)"
                    },
                    "javascript_enabled": {
                        "type": "boolean",
                        "description": "If True, execute JavaScript on each page",
                        "default": False
                    },
                    "take_screenshot": {
                        "type": "boolean",
                        "description": "If True, capture screenshots for each URL",
                        "default": False
                    },
                    "async_mode": {
                        "type": "boolean",
                        "description": "If True, process URLs asynchronously (faster)",
                        "default": True
                    },
                    "collate": {
                        "type": "boolean",
                        "description": "If True, combine all results into single markdown document",
                        "default": False
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Request timeout in seconds (minimum 10)",
                        "default": 60
                    }
                },
                "required": ["urls"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "crawl_status",
            "description": "Check Wraith crawler configuration and connection status. Reports server URL and auth token status.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    }
]

# Test challenges - from simple to complex
CHALLENGES = [
    {
        "id": 1,
        "name": "Complex inference with intent",
        "prompt": "Crawl Hacker News and give me the top AI stories",
        "expected_tool": "crawl_url",
        "expected_url_contains": ["news.ycombinator.com", "ycombinator.com"],
        "difficulty": "medium"
    },
    {
        "id": 2,
        "name": "Multiple site batch",
        "prompt": "Crawl both Hacker News and Reddit's programming page",
        "expected_tool": "crawl_batch",
        "expected_urls": 2,
        "difficulty": "medium"
    },
    {
        "id": 3,
        "name": "Explicit URL",
        "prompt": "Crawl https://www.anthropic.com",
        "expected_tool": "crawl_url",
        "expected_url_exact": "https://www.anthropic.com",
        "difficulty": "easy"
    },
    {
        "id": 4,
        "name": "JavaScript requirement",
        "prompt": "Crawl Twitter (it needs JavaScript to load)",
        "expected_tool": "crawl_url",
        "expected_params": {"javascript_enabled": True},
        "difficulty": "medium"
    },
    {
        "id": 5,
        "name": "Status check",
        "prompt": "Check if the crawler is working",
        "expected_tool": "crawl_status",
        "difficulty": "easy"
    },
    {
        "id": 6,
        "name": "Collated batch",
        "prompt": "Crawl the top 3 tech news sites and combine them into one document",
        "expected_tool": "crawl_batch",
        "expected_params": {"collate": True},
        "expected_urls": 3,
        "difficulty": "hard"
    },
    {
        "id": 7,
        "name": "Screenshot request",
        "prompt": "Crawl GitHub's homepage and take a screenshot",
        "expected_tool": "crawl_url",
        "expected_params": {"take_screenshot": True},
        "difficulty": "medium"
    },
    {
        "id": 8,
        "name": "Common abbreviation",
        "prompt": "Crawl HN",
        "expected_tool": "crawl_url",
        "expected_url_contains": ["news.ycombinator.com", "ycombinator.com"],
        "difficulty": "hard"
    },
    {
        "id": 9,
        "name": "Research task with multiple sources",
        "prompt": "Research the latest in quantum computing by crawling ArXiv and Nature",
        "expected_tool": "crawl_batch",
        "expected_urls": 2,
        "difficulty": "hard"
    },
    {
        "id": 10,
        "name": "Specific content request",
        "prompt": "Get me the pricing information from Anthropic's website",
        "expected_tool": "crawl_url",
        "expected_url_contains": ["anthropic.com"],
        "difficulty": "medium"
    },
    {
        "id": 11,
        "name": "Comparison task",
        "prompt": "Compare pricing by crawling OpenAI and Anthropic websites and combine the results",
        "expected_tool": "crawl_batch",
        "expected_params": {"collate": True},
        "expected_urls": 2,
        "difficulty": "hard"
    }
]


def call_ollama(messages: List[Dict], tools: List[Dict]) -> Dict[str, Any]:
    """Call Ollama with tools"""
    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": MODEL,
                "messages": messages,
                "tools": tools,
                "stream": False
            },
            timeout=60
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {"error": str(e)}


def validate_challenge(challenge: Dict, response: Dict) -> Dict[str, Any]:
    """Validate model response against challenge expectations"""
    result = {
        "passed": False,
        "reason": "",
        "tool_called": None,
        "args": None
    }

    message = response.get("message", {})
    tool_calls = message.get("tool_calls", [])

    if not tool_calls:
        result["reason"] = "No tool called"
        return result

    # Get first tool call
    tool_call = tool_calls[0]
    function_name = tool_call["function"]["name"]
    function_args = tool_call["function"]["arguments"]

    # Handle both string and dict args
    if isinstance(function_args, str):
        function_args = json.loads(function_args)
    elif not isinstance(function_args, dict):
        function_args = {}

    result["tool_called"] = function_name
    result["args"] = function_args

    # Check expected tool
    expected_tool = challenge.get("expected_tool")
    if expected_tool and function_name != expected_tool:
        result["reason"] = f"Wrong tool: got {function_name}, expected {expected_tool}"
        return result

    # Check URL for crawl_url
    if function_name == "crawl_url":
        url = function_args.get("url", "").lower()

        if "expected_url_exact" in challenge:
            if url != challenge["expected_url_exact"].lower():
                result["reason"] = f"Wrong URL: got {url}, expected {challenge['expected_url_exact']}"
                return result

        if "expected_url_contains" in challenge:
            if not any(exp in url for exp in challenge["expected_url_contains"]):
                result["reason"] = f"URL '{url}' doesn't contain any of {challenge['expected_url_contains']}"
                return result

    # Check URLs for crawl_batch
    if function_name == "crawl_batch":
        urls = function_args.get("urls", [])

        if "expected_urls" in challenge:
            if len(urls) != challenge["expected_urls"]:
                result["reason"] = f"Wrong URL count: got {len(urls)}, expected {challenge['expected_urls']}"
                return result

    # Check expected params
    if "expected_params" in challenge:
        for key, expected_val in challenge["expected_params"].items():
            actual_val = function_args.get(key)
            if actual_val != expected_val:
                result["reason"] = f"Wrong param {key}: got {actual_val}, expected {expected_val}"
                return result

    # All checks passed
    result["passed"] = True
    result["reason"] = "All checks passed"
    return result


def run_challenge(challenge: Dict) -> Dict[str, Any]:
    """Run a single challenge"""
    print(f"\nChallenge {challenge['id']}: {challenge['name']}")
    print(f"Difficulty: {challenge['difficulty']}")
    print(f"Prompt: \"{challenge['prompt']}\"")

    messages = [{"role": "user", "content": challenge["prompt"]}]
    response = call_ollama(messages, CRAWL_TOOLS)

    if "error" in response:
        print(f"[ERROR] {response['error']}")
        return {"challenge": challenge, "passed": False, "error": response["error"]}

    validation = validate_challenge(challenge, response)

    if validation["passed"]:
        print(f"[PASS] {validation['reason']}")
        print(f"   Tool: {validation['tool_called']}")
        if validation['args']:
            print(f"   Args: {json.dumps(validation['args'], indent=10)[:200]}")
    else:
        print(f"[FAIL] {validation['reason']}")
        print(f"   Tool called: {validation['tool_called']}")
        print(f"   Args: {json.dumps(validation['args'], indent=10)[:200]}")

    return {
        "challenge": challenge,
        "passed": validation["passed"],
        "reason": validation["reason"],
        "tool_called": validation["tool_called"],
        "args": validation["args"]
    }


def main():
    """Run all challenges"""
    print("="*70)
    print(f"Qwen3:8b Crawl Challenge Suite")
    print(f"Model: {MODEL}")
    print(f"Ollama: {OLLAMA_URL}")
    print("="*70)

    # Check model availability
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        models = {m['name'] for m in response.json().get('models', [])}
        if MODEL not in models:
            print(f"\n[ERROR] Model {MODEL} not found!")
            print(f"Available: {', '.join(sorted(models))}")
            return
    except Exception as e:
        print(f"\n[ERROR] Cannot connect to Ollama: {e}")
        return

    print(f"\n[OK] Model {MODEL} available")
    print(f"\nRunning {len(CHALLENGES)} challenges...")

    # Run challenges
    results = []
    for challenge in CHALLENGES:
        result = run_challenge(challenge)
        results.append(result)

    # Summary
    print("\n" + "="*70)
    print("RESULTS SUMMARY")
    print("="*70)

    by_difficulty = {"easy": [], "medium": [], "hard": []}
    for r in results:
        diff = r["challenge"]["difficulty"]
        by_difficulty[diff].append(r)

    for difficulty in ["easy", "medium", "hard"]:
        challenges = by_difficulty[difficulty]
        if not challenges:
            continue

        passed = sum(1 for c in challenges if c["passed"])
        total = len(challenges)
        pct = (passed / total * 100) if total > 0 else 0

        print(f"\n{difficulty.upper()}: {passed}/{total} ({pct:.0f}%)")
        for r in challenges:
            status = "[PASS]" if r["passed"] else "[FAIL]"
            print(f"  {status} #{r['challenge']['id']}: {r['challenge']['name']}")

    # Overall
    total_passed = sum(1 for r in results if r["passed"])
    total = len(results)
    overall_pct = (total_passed / total * 100) if total > 0 else 0

    print(f"\n{'='*70}")
    print(f"OVERALL: {total_passed}/{total} ({overall_pct:.0f}%)")
    print(f"{'='*70}")

    # Detailed failures
    failures = [r for r in results if not r["passed"]]
    if failures:
        print(f"\nFailed Challenges Details:")
        for r in failures:
            print(f"\n  #{r['challenge']['id']}: {r['challenge']['name']}")
            print(f"  Reason: {r['reason']}")
            if r.get("tool_called"):
                print(f"  Tool called: {r['tool_called']}")
                print(f"  Args: {json.dumps(r.get('args', {}), indent=4)}")


if __name__ == "__main__":
    main()
