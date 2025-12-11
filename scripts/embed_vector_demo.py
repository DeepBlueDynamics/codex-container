#!/usr/bin/env python3
"""
Quick embedding smoke test against the Instructor service.
Calls /embed, then prints cosine similarities between sample texts.
"""

import math
import os
import sys
from typing import List

try:
    import requests  # type: ignore
except ImportError:
    print("Please install requests: python -m pip install requests", file=sys.stderr)
    sys.exit(1)


EMBED_URL = os.environ.get("INSTRUCTOR_SERVICE_URL", "http://localhost:8787/embed")


def cosine(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def embed(texts: List[str], instruction: str = "Represent the text for semantic search") -> List[List[float]]:
    resp = requests.post(
        EMBED_URL,
        json={"texts": texts, "instruction": instruction, "normalize": True},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    embeddings = data.get("embeddings")
    if not embeddings:
        raise RuntimeError(f"No embeddings returned: {data}")
    return embeddings


def main():
    # Build ~100 meaningful strings; keep under service caps
    samples = [
        # OpenAI / corp structure / funding
        "OpenAI converted to a for-profit PBC with Microsoft owning 27 percent stake",
        "OpenAI completed a six point six billion dollar secondary sale at five hundred billion valuation",
        "OpenAI contracted to buy two hundred fifty billion in Azure cloud services as part of restructure",
        "OpenAI Foundation retains nonprofit oversight while for-profit subsidiary raises capital",
        "OpenAI revenue trajectory exceeded four billion in first half twenty twenty five per reports",
        # Models / tech
        "OpenAI is known for the GPT family of large language models and DALL E image generation",
        "ChatGPT release in November twenty twenty two catalyzed mainstream interest in generative AI",
        "Sora is the text to video model announced alongside other foundation models",
        "OpenAI Gym and Universe were early platforms for reinforcement learning research",
        # Legal / disputes
        "OpenAI faced lawsuits over copyright infringement from authors and media companies",
        "Reuters reported multiple legal actions about data scraping and training datasets",
        "The board briefly removed Sam Altman in twenty twenty three before reinstating him",
        # Partnerships / infra
        "Microsoft invested over thirteen billion dollars and provides Azure supercomputing resources",
        "The partnership included right of first refusal clauses later relaxed in restructure",
        "OpenAI agreed to share twenty percent of revenue with Microsoft until AGI milestone",
        # Governance / mission
        "OpenAI charter emphasizes safe and beneficial artificial general intelligence for humanity",
        "Founders cited AI safety and existential risk as motivation for nonprofit origins",
        "Transition to capped profit model allowed employee equity while preserving mission",
        # Benchmarks / risks
        "Some researchers left citing safety concerns and industry wide issues in twenty twenty four",
        "Analysts question sustainability of valuation given compute commitments and lawsuits",
        "Take or pay cloud commitments could pressure margins if revenue growth slows",
        # Wikipedia / general AI
        "Wikipedia main page features ongoing conflicts including Gaza war and Russo Ukrainian war",
        "Featured article highlighted Ovalipes catharus paddle crab in New Zealand waters",
        "Did you know section lists historical trivia and cultural references daily",
        "In the news items report natural disasters political upheavals and sports results",
        # Add more contextual strings to reach ~100 items
    ]

    # Pad with variations to reach ~100 entries
    base_variants = [
        "OpenAI corporate structure blends nonprofit control with for profit capital raise",
        "OpenAI valuation discussions revolve around secondary sales and primary fundraising",
        "Azure spend commitments form a significant part of OpenAI operational costs",
        "Legal exposure from copyright suits remains an overhang on OpenAI growth story",
        "Generative AI momentum tied to ChatGPT adoption and enterprise licensing",
        "Revenue quality depends on cloud subsidies and enterprise retention metrics",
        "Founders Sam Altman and Elon Musk initially co chaired OpenAI nonprofit entity",
        "OpenAI Gym and Universe established early community traction for RL research",
        "Safety researchers departures spotlight governance and risk management gaps",
        "Partnership with Microsoft expanded Copilot branding across Windows and Office",
        "Public benefit corporation status may ease future IPO or major liquidity events",
        "AI boom narratives credit OpenAI with catalyzing industry wide investment surge",
        "Potential take or pay contracts raise questions about demand forecasting accuracy",
        "Data sourcing and consent remain focal points in regulatory and legal scrutiny",
        "GPT family advances include GPT four GPT four point one and smaller OSS variants",
        "DALL E series evolved from text to image to multimodal creative tools",
        "Sora positions OpenAI in text to video generation competitive landscape",
        "Board governance changes followed the brief removal of Sam Altman as CEO",
        "Nonprofit charter aims to ensure AGI benefits all humanity per OpenAI mission",
        "Funding milestones include one billion pledges at founding and later mega rounds",
        "Supercomputing costs drive need for large capital raises and strategic partners",
        "OpenAI coding tools like Codex underpin various developer integrations",
        "Universe platform aggregated games and websites for measuring general intelligence",
        "For profit conversion allowed employee equity while capping profit multiples",
        "Secondary share sales provided liquidity to employees at high valuations",
        "Partnership revenue share clauses tied to achievement of AGI milestones",
        "Cloud resource agreements include massive Azure capacity reservations",
        "Competitive landscape includes Anthropic, Google DeepMind, Meta, xAI, Mistral",
        "Legal disputes involve authors, news outlets, and privacy advocates",
        "Public communications stress safety alignment and responsible deployment",
    ]
    # Duplicate variants to reach ~60 strings (fit within default MAX_TEXTS)
    while len(samples) < 60:
        samples.extend(base_variants)
    samples = samples[:60]

    print(f"Embedding {len(samples)} texts via {EMBED_URL} ...")
    vecs = embed(samples)
    # Compute a few pairwise sims for sanity (first 5)
    print("Sample cosine similarities:")
    for i in range(5):
        for j in range(i + 1, 5):
            sim = cosine(vecs[i], vecs[j])
            print(f"  cos({i},{j}) = {sim:.3f}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
