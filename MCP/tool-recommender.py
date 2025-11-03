#!/usr/bin/env python3
"""MCP: tool-recommender

Ask Claude to recommend which MCP tool to use for a task.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    anthropic = None
    ANTHROPIC_AVAILABLE = False

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("tool-recommender")

# Default model for recommendations
DEFAULT_MODEL = os.getenv("TOOL_RECOMMENDER_MODEL", "claude-3-5-sonnet-20240620")


def _get_available_tools() -> List[Dict[str, str]]:
    """Scan MCP directory for available tools by reading Python files."""
    tools = []
    mcp_dir = Path("/opt/codex-home/mcp")

    if not mcp_dir.exists():
        return tools

    for py_file in mcp_dir.glob("*.py"):
        if py_file.name.startswith("_"):
            continue

        try:
            content = py_file.read_text(encoding="utf-8")

            # Look for @mcp.tool() decorator and extract function names and docstrings
            lines = content.split("\n")
            i = 0
            while i < len(lines):
                line = lines[i]

                # Found a tool decorator
                if "@mcp.tool()" in line or line.strip().startswith("@mcp.tool("):
                    # Next non-empty line should be the function definition
                    i += 1
                    while i < len(lines) and not lines[i].strip():
                        i += 1

                    if i < len(lines):
                        func_line = lines[i].strip()
                        if func_line.startswith("async def ") or func_line.startswith("def "):
                            # Extract function name
                            func_name = func_line.split("(")[0].split()[-1]

                            # Extract docstring
                            i += 1
                            docstring = ""
                            if i < len(lines) and '"""' in lines[i]:
                                doc_lines = []
                                # Multi-line docstring
                                if lines[i].count('"""') == 2:
                                    # Single line docstring
                                    docstring = lines[i].strip().strip('"""').strip()
                                else:
                                    # Multi-line
                                    i += 1
                                    while i < len(lines) and '"""' not in lines[i]:
                                        doc_lines.append(lines[i])
                                        i += 1
                                    docstring = "\n".join(doc_lines).strip()

                            tools.append({
                                "module": py_file.stem,
                                "name": func_name,
                                "description": docstring[:200] if docstring else "No description"
                            })

                i += 1

        except Exception as e:
            print(f"[tool-recommender] Error scanning {py_file.name}: {e}", file=sys.stderr)
            continue

    return tools


@mcp.tool()
async def list_anthropic_models() -> Dict[str, object]:
    """List available Anthropic Claude models.

    Returns:
        Dictionary with list of available Claude models.

    Example:
        list_anthropic_models()
    """
    models = [
        {
            "id": "claude-3-5-sonnet-20241022",
            "name": "Claude 3.5 Sonnet (New)",
            "description": "Most intelligent model, best for complex tasks",
            "max_tokens": 8192
        },
        {
            "id": "claude-3-5-sonnet-20240620",
            "name": "Claude 3.5 Sonnet",
            "description": "Intelligent model for complex tasks",
            "max_tokens": 8192
        },
        {
            "id": "claude-3-5-haiku-20241022",
            "name": "Claude 3.5 Haiku",
            "description": "Fast and efficient model",
            "max_tokens": 8192
        },
        {
            "id": "claude-3-opus-20240229",
            "name": "Claude 3 Opus",
            "description": "Most powerful Claude 3 model",
            "max_tokens": 4096
        },
        {
            "id": "claude-3-sonnet-20240229",
            "name": "Claude 3 Sonnet",
            "description": "Balanced intelligence and speed",
            "max_tokens": 4096
        },
        {
            "id": "claude-3-haiku-20240307",
            "name": "Claude 3 Haiku",
            "description": "Fastest Claude 3 model",
            "max_tokens": 4096
        }
    ]

    return {
        "success": True,
        "models": models,
        "count": len(models)
    }


@mcp.tool()
async def list_available_tools() -> Dict[str, object]:
    """List all available MCP tools.

    Returns:
        Dictionary with list of all available MCP tools and their descriptions.

    Example:
        list_available_tools()
    """
    tools = _get_available_tools()

    return {
        "success": True,
        "tools": tools,
        "count": len(tools)
    }


@mcp.tool()
async def recommend_tool(task: str, model: Optional[str] = None) -> Dict[str, object]:
    """Ask Claude to recommend which MCP tools are needed to accomplish a task.

    Args:
        task: Description of the task you want to accomplish
        model: Anthropic model to use (default: from TOOL_RECOMMENDER_MODEL env var or claude-3-5-sonnet-20240620)

    Returns:
        Dictionary with recommended tools (can be multiple), reasoning, and confidence.

    Example:
        recommend_tool(task="Get current weather in Miami and log it")
        recommend_tool(task="Check tropical storms and send alert", model="claude-3-5-haiku-20241022")
    """
    # Use provided model or fall back to default
    if model is None:
        model = DEFAULT_MODEL
    if not ANTHROPIC_AVAILABLE:
        return {
            "success": False,
            "error": "anthropic package not available"
        }

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {
            "success": False,
            "error": "ANTHROPIC_API_KEY environment variable not set"
        }

    # Get available tools
    tools = _get_available_tools()

    if not tools:
        return {
            "success": False,
            "error": "No MCP tools found"
        }

    # Build prompt for Claude
    tools_list = "\n".join([
        f"- {t['module']}.{t['name']}: {t['description']}"
        for t in tools
    ])

    prompt = f"""You are helping identify which MCP tools are needed to accomplish a task.

Available tools:
{tools_list}

Task: {task}

Analyze what tools are needed and respond with JSON only:
{{
    "recommended_tools": [
        {{
            "tool": "module.function_name",
            "purpose": "why this tool is needed",
            "order": 1
        }}
    ],
    "reasoning": "overall approach to accomplish the task",
    "confidence": 0.0-1.0
}}

If multiple tools are needed, list them in the order they should be executed."""

    try:
        client = anthropic.Anthropic(api_key=api_key)

        message = client.messages.create(
            model=model,
            max_tokens=500,
            temperature=0,
            messages=[{"role": "user", "content": prompt}]
        )

        response_text = message.content[0].text

        # Parse JSON response
        try:
            recommendation = json.loads(response_text)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code block
            if "```json" in response_text:
                json_str = response_text.split("```json")[1].split("```")[0].strip()
                recommendation = json.loads(json_str)
            elif "```" in response_text:
                json_str = response_text.split("```")[1].split("```")[0].strip()
                recommendation = json.loads(json_str)
            else:
                recommendation = {"error": "Could not parse response", "raw": response_text}

        return {
            "success": True,
            "task": task,
            "model_used": model,
            "recommendation": recommendation,
            "available_tools_count": len(tools),
            "usage": {
                "input_tokens": message.usage.input_tokens,
                "output_tokens": message.usage.output_tokens
            }
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


if __name__ == "__main__":
    print(f"[tool-recommender] Starting MCP server", file=sys.stderr, flush=True)
    mcp.run()
