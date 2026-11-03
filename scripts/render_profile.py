#!/usr/bin/env python3
"""Render profile status and a colorful ASCII skyline for the recorded location."""
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
                       "current": "temperature_2m,weather_code,is_day", "temperature_unit": "fahrenheit",
                       "daily": "sunrise,sunset", "timezone": location.get("timezone", "auto"), "forecast_days": 1})
    request = Request("https://api.open-meteo.com/v1/forecast?" + query,
                      headers={"User-Agent": "github-profile-weather/1.0"})
    with urlopen(request, timeout=15) as response:
        data = json.load(response)
    current = data["current"]
    daily = data.get("daily", {})
    current["sunrise"] = (daily.get("sunrise") or [None])[0]
    current["sunset"] = (daily.get("sunset") or [None])[0]
    return current


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


def skyline_phase(local_now, sunrise=None, sunset=None):
    """Choose the light from local solar times, falling back to local 06:00/18:00."""
    hour = local_now.hour + local_now.minute / 60
    rise, setting = 6.0, 18.0
    try:
        rise_dt, set_dt = datetime.fromisoformat(sunrise), datetime.fromisoformat(sunset)
        if rise_dt.date() == local_now.date() == set_dt.date():
            rise = rise_dt.hour + rise_dt.minute / 60
            setting = set_dt.hour + set_dt.minute / 60
    except (TypeError, ValueError):
        pass
    if rise - .75 <= hour < rise + .75:
        return "dawn"
    if rise + .75 <= hour < setting - .75:
        return "day"
    if setting - .75 <= hour < setting + .75:
        return "dusk"
    return "night"


