from __future__ import annotations

import logging
import threading
from datetime import datetime

import requests

from config import Settings

log = logging.getLogger(__name__)
API_URL = "https://api.open-meteo.com/v1/forecast"
_cache: dict = {}
_lock = threading.Lock()

WEATHER_TEXT = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Freezing fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle", 56: "Freezing drizzle", 57: "Freezing drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain", 66: "Freezing rain", 67: "Freezing rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains", 80: "Rain showers",
    81: "Rain showers", 82: "Violent rain showers", 85: "Snow showers", 86: "Snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Thunderstorm with hail",
}


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def get_weather(settings: Settings, now: datetime, session=None) -> dict:
    """Current conditions from Open-Meteo. Real data only: on any failure the answer says so."""
    if not settings.weather_enabled:
        return {"ok": False, "enabled": False, "error": "Weather panel is turned off."}
    key = (settings.weather_lat, settings.weather_lon)
    with _lock:
        cached = _cache.get(key)
    if cached and (now - cached["fetched"]).total_seconds() < settings.weather_cache_minutes * 60:
        return cached["data"]
    params = {"latitude": settings.weather_lat, "longitude": settings.weather_lon, "timezone": "auto",
              "current": "temperature_2m,precipitation,wind_speed_10m,weather_code"}
    try:
        response = (session or requests).get(API_URL, params=params, timeout=settings.request_timeout,
                                              headers={"User-Agent": settings.user_agent})
        response.raise_for_status()
        current = response.json()["current"]
        data = {
            "ok": True, "enabled": True, "label": settings.weather_label,
            "temperature_c": current["temperature_2m"], "precipitation_mm": current["precipitation"],
            "wind_kmh": current["wind_speed_10m"],
            "summary": WEATHER_TEXT.get(int(current["weather_code"]), "Conditions unavailable"),
            "observed_local": current.get("time"),
            "credit": "Weather data by Open-Meteo.com", "credit_url": "https://open-meteo.com/",
        }
    except (requests.RequestException, KeyError, ValueError, TypeError) as exc:
        log.warning("Weather lookup failed: %s", type(exc).__name__)
        return {"ok": False, "enabled": True, "error": "Weather is unavailable right now."}
    with _lock:
        _cache[key] = {"fetched": now, "data": data}
    return data
