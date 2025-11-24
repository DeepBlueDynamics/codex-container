#!/usr/bin/env python3
"""Quick test to find which local models support tool calling"""

import json
import requests

OLLAMA_URL = "http://localhost:11434"

# Models to test (in priority order)
MODELS_TO_TEST = [
    "qwen3:14b",
    "qwen3:8b",
    "granite3.3:latest",
    "phi4-mini:latest",
    "llama3.2:latest",
    "qwen2.5:3b",
    "deepseek-r1:8b",
]

# Simple tool for testing
TOOLS = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get weather for a location",
        "parameters": {
            "type": "object",
            "properties": {
                "location": {"type": "string", "description": "City name"}
            },
            "required": ["location"]
        }
    }
}]

def test_model(model_name):
    """Test if a model supports tool calling"""
    print(f"\nTesting {model_name}...", end=" ", flush=True)

    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": model_name,
                "messages": [{"role": "user", "content": "What's the weather in NYC?"}],
                "tools": TOOLS,
                "stream": False
            },
            timeout=60
        )

        if response.status_code != 200:
            print(f"❌ HTTP {response.status_code}")
            return False

        result = response.json()
        message = result.get('message', {})

        # Check if model used tools
        if 'tool_calls' in message and message['tool_calls']:
            print(f"✅ SUPPORTS TOOLS ({len(message['tool_calls'])} calls)")
            print(f"   Tool: {message['tool_calls'][0]['function']['name']}")
            return True
        else:
            print(f"⚠️  No tool calls (may not support)")
            return False

    except requests.exceptions.Timeout:
        print("❌ Timeout")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def main():
    print("="*60)
    print("Testing Local Models for Tool Calling Support")
    print("="*60)

    # Get available models
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        available = {m['name'] for m in response.json().get('models', [])}
    except Exception as e:
        print(f"Error getting model list: {e}")
        return

    # Test each model
    working_models = []
    for model in MODELS_TO_TEST:
        if model not in available:
            print(f"\n{model}... ⊗ Not installed")
            continue

        if test_model(model):
            working_models.append(model)

    # Summary
    print("\n" + "="*60)
    print("RESULTS")
    print("="*60)

    if working_models:
        print("✅ Models with tool support:")
        for model in working_models:
            print(f"   • {model}")
        print(f"\n🎯 Recommended: {working_models[0]}")
    else:
        print("❌ No models with confirmed tool support found")
        print("\nTry installing one of these:")
        print("  ollama pull qwen2.5:7b")
        print("  ollama pull llama3.1:8b")
        print("  ollama pull mistral:7b-instruct")

if __name__ == "__main__":
    main()
