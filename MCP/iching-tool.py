#!/usr/bin/env python3
"""I Ching divination tool with seed-phrase-driven cryptographic randomness."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("iching-tool")

HEXAGRAMS: Dict[int, Dict[str, str]] = {
    1: {"name": "Ch'ien", "english": "The Creative", "meaning": "Strong yang energy, leadership, unbroken potential."},
    2: {"name": "K'un", "english": "The Receptive", "meaning": "Pure yin, yielding stability, supportive earth energy."},
    3: {"name": "Chun", "english": "Difficulty at the Beginning", "meaning": "Growth through challenge and learning."},
    4: {"name": "Mêng", "english": "Youthful Folly", "meaning": "Inexperience, need for guidance, openness to learning."},
    5: {"name": "Hsü", "english": "Waiting", "meaning": "Patience, nourishment, aligning with natural timing."},
    6: {"name": "Sung", "english": "Conflict", "meaning": "Tension that invites clarity and principled action."},
    7: {"name": "Shih", "english": "The Army", "meaning": "Discipline, strategy, community strength."},
    8: {"name": "Pi", "english": "Holding Together", "meaning": "Unity, alliance, mutual support."},
    9: {"name": "Hsiao Ch'u", "english": "The Taming Power of the Small", "meaning": "Attention to detail, gradual influence."},
    10: {"name": "Lü", "english": "Treading", "meaning": "Careful conduct, respect for the ground beneath you."},
    11: {"name": "T'ai", "english": "Peace", "meaning": "Harmony between heaven and earth, prosperity."},
    12: {"name": "P'i", "english": "Standstill", "meaning": "Stagnation invites inner preparation."},
    13: {"name": "T'ung Jên", "english": "Fellowship with Men", "meaning": "Community, shared ideals, collaboration."},
    14: {"name": "Ta Yu", "english": "Possession in Great Measure", "meaning": "Abundance balanced by humility."},
    15: {"name": "Ch'ien", "english": "Modesty", "meaning": "Power held gently, careful influence."},
    16: {"name": "Yü", "english": "Enthusiasm", "meaning": "Joyful motion, readiness to act."},
    17: {"name": "Sui", "english": "Following", "meaning": "Adaptation, following natural flow."},
    18: {"name": "Ku", "english": "Work on What Has Been Spoiled", "meaning": "Repairing decay through devoted effort."},
    19: {"name": "Lin", "english": "Approach", "meaning": "Influence, preparation for greatness."},
    20: {"name": "Kuan", "english": "Contemplation", "meaning": "Observation, mindful perspective."},
    21: {"name": "Shih Ho", "english": "Biting Through", "meaning": "Decisive action with clarity."},
    22: {"name": "Pi", "english": "Grace", "meaning": "Beauty born from disciplined refinement."},
    23: {"name": "Po", "english": "Splitting Apart", "meaning": "Deterioration that clears space for renewal."},
    24: {"name": "Fu", "english": "Return", "meaning": "Turning point, cyclical renewal."},
    25: {"name": "Wu Wang", "english": "Innocence", "meaning": "Spontaneous right action without ulterior motives."},
    26: {"name": "Ta Ch'u", "english": "The Taming Power of the Great", "meaning": "Restraint that channels power."},
    27: {"name": "I", "english": "Corners of the Mouth", "meaning": "Nourishment, careful attention."},
    28: {"name": "Ta Kuo", "english": "Preponderance of the Great", "meaning": "Excess leading to responsibility."},
    29: {"name": "K'an", "english": "The Abysmal Water", "meaning": "Danger met with perseverance."},
    30: {"name": "Li", "english": "The Clinging Fire", "meaning": "Clarity through illumination and attachment."},
    31: {"name": "Hsien", "english": "Influence", "meaning": "Attraction and responsiveness."},
    32: {"name": "Hêng", "english": "Duration", "meaning": "Consistent endurance."},
    33: {"name": "Tun", "english": "Retreat", "meaning": "Strategic withdrawal for greater gain."},
    34: {"name": "Ta Chuang", "english": "The Power of the Great", "meaning": "Vigorous action with purpose."},
    35: {"name": "Chin", "english": "Progress", "meaning": "Momentum aligned with clarity."},
    36: {"name": "Ming I", "english": "Darkening of the Light", "meaning": "Perseverance through adversity."},
    37: {"name": "Chia Jên", "english": "The Family", "meaning": "Structure and responsibility within relationships."},
    38: {"name": "K'uei", "english": "Opposition", "meaning": "Tension that gifts insight."},
    39: {"name": "Chien", "english": "Obstruction", "meaning": "Obstacle inviting new pathways."},
    40: {"name": "Hsieh", "english": "Deliverance", "meaning": "Release from constraint."},
    41: {"name": "Sun", "english": "Decrease", "meaning": "Simplify to restore balance."},
    42: {"name": "I", "english": "Increase", "meaning": "Growth that lifts others."},
    43: {"name": "Kuai", "english": "Breakthrough", "meaning": "Resolute clarity cutting through resistance."},
    44: {"name": "Kou", "english": "Coming to Meet", "meaning": "Encounter that demands vigilance."},
    45: {"name": "Ts'ui", "english": "Gathering Together", "meaning": "Focused community effort."},
    46: {"name": "Shêng", "english": "Pushing Upward", "meaning": "Gradual ascent with intention."},
    47: {"name": "K'un", "english": "Oppression", "meaning": "Constraint calling for inner strength."},
    48: {"name": "Ching", "english": "The Well", "meaning": "Reliable source that nourishes community."},
    49: {"name": "Ko", "english": "Revolution", "meaning": "Transformation that aligns with higher truth."},
    50: {"name": "Ting", "english": "The Cauldron", "meaning": "Cultural transformation through nourishment."},
    51: {"name": "Chên", "english": "The Arousing", "meaning": "Shock that awakens potential."},
    52: {"name": "Kên", "english": "Keeping Still", "meaning": "Calm reflection, steady foundation."},
    53: {"name": "Chien", "english": "Development", "meaning": "Gradual growth and orderly progress."},
    54: {"name": "Kuei Mei", "english": "The Marrying Maiden", "meaning": "Temporary roles requiring propriety."},
    55: {"name": "Fêng", "english": "Abundance", "meaning": "Peak prosperity that must be stewarded."},
    56: {"name": "Lü", "english": "The Wanderer", "meaning": "Adaptation through transient journeys."},
    57: {"name": "Sun", "english": "The Gentle", "meaning": "Subtle influence through persistence."},
    58: {"name": "Tui", "english": "The Joyous", "meaning": "Joy and satisfaction guiding connections."},
    59: {"name": "Huan", "english": "Dispersion", "meaning": "Release of rigidity to welcome new flow."},
    60: {"name": "Chieh", "english": "Limitation", "meaning": "Boundaries that forge clarity."},
    61: {"name": "Chung Fu", "english": "Inner Truth", "meaning": "Sincerity aligning intention and action."},
    62: {"name": "Hsiao Kuo", "english": "Preponderance of the Small", "meaning": "Detail-oriented precision."},
    63: {"name": "Chi Chi", "english": "After Completion", "meaning": "Completion that gives birth to new concerns."},
    64: {"name": "Wei Chi", "english": "Before Completion", "meaning": "Anticipation at the threshold of success."},
}

LINE_TYPES: Dict[int, Dict[str, Any]] = {
    6: {"label": "Old Yin", "symbol": "---x---", "changing": True},
    7: {"label": "Young Yang", "symbol": "-------", "changing": False},
    8: {"label": "Young Yin", "symbol": "--- ---", "changing": False},
    9: {"label": "Old Yang", "symbol": "---o---", "changing": True},
}

class SeededEntropy:
    """Cryptographic deterministic generator seeded by a passphrase."""

    def __init__(self, seed_phrase: Optional[str]) -> None:
        if seed_phrase:
            self.seed_bytes = seed_phrase.encode("utf-8")
        else:
            self.seed_bytes = secrets.token_hex(32).encode("utf-8")
        self.counter = 0

    def _digest(self) -> bytes:
        counter_bytes = self.counter.to_bytes(8, "big")
        self.counter += 1
        return hashlib.blake2b(self.seed_bytes + counter_bytes, digest_size=32).digest()

    def randbits(self, k: int) -> int:
        if k <= 0:
            return 0
        needed_bytes = (k + 7) // 8
        output = b""
        while len(output) < needed_bytes:
            output += self._digest()
        value = int.from_bytes(output[:needed_bytes], "big")
        return value & ((1 << k) - 1)

    def randbelow(self, upper: int) -> int:
        if upper <= 0:
            raise ValueError("upper must be positive")
        bits = upper.bit_length()
        while True:
            candidate = self.randbits(bits)
            if candidate < upper:
                return candidate

    def randint(self, minimum: int, maximum: int) -> int:
        if minimum > maximum:
            raise ValueError("minimum must be <= maximum")
        return minimum + self.randbelow(maximum - minimum + 1)

    def choice(self, sequence: List[Any]) -> Any:
        if not sequence:
            raise ValueError("sequence must not be empty")
        index = self.randbelow(len(sequence))
        return sequence[index]


def _cast_line(generator: SeededEntropy) -> Dict[str, Any]:
    coins = [generator.randint(2, 3) for _ in range(3)]
    total = sum(coins)
    line_type = LINE_TYPES[total]
    return {
        "value": 0 if total % 2 == 0 else 1,
        "symbol": line_type["symbol"],
        "type": line_type["label"],
        "coins": coins,
        "changing": line_type["changing"],
    }


def _hexagram_number(lines: List[int]) -> int:
    binary = "".join(str(line) for line in reversed(lines))
    return int(binary, 2) + 1


def _format_visual(lines: List[int]) -> List[str]:
    visual = []
    for idx in range(5, -1, -1):
        line_value = lines[idx]
        symbol = "-------" if line_value == 1 else "--- ---"
        visual.append(f"Line {6 - idx}: {symbol}")
    return visual


def _interpretation(primary: Dict[str, str], changing_lines: List[int], transformed: Optional[Dict[str, str]]) -> str:
    base = f"{primary['name']} ({primary['english']}): {primary['meaning']}"
    if not changing_lines:
        return f"{base}. Stability is indicated; proceed with care."
    change_info = (
        f" Changing lines {', '.join(str(line) for line in changing_lines)} point toward "
        f"{transformed['name']} ({transformed['english']}): {transformed['meaning']}" if transformed else "transformation." 
    )
    return f"{base}. {change_info}"


def _derive_generator(seed_phrase: Optional[str]) -> SeededEntropy:
    return SeededEntropy(seed_phrase)


@mcp.tool()
async def iching_casting(
    seed_phrase: Optional[str] = None,
    question: Optional[str] = None
) -> Dict[str, Any]:
    """Cast an I Ching hexagram using a passphrase-seeded cryptographic generator."""
    generator = _derive_generator(seed_phrase)
    lines: List[int] = []
    line_details: List[Dict[str, Any]] = []
    changing_lines: List[int] = []

    for line_number in range(6):
        detail = _cast_line(generator)
        lines.append(detail["value"])
        line_details.append(detail)
        if detail["changing"]:
            changing_lines.append(line_number + 1)

    primary_number = _hexagram_number(lines)
    primary = HEXAGRAMS.get(primary_number, {"name": "Unknown", "english": "Unknown", "meaning": "Unknown"})

    transformed = None
    if changing_lines:
        changed_lines = lines.copy()
        for idx in changing_lines:
            changed_lines[idx - 1] = 1 - changed_lines[idx - 1]
        transformed_number = _hexagram_number(changed_lines)
        transformed = HEXAGRAMS.get(transformed_number, {"name": "Unknown", "english": "Unknown", "meaning": "Unknown"})

    visual = _format_visual(lines)
    interpretation = _interpretation(primary, changing_lines, transformed)

    result: Dict[str, Any] = {
        "success": True,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "seed_phrase": seed_phrase,
        "question": question,
        "primary_hexagram": {
            "number": primary_number,
            "name": primary["name"],
            "english": primary["english"],
            "meaning": primary["meaning"],
        },
        "changing_lines": changing_lines,
        "changed_hexagram": {
            "name": transformed["name"],
            "english": transformed["english"],
            "meaning": transformed["meaning"],
        } if transformed else None,
        "line_details": line_details,
        "visual": visual,
        "interpretation": interpretation,
    }
    return result


if __name__ == "__main__":
    mcp.run()
