#!/usr/bin/env python3
"""MCP: pipeline-orchestrator

Route tasks to the best available MCP tool based on Claude's analysis.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, TYPE_CHECKING

try:  # Anthropic SDK is optional until routing is invoked
    import anthropic
except ImportError:  # pragma: no cover - handle missing dependency at runtime
    anthropic = None  # type: ignore

if TYPE_CHECKING:
    from anthropic import Anthropic  # pragma: no cover
else:  # Fallback type alias when SDK missing at import time
    Anthropic = Any  # type: ignore

from mcp.server.fastmcp import FastMCP

try:  # Support running inside package or as standalone script
    from ._orchestrator_schema import RoutingDecision, ToolMetadata
    from ._orchestrator_utils import (
        build_tool_manifest,
        introspect_mcp_tools,
        invoke_tool,
        parse_routing_decision,
        validate_tool_schema,
    )
except ImportError:  # pragma: no cover - fallback when executed directly
    from _orchestrator_schema import RoutingDecision, ToolMetadata  # type: ignore
    from _orchestrator_utils import (  # type: ignore
        build_tool_manifest,
        introspect_mcp_tools,
        invoke_tool,
        parse_routing_decision,
        validate_tool_schema,
    )


LOG = logging.getLogger("pipeline-orchestrator")
LOG.setLevel(logging.INFO)

mcp = FastMCP("pipeline-orchestrator")

DEFAULT_MODEL = os.getenv("ORCHESTRATOR_MODEL", "claude-3-5-sonnet-20241022")
MCP_DIR = Path(__file__).resolve().parent

_client: Optional[Anthropic] = None
_client_key: Optional[str] = None


def _get_client(api_key: Optional[str] = None) -> Anthropic:
    key = api_key or os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not configured for pipeline orchestrator")

    global _client, _client_key
    if _client is None or _client_key != key:
        if anthropic is None:
            raise RuntimeError(
                "anthropic package is not installed in the MCP environment; "
                "install it or remove pipeline-orchestrator from configuration."
            )
        _client = anthropic.Anthropic(api_key=key)
        _client_key = key
    return _client


def _build_prompt(task_description: str, context: Optional[Dict[str, Any]], manifest: Dict[str, Any]) -> str:
    instruction = {
        "task": task_description,
        "context": context or {},
        "tools": manifest.get("tools", []),
        "guidelines": {
            "respond_with": {
                "type": "json",
                "schema": {
                    "selected_tool": "string",
                    "module": "string",
                    "reasoning": "string",
                    "confidence": "number",
                    "recommended_params": "object",
                    "fallback_tools": ["string"],
                    "is_executable": "boolean"
                },
            },
            "ranking": "Provide top choice with confidence between 0 and 1.",
            "fallbacks": "List additional tools in order as module.tool strings.",
        },
    }
    return json.dumps(instruction, indent=2)


def _extract_tool_identifier(value: str, manifest_tools: Iterable[ToolMetadata]) -> Tuple[Optional[str], Optional[str]]:
    if not value:
        return None, None

    if "." in value:
        module, tool = value.split(".", 1)
        return module, tool

    # Attempt lookup by tool name
    matches = [t for t in manifest_tools if t.tool_name == value]
    if len(matches) == 1:
        return matches[0].module, matches[0].tool_name
    return None, value


def _fallback_sequence(primary: Tuple[str, str], fallbacks: Iterable[str], manifest: Iterable[ToolMetadata]) -> List[Tuple[str, str]]:
    manifest_list = list(manifest)
    sequence = [primary]
    for candidate in fallbacks:
        module, tool = _extract_tool_identifier(candidate, manifest_list)
        if module and tool:
            sequence.append((module, tool))
    deduped: List[Tuple[str, str]] = []
    for item in sequence:
        if item not in deduped:
            deduped.append(item)
    return deduped


@mcp.tool()
async def get_tool_manifest() -> Dict[str, Any]:
    """Return the current MCP tool manifest used for routing decisions."""

    manifest = build_tool_manifest(MCP_DIR)
    issues = validate_tool_schema(introspect_mcp_tools(MCP_DIR))
    return {
        "success": True,
        "manifest": manifest,
        "issues": issues,
    }


@mcp.tool()
async def route_task(
    task_description: str,
    context: Optional[Dict[str, Any]] = None,
    model: str = DEFAULT_MODEL,
    include_manifest: bool = False,
) -> Dict[str, Any]:
    """Ask Claude to select the best tool for the given task."""

    manifest = build_tool_manifest(MCP_DIR)
    manifest_tools = introspect_mcp_tools(MCP_DIR)
    prompt = _build_prompt(task_description, context, manifest)

    client = _get_client()
    LOG.info("Routing task via Claude model %s", model)

    message = client.messages.create(
        model=model,
        max_tokens=1024,
        temperature=0,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "You are a routing planner. Analyse the JSON payload and respond with JSON only.",
                    },
                    {
                        "type": "text",
                        "text": prompt,
                    },
                ],
            }
        ],
    )

    response_text = ""
    for block in message.content:
        if block.type == "text":
            response_text += block.text

    if not response_text:
        raise RuntimeError("Claude returned an empty response for routing decision")

    try:
        decision = parse_routing_decision(response_text)
    except ValueError:
        cleaned = response_text
        if "```" in response_text:
            cleaned = response_text.split("```json")[-1].split("```", 1)[0]
        decision = parse_routing_decision(cleaned)

    if not decision.module:
        module, _ = _extract_tool_identifier(decision.selected_tool, manifest_tools)
        decision.module = module

    manifest_summary = {
        "tool_count": manifest.get("tool_count", 0),
        "generated_at": manifest.get("generated_at"),
    }

    payload = {
        "success": True,
        "routing_decision": decision.to_dict(),
        "raw_response": response_text,
        "manifest_summary": manifest_summary,
    }
    if include_manifest:
        payload["tool_manifest"] = manifest
    return payload


@mcp.tool()
async def execute_routed_task(
    tool_name: str,
    module: Optional[str] = None,
    tool_params: Optional[Dict[str, Any]] = None,
    fallback_tools: Optional[List[str]] = None,
    timeout_seconds: float = 30.0,
    max_retries: int = 0,
) -> Dict[str, Any]:
    """Execute the recommended tool (with optional fallbacks)."""

    tool_params = tool_params or {}
    manifest_tools = introspect_mcp_tools(MCP_DIR)

    if module is None:
        module, _ = _extract_tool_identifier(tool_name, manifest_tools)
    if module is None:
        return {
            "success": False,
            "error": f"Unable to resolve module for tool {tool_name}",
        }

    candidates = _fallback_sequence((module, tool_name), fallback_tools or [], manifest_tools)

    attempts: List[Dict[str, Any]] = []
    for candidate_module, candidate_tool in candidates:
        module_path = MCP_DIR / f"{candidate_module}.py"
        if not module_path.exists():
            attempts.append(
                {
                    "module": candidate_module,
                    "tool": candidate_tool,
                    "success": False,
                    "error": "Module file not found",
                }
            )
            continue

        retries = 0
        while retries <= max_retries:
            success, result, error, duration = await invoke_tool(
                module_path,
                candidate_tool,
                tool_params,
                timeout=timeout_seconds,
            )
            attempts.append(
                {
                    "module": candidate_module,
                    "tool": candidate_tool,
                    "success": success,
                    "error": error,
                    "duration_ms": duration,
                    "retry": retries,
                }
            )
            if success:
                return {
                    "success": True,
                    "active_tool": f"{candidate_module}.{candidate_tool}",
                    "result": result,
                    "attempts": attempts,
                }

            retries += 1

    return {
        "success": False,
        "error": "All candidate tools failed",
        "attempts": attempts,
    }


@mcp.tool()
async def explain_routing_decision(
    routing_decision: Dict[str, Any],
    model: str = DEFAULT_MODEL,
) -> Dict[str, Any]:
    """Ask Claude to elaborate on a prior routing decision."""

    client = _get_client()
    prompt = json.dumps({"routing_decision": routing_decision}, indent=2)

    message = client.messages.create(
        model=model,
        max_tokens=512,
        temperature=0,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Explain this routing decision for audit logs in 3 bullet points.",
                    },
                    {
                        "type": "text",
                        "text": prompt,
                    },
                ],
            }
        ],
    )

    explanation = "\n".join(block.text for block in message.content if block.type == "text")
    return {
        "success": True,
        "explanation": explanation,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    mcp.run()
