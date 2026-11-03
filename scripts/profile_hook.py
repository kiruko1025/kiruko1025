#!/usr/bin/env python3
"""Install a global Git hook and publish the location of local commits."""
import base64
from datetime import datetime, timezone
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
from urllib.request import Request, urlopen

REPOSITORY = "kiruko1025/kiruko1025"
HOOKS = "applypatch-msg pre-applypatch post-applypatch pre-commit pre-merge-commit prepare-commit-msg commit-msg post-commit pre-rebase post-checkout post-merge pre-push pre-receive update proc-receive post-receive post-update reference-transaction push-to-checkout pre-auto-gc post-rewrite sendemail-validate fsmonitor-watchman p4-changelist p4-prepare-changelist p4-post-changelist p4-pre-submit post-index-change".split()


def command(*args, check=True, **kwargs):
    return subprocess.run(args, text=True, capture_output=True, check=check, **kwargs)


def gh(*args, payload=None):
    args = ["gh", "api", "--hostname", "github.com", *args]
    if payload is not None:
        args += ["--input", "-"]
    result = command(*args, input=json.dumps(payload) if payload else None, timeout=20)
    return json.loads(result.stdout or "null")


def install():
    if not shutil.which("gh"):
        raise RuntimeError("Install GitHub CLI, then run gh auth login --hostname github.com.")
    if gh("user")["login"] != REPOSITORY.split("/")[0]:
        raise RuntimeError("GitHub CLI must be signed in as kiruko1025 on github.com.")
    root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "github-profile-location"
    root = root.expanduser().resolve()
    hooks = root / "hooks"
    config = root / "config.json"
    old = command("git", "config", "--global", "--get-all", "core.hooksPath", check=False)
    values = old.stdout.splitlines()
    if len(values) > 1:
        raise RuntimeError("Multiple global core.hooksPath values: resolve them before installing.")
    previous = values[0] if values else None
    if previous == str(hooks):
        settings = json.loads(config.read_text())
    else:
        if config.exists():
            raise RuntimeError("An earlier installation exists; uninstall it before reinstalling.")
        settings = {"previous_hooks_path": previous}
    hooks.mkdir(parents=True, exist_ok=True)
    target = root / "profile_hook.py"
    if Path(__file__).resolve() != target:
        shutil.copyfile(__file__, target)
    config.write_text(json.dumps(settings, indent=2) + "\n")
    for name in HOOKS:
        wrapper = hooks / name
        wrapper.write_text("#!/bin/sh\nexec " + shlex.quote(sys.executable) + " " + shlex.quote(str(target)) + " hook " + shlex.quote(name) + ' "$@"\n')
        wrapper.chmod(0o755)
    command("git", "config", "--global", "core.hooksPath", str(hooks))
    print("Installed. Your next local commit will publish its public IP and approximate city.")
    print("Repositories with their own core.hooksPath override the global hook; see SETUP.md.")
    print("Uninstall: " + shlex.quote(sys.executable) + " " + shlex.quote(str(target)) + " uninstall")


def uninstall():
    root = Path(__file__).resolve().parent
    settings = json.loads((root / "config.json").read_text())
    active = command("git", "config", "--global", "--get", "core.hooksPath", check=False).stdout.strip()
    if active != str(root / "hooks"):
        raise RuntimeError("Global hooks path has changed; leaving it untouched.")
    previous = settings["previous_hooks_path"]
    if previous is None:
        command("git", "config", "--global", "--unset-all", "core.hooksPath")
    else:
        command("git", "config", "--global", "core.hooksPath", previous)
    (root / "config.json").unlink()
    print("Restored the previous global hooks configuration.")


def location_record(data, recorded_at):
    if data.get("error"):
        raise ValueError("IP geolocation is temporarily unavailable")
    ip = ipaddress.ip_address(data["ip"])
    if not ip.is_global:
        raise ValueError("Expected a public IP address")
    lat, lon = float(data["latitude"]), float(data["longitude"])
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or not data.get("city"):
        raise ValueError("IP geolocation did not return a valid city")
    return {"ip": str(ip), "city": data["city"], "region": data.get("region_code") or data.get("region", ""),
            "country": data.get("country", ""), "latitude": round(lat, 2), "longitude": round(lon, 2),
            "timezone": data.get("timezone") or "UTC", "recorded_at": recorded_at}


def publish(recorded_at):
    # Never mistake a hosted CI runner's address for the user's address.
    if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS") or os.environ.get("PROFILE_LOCATION_SKIP"):
        return
    if gh("user")["login"] != REPOSITORY.split("/")[0]:
        raise RuntimeError("GitHub CLI is not signed in as kiruko1025")
    request = Request("https://ipapi.co/json/", headers={"User-Agent": "github-profile-location/1.0"})
    with urlopen(request, timeout=10) as response:
        record = location_record(json.load(response), recorded_at)
    endpoint = f"repos/{REPOSITORY}/contents/profile-location.json"
    # The initial file is shipped with the installer; never overwrite newer device updates.
    for attempt in range(3):
        current = gh(endpoint + "?ref=main")
        previous = json.loads(base64.b64decode(current["content"]))
        if previous.get("recorded_at", "") >= recorded_at:
            return
        payload = {"message": "Update location from latest local commit", "branch": "main", "sha": current["sha"],
                   "content": base64.b64encode((json.dumps(record, indent=2) + "\n").encode()).decode()}
        try:
            gh(endpoint, "--method", "PUT", payload=payload)
            return
        except subprocess.CalledProcessError as error:
            if "409" not in error.stderr and "422" not in error.stderr:
                raise
            if attempt == 2:
                raise


def hook(name, args):
    recorded_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    root = Path(__file__).resolve().parent
    settings = json.loads((root / "config.json").read_text())
    previous = settings["previous_hooks_path"]
    if previous is None:
        # --git-common-dir also handles linked worktrees.
        common = command("git", "rev-parse", "--git-common-dir").stdout.strip()
        delegate = Path(common) / "hooks" / name
    else:
        delegate = Path(os.path.expanduser(previous)) / name
    status = 0
    if delegate.resolve() != (root / "hooks" / name).resolve() and os.access(delegate, os.X_OK) and delegate.is_file():
        status = subprocess.run([str(delegate.resolve()), *args]).returncode
    if name == "post-commit":
        publish_safely(root, recorded_at)
    return status


def publish_safely(root, recorded_at):
    try:
        # Serialize concurrent commits on this device; remote SHA checks handle other devices.
        with (root / "publish.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            publish(recorded_at)
    except Exception:
        print("Profile location update failed; your commit succeeded. Check network and gh auth status.", file=sys.stderr)


if __name__ == "__main__":
    try:
        if sys.argv[1:] == ["install"]:
            install()
        elif sys.argv[1:] == ["uninstall"]:
            uninstall()
        elif len(sys.argv) >= 3 and sys.argv[1] == "hook":
            sys.exit(hook(sys.argv[2], sys.argv[3:]))
        elif sys.argv[1:] == ["publish"]:
            publish_safely(Path(__file__).resolve().parent, datetime.now(timezone.utc).isoformat(timespec="microseconds"))
        else:
            raise RuntimeError("Usage: profile_hook.py install|uninstall")
    except Exception as error:
        print(f"Profile hook: {error}", file=sys.stderr)
        sys.exit(1)
