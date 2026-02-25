from __future__ import annotations

from typing import Any, Dict, Optional

import httpx

from app.mcp_server.server import mcp

OPEN_METEO_GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
OPEN_METEO_FORECAST = "https://api.open-meteo.com/v1/forecast"

# Shorter timeouts for faster response
HTTP_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


async def _geocode_city(city: str, country: Optional[str]) -> Dict[str, Any]:
    params: Dict[str, Any] = {"name": city, "count": 1, "language": "en", "format": "json"}
    if country:
        params["country"] = country

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        r = await client.get(OPEN_METEO_GEOCODE, params=params)
        r.raise_for_status()
        data = r.json()

    results = data.get("results") or []
    if not results:
        raise ValueError("City not found")

    hit = results[0]
    return {
        "name": hit.get("name"),
        "country": hit.get("country"),
        "admin1": hit.get("admin1"),
        "latitude": hit.get("latitude"),
        "longitude": hit.get("longitude"),
        "timezone": hit.get("timezone"),
    }


async def _fetch_weather(latitude: float, longitude: float) -> Dict[str, Any]:
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": ["temperature_2m", "relative_humidity_2m", "wind_speed_10m"],
        "forecast_days": 1,
    }

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        r = await client.get(OPEN_METEO_FORECAST, params=params)
        r.raise_for_status()
        return r.json()


@mcp.tool
async def weather_get(
    city: Optional[str] = None,
    country: Optional[str] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
) -> Dict[str, Any]:
    resolved: Optional[Dict[str, Any]] = None

    if city and (latitude is None or longitude is None):
        resolved = await _geocode_city(city=city, country=country)
        latitude = float(resolved["latitude"])
        longitude = float(resolved["longitude"])

    if latitude is None or longitude is None:
        raise ValueError("Provide either city (and optional country) or latitude/longitude")

    raw = await _fetch_weather(latitude=float(latitude), longitude=float(longitude))
    current = raw.get("current") or {}

    return {
        "location": resolved or {"latitude": latitude, "longitude": longitude},
        "current": {
            "time": current.get("time"),
            "temperature_2m": current.get("temperature_2m"),
            "relative_humidity_2m": current.get("relative_humidity_2m"),
            "wind_speed_10m": current.get("wind_speed_10m"),
        },
        "raw": raw,
    }
