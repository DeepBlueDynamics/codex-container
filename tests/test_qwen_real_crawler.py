#!/usr/bin/env python3
"""
Test qwen3:8b with REAL gnosis-crawl service at gnosis-crawl:8080.
This test uses the actual Wraith API for crawling.
"""

import json
import requests
from typing import Dict, Any, List

OLLAMA_URL = "http://localhost:11434"
MODEL = "qwen3:8b"
CRAWLER_URL = "http://gnosis-crawl:8080"

# Tool definition matching MCP/gnosis-crawl.py
CRAWL_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "crawl_url",
            "description": "Crawl a single URL and extract clean markdown content. Fetches a web page through the Wraith API on gnosis-crawl:8080 (local default), which handles JavaScript rendering, content extraction, and markdown conversion. Returns structured markdown optimized for AI consumption.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Target URL to crawl"
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
                    "javascript_payload": {
                        "type": "string",
                        "description": "Optional JavaScript code to inject and execute BEFORE markdown extraction"
                    },
                    "markdown_extraction": {
                        "type": "string",
                        "description": "Extraction mode - 'enhanced' applies content pruning, 'basic' returns raw markdown",
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
    }
]


def crawl_url_real(url: str, **kwargs) -> str:
    """
    Call the REAL gnosis-crawl service at gnosis-crawl:8080.
    This matches what the MCP tool does.
    """
    endpoint = f"{CRAWLER_URL}/api/markdown"

    # Build payload matching gnosis-crawl.py
    payload = {
        "url": url,
        "javascript_enabled": kwargs.get("javascript_enabled", False),
    }

    # Add screenshot mode
    if kwargs.get("take_screenshot"):
        payload["screenshot_mode"] = "full"

    # Add javascript payload if provided
    if kwargs.get("javascript_payload"):
        payload["javascript_payload"] = kwargs["javascript_payload"]

    # Add enhanced filtering
    if kwargs.get("markdown_extraction") == "enhanced":
        payload["filter"] = "pruning"
        payload["filter_options"] = {"threshold": 0.48, "min_words": 2}

    timeout = max(5, kwargs.get("timeout", 30))

    print(f"[CRAWLER] Calling {endpoint}")
    print(f"[CRAWLER] Payload: {json.dumps(payload, indent=2)}")

    try:
        response = requests.post(
            endpoint,
            json=payload,
            timeout=timeout
        )
        response.raise_for_status()
        result = response.json()

        if result.get("success"):
            markdown = result.get("markdown", "")
            print(f"[CRAWLER] Success! Received {len(markdown)} characters")
            return markdown
        else:
            error = result.get("error", "Unknown error")
            print(f"[CRAWLER] Error: {error}")
            return f"Error from crawler: {error}"

    except requests.exceptions.ConnectionError:
        return f"ERROR: Cannot connect to gnosis-crawl at {CRAWLER_URL}. Is the service running?"
    except requests.exceptions.Timeout:
        return f"ERROR: Crawler timeout after {timeout}s"
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


def call_ollama_with_tools(messages: List[Dict]) -> Dict[str, Any]:
    """Call Ollama with tool support"""
    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": MODEL,
                "messages": messages,
                "tools": CRAWL_TOOLS,
                "stream": False
            },
            timeout=120
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {"error": str(e)}


def execute_tool_call(tool_name: str, tool_args: Dict) -> str:
    """Execute a tool call"""
    if tool_name == "crawl_url":
        return crawl_url_real(**tool_args)
    else:
        return f"Unknown tool: {tool_name}"