def weather_scene(code, local_now, sunrise=None, sunset=None):
    """Color a genuine ASCII character grid as a responsive SVG skyline."""
    phase = skyline_phase(local_now, sunrise, sunset)
    palettes = {
        "dawn": dict(top="#202542", bottom="#a36e79", back="#95778f", stars="#efd6e0",
                     buildings=["#eec3aa", "#d2accd", "#9fc5d7", "#f6bd98"],
                     lit=["#fff0bf", "#ffcf86", "#e2e4f5"], dark="#8d8094", water="#9e7f9b"),
        "day": dict(top="#123d5a", bottom="#458c9a", back="#679fae", stars="#c8edf1",
                    buildings=["#9de2e1", "#c2ddff", "#a3bfdc", "#e7d8b3"],
                    lit=["#fff0b4", "#d0f9ff", "#c6d7f9"], dark="#578d9e", water="#6cb2bd"),
        "dusk": dict(top="#282348", bottom="#b85c78", back="#795c85", stars="#f0c9df",
                     buildings=["#f3b6c7", "#c5a8f1", "#9fc9e7", "#ffcb9d"],
                     lit=["#ffde8c", "#ffc2a8", "#f1d1fc"], dark="#866c92", water="#ad7da9"),
        "night": dict(top="#0a1025", bottom="#202b4b", back="#3b4e73", stars="#b7cbf5",
                      buildings=["#72d8d4", "#ab9ee7", "#7fb2f2", "#de9ec6"],
                      lit=["#f3cb84", "#9fe3de", "#ebadd4"], dark="#344568", water="#476c91"),
    }
    p = palettes[phase]
    cols, rows = 132, 36
    grid = [[(" ", p["back"]) for _ in range(cols)] for _ in range(rows)]

    def put(x, y, text, color):
        if 0 <= y < rows:
            for offset, char in enumerate(text):
                if 0 <= x + offset < cols:
                    grid[y][x + offset] = (char, color)

    def art(x, y, lines, color):
        for offset, line in enumerate(lines):
            put(x, y + offset, line, color)

    # The same sky persists between updates; time changes the light and windows.
    if phase in ("night", "dawn", "dusk"):
        for i in range(56 if phase == "night" else 18):
            x, y = (i * 37 + 11) % cols, 2 + (i * 13) % 15
            put(x, y, "+" if i % 9 == 0 else ".", p["stars"])
    hour = local_now.hour + local_now.minute / 60
    if phase == "night":
        art(108, 3, ["  .--.  ", " / .-'  ", "| (     ", " \\ `-.  ", "  `--'  "], "#f6dc9e")
    elif phase == "day":
        sun_x = max(12, min(113, int(18 + (hour - 7) * 9)))
        art(sun_x, 3, ["  \\ | /  ", " -- .-. --", " - ( O ) -", " -- `-' --", "  / | \\  "], "#ffe5a1")
    else:
        art(107 if phase == "dusk" else 11, 10, ["   .---.   ", " .'     '. ", "(   O O   )", " '-------' "], "#ffcb9d")

    condition = CONDITIONS.get(code)
    if code is not None and code != 0:
        for x, y in ((26, 4), (78, 7)):
            art(x, y, ["    .--.    ", " .-(    ).  ", "(___.__)__) "], p["stars"])
    if condition in ("raining", "stormy", "snowing"):
        for i in range(60):
            x, y = (i * 23 + 5) % cols, 9 + (i * 7) % 18
            put(x, y, "*" if condition == "snowing" else "/", p["stars"])
    if condition == "stormy":
        art(89, 10, ["  /_", "   /", "  / "], "#ffe39c")

    def building(x, top, width, color, foreground, seed):
        bottom = 29
        # Spaces occlude the sky and the more distant buildings.
        for y in range(top, bottom + 1):
            put(x, y, " " * width, color)
        put(x, top, "+" + "-" * (width - 2) + "+", color)
        for y in range(top + 1, bottom):
            put(x, y, "|", color)
            put(x + width - 1, y, "|", color)
            for column in range(x + 2, x + width - 2, 4):
                if (y - top) % 3 == 2:
                    sample = (column * 7 + y * 11 + seed + local_now.hour) % 10
                    lit = foreground and sample < (7 if phase == "night" else 5 if phase in ("dawn", "dusk") else 2)
                    put(column, y, "[]" if foreground else "::",
                        p["lit"][(column + y) % 3] if lit else p["dark"] if foreground else color)
        put(x, bottom, "+" + "-" * (width - 2) + "+", color)

    # Distant towers sit behind a varied, continuous foreground silhouette.
    for i, (x, top, width) in enumerate(((0, 19, 9), (10, 16, 8), (22, 13, 9), (34, 17, 11),
                                        (48, 12, 10), (62, 16, 8), (74, 13, 12), (91, 17, 10),
                                        (104, 12, 8), (116, 18, 9), (126, 15, 6))):
        building(x, top, width, p["back"], False, i)
    towers = [(0, 24, 12), (14, 20, 10), (26, 17, 13), (41, 23, 11), (54, 11, 12),
              (68, 20, 11), (81, 16, 13), (96, 22, 12), (110, 19, 9), (121, 24, 11)]
    for i, (x, top, width) in enumerate(towers):
        color = p["buildings"][i % 4]
        building(x, top, width, color, True, i * 17)
        if i in (2, 6, 8):
            put(x + width // 2, top - 2, "|", color)
            put(x + width // 2 - 2, top - 1, "_|||_", color)
        if i == 4:
            art(x + 3, top - 6, ["   +   ", "   |   ", "  /|\\  ", " /_|_\\ ", " |:::| ", "_|___|_"], color)
            put(x + 4, top + 2, "(o)", p["lit"][0])
        if i in (1, 5, 7):
            put(x + 2, top - 1, "_" * (width - 4), color)

    if condition == "foggy":
        for y in (22, 26):
            for x in range(0, cols, 17):
                put(x, y, "~ ~ ~ ~", p["stars"])
    put(0, 30, "=" * cols, p["back"])
    # Broken reflections pick up the actual window colors above the waterfront.
    for y in range(32, 35):
        for x in range(cols):
            _, color = grid[29 - (y - 31) * 2][x]
            if (x * 3 + y * 5) % 11 < 4:
                put(x, y, "~" if (x + y) % 3 == 0 else ".", color if color in p["lit"] else p["water"])
    label = f"Colorful ASCII skyline at {phase}, {local_now.strftime('%I:%M %p %Z').lstrip('0')}"
    if condition:
        label += f", {'clear' if condition == 'sunny' and phase == 'night' else condition}"
    width, height = 1088, 464
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(label)}">',
           f'<title>{escape(label)}</title>',
           '<defs><linearGradient id="sky" x2="0" y2="1">',
           f'<stop stop-color="{p["top"]}"/><stop offset="1" stop-color="{p["bottom"]}"/>',
           '</linearGradient></defs>',
           f'<rect width="{width}" height="{height}" rx="12" fill="url(#sky)"/>',
           '<g font-family="DejaVu Sans Mono,Consolas,monospace" font-size="13" font-weight="600" xml:space="preserve">']
    for row, cells in enumerate(grid):
        start = 0
        while start < cols:
            color = cells[start][1]
            end = start + 1
            while end < cols and cells[end][1] == color:
                end += 1
            text = "".join(char for char, _ in cells[start:end])
            if text.strip():
                svg.append(f'<text x="{16+start*8}" y="{20+row*12}" fill="{color}" textLength="{len(text)*8}" lengthAdjust="spacingAndGlyphs">{escape(text)}</text>')
            start = end
    svg += ['</g>', f'<text x="1070" y="450" text-anchor="end" font-family="monospace" font-size="9" letter-spacing="3" fill="{p["stars"]}" opacity=".7">{phase.upper()}</text>', '</svg>']
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
                 fetch_air_quality=air_quality):
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
    now = datetime.now(timezone.utc)
    try:
        local_now = now.astimezone(ZoneInfo(location.get("timezone", "UTC")))
    except (ZoneInfoNotFoundError, ValueError):
        local_now = now
    svg, label = weather_scene(current.get("weather_code") if current else None, local_now,
                               current.get("sunrise") if current else None,
                               current.get("sunset") if current else None)
    version = hashlib.sha256(svg.encode()).hexdigest()[:12]
    image = f'<img src="assets/weather-scene.svg?v={version}" width="100%" alt="{escape(label)}" />'
    output = profile_line(location, fetch_weather=summary, now=now)
    if "--terminal" in sys.argv:
        print(output, end="")
    else:
        (ROOT / "assets").mkdir(exist_ok=True)
        (ROOT / "assets/weather-scene.svg").write_text(svg)
        (ROOT / "README.md").write_text(output + "\n" + image + "\n")


if __name__ == "__main__":
    main()
