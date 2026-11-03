#!/usr/bin/env python3
"""Authorize Spotify with PKCE, saving credentials directly into Actions secrets."""
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import secrets
import subprocess
import sys
import time
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

REPO = "kiruko1025/kiruko1025"
REDIRECT = "http://127.0.0.1:8888/callback"


def connect(client_id):
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    result = {}

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            url = urlsplit(self.path)
            params = parse_qs(url.query)
            valid = url.path == "/callback" and secrets.compare_digest(params.get("state", [""])[0], state)
            if valid:
                result["code"] = params.get("code", [None])[0]
                result["error"] = params.get("error", [None])[0]
            self.send_response(200 if valid else 400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(b"Spotify authorization received. You may return to Codex." if valid else b"Invalid callback.")

    params = {"client_id": client_id, "response_type": "code", "redirect_uri": REDIRECT,
              "scope": "user-read-currently-playing", "state": state,
              "code_challenge_method": "S256", "code_challenge": challenge}
    with HTTPServer(("127.0.0.1", 8888), Callback) as server:
        server.timeout = 1
        print("Authorize Spotify: https://accounts.spotify.com/authorize?" + urlencode(params), flush=True)
        deadline = time.monotonic() + 600
        while not result and time.monotonic() < deadline:
            server.handle_request()
    if not result.get("code"):
        raise RuntimeError("Spotify authorization was declined or timed out; rerun to reconnect.")
    payload = urlencode({"grant_type": "authorization_code", "code": result["code"], "redirect_uri": REDIRECT,
                         "client_id": client_id, "code_verifier": verifier}).encode()
    request = Request("https://accounts.spotify.com/api/token", data=payload,
                      headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urlopen(request, timeout=20) as response:
        token = json.load(response)["refresh_token"]
    for name, value in (("SPOTIFY_REFRESH_TOKEN", token), ("SPOTIFY_CLIENT_ID", client_id)):
        subprocess.run(["gh", "secret", "set", name, "--repo", REPO], input=value, text=True,
                       capture_output=True, check=True, timeout=30)
    print("Spotify connected. Credentials saved to GitHub Actions secrets; no token was printed.", flush=True)
    subprocess.run(["gh", "workflow", "run", "setup.yml", "--repo", REPO], check=True, timeout=30)


if __name__ == "__main__":
    try:
        if len(sys.argv) != 2:
            raise RuntimeError("Usage: python3 scripts/connect_spotify.py YOUR_CLIENT_ID")
        connect(sys.argv[1])
    except Exception:
        print("Spotify connection could not be completed. Check the redirect URI, app access and GitHub CLI login.", file=sys.stderr)
        sys.exit(1)
