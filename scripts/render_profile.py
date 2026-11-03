#!/usr/bin/env python3
"""Render the terminal header using the last location recorded on a local device."""
from datetime import datetime
import json
from pathlib import Path
import sys
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
CONDITIONS = {0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Rime fog",
              51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle", 56: "Freezing drizzle", 57: "Freezing drizzle",
              61: "Light rain", 63: "Rain", 65: "Heavy rain", 66: "Freezing rain", 67: "Freezing rain",
              71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains", 80: "Light showers",
              81: "Showers", 82: "Heavy showers", 85: "Snow showers", 86: "Heavy snow showers",
              95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Thunderstorm with hail"}


def clean(value):
    # Keep remote text inside a single terminal line and its Markdown code fence.
    return " ".join(str(value).replace("`", "'").split())


def weather(location):
    query = urlencode({"latitude": location["latitude"], "longitude": location["longitude"],
                       "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
                       "temperature_unit": "fahrenheit", "wind_speed_unit": "mph", "timezone": "auto"})
    request = Request("https://api.open-meteo.com/v1/forecast?" + query,
                      headers={"User-Agent": "github-profile-weather/1.0"})
    with urlopen(request, timeout=15) as response:
        data = json.load(response)
    current = data["current"]
    condition = CONDITIONS.get(current["weather_code"], "Unknown conditions")
    return (f"{condition}, {current['temperature_2m']:g}°F (feels {current['apparent_temperature']:g}°F), "
            f"wind {current['wind_speed_10m']:g} mph\n"
            f"Weather as of {clean(current['time'])} ({clean(data['timezone'])})")


def terminal(location, fetch_weather=weather):
    lines = ['echo "hello world, im $(whoami)."', 'hello world, im everett.', '', '$ profile --last-commit']
    if location.get("recorded_at"):
        local = datetime.fromisoformat(location["recorded_at"]).astimezone(ZoneInfo(location.get("timezone", "UTC")))
        lines += ["Last local commit: " + local.strftime("%a, %d %b %Y at %H:%M:%S %Z"),
                  "Location: " + ", ".join(clean(location[k]) for k in ("city", "region", "country") if location.get(k)),
                  "Public IP: " + clean(location["ip"]), '', '$ weather --local']
        try:
            lines.append(fetch_weather(location))
        except Exception:
            lines.append("Weather temporarily unavailable; last commit location is unchanged.")
    else:
        lines += ["Waiting for the first commit from a computer with the location hook installed.", '',
                  '$ weather --local', 'Waiting for a recorded location.']
    lines += ['', '$ do one thing and do it well. ^U^D', '']
    return "\n".join(lines) + "\n"


def main():
    location = json.loads((ROOT / "profile-location.json").read_text())
    output = terminal(location)
    if "--terminal" in sys.argv:
        print(output, end="")
    else:
        attribution = "Location is approximate and reflects the network used for my last local commit. Weather: [Open-Meteo](https://open-meteo.com/).\n\n"
        (ROOT / "README.md").write_text("```bash\n" + output + "```\n\n" + attribution + (ROOT / "static.md").read_text())


if __name__ == "__main__":
    main()
