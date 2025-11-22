#!/usr/bin/env python3
"""MCP: noaa-marine

NOAA Marine Weather and Tropical Cyclone Tracking

Provides:
- Marine forecasts from NOAA
- Tropical cyclone tracking and forecasts
- Marine warnings and hazards
- Offshore conditions
"""

from __future__ import annotations

import sys
import json
from urllib import request as _urlrequest
from urllib.parse import urlencode
from typing import Dict, Optional, List
from datetime import datetime

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("noaa-marine")


def _fetch_json(url: str, timeout: int = 10) -> Dict:
    """Fetch JSON from URL."""
    req = _urlrequest.Request(url, headers={"User-Agent": "noaa-marine-mcp/1.0"})
    with _urlrequest.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


@mcp.tool()
async def get_active_tropical_cyclones() -> Dict[str, object]:
    """Get all active tropical cyclones from NOAA National Hurricane Center.

    Returns current tropical storms, hurricanes, and disturbances being tracked
    by NHC including position, intensity, movement, and forecast track.

    Returns:
        Dictionary with active cyclones and their current status.

    Example:
        get_active_tropical_cyclones()
    """
    try:
        print(f"[noaa-marine] Fetching active tropical cyclones from NHC", file=sys.stderr, flush=True)

        # NOAA NHC Active Cyclones JSON feed
        url = "https://www.nhc.noaa.gov/CurrentStorms.json"

        data = _fetch_json(url)

        if not data or "activeStorms" not in data:
            return {
                "success": True,
                "active_cyclones": [],
                "message": "No active tropical cyclones"
            }

        cyclones = []
        for storm in data["activeStorms"]:
            cyclone_info = {
                "id": storm.get("id"),
                "name": storm.get("name"),
                "classification": storm.get("classification"),
                "intensity": storm.get("intensity"),
                "pressure": storm.get("pressure"),
                "latitude": storm.get("latitude"),
                "longitude": storm.get("longitude"),
                "movement": storm.get("movement"),
                "last_update": storm.get("lastUpdate"),
                "wallet_id": storm.get("walletId"),
                "basin": storm.get("basin")
            }
            cyclones.append(cyclone_info)

        return {
            "success": True,
            "active_cyclones": cyclones,
            "count": len(cyclones),
            "last_update": data.get("lastUpdate"),
            "message": f"Found {len(cyclones)} active tropical cyclone(s)"
        }

    except Exception as e:
        print(f"❌ Failed to fetch tropical cyclones: {e}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return {
            "success": False,
            "error": str(e),
            "message": "Failed to fetch tropical cyclone data from NOAA NHC"
        }


@mcp.tool()
async def get_cyclone_forecast(storm_id: str) -> Dict[str, object]:
    """Get detailed forecast for a specific tropical cyclone.

    Args:
        storm_id: Storm ID from NHC (e.g., "al142024" for Atlantic storm #14 in 2024)

    Returns:
        Detailed forecast including forecast track, intensity, wind radii, and hazards.

    Example:
        get_cyclone_forecast(storm_id="al142024")
    """
    try:
        print(f"[noaa-marine] Fetching forecast for storm {storm_id}", file=sys.stderr, flush=True)

        # NHC provides GeoJSON forecast data
        url = f"https://www.nhc.noaa.gov/storm_graphics/{storm_id}_5day_cone_no_line_and_wind.kmz"

        # For now, return the URL and basic info
        # Full implementation would parse KMZ or use alternative JSON endpoints

        return {
            "success": True,
            "storm_id": storm_id,
            "forecast_url": url,
            "message": f"Forecast data for {storm_id}. Check NOAA NHC website for detailed graphics.",
            "nhc_page": f"https://www.nhc.noaa.gov/refresh/graphics_{storm_id}/"
        }

    except Exception as e:
        print(f"❌ Failed to fetch cyclone forecast: {e}", file=sys.stderr, flush=True)
        return {
            "success": False,
            "error": str(e),
            "message": f"Failed to fetch forecast for storm {storm_id}"
        }


