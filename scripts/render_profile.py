#!/usr/bin/env python3
"""Render a single profile line from the last recorded local commit location."""
from html import escape
import json
from pathlib import Path
import sys
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
CONDITIONS = {0: "sunny", 1: "sunny", 2: "cloudy", 3: "cloudy", 45: "foggy", 48: "foggy",
              51: "raining", 53: "raining", 55: "raining", 56: "raining", 57: "raining",
              61: "raining", 63: "raining", 65: "raining", 66: "raining", 67: "raining",
              71: "snowing", 73: "snowing", 75: "snowing", 77: "snowing", 80: "raining",
              81: "raining", 82: "raining", 85: "snowing", 86: "snowing",
              95: "stormy", 96: "stormy", 99: "stormy"}


def clean(value):
    return escape(" ".join(str(value).replace("`", "'").split()))


def weather(location):
    query = urlencode({"latitude": location["latitude"], "longitude": location["longitude"],
                       "current": "temperature_2m,weather_code,is_day", "temperature_unit": "fahrenheit"})
    request = Request("https://api.open-meteo.com/v1/forecast?" + query,
                      headers={"User-Agent": "github-profile-weather/1.0"})
    with urlopen(request, timeout=15) as response:
        data = json.load(response)
    current = data["current"]
    condition = CONDITIONS.get(current["weather_code"], "unknown conditions")
    if current["weather_code"] in (0, 1) and not current.get("is_day", 1):
        condition = "clear"
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
