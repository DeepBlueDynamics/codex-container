#!/usr/bin/env python3
"""
Test script for Ollama gpt-oss:120b-cloud model with tool use.
Tests function calling capabilities on local Ollama instance.
"""

import json
import requests
from datetime import datetime

OLLAMA_URL = "http://localhost:11434"
MODEL = "gpt-oss:120b-cloud"

# Define test tools
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_current_weather",
            "description": "Get the current weather for a location",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "The city and state, e.g. San Francisco, CA"
                    },
                    "unit": {
                        "type": "string",
                        "enum": ["celsius", "fahrenheit"],
                        "description": "The temperature unit to use"
                    }
                },
                "required": ["location"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "Perform a mathematical calculation",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "The mathematical expression to evaluate"
                    }
                },
                "required": ["expression"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_time",
            "description": "Get the current time in a specific timezone",
            "parameters": {
                "type": "object",
                "properties": {
                    "timezone": {
                        "type": "string",
                        "description": "IANA timezone name, e.g. America/New_York"
                    }
                },
                "required": ["timezone"]
            }
        }
    }
]

# Mock tool implementations
def get_current_weather(location, unit="fahrenheit"):
    """Mock weather function"""
    return {
        "location": location,
        "temperature": 72 if unit == "fahrenheit" else 22,
        "unit": unit,
        "conditions": "sunny",
        "humidity": 45
    }

def calculate(expression):
    """Safe calculator"""
    try:
        # Only allow basic math operations
        allowed_chars = set('0123456789+-*/() .')
        if not all(c in allowed_chars for c in expression):
            return {"error": "Invalid characters in expression"}
        result = eval(expression, {"__builtins__": {}}, {})
        return {"expression": expression, "result": result}
    except Exception as e:
        return {"error": str(e)}

def get_time(timezone):
    """Get current time"""
    return {
        "timezone": timezone,
        "current_time": datetime.now().isoformat(),
        "note": "This is system time, not actual timezone conversion"
    }

TOOL_FUNCTIONS = {
    "get_current_weather": get_current_weather,
    "calculate": calculate,
    "get_time": get_time
}

def call_ollama(messages, tools=None, stream=False):
    """Call Ollama API with tool support"""
    payload = {
        "model": MODEL,
        "messages": messages,
        "stream": stream
    }

    if tools:
        payload["tools"] = tools

    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json=payload,
            timeout=120
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.ConnectionError:
        print(f"ERROR: Cannot connect to Ollama at {OLLAMA_URL}")
        print(f"Make sure Ollama is running on port 11434")
        return None
    except Exception as e:
        print(f"ERROR: {e}")
        return None

def test_basic_chat():
    """Test basic chat without tools"""
    print("\n" + "="*60)
    print("TEST 1: Basic Chat (no tools)")
    print("="*60)

    messages = [
        {"role": "user", "content": "Hello! Please introduce yourself briefly."}
    ]

    response = call_ollama(messages)
    if response:
        print(f"Model: {MODEL}")
        print(f"Response: {response['message']['content']}")
        return True
    return False

def test_tool_calling():
    """Test function calling"""
    print("\n" + "="*60)
    print("TEST 2: Tool Calling")
    print("="*60)

    messages = [
        {
            "role": "user",
            "content": "What's the weather like in San Francisco, CA? Also, what's 125 * 37?"
        }
    ]

    print(f"User: {messages[0]['content']}")

    # First call - model should request tool use
    response = call_ollama(messages, tools=TOOLS)
    if not response:
        return False

    assistant_message = response['message']
    print(f"\nAssistant response received")

    # Check if model wants to use tools
    if 'tool_calls' in assistant_message and assistant_message['tool_calls']:
        print(f"Tools called: {len(assistant_message['tool_calls'])}")

        # Add assistant message to conversation
        messages.append(assistant_message)

        # Execute each tool call
        for tool_call in assistant_message['tool_calls']:
            function_name = tool_call['function']['name']
            function_args = tool_call['function']['arguments']

            # Handle if arguments are JSON string vs dict
            if isinstance(function_args, str):
                function_args = json.loads(function_args)
            elif not isinstance(function_args, dict):
                function_args = {}

            print(f"\n  → Calling {function_name}({json.dumps(function_args)})")

            # Execute the function
            if function_name in TOOL_FUNCTIONS:
                result = TOOL_FUNCTIONS[function_name](**function_args)
                print(f"  ← Result: {json.dumps(result, indent=2)}")

                # Add tool result to conversation
                messages.append({
                    "role": "tool",
                    "content": json.dumps(result)
                })

        # Get final response with tool results
        print("\nGetting final response with tool results...")
        final_response = call_ollama(messages, tools=TOOLS)
        if final_response:
            print(f"\nFinal Answer: {final_response['message']['content']}")
            return True
    else:
        print("Model did not use tools (may not support function calling)")
        print(f"Response: {assistant_message.get('content', 'No content')}")

    return False

def test_streaming():
    """Test streaming response"""
    print("\n" + "="*60)
    print("TEST 3: Streaming Response")
    print("="*60)

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "user", "content": "Count from 1 to 5 slowly."}
        ],
        "stream": True
    }

    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json=payload,
            stream=True,
            timeout=120
        )
        response.raise_for_status()

        print("Streaming: ", end="", flush=True)
        for line in response.iter_lines():
            if line:
                chunk = json.loads(line)
                if 'message' in chunk and 'content' in chunk['message']:
                    print(chunk['message']['content'], end="", flush=True)
                if chunk.get('done', False):
                    print("\n")
                    return True
    except Exception as e:
        print(f"\nERROR: {e}")
        return False

    return False

def test_model_info():
    """Get model information"""
    print("\n" + "="*60)
    print("MODEL INFO")
    print("="*60)

    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/show",
            json={"name": MODEL},
            timeout=30
        )
        response.raise_for_status()
        info = response.json()

        print(f"Model: {MODEL}")
        if 'modelfile' in info:
            print(f"Modelfile preview: {info['modelfile'][:200]}...")
        if 'parameters' in info:
            print(f"Parameters: {info['parameters']}")
        return True
    except Exception as e:
        print(f"Could not get model info: {e}")
        return False

def main():
    """Run all tests"""
    print(f"\nOllama Tool Use Test Suite")
    print(f"URL: {OLLAMA_URL}")
    print(f"Model: {MODEL}")

    # Check if Ollama is running
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        response.raise_for_status()
        models = response.json().get('models', [])
        model_names = [m['name'] for m in models]
        print(f"\nAvailable models: {', '.join(model_names)}")

        if MODEL not in model_names:
            print(f"\nWARNING: {MODEL} not found in available models!")
            print("You may need to pull it: ollama pull gpt-oss:120b-cloud")
    except Exception as e:
        print(f"\nERROR: Cannot connect to Ollama: {e}")
        print("Make sure Ollama is running: ollama serve")
        return

    # Run tests
    results = []

    results.append(("Model Info", test_model_info()))
    results.append(("Basic Chat", test_basic_chat()))
    results.append(("Tool Calling", test_tool_calling()))
    results.append(("Streaming", test_streaming()))

    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    for test_name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status} - {test_name}")

    passed = sum(1 for _, p in results if p)
    total = len(results)
    print(f"\nPassed: {passed}/{total}")

if __name__ == "__main__":
    main()
