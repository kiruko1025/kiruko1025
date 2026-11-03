# Location from local commits

The single README line displays the public IP and approximate city of the computer
that most recently made a local commit with this hook installed. A scheduled
GitHub Action refreshes weather, air quality, local time and Spotify playback every 5 minutes
(GitHub scheduling can be delayed). It never geolocates the Actions runner.

## Install on each computer used to commit

Requirements: macOS or Linux, Git, Python 3.9+, and [GitHub CLI](https://cli.github.com/).
Sign in as `kiruko1025` with repository write access, then run:

```sh
gh auth login --hostname github.com
gh repo clone kiruko1025/kiruko1025 github-profile
cd github-profile
python3 scripts/profile_hook.py install
```

If already cloned, pull the latest version and run the installer there instead.
The installer copies the hook into your user data directory, so the clone can
subsequently be moved. Your next local commit in any repository using the global
hooks configuration will publish the IP, city, region, country, approximate
coordinates, timezone, and local-commit time to `profile-location.json` in this
public repository. Repository names, paths, messages, and commit hashes are never
sent. This includes commits in private repositories and commits not yet pushed.

The public profile updates after the resulting GitHub Action runs. In repository
Actions settings, Actions must be enabled with permission to write contents.
Weather data comes from [Open-Meteo](https://open-meteo.com/); IP geolocation uses
[ipapi.co](https://ipapi.co/api/). A VPN or proxy changes the location to that
network's location. API outages/rate limits leave the previous location intact;
the next local commit retries. Weather outages show an unavailable message.

## Existing hooks and exceptions

The installer saves the previous global `core.hooksPath`. Wrappers forward hook
arguments, standard input/output, and exit codes to that directory, or to each
repository's normal Git hooks directory when no previous global path existed.
No existing hook file is overwritten. Do not delete an old hooks directory that
is being forwarded to.

Repositories that explicitly set their own `core.hooksPath` (for example, Husky)
override the global setting. In such repositories, keep that configuration and
append this line to the existing `post-commit` hook, replacing the path with the
installed path printed by the installer:

```sh
python3 "$HOME/.local/share/github-profile-location/profile_hook.py" publish
```

With `XDG_DATA_HOME` set, use `$XDG_DATA_HOME/github-profile-location` instead.
On repositories without a remote, local commits still update the profile.
Web commits, CI commits, and commits on computers without this hook cannot
provide a location. Git clients must support Git hooks. This does not infer
locations for earlier commits.

Skip a single update with `PROFILE_LOCATION_SKIP=1 git commit ...`.
To disable globally and restore the previous configuration:

```sh
python3 "$HOME/.local/share/github-profile-location/profile_hook.py" uninstall
```

Remove any manually appended per-repository hook lines when uninstalling. Public
IP/location updates remain in Git history after the feature is disabled.

## Local time and Spotify

The README stays one line: location and IP, local time, weather, and Spotify
playback. The clock uses the timezone recorded by the location hook, including
daylight saving time. Both time and music are snapshots from the last workflow
run, rather than a continuously ticking clock or a live player.

Create an app in the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard),
select Web API, and register `http://127.0.0.1:8888/callback` as a redirect URI.
The app's Client ID is available on its settings page. Spotify currently requires
the developer app owner to have Premium. Then, from this checkout, run:

```sh
python3 scripts/connect_spotify.py YOUR_CLIENT_ID
```

Open the printed Spotify authorization URL, sign in, and allow
`user-read-currently-playing`. The helper uses PKCE and writes
`SPOTIFY_CLIENT_ID` and `SPOTIFY_REFRESH_TOKEN` straight to this repository's
GitHub Actions secrets through your authenticated GitHub CLI. It does not need
your Client Secret and never writes the refresh token to the repository or logs.
Credentials are used only for the Spotify token endpoint and playback endpoint.

Until connected, the music section is omitted. Once connected, it shows the
track and artist linked to Spotify, or `not playing` when playback is inactive.
Errors show `listening status unavailable`; they never reuse an older track.
Developer-app refresh tokens currently expire after six months; rerun the
connection helper when authorization expires or is revoked.

## Air quality and weather scene

Air quality uses the U.S. AQI scale, with a number and category (good, moderate,
unhealthy for sensitive groups, unhealthy, very unhealthy or hazardous).
It is a CAMS model estimate from the [Open-Meteo air-quality API](https://open-meteo.com/en/docs/air-quality-api),
not a reading from a sensor at your exact location. If data is missing, the
profile says `air quality unavailable`.

The tiny inline skyline is generated as `assets/weather-scene.svg`. It uses the
same weather response as the text, with sun/moon, clouds, rain, snow, lightning
or fog. The buildings are decorative. It updates with the profile; if weather
data is unavailable, the skyline becomes neutral instead of showing stale weather.
