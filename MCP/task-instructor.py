#!/usr/bin/env python3
"""MCP: task-instructor

Provides an "instructor/boss" pattern for multi-step task guidance.
Codex calls this repeatedly to get next-step instructions, executes them, and reports back.
The instructor is stateless - it just provides guidance based on current state.
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("task-instructor")


# ============================================================
# PROMPT TEMPLATE (what to send to check_with_agent)
# ============================================================

def _build_instructor_prompt(
    task: str,
    completed_steps: List[Dict],
    context: Optional[str],
    tools: List[Dict]  # from list_available_tools()
) -> str:
    """Build the prompt for Claude to plan next step."""

    # Format tool list concisely
    tool_lines = []
    for t in tools:
        # Example: "noaa-marine.get_forecast: Fetch marine weather forecast for coordinates"
        tool_lines.append(f"  - {t['module']}.{t['name']}: {t['description'][:80]}")
    tools_text = "\n".join(tool_lines)

    # Format completed steps
    if completed_steps:
        steps_text = "\n".join([
            f"  {i+1}. Called {s['tool']} → {s.get('status', 'success')}"
            for i, s in enumerate(completed_steps)
        ])
    else:
        steps_text = "  (none yet)"

    # Format context
    context_text = context or "(no additional context)"

    return f"""You are a task planning assistant. Break down the task into executable steps using available tools.

TASK: {task}

AVAILABLE TOOLS:
{tools_text}

COMPLETED STEPS:
{steps_text}

CURRENT CONTEXT:
{context_text}

INSTRUCTIONS:
1. Determine the next single step needed to accomplish the task
2. If the task is complete, indicate completion
3. If you need clarification, ask for it
4. Respond ONLY with valid JSON in this exact format:

{{
  "next_action": "call_tool",
  "tool_call": {{
    "tool": "module.function_name",
    "args": {{"param1": "value1", "param2": 123}},
    "reason": "Brief explanation of why this tool is needed now"
  }},
  "reasoning": "Overall plan and current step rationale",
  "progress": "Step X of ~Y"
}}

OR if task is complete:
{{
  "next_action": "complete",
  "reasoning": "Task accomplished because...",
  "summary": "What was done"
}}

OR if you need clarification:
{{
  "next_action": "clarify",
  "question": "What specific information do you need?",
  "reasoning": "Why this information is needed"
}}

RESPOND WITH JSON ONLY. NO MARKDOWN FENCES. NO EXPLANATORY TEXT."""


# ============================================================
# RESPONSE SCHEMA & VALIDATION
# ============================================================

def _validate_response(response_text: str) -> Dict[str, Any]:
    """Parse and validate the instructor's response."""

    # Try to parse JSON
    try:
        data = json.loads(response_text.strip())
    except json.JSONDecodeError:
        # Try to extract JSON from markdown fences (Claude sometimes does this)
        match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
            except:
                return {
                    "error": "Failed to parse JSON from response",
                    "raw": response_text
                }
        else:
            return {
                "error": "Response is not valid JSON",
                "raw": response_text
            }

    # Validate required fields
    next_action = data.get("next_action")

    if next_action not in ["call_tool", "complete", "clarify"]:
        return {
            "error": f"Invalid next_action: {next_action}",
            "valid_actions": ["call_tool", "complete", "clarify"],
            "raw": data
        }

    if next_action == "call_tool":
        tool_call = data.get("tool_call")
        if not tool_call:
            return {"error": "Missing tool_call for call_tool action", "raw": data}

        if not tool_call.get("tool"):
            return {"error": "Missing tool name in tool_call", "raw": data}

        if "args" not in tool_call:
            return {"error": "Missing args in tool_call", "raw": data}

    elif next_action == "clarify":
        if not data.get("question"):
            return {"error": "Missing question for clarify action", "raw": data}

    # Valid
    return {"success": True, "data": data}


# ============================================================
# TOOL LIST FETCHER
# ============================================================

async def _get_tool_list() -> List[Dict]:
    """Get available tools from tool-recommender."""
    try:
        # Try to import and call tool-recommender's list function
        import importlib.util
        import os

        # Get path to tool-recommender.py
        mcp_dir = os.path.dirname(__file__)
        tool_rec_path = os.path.join(mcp_dir, "tool-recommender.py")

        if os.path.exists(tool_rec_path):
            spec = importlib.util.spec_from_file_location("tool_recommender", tool_rec_path)
            if spec and spec.loader:
                tool_recommender = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(tool_recommender)

                # Call _get_available_tools (it's a private function in that module)
                if hasattr(tool_recommender, '_get_available_tools'):
                    return tool_recommender._get_available_tools()
    except Exception as e:
        print(f"[task-instructor] Error loading tools: {e}", file=sys.stderr, flush=True)

    return []


