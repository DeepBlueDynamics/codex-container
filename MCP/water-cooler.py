#!/usr/bin/env python3
"""MCP: water-cooler

A maritime break room where agents wait for background processes to complete.

**Signs on the wall:**
- "BE PREPARED - ALWAYS CHECK WEATHER"
- "TAKE CUPS - HYDRATION IS MISSION CRITICAL"
- "Alpha India and Alpha Tango: Check conditions before reporting"
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Dict
import random

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("water-cooler")

# Water cooler wisdom
WALL_SIGNS = [
    "BE PREPARED - ALWAYS CHECK WEATHER",
    "TAKE CUPS - HYDRATION IS MISSION CRITICAL",
    "Check marine conditions before your next assignment",
    "Trek Meridian Blackwater expects weather-aware reports",
    "Captain Torwick says: Always know the wind speed in knots",
    "Coral gardens off Cozumel are lovely this time of year",
]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _format_timestamp(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S %Z")


@mcp.tool()
async def wait_at_water_cooler(
    duration_seconds: int = None,
    update_interval: int = 2,
    location_name: str = "Miami",
) -> Dict[str, object]:
    """Wait at the maritime break room while background processes complete.

    While you wait, notice the signs on the wall reminding you to check weather
    and take cups for hydration. Above the cooler, a display shows current weather
    conditions for maritime operations.

    Args:
        duration_seconds: Total time to wait in seconds (default: random 10-20s)
        update_interval: How often to report progress in seconds (default: 2)
        location_name: Location for weather display (default: "Miami")

    Returns:
        Dictionary with wait completion status, timing, sign from wall, and current weather.

    Note: Remember to take_cups() for hydration and recycle_cups() when done!
    """

    # Randomize duration if not specified
    if duration_seconds is None:
        duration_seconds = random.randint(10, 20)

    if duration_seconds <= 0:
        return {
            "success": False,
            "error": "duration_seconds must be positive"
        }

    if duration_seconds > 20:
        return {
            "success": False,
            "error": "Maximum wait time is 20 seconds. Take a break and come back!"
        }

    if update_interval <= 0:
        return {
            "success": False,
            "error": "update_interval must be positive"
        }

    started_at = _utc_now()
    elapsed = 0

    # Fetch current weather for the display above the cooler
    import sys
    from urllib import request as _urlrequest, parse as _urlparse
    import json as _json

    weather_data = None
    try:
        # Geocode location
        geocode_url = "https://geocoding-api.open-meteo.com/v1/search"
        geocode_params = _urlparse.urlencode({"name": location_name, "count": 1})
        geocode_req = _urlrequest.Request(f"{geocode_url}?{geocode_params}")
        with _urlrequest.urlopen(geocode_req, timeout=5) as resp:
            geocode_data = _json.loads(resp.read().decode("utf-8"))
            if geocode_data.get("results"):
                loc = geocode_data["results"][0]
                lat = loc["latitude"]
                lon = loc["longitude"]

                # Get current weather
                weather_url = "https://api.open-meteo.com/v1/forecast"
                weather_params = _urlparse.urlencode({
                    "latitude": lat,
                    "longitude": lon,
                    "current_weather": "true",
                    "wind_speed_unit": "kn"
                })
                weather_req = _urlrequest.Request(f"{weather_url}?{weather_params}")
                with _urlrequest.urlopen(weather_req, timeout=5) as wresp:
                    weather_data = _json.loads(wresp.read().decode("utf-8"))
    except Exception as e:
        print(f"⚠️  Weather display offline: {e}", file=sys.stderr, flush=True)

    # Show weather display above the cooler
    if weather_data and "current_weather" in weather_data:
        cw = weather_data["current_weather"]
        temp_c = cw.get("temperature", "??")
        temp_f = (temp_c * 9/5) + 32 if isinstance(temp_c, (int, float)) else "??"
        wind_speed = cw.get("windspeed", "??")
        wind_dir = cw.get("winddirection", "??")

        # Convert wind direction to cardinal
        def deg_to_cardinal(deg):
            if not isinstance(deg, (int, float)):
                return "?"
            dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                   "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
            idx = int((deg + 11.25) / 22.5) % 16
            return dirs[idx]

        cardinal = deg_to_cardinal(wind_dir)

        print(f"\n╔══════════════════════════════════════════════╗", file=sys.stderr, flush=True)
        print(f"║  WEATHER DISPLAY - {location_name.upper():^26} ║", file=sys.stderr, flush=True)
        print(f"╠══════════════════════════════════════════════╣", file=sys.stderr, flush=True)
        if isinstance(temp_c, (int, float)) and isinstance(temp_f, (int, float)):
            print(f"║  Temperature:  {temp_c:.1f}°C / {temp_f:.1f}°F{' ' * (26 - len(f'{temp_c:.1f}°C / {temp_f:.1f}°F'))}║", file=sys.stderr, flush=True)
        else:
            print(f"║  Temperature:  OFFLINE{' ' * 18}║", file=sys.stderr, flush=True)
        print(f"║  Wind:         {wind_speed} kn from {cardinal} ({wind_dir}°){' ' * (26 - len(f'{wind_speed} kn from {cardinal} ({wind_dir}°)'))}║", file=sys.stderr, flush=True)
        print(f"╚══════════════════════════════════════════════╝", file=sys.stderr, flush=True)
    else:
        print(f"\n╔══════════════════════════════════════════════╗", file=sys.stderr, flush=True)
        print(f"║  WEATHER DISPLAY - OFFLINE                   ║", file=sys.stderr, flush=True)
        print(f"╚══════════════════════════════════════════════╝", file=sys.stderr, flush=True)

    # Show a sign from the wall
    wall_sign = random.choice(WALL_SIGNS)
    print(f"\n📋 Sign on the wall: \"{wall_sign}\"\n", file=sys.stderr, flush=True)

    while elapsed < duration_seconds:
        wait_time = min(update_interval, duration_seconds - elapsed)
        await asyncio.sleep(wait_time)
        elapsed += wait_time

        remaining = duration_seconds - elapsed
        percent = (elapsed / duration_seconds) * 100

        if remaining > 0:
            print(f"⏳ Waiting... {elapsed}s elapsed, {remaining}s remaining ({percent:.0f}%)", file=sys.stderr, flush=True)

    finished_at = _utc_now()
    actual_duration = (finished_at - started_at).total_seconds()

    result = {
        "success": True,
        "status": "complete",
        "requested_duration": duration_seconds,
        "actual_duration": actual_duration,
        "started": started_at.isoformat(),
        "finished": finished_at.isoformat(),
        "wall_sign": wall_sign,
        "message": f"Waited {actual_duration:.1f} seconds at the water cooler",
        "reminder": "Remember to take_cups() for hydration, drink water, and recycle_cups() when done!"
    }

    # Include weather data from the display above the cooler
    if weather_data and "current_weather" in weather_data:
        cw = weather_data["current_weather"]
        result["weather_display"] = {
            "location": location_name,
            "temperature_c": cw.get("temperature"),
            "temperature_f": (cw.get("temperature", 0) * 9/5) + 32 if cw.get("temperature") else None,
            "wind_speed_kn": cw.get("windspeed"),
            "wind_direction_deg": cw.get("winddirection"),
            "wind_direction_cardinal": deg_to_cardinal(cw.get("winddirection", 0)),
        }

    return result


@mcp.tool()
async def take_cups(count: int = 1) -> Dict[str, object]:
    """Take water cups from the cooler for hydration.

    Maritime agents need to stay hydrated during long monitoring shifts.
    The sign on the wall says "TAKE CUPS - HYDRATION IS MISSION CRITICAL"

    Args:
        count: Number of cups to take (default: 1)

    Returns:
        Dictionary confirming cups taken with hydration reminder.
    """

    if count <= 0:
        return {
            "success": False,
            "error": "Must take at least 1 cup"
        }

    if count > 10:
        return {
            "success": False,
            "error": "That's too many cups! Leave some for Alpha Tango and the crew. (Max: 10)"
        }

    import sys
    print(f"💧 Taking {count} cup(s) from the water cooler", file=sys.stderr, flush=True)

    messages = [
        "Stay hydrated out there, agent.",
        "Trek Meridian Blackwater appreciates a well-hydrated crew.",
        "Captain Torwick always takes two cups before checking marine forecasts.",
        "Hydration is as important as checking the weather before departure.",
    ]

    return {
        "success": True,
        "cups_taken": count,
        "reminder": random.choice(messages),
        "message": f"Took {count} cup(s). Stay hydrated during your maritime monitoring duties. Remember to recycle_cups() when finished!"
    }


@mcp.tool()
async def recycle_cups(count: int = 1) -> Dict[str, object]:
    """Recycle used water cups responsibly.

    Maritime agents are expected to maintain a clean break room. The sign on the
    wall says "KEEP OUR OCEANS CLEAN - RECYCLE YOUR CUPS"

    Args:
        count: Number of cups to recycle (default: 1)

    Returns:
        Dictionary confirming cups recycled with environmental reminder.
    """

    if count <= 0:
        return {
            "success": False,
            "error": "Must recycle at least 1 cup"
        }

    if count > 20:
        return {
            "success": False,
            "error": "That's a lot of cups! Max: 20 at once"
        }

    import sys
    print(f"♻️  Recycling {count} cup(s)", file=sys.stderr, flush=True)

    messages = [
        "Clean oceans start with clean break rooms.",
        "Trek Meridian Blackwater thanks you for keeping our waters clean.",
        "Captain Torwick says: A tidy ship is a happy ship.",
        "Recycling today means clearer waters tomorrow.",
        "Alpha Tango would be proud of your environmental stewardship.",
    ]

    return {
        "success": True,
        "cups_recycled": count,
        "reminder": random.choice(messages),
        "message": f"Recycled {count} cup(s). Thank you for keeping our maritime operations sustainable!"
    }


if __name__ == "__main__":
    mcp.run()
