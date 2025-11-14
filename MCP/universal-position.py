#!/usr/bin/env python3
"""MCP: universal-position

Expose a deterministic, four-dimensional Universal Positioning Coordinate (UPC)
frame as an MCP tool. The first three axes are barycentric ecliptic Cartesian
coordinates (kilometres) aligned with the mean equinox of J2000.0, and the
fourth component is elapsed SI seconds since J2000.0.

The math adapts NASA/NOAA solar position approximations which are lightweight
yet accurate to well within 10,000 km—plenty for a fun positioning system.
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timezone
from typing import Dict

from mcp.server.fastmcp import FastMCP


mcp = FastMCP("universal-position")


AU_IN_KILOMETERS = 149_597_870.7
J2000 = datetime(2000, 1, 1, 12, tzinfo=timezone.utc)


@dataclass(frozen=True)
class UPCVector:
    """Convenience container for the four UPC components."""

    x_km: float
    y_km: float
    z_km: float
    t_seconds_since_j2000: float

    def as_dict(self) -> Dict[str, float]:
        """Serialize the vector for transport over MCP."""

        return {
            "x_km": self.x_km,
            "y_km": self.y_km,
            "z_km": self.z_km,
            "t_seconds_since_j2000": self.t_seconds_since_j2000,
        }


def _to_julian_date(timestamp: datetime) -> float:
    """Convert a timezone-aware datetime into a Julian Date."""

    timestamp = timestamp.astimezone(UTC)
    year = timestamp.year
    month = timestamp.month
    day = timestamp.day + (
        timestamp.hour / 24
        + timestamp.minute / 1_440
        + timestamp.second / 86_400
        + timestamp.microsecond / 86_400_000_000
    )

    if month <= 2:
        year -= 1
        month += 12

    a = year // 100
    b = 2 - a + a // 4
    return (
        math.floor(365.25 * (year + 4716))
        + math.floor(30.6001 * (month + 1))
        + day
        + b
        - 1524.5
    )


def _normalize_angle(value_degrees: float) -> float:
    """Wrap angle to [0, 360) degrees."""

    return value_degrees % 360.0


def compute_upc(timestamp: datetime) -> UPCVector:
    """Return Earth's UPC vector for the supplied instant."""

    julian_date = _to_julian_date(timestamp)
    centuries = (julian_date - 2_451_545.0) / 36_525.0

    mean_longitude = _normalize_angle(
        280.46646 + 36_000.76983 * centuries + 0.0003032 * centuries**2
    )
    mean_anomaly = _normalize_angle(
        357.52911 + 35_999.05029 * centuries - 0.0001537 * centuries**2
    )
    eccentricity = 0.016708634 - 0.000042037 * centuries - 0.0000001267 * centuries**2

    m_rad = math.radians(mean_anomaly)
    equation_of_center = (
        (1.914602 - 0.004817 * centuries - 0.000014 * centuries**2) * math.sin(m_rad)
        + (0.019993 - 0.000101 * centuries) * math.sin(2 * m_rad)
        + 0.000289 * math.sin(3 * m_rad)
    )

    true_longitude = mean_longitude + equation_of_center
    true_anomaly = mean_anomaly + equation_of_center

    radius_vector_au = (
        (1.000001018 * (1 - eccentricity * eccentricity))
        / (1 + eccentricity * math.cos(math.radians(true_anomaly)))
    )
    radius_km = radius_vector_au * AU_IN_KILOMETERS

    true_longitude_rad = math.radians(true_longitude)
    x_km = radius_km * math.cos(true_longitude_rad)
    y_km = radius_km * math.sin(true_longitude_rad)
    z_km = 0.0  # Earth shares the ecliptic plane to high precision.

    t_seconds = (timestamp.astimezone(UTC) - J2000).total_seconds()

    return UPCVector(
        x_km=x_km,
        y_km=y_km,
        z_km=z_km,
        t_seconds_since_j2000=t_seconds,
    )


def _parse_timestamp(timestamp: str | None) -> datetime:
    """Parse ISO 8601 input, defaulting to current UTC."""

    if not timestamp:
        return datetime.now(tz=UTC)

    cleaned = timestamp.strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"

    dt = datetime.fromisoformat(cleaned)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


@mcp.tool()
async def earth_universal_position(timestamp: str | None = None) -> Dict[str, object]:
    """Return Earth's Universal Positioning Coordinates.

    Args:
        timestamp: Optional ISO 8601 instant. Defaults to current UTC if omitted.

    Returns:
        Dictionary describing the coordinate system and four-component vector.
    """

    instant = _parse_timestamp(timestamp)
    vector = compute_upc(instant)
    return {
        "coordinate_system": "UPC::BarycentricEcliptic+SecondsSinceJ2000",
        "timestamp_utc": instant.isoformat(),
        "vector": vector.as_dict(),
    }


if __name__ == "__main__":  # pragma: no cover - CLI entry
    print("[universal-position] Starting MCP server", file=sys.stderr, flush=True)
    mcp.run()
