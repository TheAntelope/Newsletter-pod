from __future__ import annotations

from datetime import date

from newsletter_pod import weather


class FakeResponse:
    def __init__(self, status_code: int = 200, json_data: dict | None = None) -> None:
        self.status_code = status_code
        self._json_data = json_data or {}

    def json(self) -> dict:
        return self._json_data


def _patch_requests(monkeypatch, country_code: str) -> list[dict]:
    weather._reset_cache_for_tests()
    captured: list[dict] = []

    def fake_get(url, params, timeout):
        captured.append({"url": url, "params": params})
        if url == weather.GEOCODE_URL:
            return FakeResponse(
                json_data={
                    "results": [
                        {
                            "name": "Test City",
                            "latitude": 1.0,
                            "longitude": 2.0,
                            "country_code": country_code,
                        }
                    ]
                }
            )
        if url == weather.FORECAST_URL:
            return FakeResponse(
                json_data={
                    "current": {"temperature_2m": 20.0, "weather_code": 2},
                    "daily": {"temperature_2m_max": [25.0], "temperature_2m_min": [15.0]},
                }
            )
        raise AssertionError(url)

    monkeypatch.setattr(weather.requests, "get", fake_get)
    return captured


def test_us_location_returns_fahrenheit(monkeypatch):
    captured = _patch_requests(monkeypatch, country_code="US")

    summary = weather.fetch_weather_summary("Brooklyn", today=date(2026, 5, 11))

    assert summary is not None
    assert "°F" in summary
    assert "°C" not in summary
    forecast_call = next(c for c in captured if c["url"] == weather.FORECAST_URL)
    assert forecast_call["params"]["temperature_unit"] == "fahrenheit"


def test_non_us_location_returns_celsius(monkeypatch):
    captured = _patch_requests(monkeypatch, country_code="DE")

    summary = weather.fetch_weather_summary("Berlin", today=date(2026, 5, 11))

    assert summary is not None
    assert "°C" in summary
    assert "°F" not in summary
    forecast_call = next(c for c in captured if c["url"] == weather.FORECAST_URL)
    assert forecast_call["params"]["temperature_unit"] == "celsius"


def test_missing_country_code_defaults_to_celsius(monkeypatch):
    captured = _patch_requests(monkeypatch, country_code="")

    summary = weather.fetch_weather_summary("Mystery", today=date(2026, 5, 11))

    assert summary is not None
    assert "°C" in summary
    forecast_call = next(c for c in captured if c["url"] == weather.FORECAST_URL)
    assert forecast_call["params"]["temperature_unit"] == "celsius"