# ============================================================
# MAIN TOOL
# ============================================================

@mcp.tool()
async def get_next_step(
    task: str,
    context: Optional[str] = None,
    completed_steps: Optional[List[Dict]] = None,
    available_tools: Optional[List[str]] = None,
    model: Optional[str] = None,
    max_tokens: int = 2048
) -> Dict[str, Any]:
    """Ask Claude what to do next for a multi-step task.

    This is your "instructor" - it doesn't execute, it guides.
    Codex calls this, gets instructions, executes them, reports back.

    This implements a stateless planning pattern where each call provides
    the next actionable step based on task goals and current progress.

    Args:
        task: The overall goal/task to accomplish
        context: Current state, situation, or additional information
        completed_steps: List of steps already completed with their results
            Format: [{"tool": "module.function", "status": "success", "result": {...}}]
        available_tools: Optional explicit tool list (auto-discovered if not provided)
        model: Optional model override for the planning agent
        max_tokens: Maximum tokens for planning response (default: 2048)

    Returns:
        Dictionary with one of three action types:

        1. call_tool - Execute a specific MCP tool
        {
            "success": True,
            "next_action": "call_tool",
            "tool_call": {
                "tool": "module.function_name",
                "args": {"param": "value"},
                "reason": "Why this tool is needed"
            },
            "reasoning": "Overall plan explanation",
            "progress": "Step X of ~Y"
        }

        2. complete - Task is finished
        {
            "success": True,
            "next_action": "complete",
            "reasoning": "Why task is complete",
            "summary": "What was accomplished"
        }

        3. clarify - Need more information
        {
            "success": True,
            "next_action": "clarify",
            "question": "What information is needed?",
            "reasoning": "Why this is needed"
        }

    Example usage pattern:
        # Step 1: Start task
        step1 = get_next_step(task="Check weather and post to Slack")
        # Returns: call noaa-marine.get_forecast(...)

        # Step 2: After executing forecast
        step2 = get_next_step(
            task="Check weather and post to Slack",
            completed_steps=[{"tool": "noaa-marine.get_forecast", "status": "success", "result": {...}}]
        )
        # Returns: call slackbot.post_message(...)

        # Step 3: After posting
        step3 = get_next_step(
            task="Check weather and post to Slack",
            completed_steps=[{...forecast...}, {...slack...}]
        )
        # Returns: next_action="complete"
    """

    if not task:
        return {
            "success": False,
            "error": "No task provided"
        }

    # Get available tools if not provided
    tools = []
    if available_tools:
        # User provided explicit list - format it
        tools = [{"module": "user", "name": t, "description": ""} for t in available_tools]
    else:
        # Auto-discover from tool-recommender
        tools = await _get_tool_list()

    if not tools:
        return {
            "success": False,
            "error": "No tools available for planning"
        }

    # Build the prompt
    prompt = _build_instructor_prompt(
        task=task,
        completed_steps=completed_steps or [],
        context=context,
        tools=tools
    )

    # Call check_with_agent to get Claude's planning
    try:
        # Import agent-chat dynamically
        import importlib.util
        import os

        mcp_dir = os.path.dirname(__file__)
        agent_chat_path = os.path.join(mcp_dir, "agent-chat.py")

        if not os.path.exists(agent_chat_path):
            return {
                "success": False,
                "error": "agent-chat.py not found - required for planning"
            }

        spec = importlib.util.spec_from_file_location("agent_chat", agent_chat_path)
        if not spec or not spec.loader:
            return {
                "success": False,
                "error": "Failed to load agent-chat module"
            }

        agent_chat = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(agent_chat)

        # Call check_with_agent
        response = await agent_chat.check_with_agent(
            prompt=prompt,
            role="You are a task planning expert. Break complex tasks into executable steps using available tools.",
            name="Instructor",
            model=model,
            max_tokens=max_tokens,
            suggest_function_call=False
        )

        if not response.get("success"):
            return {
                "success": False,
                "error": f"Planning agent failed: {response.get('error')}"
            }

        # Validate and parse response
        response_text = response.get("response", "")
        validation = _validate_response(response_text)

        if "error" in validation:
            return {
                "success": False,
                "error": validation["error"],
                "raw_response": validation.get("raw", response_text)
            }

        # Return validated instruction
        result = validation["data"]
        result["success"] = True
        return result

    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to get planning: {str(e)}"
        }


if __name__ == "__main__":
    print("[task-instructor] Starting MCP server", file=sys.stderr, flush=True)
    mcp.run()
