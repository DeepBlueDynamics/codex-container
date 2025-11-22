#!/usr/bin/env python3
"""
Open-Meteo MCP server exposing weather tools for maritime operations.

Provides geocoding, weather forecasts, marine conditions, and historical weather data.
Useful for Alpha India and Alpha Tango to check conditions for maritime traffic monitoring.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
import json
from urllib import request as _urlrequest
from urllib import parse as _urlparse

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("open-meteo")


def _get(url: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Make HTTP GET request to Open-Meteo API."""
    query = _urlparse.urlencode(params, doseq=True)
    full_url = f"{url}?{query}"
    req = _urlrequest.Request(full_url, headers={"User-Agent": "open-meteo-mcp/1.0"})
    with _urlrequest.urlopen(req, timeout=30) as resp:
        if resp.status < 200 or resp.status >= 300:
            raise RuntimeError(f"HTTP {resp.status} for {full_url}")
        data = resp.read()
        return json.loads(data.decode("utf-8"))


def _csv_list(value: Optional[str | List[str]], default: str) -> str:
    """Convert list or string to CSV string."""
    if value is None:
        return default
    if isinstance(value, str):
        return value
    return ",".join(value)


@mcp.tool()
async def weather_geocode(name: str, count: int = 1) -> Dict[str, Any]:
    """Get coordinates for a location name.

    Use this to find latitude/longitude for weather queries.

    Args:
        name: Location name (city, port, region)
        count: Number of results to return (default: 1)

    Returns:
        Dictionary with geocoding results including lat/lon coordinates.

    Example:
        weather_geocode(name="Port of Miami")
        weather_geocode(name="Cozumel", count=3)
    """
    try:
        url = "https://geocoding-api.open-meteo.com/v1/search"
        data = _get(url, {"name": name, "count": count})
        return {
            "success": True,
            "query": name,
            "count": len(data.get("results", []) or []),
            "results": data.get("results", [])
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def weather_forecast(
    latitude: float,
    longitude: float,
    hourly: Optional[List[str] | str] = None,
    daily: Optional[List[str] | str] = None,
    current_weather: bool = True,
    wind_speed_unit: str = "kn",
    timezone: str = "auto",
    forecast_days: int = 7,
) -> Dict[str, Any]:
    """Get weather forecast for maritime operations.

    Args:
        latitude: Latitude in decimal degrees
        longitude: Longitude in decimal degrees
        hourly: Hourly variables to include (default: wind metrics)
        daily: Daily variables to include (optional)
        current_weather: Include current conditions (default: True)
        wind_speed_unit: Unit for wind speed - "kn" for knots (default), "ms", "kmh", "mph"
        timezone: Timezone (default: "auto" uses location timezone)
        forecast_days: Number of days to forecast (1-16, default: 7)

    Returns:
        Dictionary with weather forecast data.

    Example:
        weather_forecast(latitude=25.7617, longitude=-80.1918)  # Miami
        weather_forecast(latitude=20.5, longitude=-86.95, wind_speed_unit="kn", forecast_days=3)  # Cozumel
    """
    try:
        url = "https://api.open-meteo.com/v1/forecast"
        hourly_default = "wind_speed_10m,wind_direction_10m,wind_gusts_10m"
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": _csv_list(hourly, hourly_default),
            "timezone": timezone,
            "current_weather": str(current_weather).lower(),
            "wind_speed_unit": wind_speed_unit,
            "forecast_days": forecast_days,
        }
        if daily:
            params["daily"] = _csv_list(daily, "")
        data = _get(url, params)
        return {"success": True, "params": params, "data": data}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def weather_marine(
    latitude: float,
    longitude: float,
    hourly: Optional[List[str] | str] = None,
    timezone: str = "auto",
    forecast_days: int = 7,
) -> Dict[str, Any]:
    """Get marine weather conditions (waves, swells, etc).

    Essential for maritime operations - provides wave heights, swell direction, periods.

    Args:
        latitude: Latitude in decimal degrees
        longitude: Longitude in decimal degrees
        hourly: Hourly marine variables (default: wave and swell metrics)
        timezone: Timezone (default: "auto")
        forecast_days: Number of days to forecast (1-7, default: 7)

    Returns:
        Dictionary with marine forecast data.

    Example:
        weather_marine(latitude=25.7617, longitude=-80.1918)  # Miami waters
        weather_marine(latitude=20.5, longitude=-86.95, forecast_days=3)  # Cozumel
    """
    try:
        url = "https://marine-api.open-meteo.com/v1/marine"
        hourly_default = "wave_height,wind_wave_height,wind_wave_direction,swell_wave_height,swell_wave_direction,swell_wave_period"
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": _csv_list(hourly, hourly_default),
            "timezone": timezone,
            "forecast_days": forecast_days,
        }
        data = _get(url, params)
        return {"success": True, "params": params, "data": data}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def weather_archive(
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
    hourly: Optional[List[str] | str] = None,
    wind_speed_unit: str = "kn",
    timezone: str = "auto",
) -> Dict[str, Any]:
    """Get historical weather data for maritime route analysis.

    Args:
        latitude: Latitude in decimal degrees
        longitude: Longitude in decimal degrees
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        hourly: Hourly variables to include (default: wind metrics)
        wind_speed_unit: Unit for wind speed - "kn" for knots (default), "ms", "kmh", "mph"
        timezone: Timezone (default: "auto")

    Returns:
        Dictionary with historical weather data.

    Example:
        weather_archive(latitude=25.7617, longitude=-80.1918,
                       start_date="2025-10-01", end_date="2025-10-15")
    """
    try:
        url = "https://archive-api.open-meteo.com/v1/archive"
        hourly_default = "wind_speed_10m,wind_direction_10m,wind_gusts_10m"
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "start_date": start_date,
            "end_date": end_date,
            "hourly": _csv_list(hourly, hourly_default),
            "timezone": timezone,
            "wind_speed_unit": wind_speed_unit,
        }
        data = _get(url, params)
        return {"success": True, "params": params, "data": data}
    except Exception as e:
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    mcp.run()
