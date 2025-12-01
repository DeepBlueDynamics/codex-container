#!/usr/bin/env python3
"""
MCP: gnosis-proxy-repl

Proxy REPL for agent translation. Accepts agent-style conversations, available tools, and task hints,
then proposes routing plans, tool recommendations, and cached intent hints aligned to the architecture.
"""

from __future__ import annotations

import logging
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("gnosis-proxy-repl")
logger = logging.getLogger("gnosis_proxy_repl")


def _score_tool(task: str, tool: Dict[str, Any]) -> float:
    description = tool.get("description", "")
    name = tool.get("name", "")
    matcher = SequenceMatcher(None, task.lower(), f"{name} {description}".lower())
    return matcher.ratio()


def _suggest_providers(model_hint: Optional[str]) -> List[str]:
    default_providers = ["codex_gateway", "anthropic", "gemini", "bedrock", "openai"]
    if model_hint:
        model_hint = model_hint.lower()
        return sorted(default_providers, key=lambda x: 0 if x in model_hint else 1)
    return default_providers


def _build_plan(
    task: str,
    tools: List[Dict[str, Any]],
    providers: List[str],
    qdrant_hint: Optional[str],
) -> List[Dict[str, Any]]:
    ranked = sorted(tools, key=lambda t: _score_tool(task or "", t), reverse=True)
    plan = []
    primary_provider = providers[0]
    for tool in ranked[:3]:
        plan.append({
            "tool": tool.get("name"),
            "provider": primary_provider,
            "score": round(_score_tool(task or "", tool), 3),
            "description": tool.get("description"),
            "cache_hint": qdrant_hint or "session_history",
        })
    return plan


def _build_response(plan: List[Dict[str, Any]], task: str, providers: List[str]) -> Dict[str, Any]:
    summary = [[p.get("tool"), p.get("provider"), p.get("score")] for p in plan]
    routing = {name: idx + 1 for idx, name in enumerate(providers)}
    return {
        "success": True,
        "task": task,
        "plan": plan,
        "summary": summary,
        "routing_map": routing,
        "log": f"Selected {len(plan)} tools for '{task}'",
    }


@mcp.tool()
async def proxy_repl(
    messages: List[Dict[str, str]],
    tools: List[Dict[str, Any]],
    task_hint: Optional[str] = None,
    model_hint: Optional[str] = None,
    constraints: Optional[Dict[str, Any]] = None,
    qdrant_hint: Optional[str] = None,
    cache_policy: Optional[str] = None,
) -> Dict[str, Any]:
    """Simulate translation/routing for an agent request."

    The architecture presumes:
    - Requests enter via Codex → gateway → proxy.
    - Proxy can consult Qdrant cache before spinning Codex sessions.
    - This REPL helps test routing/plan before the Rust service executes it.
    """
    try:
        logger.info(
            "Proxy REPL request - task_hint=%s model_hint=%s constraints=%s qdrant_hint=%s cache_policy=%s",
            task_hint,
            model_hint,
            constraints,
            qdrant_hint,
            cache_policy,
        )
        providers = _suggest_providers(model_hint)
        plan = _build_plan(task_hint or "", tools, providers, qdrant_hint)
        response = _build_response(plan, task_hint or "general", providers)
        if cache_policy:
            response["cache_policy"] = cache_policy
        logger.info("Proxy REPL response plan: %s", plan)
        return response
    except Exception as exc:  # pragma: no cover
        logger.error("Proxy REPL error: %s", exc)
        return {"success": False, "error": str(exc)}


if __name__ == "__main__":
    logger.setLevel(logging.INFO)
    mcp.run()
