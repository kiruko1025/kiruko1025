#!/usr/bin/env python3
"""Render a single profile line from the last recorded local commit location."""
from html import escape
import json
from pathlib import Path
import sys
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
CONDITIONS = {0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Rime fog",
              51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle", 56: "Freezing drizzle", 57: "Freezing drizzle",
              61: "Light rain", 63: "Rain", 65: "Heavy rain", 66: "Freezing rain", 67: "Freezing rain",
              71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains", 80: "Light showers",
              81: "Showers", 82: "Heavy showers", 85: "Snow showers", 86: "Heavy snow showers",
              95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Thunderstorm with hail"}


def clean(value):
    return escape(" ".join(str(value).replace("`", "'").split()))


def weather(location):
    query = urlencode({"latitude": location["latitude"], "longitude": location["longitude"],
                       "current": "temperature_2m,weather_code", "temperature_unit": "fahrenheit"})
    request = Request("https://api.open-meteo.com/v1/forecast?" + query,
                      headers={"User-Agent": "github-profile-weather/1.0"})
    with urlopen(request, timeout=15) as response:
        data = json.load(response)
    current = data["current"]
    condition = CONDITIONS.get(current["weather_code"], "Unknown conditions")
    return f"{condition}, {current['temperature_2m']:g}°F"


def profile_line(location, fetch_weather=weather):
    if location.get("recorded_at"):
        place = ", ".join(clean(location[k]) for k in ("city", "region", "country") if location.get(k))
        ip = clean(location["ip"])
        try:
            conditions = f"[{clean(fetch_weather(location))}](https://open-meteo.com/)"
        except Exception:
            conditions = "weather unavailable"
    else:
        place, ip, conditions = "an unknown location", "IP unavailable", "weather unavailable"
    return f"Everett is at {place} ({ip}) — {conditions}.\n"


def main():
    location = json.loads((ROOT / "profile-location.json").read_text())
    output = profile_line(location)
    if "--terminal" in sys.argv:
        print(output, end="")
    else:
        (ROOT / "README.md").write_text(output)


if __name__ == "__main__":
    main()