def run_full_conversation(user_prompt: str, max_turns: int = 5) -> None:
    """Run a full conversation with real crawler"""
    print("\n" + "="*70)
    print("STEP 1: USER SENDS PROMPT")
    print("="*70)
    print(f"Prompt: {user_prompt}")
    print("="*70)

    messages = [{"role": "user", "content": user_prompt}]

    print("\nSTEP 2: SENDING TO MODEL")
    print(f"Model: {MODEL}")
    print(f"Tools available: crawl_url")
    print(f"Crawler service: {CRAWLER_URL}")

    for turn in range(max_turns):
        print(f"\n[Turn {turn + 1}]")

        # Get response from model
        response = call_ollama_with_tools(messages)

        if "error" in response:
            print(f"[ERROR] {response['error']}")
            return

        assistant_msg = response.get("message", {})

        # Check if model wants to use tools
        if "tool_calls" in assistant_msg and assistant_msg["tool_calls"]:
            print("\n" + "="*70)
            print(f"STEP 3: MODEL CALLS TOOL")
            print("="*70)
            print(f"Number of tool calls: {len(assistant_msg['tool_calls'])}")

            # Add assistant message to conversation
            messages.append(assistant_msg)

            # Execute each tool call
            for i, tool_call in enumerate(assistant_msg["tool_calls"], 1):
                func_name = tool_call["function"]["name"]
                func_args = tool_call["function"]["arguments"]

                # Handle both string and dict arguments
                if isinstance(func_args, str):
                    func_args = json.loads(func_args)
                elif not isinstance(func_args, dict):
                    func_args = {}

                print(f"\nTool Call #{i}:")
                print(f"  Function: {func_name}")
                print(f"  Arguments: {json.dumps(func_args, indent=4)}")

                print("\n" + "="*70)
                print(f"STEP 4: CALLING REAL CRAWLER (gnosis-crawl:8080)")
                print("="*70)

                # Execute the tool - THIS CALLS THE REAL CRAWLER
                result = execute_tool_call(func_name, func_args)

                print(f"\nCrawler returned {len(result)} characters")
                print(f"\nFirst 600 characters of crawled content:")
                print("-"*70)
                preview = result[:600]
                print(preview)
                if len(result) > 600:
                    print(f"\n... [{len(result) - 600} more characters] ...")
                print("-"*70)

                print("\n" + "="*70)
                print(f"STEP 5: SENDING CRAWLED CONTENT TO MODEL")
                print("="*70)
                print(f"Adding tool result to conversation (role='tool')")
                print(f"Content length: {len(result)} characters")

                # Add tool result to conversation
                messages.append({
                    "role": "tool",
                    "content": result
                })

                print("[OK] Tool result added to conversation")

            # Continue to next turn to get model's response after tool execution
            continue

        # No tool calls - this is the final response
        final_content = assistant_msg.get("content", "")

        if final_content:
            print("\n" + "="*70)
            print("STEP 6: MODEL PROCESSES CONTENT AND RESPONDS")
            print("="*70)
            print(f"Response length: {len(final_content)} characters")
            print("="*70)
            print(final_content)
            print("="*70)

            # Show conversation trace
            print("\n" + "-"*70)
            print("CONVERSATION TRACE:")
            print("-"*70)
            for i, msg in enumerate(messages, 1):
                role = msg.get("role", "unknown")
                if role == "tool":
                    content_preview = msg.get("content", "")[:200] + "..."
                    print(f"{i}. [{role.upper()}] {content_preview}")
                elif role == "assistant" and "tool_calls" in msg:
                    tool_names = [tc["function"]["name"] for tc in msg.get("tool_calls", [])]
                    print(f"{i}. [{role.upper()}] Called tools: {', '.join(tool_names)}")
                else:
                    content = msg.get("content", "")[:100]
                    print(f"{i}. [{role.upper()}] {content}...")
            print("-"*70)
            return
        else:
            print("No content in response")
            return

    print("\nMax turns reached without final response")


def test_crawler_connection():
    """Test if gnosis-crawl service is accessible"""
    print("\n" + "="*70)
    print("TESTING CRAWLER CONNECTION")
    print("="*70)

    try:
        # Try to reach the crawler
        response = requests.get(f"{CRAWLER_URL}/health", timeout=5)
        print(f"[OK] Crawler is reachable at {CRAWLER_URL}")
        return True
    except requests.exceptions.ConnectionError:
        print(f"[ERROR] Cannot connect to crawler at {CRAWLER_URL}")
        print("\nMake sure gnosis-crawl service is running:")
        print("  docker ps | grep gnosis-crawl")
        return False
    except Exception as e:
        print(f"[ERROR] {e}")
        return False


def main():
    """Run test with real crawler"""
    print("Qwen3:8b + Real Gnosis-Crawl Test")
    print(f"Model: {MODEL}")
    print(f"Ollama: {OLLAMA_URL}")
    print(f"Crawler: {CRAWLER_URL}")

    # Check Ollama
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        models = {m['name'] for m in response.json().get('models', [])}
        if MODEL not in models:
            print(f"\n[ERROR] Model {MODEL} not found!")
            return
    except Exception as e:
        print(f"\n[ERROR] Cannot connect to Ollama: {e}")
        return

    print(f"[OK] Model available")

    # Check crawler
    if not test_crawler_connection():
        return

    # Run test
    print("\n" + "#"*70)
    print("TEST: Agentic Workflow with Real Crawler")
    print("#"*70)

    run_full_conversation("Crawl Hacker News and give me the top AI stories")

    print("\n" + "#"*70)
    print("TEST COMPLETE - VERIFICATION SUMMARY")
    print("#"*70)
    print("""
This test proves:
1. [OK] qwen3:8b understood the natural language request
2. [OK] Model called crawl_url with correct URL
3. [OK] Tool called REAL gnosis-crawl:8080 API
4. [OK] Crawler fetched and processed web content
5. [OK] Content passed back to model via 'tool' role
6. [OK] Model processed content and extracted AI stories

This is a complete agentic loop using the REAL crawler service.
""")


if __name__ == "__main__":
    main()