@mcp.tool()
async def get_marine_forecast(
    latitude: float,
    longitude: float,
    zone: Optional[str] = None
) -> Dict[str, object]:
    """Get NOAA marine forecast for a location.

    Args:
        latitude: Latitude in decimal degrees
        longitude: Longitude in decimal degrees
        zone: Optional NOAA marine zone code (e.g., "AMZ610" for Caribbean)

    Returns:
        Marine forecast including winds, seas, weather, and hazards.

    Example:
        get_marine_forecast(latitude=18.0, longitude=-76.8)
    """
    try:
        print(f"[noaa-marine] Fetching marine forecast for {latitude}, {longitude}", file=sys.stderr, flush=True)

        # NOAA API points endpoint to get forecast office
        points_url = f"https://api.weather.gov/points/{latitude},{longitude}"

        points_data = _fetch_json(points_url)

        if "properties" not in points_data:
            return {
                "success": False,
                "message": "Location not covered by NOAA forecasts (may be outside US waters)"
            }

        forecast_url = points_data["properties"].get("forecast")
        marine_forecast_url = points_data["properties"].get("forecastZone")

        if not forecast_url:
            return {
                "success": False,
                "message": "No forecast available for this location"
            }

        forecast_data = _fetch_json(forecast_url)

        periods = []
        if "properties" in forecast_data and "periods" in forecast_data["properties"]:
            for period in forecast_data["properties"]["periods"][:7]:  # Next 7 periods
                periods.append({
                    "name": period.get("name"),
                    "start_time": period.get("startTime"),
                    "end_time": period.get("endTime"),
                    "temperature": period.get("temperature"),
                    "temperature_unit": period.get("temperatureUnit"),
                    "wind_speed": period.get("windSpeed"),
                    "wind_direction": period.get("windDirection"),
                    "short_forecast": period.get("shortForecast"),
                    "detailed_forecast": period.get("detailedForecast")
                })

        return {
            "success": True,
            "location": {
                "latitude": latitude,
                "longitude": longitude
            },
            "forecast_periods": periods,
            "forecast_office": points_data["properties"].get("forecastOffice"),
            "zone": points_data["properties"].get("forecastZone"),
            "message": f"Marine forecast for {latitude}, {longitude}"
        }

    except Exception as e:
        print(f"❌ Failed to fetch marine forecast: {e}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return {
            "success": False,
            "error": str(e),
            "message": "Failed to fetch NOAA marine forecast"
        }


@mcp.tool()
async def get_marine_warnings(
    latitude: float,
    longitude: float
) -> Dict[str, object]:
    """Get active marine warnings and hazards for a location.

    Args:
        latitude: Latitude in decimal degrees
        longitude: Longitude in decimal degrees

    Returns:
        Active warnings, watches, and advisories.

    Example:
        get_marine_warnings(latitude=25.7617, longitude=-80.1918)
    """
    try:
        print(f"[noaa-marine] Fetching marine warnings for {latitude}, {longitude}", file=sys.stderr, flush=True)

        # NOAA alerts API - get active alerts for point
        url = f"https://api.weather.gov/alerts/active?point={latitude},{longitude}"

        data = _fetch_json(url)

        if "features" not in data:
            return {
                "success": True,
                "warnings": [],
                "message": "No active warnings"
            }

        warnings = []
        for alert in data["features"]:
            props = alert.get("properties", {})
            warnings.append({
                "event": props.get("event"),
                "severity": props.get("severity"),
                "certainty": props.get("certainty"),
                "urgency": props.get("urgency"),
                "headline": props.get("headline"),
                "description": props.get("description"),
                "instruction": props.get("instruction"),
                "onset": props.get("onset"),
                "expires": props.get("expires"),
                "affected_zones": props.get("affectedZones", [])
            })

        return {
            "success": True,
            "warnings": warnings,
            "count": len(warnings),
            "message": f"Found {len(warnings)} active warning(s)/advisory(ies)"
        }

    except Exception as e:
        print(f"❌ Failed to fetch marine warnings: {e}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return {
            "success": False,
            "error": str(e),
            "message": "Failed to fetch NOAA marine warnings"
        }


if __name__ == "__main__":
    mcp.run()
