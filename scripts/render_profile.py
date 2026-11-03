#!/usr/bin/env python3
"""Render a single profile line from the last recorded local commit location."""
from html import escape
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parent.parent
CONDITIONS = {0: "sunny", 1: "sunny", 2: "cloudy", 3: "cloudy", 45: "foggy", 48: "foggy",
              51: "raining", 53: "raining", 55: "raining", 56: "raining", 57: "raining",
              61: "raining", 63: "raining", 65: "raining", 66: "raining", 67: "raining",
              71: "snowing", 73: "snowing", 75: "snowing", 77: "snowing", 80: "raining",
              81: "raining", 82: "raining", 85: "snowing", 86: "snowing",
              95: "stormy", 96: "stormy", 99: "stormy"}


def clean(value):
    return escape(" ".join(str(value).replace("`", "'").split()))


def markdown_text(value):
    return re.sub(r"([\\\[\]*_~|])", r"\\\1", clean(value))


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


def listening():
    client = os.environ.get("SPOTIFY_CLIENT_ID")
    refresh = os.environ.get("SPOTIFY_REFRESH_TOKEN")
    if not client or not refresh:
        return None
    payload = urlencode({"grant_type": "refresh_token", "client_id": client, "refresh_token": refresh}).encode()
    request = Request("https://accounts.spotify.com/api/token", data=payload,
                      headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urlopen(request, timeout=15) as response:
        token = json.load(response)["access_token"]
    request = Request("https://api.spotify.com/v1/me/player/currently-playing?additional_types=track,episode",
                      headers={"Authorization": "Bearer " + token})
    with urlopen(request, timeout=15) as response:
        if response.status == 204:
            return "♫ not playing"
        data = json.load(response)
    item = data.get("item")
    if not data.get("is_playing") or not item or (data.get("device") or {}).get("is_private_session"):
        return "♫ not playing"
    artists = ", ".join(a["name"] for a in item.get("artists", []))
    if not artists:
        artists = item.get("show", {}).get("name", "")
    label = markdown_text(item["name"] + (" — " + artists if artists else ""))
    url = item.get("external_urls", {}).get("spotify", "")
    if re.fullmatch(r"https://open\.spotify\.com/(track|episode)/[A-Za-z0-9]+", url):
        return f"♫ [{label}]({url})"
    return "♫ " + label


def profile_line(location, fetch_weather=weather, fetch_listening=listening, now=None):
    if location.get("recorded_at"):
        place = ", ".join(clean(location[k]) for k in ("city", "region", "country") if location.get(k))
        ip = clean(location["ip"])
        try:
            conditions = f"[{clean(fetch_weather(location))}](https://open-meteo.com/)"
        except Exception:
            conditions = "weather unavailable"
    else:
        place, ip, conditions = "location unavailable", "IP unavailable", "weather unavailable"
    clock = "local time unavailable"
    if location.get("timezone"):
        try:
            local = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(location["timezone"]))
            clock = local.strftime("%I:%M %p %Z").lstrip("0")
        except (ZoneInfoNotFoundError, ValueError):
            pass
    parts = [f"{place} ({ip})", clock, conditions]
    try:
        music = fetch_listening()
    except Exception:
        music = "♫ listening status unavailable"
    if music:
        parts.append(music)
    return " · ".join(parts) + "\n"


def main():
    location = json.loads((ROOT / "profile-location.json").read_text())
    output = profile_line(location)
    if "--terminal" in sys.argv:
        print(output, end="")
    else:
        (ROOT / "README.md").write_text(output)


if __name__ == "__main__":
    main()
