"""Weather at posting time, from Open-Meteo (free, no API key).

The point is not the forecast itself but the *situation*: a foggy 14°C morning in
Dhaka reads very differently from a dry 26°C noon, and the hook is written for
whichever one the reader is living in. Everything here is best-effort: a dead
request returns ``None`` and the pipeline falls back to season-only context.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Sequence

import requests

ENDPOINT = "https://api.open-meteo.com/v1/forecast"
HOURLY = (
    "temperature_2m",
    "apparent_temperature",
    "relative_humidity_2m",
    "precipitation",
    "weather_code",
    "wind_speed_10m",
)

# WMO weather codes -> human words. Only the groups we care about.
FOG_CODES = {45, 48}
DRIZZLE_CODES = {51, 53, 55, 56, 57}
RAIN_CODES = {61, 63, 65, 66, 67, 80, 81, 82}
STORM_CODES = {95, 96, 99}
CLOUD_CODES = {1, 2, 3}
CLEAR_CODES = {0}


@dataclass(frozen=True)
class Weather:
    temperature: float
    feels_like: float
    humidity: float
    wind: float
    code: int
    hour: int
    tags: tuple[str, ...]
    summary: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "temperature": round(self.temperature, 1),
            "feels_like": round(self.feels_like, 1),
            "humidity": round(self.humidity),
            "wind": round(self.wind, 1),
            "code": self.code,
            "hour": self.hour,
            "tags": list(self.tags),
            "summary": self.summary,
        }


def classify(temp: float, feels: float, humidity: float, code: int) -> tuple[str, ...]:
    """Turn numbers into a small set of situation tags the writer can use."""
    tags: list[str] = []
    if code in FOG_CODES:
        tags += ["fog", "mist", "morning"]
    if code in DRIZZLE_CODES or code in RAIN_CODES:
        tags += ["rain", "wet", "damp"]
    if code in STORM_CODES:
        tags += ["rain", "storm"]
    if code in CLEAR_CODES:
        tags.append("sunny")
    if code in CLOUD_CODES:
        tags.append("cloudy")

    if feels <= 11:
        tags += ["very-cold", "cold"]
    elif feels <= 16:
        tags += ["cold", "chilly"]
    elif feels <= 21:
        tags += ["cool", "chilly"]
    elif feels <= 27:
        tags.append("mild")
    else:
        tags.append("warm")

    if humidity >= 80:
        tags.append("humid")
    if not tags:
        tags.append("mild")
    return tuple(dict.fromkeys(tags))


def describe(tags: Sequence[str], temp: float, feels: float, code: int) -> str:
    """One short English line for the writer's brief (translated by the writer)."""
    parts: list[str] = []
    if "fog" in tags:
        parts.append("foggy")
    elif "rain" in tags:
        parts.append("rainy")
    elif "sunny" in tags:
        parts.append("clear and sunny")
    elif "cloudy" in tags:
        parts.append("overcast")
    if "very-cold" in tags:
        parts.append("very cold")
    elif "cold" in tags:
        parts.append("cold")
    elif "chilly" in tags:
        parts.append("chilly")
    elif "mild" in tags:
        parts.append("mild")
    else:
        parts.append("warm")
    text = " ".join(parts) or "mild"
    return f"{text}, around {round(feels)}C (feels like)"


def fetch(
    latitude: float,
    longitude: float,
    day: date,
    hour: int,
    session: requests.Session,
    *,
    timezone_name: str = "Asia/Dhaka",
    timeout: int = 15,
) -> Weather | None:
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": ",".join(HOURLY),
        "timezone": timezone_name,
        "start_date": day.isoformat(),
        "end_date": day.isoformat(),
    }
    try:
        response = session.get(ENDPOINT, params=params, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        return None

    hourly = payload.get("hourly") or {}
    times: list[str] = hourly.get("time") or []
    if not times:
        return None

    index = None
    target = f"{day.isoformat()}T{hour:02d}:00"
    for position, stamp in enumerate(times):
        if stamp.startswith(target):
            index = position
            break
    if index is None:
        index = min(hour, len(times) - 1)

    def value(name: str, default: float = 0.0) -> float:
        series = hourly.get(name) or []
        if index < len(series) and series[index] is not None:
            return float(series[index])
        return default

    temp = value("temperature_2m")
    feels = value("apparent_temperature", temp)
    humidity = value("relative_humidity_2m")
    wind = value("wind_speed_10m")
    code = int(value("weather_code"))
    tags = classify(temp, feels, humidity, code)
    return Weather(
        temperature=temp,
        feels_like=feels,
        humidity=humidity,
        wind=wind,
        code=code,
        hour=hour,
        tags=tags,
        summary=describe(tags, temp, feels, code),
    )
