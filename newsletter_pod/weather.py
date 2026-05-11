from __future__ import annotations

from datetime import date
from typing import Optional

import requests

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# Open-Meteo "weather_code" → short human label. Subset is fine; unknown codes
# fall back to "mixed conditions".
_WEATHER_CODE_LABELS: dict[int, str] = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "foggy",
    48: "freezing fog",
    51: "light drizzle",
    53: "drizzle",
    55: "heavy drizzle",
    61: "light rain",
    63: "rain",
    65: "heavy rain",
    71: "light snow",
    73: "snow",
    75: "heavy snow",
    80: "rain showers",
    81: "heavy showers",
    82: "violent showers",
    95: "thunderstorms",
    96: "thunderstorms with hail",
    99: "thunderstorms with hail",
}


# Process-local cache, keyed by (location, date). Avoids refetching when many
# users in the same city run in the same dispatch sweep.
_cache: dict[tuple[str, date], Optional[str]] = {}


def fetch_weather_summary(
    location: str,
    *,
    today: Optional[date] = None,
    timeout_seconds: float = 2.0,
) -> Optional[str]:
    """Return a one-line weather summary for ``location``, or ``None`` on failure.

    Uses Open-Meteo (no API key). All errors are swallowed — callers should
    treat ``None`` as "skip the weather mention this episode."
    """
    cleaned = (location or "").strip()
    if not cleaned:
        return None

    today = today or date.today()
    cache_key = (cleaned.casefold(), today)
    if cache_key in _cache:
        return _cache[cache_key]

    summary: Optional[str]
    try:
        summary = _fetch(cleaned, timeout_seconds)
    except Exception:
        summary = None

    _cache[cache_key] = summary
    return summary


def _fetch(location: str, timeout_seconds: float) -> Optional[str]:
    geo = requests.get(
        GEOCODE_URL,
        params={"name": location, "count": 1, "language": "en", "format": "json"},
        timeout=timeout_seconds,
    )
    if geo.status_code != 200:
        return None
    geo_data = geo.json() or {}
    results = geo_data.get("results") or []
    if not results:
        return None
    place = results[0]
    lat = place.get("latitude")
    lon = place.get("longitude")
    if lat is None or lon is None:
        return None
    pretty_name = place.get("name") or location

    country_code = str(place.get("country_code") or "").strip().upper()
    use_fahrenheit = country_code == "US"
    unit_param = "fahrenheit" if use_fahrenheit else "celsius"
    unit_symbol = "°F" if use_fahrenheit else "°C"

    forecast = requests.get(
        FORECAST_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,weather_code",
            "daily": "temperature_2m_max,temperature_2m_min",
            "temperature_unit": unit_param,
            "timezone": "auto",
            "forecast_days": 1,
        },
        timeout=timeout_seconds,
    )
    if forecast.status_code != 200:
        return None
    fc = forecast.json() or {}
    current = fc.get("current") or {}
    daily = fc.get("daily") or {}

    temp_now = current.get("temperature_2m")
    code = current.get("weather_code")
    highs = daily.get("temperature_2m_max") or []
    lows = daily.get("temperature_2m_min") or []
    high = highs[0] if highs else None
    low = lows[0] if lows else None

    condition = _WEATHER_CODE_LABELS.get(int(code), "mixed conditions") if code is not None else None

    parts: list[str] = []
    if temp_now is not None and condition:
        parts.append(f"{round(temp_now)}{unit_symbol} and {condition}")
    elif temp_now is not None:
        parts.append(f"{round(temp_now)}{unit_symbol}")
    elif condition:
        parts.append(condition)
    if high is not None and low is not None:
        parts.append(f"high {round(high)}{unit_symbol}, low {round(low)}{unit_symbol}")
    elif high is not None:
        parts.append(f"high {round(high)}{unit_symbol}")

    if not parts:
        return None
    return f"{pretty_name} — {', '.join(parts)}."


def _reset_cache_for_tests() -> None:
    _cache.clear()
