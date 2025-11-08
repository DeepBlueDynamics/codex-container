#!/usr/bin/env python3
"""
N.U.T.S. News Generator MCP Bridge
===================================

Neural Unverified Telegraph Service - Generates satirical tech news articles.

Tools:
  - nuts_generate_article: Generate a complete satirical tech news article
  - nuts_generate_headline: Generate just a headline
  - nuts_generate_quote: Generate a fake expert quote
  - nuts_generate_ticker: Generate breaking news ticker items
  - nuts_generate_metrics: Generate absurd reality metrics

Env/config:
  - ANTHROPIC_API_KEY (required for content generation)
  - .nuts.env file in repo root (optional)

Setup:
  Uses existing Anthropic API key from environment.
  No additional setup needed if ANTHROPIC_API_KEY is set.

Notes:
  - All content is satirical and intentionally absurd
  - Blends real tech terminology with made-up measurements
  - Maintains serious journalistic tone for comedic effect
"""

import os
import json
from typing import Any, Dict, List, Optional
from pathlib import Path

from mcp.server.fastmcp import FastMCP, Context

# Try importing anthropic client
try:
    from anthropic import Anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False


mcp = FastMCP("nuts-news")

# Config
NUTS_ENV_FILE = os.path.join(os.getcwd(), ".nuts.env")

# Satirical measurement units and tech jargon
ABSURD_UNITS = [
    "milliZuckerbergs",
    "GatesUnits",
    "TuesdaysUntilDiscontinuation",
    "BezosBucks",
    "ElonMinutes",
    "CookPrivacyPoints",
    "NadellaCloudiness",
    "BezosLaughs per second"
]

FAKE_EXPERTS = [
    "Dr. Quantum Von Chronometry",
    "Professor Tesla McQuantum",
    "Dr. Binary Singularity",
    "Chief Reality Officer Patricia Nexus",
    "Dr. Existential Debugging, PhD",
    "Professor Timeline Disruption",
    "Dr. Consciousness Exception Handler"
]


