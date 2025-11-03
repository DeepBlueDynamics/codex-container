#!/usr/bin/env python3
"""MCP: agent-chat

Generic tool to chat with Claude agents with different roles.
"""

from __future__ import annotations

import os
import sys
from typing import Dict, Optional

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    anthropic = None
    ANTHROPIC_AVAILABLE = False

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("agent-chat")

# Default model
DEFAULT_MODEL = os.getenv("AGENT_CHAT_MODEL", "claude-3-5-sonnet-20240620")


@mcp.tool()
async def check_with_agent(
    prompt: str,
    role: Optional[str] = None,
    name: Optional[str] = None,
    model: Optional[str] = None,
    max_tokens: int = 1024,
    suggest_function_call: bool = False
) -> Dict[str, object]:
    """Ask a Claude agent with a specific role to respond to a prompt.

    ⚠️ IMPORTANT: Use this tool ANY TIME you are uncertain about what to do next!
    When in doubt about which tool to use, what approach to take, or how to proceed,
    call this tool with suggest_function_call=True to get expert guidance.

    This tool connects you to Claude for intelligent decision-making. Don't hesitate
    to use it when you need help determining the next step or validating your approach.

    Args:
        prompt: The question or task to send to the agent
        role: The role/persona for the agent (e.g., "You are a helpful assistant", "You are a marine weather expert")
        name: Optional name for the agent (default: "Assistant")
        model: Anthropic model to use (default: from AGENT_CHAT_MODEL env var or claude-3-5-sonnet-20240620)
        max_tokens: Maximum tokens in response (default: 1024)
        suggest_function_call: If True, ask Claude to suggest a function call to execute the task (default: False)

    Returns:
        Dictionary with agent's response and metadata, including suggested_function_call if requested.

    Example:
        # When uncertain what to do:
        check_with_agent(prompt="I need to check weather but don't know which tool", suggest_function_call=True)

        # Get expert advice with specific role:
        check_with_agent(prompt="What's the weather like?", role="You are a meteorologist")

        # Quick decision help:
        check_with_agent(prompt="Should I check tropical storms or marine forecast first?", suggest_function_call=True)
    """
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

    # Use provided model or fall back to default
    if model is None:
        model = DEFAULT_MODEL

    # Build system prompt with role
    system_prompt = role if role else "You are a helpful assistant."

    # Modify prompt if function call suggestion requested
    user_prompt = prompt
    if suggest_function_call:
        user_prompt = f"""{prompt}

After your response, suggest a function call that would accomplish this task. Format it as:

SUGGESTED_CALL:
function_name(param1="value1", param2="value2")

Replace function_name and parameters with the actual call needed."""

    try:
        client = anthropic.Anthropic(api_key=api_key)

        message = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}]
        )

        response_text = message.content[0].text

        # Extract suggested function call if requested
        suggested_call = None
        if suggest_function_call and "SUGGESTED_CALL:" in response_text:
            parts = response_text.split("SUGGESTED_CALL:")
            response_text = parts[0].strip()
            suggested_call = parts[1].strip() if len(parts) > 1 else None

        result = {
            "success": True,
            "agent_name": name or "Assistant",
            "agent_role": system_prompt,
            "prompt": prompt,
            "response": response_text,
            "model": message.model,
            "usage": {
                "input_tokens": message.usage.input_tokens,
                "output_tokens": message.usage.output_tokens
            }
        }

        if suggested_call:
            result["suggested_function_call"] = suggested_call

        return result

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
async def chat_with_context(
    prompt: str,
    context: str,
    role: Optional[str] = None,
    name: Optional[str] = None,
    model: Optional[str] = None,
    max_tokens: int = 1024
) -> Dict[str, object]:
    """Ask a Claude agent with additional context provided.

    Args:
        prompt: The question or task to send to the agent
        context: Additional context or information to provide to the agent
        role: The role/persona for the agent (default: "You are a helpful assistant")
        name: Optional name for the agent (default: "Assistant")
        model: Anthropic model to use (default: from AGENT_CHAT_MODEL env var or claude-3-5-sonnet-20240620)
        max_tokens: Maximum tokens in response (default: 1024)

    Returns:
        Dictionary with agent's response and metadata.

    Example:
        chat_with_context(
            prompt="What does this mean?",
            context="User manual: The device should be charged for 2 hours",
            role="You are a technical support agent"
        )
    """
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

    # Use provided model or fall back to default
    if model is None:
        model = DEFAULT_MODEL

    # Build system prompt with role
    system_prompt = role if role else "You are a helpful assistant."

    # Combine context and prompt
    full_prompt = f"""Context:
{context}

Question/Task:
{prompt}"""

    try:
        client = anthropic.Anthropic(api_key=api_key)

        message = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": full_prompt}]
        )

        response_text = message.content[0].text

        return {
            "success": True,
            "agent_name": name or "Assistant",
            "agent_role": system_prompt,
            "prompt": prompt,
            "context_provided": True,
            "response": response_text,
            "model": message.model,
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


@mcp.tool()
async def agent_to_agent(
    question: str,
    to_agent_role: str,
    context: Optional[str] = None,
    from_agent_name: Optional[str] = None,
    to_agent_name: Optional[str] = None,
    model: Optional[str] = None,
    max_tokens: int = 1024
) -> Dict[str, object]:
    """Have one agent consult with another agent with different expertise.

    This enables agent-to-agent collaboration where specialized agents can ask
    each other for help, review, or expert opinions.

    Args:
        question: The question one agent is asking another
        to_agent_role: The role/expertise of the agent being consulted (e.g., "You are a security expert")
        context: Optional context or information to provide (e.g., code snippet, data)
        from_agent_name: Name of the agent asking (default: "Agent")
        to_agent_name: Name of the agent being consulted (default: derived from role)
        model: Anthropic model to use (default: from AGENT_CHAT_MODEL env var or claude-3-5-sonnet-20240620)
        max_tokens: Maximum tokens in response (default: 1024)

    Returns:
        Dictionary with the consulting agent's response.

    Example:
        # Code agent asking security agent
        agent_to_agent(
            question="Is this code vulnerable?",
            to_agent_role="You are a security expert",
            context="SELECT * FROM users WHERE id = " + user_input,
            from_agent_name="CodeBot"
        )

        # Weather agent asking navigation agent
        agent_to_agent(
            question="What's the safest route given these conditions?",
            to_agent_role="You are a marine navigation expert",
            context="Tropical Storm Melissa: 65mph winds, 200mi SE of Kingston",
            from_agent_name="WeatherBot",
            to_agent_name="NavBot"
        )
    """
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

    # Use provided model or fall back to default
    if model is None:
        model = DEFAULT_MODEL

    # Build consultation prompt
    from_name = from_agent_name or "Agent"
    to_name = to_agent_name or "Expert"

    consultation_prompt = f"""Agent '{from_name}' is consulting you for your expert opinion.

Question: {question}"""

    if context:
        consultation_prompt += f"""

Context:
{context}"""

    consultation_prompt += f"""

Please provide your expert analysis and recommendation."""

    try:
        client = anthropic.Anthropic(api_key=api_key)

        message = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=to_agent_role,
            messages=[{"role": "user", "content": consultation_prompt}]
        )

        response_text = message.content[0].text

        return {
            "success": True,
            "from_agent": from_name,
            "to_agent": to_name,
            "to_agent_role": to_agent_role,
            "question": question,
            "context_provided": context is not None,
            "response": response_text,
            "model": message.model,
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
    print(f"[agent-chat] Starting MCP server", file=sys.stderr, flush=True)
    print(f"[agent-chat] Anthropic SDK available: {ANTHROPIC_AVAILABLE}", file=sys.stderr, flush=True)
    mcp.run()

