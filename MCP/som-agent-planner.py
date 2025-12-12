#!/usr/bin/env python3
"""
Society-of-Mind agent planner (Anthropic-backed).

Expects ANTHROPIC_API_KEY. Optional: AGENT_CHAT_MODEL (default: claude-3-5-sonnet-20240620).
Does not execute actions; returns a structured plan with agents, steps, risks, next_actions.
"""
import os
from typing import Any, Dict

try:
    import anthropic
except Exception as exc:
    raise RuntimeError("anthropic package is required for som-agent-planner") from exc


def _require_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    return key


def _get_model() -> str:
    return os.environ.get("AGENT_CHAT_MODEL", "claude-3-5-sonnet-20240620")


def _invoke_llm(prompt: str) -> Dict[str, Any]:
    client = anthropic.Anthropic(api_key=_require_api_key())
    resp = client.messages.create(
        model=_get_model(),
        max_tokens=800,
        temperature=0.4,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp


def _build_prompt(task: str, context: str = "") -> str:
    return f"""You are a society-of-mind coordinator. Analyze the task and propose a plan without executing it.

Task:
{task}

Context (optional):
{context or "(none)"}

Return JSON with:
- agents: list of short agent roles
- plan: ordered list of steps (1-5 steps)
- risks: list of notable risks or blockers
- next_actions: 1-3 concrete next actions to start
- raw: brief free-form rationale
Do not execute tools or actions; only return the plan."""


def run_som_agent_planner(task: str, context: str = "") -> Dict[str, Any]:
    prompt = _build_prompt(task, context)
    resp = _invoke_llm(prompt)
    usage = getattr(resp, "usage", None)
    text_chunks = []
    for block in resp.content:
        if getattr(block, "type", "") == "text":
            text_chunks.append(block.text)
    combined = "\n".join(text_chunks).strip()
    plan_obj: Dict[str, Any] = {
        "agents": [],
        "plan": [],
        "risks": [],
        "next_actions": [],
        "raw": combined,
        "usage": getattr(usage, "__dict__", None) or dict(usage) if usage else None,
        "model": _get_model(),
    }
    # Best-effort parse if the model returned JSON-like content; otherwise keep raw text.
    try:
        import json
        parsed = json.loads(combined)
        if isinstance(parsed, dict):
            for key in ["agents", "plan", "risks", "next_actions", "raw"]:
                if key in parsed:
                    plan_obj[key] = parsed[key]
    except Exception:
        pass
    plan_obj["success"] = True
    return plan_obj


# MCP entry point
def handler(request: Dict[str, Any]) -> Dict[str, Any]:
    args = request.get("arguments", {}) or {}
    task = args.get("task") or args.get("goal") or ""
    context = args.get("context") or ""
    if not task:
        return {"success": False, "error": "task is required"}
    try:
        result = run_som_agent_planner(task, context)
        return {"success": True, "content": result}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


if __name__ == "__main__":
    # Simple manual test
    import json
    print(json.dumps(handler({"arguments": {"task": "Plan a quick agentic research pass on agent frameworks."}}), indent=2))