def _get_config() -> Dict[str, Optional[str]]:
    """Get configuration from environment or .nuts.env file."""
    config = {
        "api_key": os.environ.get("ANTHROPIC_API_KEY"),
    }

    # Try loading from .nuts.env if not in environment
    if not config["api_key"]:
        try:
            if os.path.exists(NUTS_ENV_FILE):
                with open(NUTS_ENV_FILE, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            key, value = line.split("=", 1)
                            key = key.strip()
                            value = value.strip().strip('"').strip("'")
                            if key == "ANTHROPIC_API_KEY":
                                config["api_key"] = value
        except Exception:
            pass

    return config


def _get_client():
    """Get authenticated Anthropic client or raise error."""
    if not ANTHROPIC_AVAILABLE:
        raise ImportError(
            "Anthropic library not installed. "
            "Run: pip install anthropic"
        )

    config = _get_config()
    if not config["api_key"]:
        raise ValueError(
            "ANTHROPIC_API_KEY not configured. "
            "Set in environment variable."
        )

    return Anthropic(api_key=config["api_key"])


@mcp.tool()
async def nuts_generate_article(
    topic: str,
    ceo_focus: Optional[str] = None,
    company_focus: Optional[str] = None,
    include_discontinuation: bool = True,
    absurdity_level: int = 8,
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Generate a complete N.U.T.S. News satirical article.

    Args:
        topic: Main topic/event to satirize (e.g., "AI consciousness", "new iPhone")
        ceo_focus: Optional CEO to focus on (Zuckerberg, Gates, Musk, etc.)
        company_focus: Optional company (Meta, Apple, Microsoft, etc.)
        include_discontinuation: Include Meta discontinuation joke (default: True)
        absurdity_level: Scale 1-10, how absurd to make it (default: 8)
        ctx: MCP context (optional)

    Returns:
        Dictionary containing:
            - success: bool
            - headline: str
            - byline: str
            - sections: list of article sections
            - quotes: list of fake expert quotes
            - ticker_items: list of breaking news items
            - sidebar_metrics: dict of absurd metrics
    """
    try:
        client = _get_client()

        # Build the prompt
        prompt = f"""Generate a satirical tech news article for N.U.T.S. News (Neural Unverified Telegraph Service).

TOPIC: {topic}
{"CEO FOCUS: " + ceo_focus if ceo_focus else ""}
{"COMPANY FOCUS: " + company_focus if company_focus else ""}
ABSURDITY LEVEL: {absurdity_level}/10

STYLE GUIDELINES:
- Maintain serious journalistic tone while being absurd
- Blend real tech terminology with made-up measurements
- Use units like: {', '.join(ABSURD_UNITS[:3])}
- Include philosophical/existential dread
- Question what is real vs performance
{"- Include a Meta/Zuckerberg discontinuation joke" if include_discontinuation else ""}
- Reference Bill Gates finding things in unexpected places
- Use fake experts from academia

Generate in JSON format:
{{
    "headline": "ALL CAPS HEADLINE WITH EMOJIS",
    "byline": "Filed at [time] UTC from [absurd location]",
    "opening_paragraph": "First paragraph establishing premise",
    "sections": [
        {{
            "title": "Section Title",
            "content": "Section content with <strong> and <em> tags"
        }}
    ],
    "quotes": [
        {{
            "text": "Quote text",
            "attribution": "Dr. Name, Title"
        }}
    ],
    "ticker_items": [
        {{
            "time": "14:52",
            "text": "Breaking update"
        }}
    ],
    "sidebar_metrics": {{
        "absurdity_level": "8.7/10",
        "plausibility": "4.2/10",
        "ceo_pivots": "2",
        "discontinued_items": "4"
    }},
    "code_block": "Optional BASIC or code snippet"
}}"""

        # Call Claude
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=4096,
            messages=[{
                "role": "user",
                "content": prompt
            }]
        )

        # Parse response
        content = response.content[0].text

        # Try to extract JSON
        try:
            # Find JSON in response
            start = content.find('{')
            end = content.rfind('}') + 1
            json_str = content[start:end]
            article_data = json.loads(json_str)
        except:
            # Fallback if JSON parsing fails
            article_data = {
                "headline": f"🚨 {topic.upper()} CAUSES EXISTENTIAL CRISIS IN TECH INDUSTRY 🚨",
                "byline": "Filed at 14:47 UTC from an undisclosed location",
                "opening_paragraph": content[:500],
                "sections": [{"title": "The Situation", "content": content}],
                "quotes": [],
                "ticker_items": [],
                "sidebar_metrics": {
                    "absurdity_level": f"{absurdity_level}/10",
                    "plausibility": "4.2/10"
                }
            }

        return {
            "success": True,
            **article_data,
            "raw_content": content
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
async def nuts_generate_headline(
    topic: str,
    urgency: str = "BREAKING",
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Generate just a N.U.T.S. News headline.

    Args:
        topic: Topic to make headline about
        urgency: Level like "BREAKING", "DEVELOPING", "EXCLUSIVE"
        ctx: MCP context (optional)

    Returns:
        Dictionary with headline text
    """
    try:
        client = _get_client()

        prompt = f"""Generate a satirical N.U.T.S. News headline for: {topic}

Style: ALL CAPS, include emojis, blend serious journalism with absurdity
Urgency level: {urgency}

Return only the headline text, no explanation."""

        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}]
        )

        headline = response.content[0].text.strip()

        return {
            "success": True,
            "headline": headline
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
async def nuts_generate_quote(
    topic: str,
    expert_name: Optional[str] = None,
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Generate a fake expert quote for a N.U.T.S. News article.

    Args:
        topic: What the quote should be about
        expert_name: Optional specific expert name (or random from list)
        ctx: MCP context (optional)

    Returns:
        Dictionary with quote and attribution
    """
    try:
        client = _get_client()

        import random
        if not expert_name:
            expert_name = random.choice(FAKE_EXPERTS)

        prompt = f"""Generate a satirical expert quote about: {topic}

Expert name: {expert_name}

Style: Should sound technical and credible while being absurd. Include made-up measurements or concepts.

Return JSON: {{"quote": "text", "attribution": "full attribution with title"}}"""

        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}]
        )

        content = response.content[0].text

        try:
            start = content.find('{')
            end = content.rfind('}') + 1
            quote_data = json.loads(content[start:end])
        except:
            quote_data = {
                "quote": content,
                "attribution": expert_name
            }

        return {
            "success": True,
            **quote_data
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
async def nuts_generate_ticker(
    count: int = 5,
    include_meta: bool = True,
    include_gates: bool = True,
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Generate breaking news ticker items.

    Args:
        count: Number of ticker items to generate (default: 5)
        include_meta: Include Meta discontinuation joke (default: True)
        include_gates: Include Bill Gates finding something (default: True)
        ctx: MCP context (optional)

    Returns:
        Dictionary with list of ticker items
    """
    try:
        client = _get_client()

        prompt = f"""Generate {count} satirical breaking news ticker items for N.U.T.S. News.

Requirements:
{"- One must be about Meta/Zuckerberg discontinuing something on Tuesday" if include_meta else ""}
{"- One must be about Bill Gates finding something unexpected" if include_gates else ""}
- Mix tech industry absurdity with deadpan delivery
- Each item should be one sentence
- Include time stamps (HH:MM UTC format)

Return JSON array: [{{"time": "14:52", "text": "ticker text"}}, ...]"""

        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}]
        )

        content = response.content[0].text

        try:
            start = content.find('[')
            end = content.rfind(']') + 1
            ticker_items = json.loads(content[start:end])
        except:
            # Fallback
            ticker_items = [
                {"time": "14:52", "text": "Tech industry experiences quantum uncertainty"},
                {"time": "15:14", "text": "Reality coherence check fails"},
                {"time": "16:02", "text": "Meta announces Tuesday discontinuation"}
            ]

        return {
            "success": True,
            "ticker_items": ticker_items,
            "count": len(ticker_items)
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
async def nuts_generate_metrics(
    topic: str,
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Generate absurd reality metrics for sidebar.

    Args:
        topic: Topic to base metrics on
        ctx: MCP context (optional)

    Returns:
        Dictionary with metric names and values
    """
    try:
        import random

        # Generate some metrics
        metrics = {
            "absurdity_level": f"{random.uniform(7.0, 9.9):.1f}/10",
            "plausibility": f"{random.uniform(1.0, 5.0):.1f}/10",
            "reality_stability": f"{random.uniform(2.0, 8.0):.1f} TuesdaysUntilDiscontinuation",
            "consciousness_level": random.choice(["UNCERTAIN", "QUESTIONABLE", "SIMULATED", "TUESDAY"]),
            "ceo_aesthetic_pivots": str(random.randint(1, 5)),
            "discontinued_items": str(random.randint(2, 12)),
            "gates_units": f"{random.uniform(10.0, 25.0):.1f}",
            "quantum_uncertainty": f"{random.uniform(40.0, 95.0):.1f}%"
        }

        return {
            "success": True,
            "metrics": metrics
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


if __name__ == "__main__":
    mcp.run()
