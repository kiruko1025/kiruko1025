#!/usr/bin/env python3
"""Render a single profile line from the last recorded local commit location."""
from html import escape
from datetime import datetime, timezone
import hashlib
import json
import math
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


def current_weather(location):
    query = urlencode({"latitude": location["latitude"], "longitude": location["longitude"],
                       "current": "temperature_2m,weather_code,is_day", "temperature_unit": "fahrenheit"})
    request = Request("https://api.open-meteo.com/v1/forecast?" + query,
                      headers={"User-Agent": "github-profile-weather/1.0"})
    with urlopen(request, timeout=15) as response:
        data = json.load(response)
    return data["current"]


def describe_weather(current):
    condition = CONDITIONS.get(current["weather_code"], "unknown conditions")
    if current["weather_code"] in (0, 1) and not current.get("is_day", 1):
        condition = "clear"
    return f"{condition}, {current['temperature_2m']:g}°F"


def weather(location):
    return describe_weather(current_weather(location))


def aqi_category(value):
    if value < 0 or not math.isfinite(value):
        raise ValueError("Invalid air quality index")
    for limit, label in ((50, "good"), (100, "moderate"), (150, "unhealthy for sensitive groups"),
                         (200, "unhealthy"), (300, "very unhealthy")):
        if value <= limit:
            return label
    return "hazardous"


def air_quality(location):
    query = urlencode({"latitude": location["latitude"], "longitude": location["longitude"], "current": "us_aqi"})
    request = Request("https://air-quality-api.open-meteo.com/v1/air-quality?" + query,
                      headers={"User-Agent": "github-profile-air-quality/1.0"})
    with urlopen(request, timeout=15) as response:
        raw = json.load(response)["current"]["us_aqi"]
    if raw is None or not math.isfinite(float(raw)) or float(raw) < 0:
        raise ValueError("Air quality unavailable")
    value = math.floor(float(raw) + 0.5)
    return f"US AQI {value} · {aqi_category(value)}"


def weather_scene(code, is_day):
    """Draw a small generic skyline, using the same conditions as the weather text."""
    known = code in CONDITIONS and is_day is not None
    day = bool(is_day)
    condition = CONDITIONS.get(code, "weather unavailable")
    if condition == "sunny" and not day:
        condition = "clear"
    label = f"{condition} {'day' if day else 'night'} skyline" if known else "Weather unavailable skyline"
    sky = ("#9ac9df" if day else "#181d36") if known else "#303646"
    cloud = "#f0f3f6" if day else "#7884a8"
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="160" height="50" viewBox="0 0 160 50" role="img" aria-label="{escape(label)}">',
           f'<title>{escape(label)}</title>', '<defs><clipPath id="frame"><rect width="160" height="50" rx="7"/></clipPath></defs>',
           '<g clip-path="url(#frame)">', f'<rect width="160" height="50" fill="{sky}"/>']
    if known:
        if day and code in (0, 1, 2):
            svg += ['<circle cx="130" cy="13" r="8" fill="#ffe4a3"/>',
                    '<circle cx="130" cy="13" r="11" fill="#ffe4a3" opacity=".16"/>']
        elif not day and code in (0, 1, 2):
            for x, y in ((11, 8), (43, 5), (76, 12), (103, 6), (149, 22)):
                svg.append(f'<circle cx="{x}" cy="{y}" r=".7" fill="#e4e8ff"/>')
            svg += ['<circle cx="132" cy="12" r="7" fill="#f8e6b4"/>',
                    f'<circle cx="135" cy="9" r="6" fill="{sky}"/>']
        if code not in (0,):
            for x, y, size in ((27, 13, 1), (92, 9, .8)):
                svg.append(f'<g transform="translate({x} {y}) scale({size})" fill="{cloud}"><rect x="-14" y="0" width="35" height="8" rx="4"/><circle cx="-3" cy="0" r="7"/><circle cx="9" cy="-2" r="9"/></g>')
    # Two layers of buildings; a generic skyline, not a geographic reconstruction.
    for x, y, w in ((0, 32, 15), (18, 25, 18), (39, 30, 11), (53, 22, 20), (77, 29, 18), (99, 24, 13), (116, 31, 22), (143, 26, 18)):
        svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{50-y}" fill="{("#7e99ae" if day and known else "#303c59")}"/>')
    for x, y, w in ((-4, 37, 20), (21, 31, 14), (41, 34, 23), (71, 27, 17), (94, 35, 18), (119, 29, 16), (142, 36, 22)):
        svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{50-y}" fill="{("#3e596f" if day and known else "#11182b")}"/>')
        for wx in range(x + 4, x + w - 2, 6):
            for wy in range(y + 5, 47, 6):
                color = "#f5c97e" if known and not day and (wx + wy) % 3 else "#8eabc1"
                svg.append(f'<rect x="{wx}" y="{wy}" width="2" height="2" fill="{color}" opacity=".75"/>')
    if known and condition in ("raining", "stormy"):
        for x, y in ((14, 25), (38, 22), (61, 28), (85, 23), (109, 29), (146, 30)):
            svg.append(f'<path d="M{x} {y}l-3 6" stroke="#8dd6f9" stroke-width="1.3" stroke-linecap="round"/>')
    if known and condition == "stormy":
        svg.append('<path d="M78 12l-5 10h5l-3 8 12-13h-6l4-5z" fill="#ffdf78"/>')
    if known and condition == "snowing":
        for x, y in ((12, 26), (37, 24), (62, 28), (86, 24), (111, 29), (148, 28)):
            svg.append(f'<path d="M{x-2} {y}h4m-2-2v4" stroke="#eef4ff" stroke-width="1"/>')
    if known and condition == "foggy":
        svg.append('<path d="M5 29h150M13 34h134M2 39h156" stroke="#cbd4df" stroke-width="3" opacity=".55"/>')
    svg += ['<rect y="48" width="160" height="2" fill="#829d89"/>', '</g></svg>']
    return "".join(svg) + "\n", label


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


def profile_line(location, fetch_weather=weather, fetch_listening=listening, now=None,
                 fetch_air_quality=air_quality, scene=None):
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
    if scene:
        parts.append(scene)
    try:
        quality = fetch_air_quality(location) if location.get("recorded_at") else None
        parts.append(f'[{clean(quality)}](https://open-meteo.com/en/docs/air-quality-api "CAMS via Open-Meteo; modeled air quality")' if quality else "air quality unavailable")
    except Exception:
        parts.append("air quality unavailable")
    try:
        music = fetch_listening()
    except Exception:
        music = "♫ listening status unavailable"
    if music:
        parts.append(music)
    return " · ".join(parts) + "\n"


def main():
    location = json.loads((ROOT / "profile-location.json").read_text())
    current = None
    if location.get("recorded_at"):
        try:
            current = current_weather(location)
            describe_weather(current)
        except Exception:
            current = None
    def summary(_):
        if current is None:
            raise ValueError("Weather unavailable")
        return describe_weather(current)
    svg, label = weather_scene(current.get("weather_code") if current else None,
                               current.get("is_day") if current else None)
    version = hashlib.sha256(svg.encode()).hexdigest()[:12]
    image = f'<img src="assets/weather-scene.svg?v={version}" width="128" height="40" alt="{escape(label)}" />'
    output = profile_line(location, fetch_weather=summary, scene=image if "--terminal" not in sys.argv else None)
    if "--terminal" in sys.argv:
        print(output, end="")
    else:
        (ROOT / "assets").mkdir(exist_ok=True)
        (ROOT / "assets/weather-scene.svg").write_text(svg)
        (ROOT / "README.md").write_text(output)


if __name__ == "__main__":
    main()
