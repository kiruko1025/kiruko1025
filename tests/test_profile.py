import base64
from datetime import datetime
from contextlib import contextmanager
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from xml.etree import ElementTree
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


hook = module("profile_hook")
render = module("render_profile")
GEO = {"ip": "8.8.8.8", "city": "Example City", "region_code": "CA", "country": "US",
       "latitude": 37.12345, "longitude": -122.12345, "timezone": "America/Los_Angeles"}
TIME = "2026-11-03T01:00:00.000000+00:00"


def http_json(data):
    response = io.StringIO(json.dumps(data))
    response.status = 200
    return response


class ProfileTests(unittest.TestCase):
    def test_location_whitelist(self):
        record = hook.location_record(dict(GEO, postal="secret", org="private"), TIME)
        self.assertEqual(record["latitude"], 37.12)
        self.assertNotIn("postal", record)
        self.assertNotIn("org", record)
        with self.assertRaises(ValueError):
            hook.location_record(dict(GEO, ip="127.0.0.1"), TIME)
        with self.assertRaises(ValueError):
            hook.location_record(dict(GEO, error=True), TIME)

    def test_single_line_and_weather_failure(self):
        location = hook.location_record(GEO, TIME)
        def unavailable(_):
            raise TimeoutError()
        result = render.profile_line(location, unavailable, lambda: None, datetime.fromisoformat(TIME), fetch_air_quality=lambda _: None)
        self.assertEqual(result, "Example City, CA, US (8.8.8.8) · 5:00 PM PST · weather unavailable · air quality unavailable\n")
        self.assertEqual(len(result.splitlines()), 1)
        self.assertEqual(render.profile_line({}, fetch_listening=lambda: None), "location unavailable (IP unavailable) · local time unavailable · weather unavailable · air quality unavailable\n")

    def test_local_time_dst_and_music_failure(self):
        location = dict(hook.location_record(GEO, TIME), timezone="America/Detroit")
        def unavailable():
            raise TimeoutError()
        result = render.profile_line(location, lambda _: "cloudy, 56°F", unavailable, datetime.fromisoformat(TIME), fetch_air_quality=lambda _: None)
        self.assertIn("8:00 PM EST", result)
        self.assertIn("listening status unavailable", result)
        self.assertEqual(len(result.splitlines()), 1)

    def test_aqi_category_boundaries(self):
        for value, category in ((0, "good"), (50, "good"), (51, "moderate"), (100, "moderate"),
                                (101, "unhealthy for sensitive groups"), (150, "unhealthy for sensitive groups"),
                                (151, "unhealthy"), (200, "unhealthy"), (201, "very unhealthy"),
                                (300, "very unhealthy"), (301, "hazardous"), (501, "hazardous")):
            self.assertEqual(render.aqi_category(value), category)
        for value in (-1, float("nan"), float("inf")):
            with self.assertRaises(ValueError): render.aqi_category(value)

    def test_aqi_api_missing_and_rounding(self):
        location = hook.location_record(GEO, TIME)
        with patch.object(render, "urlopen", return_value=http_json({"current": {"us_aqi": 50.6}})) as api:
            self.assertEqual(render.air_quality(location), "US AQI 51 · moderate")
        self.assertIn("current=us_aqi", api.call_args.args[0].full_url)
        for value in (None, -1, float("nan")):
            with patch.object(render, "urlopen", return_value=http_json({"current": {"us_aqi": value}})):
                with self.assertRaises(ValueError): render.air_quality(location)

    def test_scenes_are_valid_and_change_with_weather_and_daylight(self):
        images = set()
        for code in (0, 2, 3, 45, 61, 73, 95, None):
            for hour in (6, 12, 18, 22):
                local_now = datetime.fromisoformat(TIME).replace(hour=hour, minute=0)
                svg, label = render.weather_scene(code, local_now)
                root = ElementTree.fromstring(svg)
                self.assertEqual(root.attrib["viewBox"], "0 0 1088 464")
                self.assertEqual(root.find("{http://www.w3.org/2000/svg}title").text, label)
                self.assertGreater(len(root.findall(".//{http://www.w3.org/2000/svg}text")), 100)
                self.assertNotIn("<script", svg)
                self.assertNotIn("href=", svg)
                images.add(svg)
        self.assertGreaterEqual(len(images), 14)
        for hour, minute, phase in ((6, 30, "dawn"), (8, 0, "day"), (17, 0, "dusk"), (19, 0, "night")):
            local_now = datetime.fromisoformat(TIME).replace(hour=hour, minute=minute)
            self.assertEqual(render.skyline_phase(local_now, "2026-11-03T07:15", "2026-11-03T17:25"), phase)
        night = datetime.fromisoformat(TIME).replace(hour=22)
        self.assertIn("night", render.weather_scene(None, night)[1])

    def test_spotify_unconfigured_avoids_requests(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(render, "urlopen") as api:
            self.assertIsNone(render.listening())
            api.assert_not_called()

    def test_spotify_track_and_safe_markdown(self):
        data = {"is_playing": True, "item": {"name": "Song [test]\nTitle", "artists": [{"name": "Artist"}],
                "external_urls": {"spotify": "https://open.spotify.com/track/abc123"}}}
        with patch.dict(os.environ, {"SPOTIFY_CLIENT_ID": "client", "SPOTIFY_REFRESH_TOKEN": "private"}), \
             patch.object(render, "urlopen", side_effect=[io.StringIO('{"access_token":"access"}'), http_json(data)]) as api:
            result = render.listening()
        self.assertEqual(result, "♫ [Song \\[test\\] Title — Artist](https://open.spotify.com/track/abc123)")
        self.assertIn("refresh_token=private", api.call_args_list[0].args[0].data.decode())
        self.assertEqual(api.call_args_list[1].args[0].get_header("Authorization"), "Bearer access")

    def test_spotify_paused_null_and_no_content(self):
        for data in ({"is_playing": False, "item": {"name": "Paused"}}, {"is_playing": True, "item": None}):
            with patch.dict(os.environ, {"SPOTIFY_CLIENT_ID": "client", "SPOTIFY_REFRESH_TOKEN": "private"}), \
                 patch.object(render, "urlopen", side_effect=[io.StringIO('{"access_token":"access"}'), http_json(data)]):
                self.assertEqual(render.listening(), "♫ not playing")
        response = io.StringIO("")
        response.status = 204
        with patch.dict(os.environ, {"SPOTIFY_CLIENT_ID": "client", "SPOTIFY_REFRESH_TOKEN": "private"}), \
             patch.object(render, "urlopen", side_effect=[io.StringIO('{"access_token":"access"}'), response]):
            self.assertEqual(render.listening(), "♫ not playing")

    def test_remote_text_cannot_escape_fence(self):
        self.assertEqual(render.clean("city\n```\n<script>"), "city &#x27;&#x27;&#x27; &lt;script&gt;")

    def test_weather_request_and_render(self):
        response = {"current": {"weather_code": 2, "temperature_2m": 72.5,
                    "apparent_temperature": 71, "wind_speed_10m": 3.5, "time": "2026-11-02T17:00"},
                    "timezone": "America/Los_Angeles"}
        with patch.object(render, "urlopen", return_value=io.StringIO(json.dumps(response))) as api:
            result = render.weather(hook.location_record(GEO, TIME))
        self.assertIn("latitude=37.12", api.call_args.args[0].full_url)
        self.assertIn("cloudy, 72.5°F", result)
        self.assertEqual(result, "cloudy, 72.5°F")

    def test_publish_skips_ci(self):
        with patch.dict(os.environ, {"CI": "true"}), patch.object(hook, "gh") as api:
            hook.publish(TIME)
            api.assert_not_called()

    def test_publish_retries_conflict_and_omits_repo_identity(self):
        calls = []
        def api(*args, payload=None):
            if args == ("user",):
                return {"login": "kiruko1025"}
            if payload is None:
                return {"sha": "sha", "content": base64.b64encode(b"{}").decode()}
            calls.append(payload)
            if len(calls) == 1:
                raise subprocess.CalledProcessError(1, "gh", stderr="HTTP 409")
            return {}
        with patch.dict(os.environ, {}, clear=True), patch.object(hook, "gh", side_effect=api), \
             patch.object(hook, "urlopen", return_value=io.StringIO(json.dumps(GEO))):
            hook.publish(TIME)
        self.assertEqual(len(calls), 2)
        record = json.loads(base64.b64decode(calls[-1]["content"]))
        self.assertEqual(record, hook.location_record(GEO, TIME))

    def test_newer_location_is_not_overwritten(self):
        def api(*args, payload=None):
            if args == ("user",): return {"login": "kiruko1025"}
            self.assertIsNone(payload)
            return {"sha": "sha", "content": base64.b64encode(json.dumps({"recorded_at": "2027-01-01"}).encode()).decode()}
        with patch.dict(os.environ, {}, clear=True), patch.object(hook, "gh", side_effect=api), \
             patch.object(hook, "urlopen", return_value=io.StringIO(json.dumps(GEO))):
            hook.publish(TIME)

    @contextmanager
    def sandbox(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / "bin"
            binary.mkdir()
            gh = binary / "gh"
            gh.write_text('#!/bin/sh\nprintf \'{"login":"kiruko1025"}\\n\'\n')
            gh.chmod(0o755)
            env = dict(os.environ, GIT_CONFIG_GLOBAL=str(root / "gitconfig"), GIT_CONFIG_NOSYSTEM="1",
                       XDG_DATA_HOME=str(root / "data"), PATH=str(binary) + os.pathsep + os.environ["PATH"],
                       PROFILE_LOCATION_SKIP="1")
            # Remove ambient Git variables so the temporary repository is isolated.
            for key in list(env):
                if key.startswith("GIT_") and key not in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM"):
                    del env[key]
            def run(*args, check=True, input=None):
                return subprocess.run(args, env=env, cwd=root, text=True, capture_output=True, check=check, input=input)
            run("git", "init", "--quiet")
            run("git", "config", "user.name", "Test")
            run("git", "config", "user.email", "test@example.invalid")
            yield root, run

    def test_install_preserves_local_hooks_and_uninstall(self):
        with self.sandbox() as (root, run):
            post = root / ".git/hooks/post-commit"
            post.write_text('#!/bin/sh\nprintf post >> hook-log\n')
            post.chmod(0o755)
            run(sys.executable, str(ROOT / "scripts/profile_hook.py"), "install")
            # Repeat install must preserve the original delegation configuration.
            run(sys.executable, str(ROOT / "scripts/profile_hook.py"), "install")
            run("git", "commit", "--allow-empty", "-m", "test")
            self.assertEqual((root / "hook-log").read_text(), "post")
            pre = root / ".git/hooks/pre-commit"
            pre.write_text('#!/bin/sh\nexit 17\n')
            pre.chmod(0o755)
            self.assertNotEqual(run("git", "commit", "--allow-empty", "-m", "blocked", check=False).returncode, 0)
            installed = root / "data/github-profile-location/profile_hook.py"
            run(sys.executable, str(installed), "uninstall")
            self.assertEqual(run("git", "config", "--global", "--get", "core.hooksPath", check=False).returncode, 1)
            self.assertTrue(post.exists())

    def test_install_preserves_global_hook_stdin_arguments_exit(self):
        with self.sandbox() as (root, run):
            old = root / "old hooks"
            old.mkdir()
            pre = old / "pre-push"
            pre.write_text('#!/bin/sh\nprintf "%s" "$1" > argument\ncat > received\nexit 23\n')
            pre.chmod(0o755)
            run("git", "config", "--global", "core.hooksPath", str(old))
            run(sys.executable, str(ROOT / "scripts/profile_hook.py"), "install")
            wrapper = root / "data/github-profile-location/hooks/pre-push"
            result = run(str(wrapper), "origin", "remote", input="refs example\n", check=False)
            self.assertEqual(result.returncode, 23)
            self.assertEqual((root / "argument").read_text(), "origin")
            self.assertEqual((root / "received").read_text(), "refs example\n")
            installed = root / "data/github-profile-location/profile_hook.py"
            run(sys.executable, str(installed), "uninstall")
            self.assertEqual(run("git", "config", "--global", "--get", "core.hooksPath").stdout.strip(), str(old))

    def test_failed_publisher_does_not_break_commit(self):
        with self.sandbox() as (root, run):
            run(sys.executable, str(ROOT / "scripts/profile_hook.py"), "install")
            # Fail authentication before any external request can happen.
            (root / "bin/gh").write_text('#!/bin/sh\nexit 1\n')
            wrapper = root / "data/github-profile-location/hooks/post-commit"
            wrapper.write_text(wrapper.read_text().replace('#!/bin/sh\n', '#!/bin/sh\nunset PROFILE_LOCATION_SKIP CI GITHUB_ACTIONS\n'))
            result = run("git", "commit", "--allow-empty", "-m", "survives")
            self.assertIn("your commit succeeded", result.stderr)
            self.assertEqual(run("git", "log", "-1", "--format=%s").stdout.strip(), "survives")


if __name__ == "__main__":
    unittest.main()
