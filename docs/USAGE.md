# USAGE.md

How to run airplay2tv: stream, pair, doctor, and devices.

## Quick start

```bash
# From a source checkout (recommended)
source source_me.sh && python3 stream.py -i video.mkv

# After brew install (Homebrew packaged install)
airplay2tv -i video.mkv
```

A bare invocation (`stream.py` or `airplay2tv` with no arguments) prints full
help text and exits 0.

If you supply flags but omit `-i/--input`, the tool fails fast before any
device discovery with:

```
error: no input file: pass -i/--input PATH
```

The first normal run discovers all AirPlay and Roku receivers on the local
network, shows a numbered list, prompts for a device, pairs inline when a PIN
is required (AirPlay), then streams the file.

## Default stream action

```bash
# source checkout
source source_me.sh && python3 stream.py -i FILE [options]

# Homebrew install
airplay2tv -i FILE [options]
```

Discover, pick, pair (if needed), prepare the media, serve it over HTTP, and
play. Press Ctrl+C to stop; the HTTP server and any temp files are cleaned up
on every exit.

### First-run inline pair-and-play (AirPlay)

```
$ airplay2tv -i movie.mp4
1. Living Room TV  [airplay]  id=AA:BB:...  addr=192.168.1.50
Select a device [1]: 1
Enter the 4-digit code shown on the device: 1234
Streaming to Living Room TV
Serving at http://192.168.1.10:3500/transcoded.mp4
Press Ctrl+C to stop.
```

Steps:

1. Discovery runs (up to 7 s).
2. A numbered list of receivers is shown; type the number and press Enter.
3. For AirPlay: the TV shows a 4-digit PIN; type it and press Enter.
4. The file is prepared (passthrough, remux, or transcode -- see below).
5. The status banner prints; playback starts on the device.

### Repeat-run (device already saved)

```
$ airplay2tv -i movie.mp4 --default-device AA:BB:...
Streaming to Living Room TV
Serving at http://192.168.1.10:3500/movie.mp4
Press Ctrl+C to stop.
```

No prompt, no PIN; the saved device is reused automatically.

### Streaming a remote URL (including m3u8 / HLS)

`-i` also accepts an `http://` or `https://` URL, including a `.m3u8` HLS
playlist:

```bash
source source_me.sh && python3 stream.py -i 'https://host/stream.m3u8' -d "Living Room TV"

# Homebrew install
airplay2tv -i 'https://host/stream.m3u8' -d "Living Room TV"
```

For a remote URL the TV fetches the URL **directly** -- there is no local
file preparation and no local HTTP server. This means the URL must be
reachable from the TV's network position, not just from the Mac running
`airplay2tv`. Practical caveats:

- `localhost`/`127.0.0.1` URLs only resolve on the Mac; the TV cannot reach
  them.
- VPN-only URLs that only the Mac can route to will fail on the TV.
- URLs that need cookies or auth headers are not supported: the TV's player
  issues a plain GET with no extra headers.
- Self-signed or otherwise untrusted TLS certificates may be rejected by the
  TV's HTTP client even when `curl`/the browser on the Mac trusts them.

AirPlay is the confirmed working path for `.m3u8` HLS playback. Roku ECP
sends a best-effort `streamFormat=hls` launch parameter for `.m3u8` URLs, but
this has not been verified against real Roku hardware (a prior direct test
returned HTTP 403 from the ECP endpoint).

Unsupported URL schemes (for example `rtsp://` or `file://`) fail fast with
a one-line error before any device discovery.

`doctor -i <URL>` does not probe the URL: it prints a `[WARN]` line and
skips the local media dry run, since doctor only inspects local files with
`ffprobe`.

## Flags

### Stream action flags

| Flag | Destination | Description |
| --- | --- | --- |
| `-i FILE` | `input_file` | Path or http(s) URL (including `.m3u8` HLS) to stream (required). |
| `-d NAME_OR_ID_OR_IP` | `device` | Name, identifier, or bare IPv4 address of the target device. |
| `--bind HOST` | `bind_host` | Interface the file server binds to (default: all). |
| `--save-device` | `save_device` | Save the selected device to config after playback. |
| `--default-device ID` | `default_device` | Use this identifier as the default and save it. |
| `--passthrough` | `media_mode` | Serve the original file if the device supports it. |
| `--transcode` | `media_mode` | Always transcode to portable MP4 H.264/AAC. |
| `-v` / `--verbose` | `verbose` | Show informational log messages. |
| `--debug` | `debug` | Show all debug log messages and full tracebacks. |

`--passthrough` and `--transcode` are mutually exclusive. Omitting both lets
the pipeline choose automatically (see [Media preparation](#media-preparation)).

### Device selection order

When no `--device` flag is given, the stream action resolves the target in
this order:

1. `--default-device ID` -- if that device is on the network, use it.
2. Saved default device id from config -- if on the network, use it.
3. Interactive (or single-device) picker.

When a preferred device is not reachable, a notice prints to stderr and the
interactive picker runs.

### Saving a device

`--save-device` writes the selected device record to
`~/.config/airplay2tv/config.yaml` after playback starts.

`--default-device ID` writes the device record AND marks it as the default id
so future runs skip the picker automatically. To get a device's identifier,
run `airplay2tv devices`.

Example: stream once and remember the device forever:

```bash
airplay2tv -i movie.mp4 --default-device AA:BB:CC:DD:EE:FF --save-device
```

## Subcommands

### `airplay2tv devices` / `stream.py devices`

Discover all receivers and print the numbered list, then exit.

```bash
# source checkout
source source_me.sh && python3 stream.py devices

# Homebrew install
airplay2tv devices
```

```
1. Living Room TV  [airplay]   id=AA:BB:CC:DD:EE:FF  addr=192.168.1.50
2. Kitchen TV      [roku-ecp]  id=uuid:...             addr=192.168.1.51
```

Use this to look up the identifier string needed for `--default-device` or
`airplay2tv pair -d`.

Discovery progress is printed to stderr (a `Scanning for ...` line per backend
and a per-backend result line), while the numbered device list goes to stdout,
so `stream.py devices 2>/dev/null` yields a clean, pipeable list. If a required
backend dependency (`pyatv` or `rokuecp`) is not installed, the command prints
`error: required backend dependencies not installed: ...; install them with:
pip install -r pip_requirements.txt` instead of an empty "no receivers" result.

### `airplay2tv pair` / `stream.py pair`

Run the interactive PIN-pairing handshake for an AirPlay device that requires
pairing. Use this when running headless (no TTY) or when credentials need to
be refreshed.

```bash
# source checkout
source source_me.sh && python3 stream.py pair
source source_me.sh && python3 stream.py pair -d "Living Room TV"

# Homebrew install
airplay2tv pair
airplay2tv pair -d "Living Room TV"
airplay2tv pair -d AA:BB:CC:DD:EE:FF
```

The device shows a 4-digit code; type it and press Enter. The pairing record
is saved to `~/.config/airplay2tv/credentials.yaml` (mode 0600).

Roku devices do not require a PIN. Run `airplay2tv pair` for AirPlay
receivers only.

### `airplay2tv doctor` / `stream.py doctor`

Check the environment and print PASS/FAIL/INFO/WARN lines to stdout.

```bash
# source checkout
source source_me.sh && python3 stream.py doctor
source source_me.sh && python3 stream.py doctor -d "Living Room TV"
source source_me.sh && python3 stream.py doctor -i sample.mkv

# Homebrew install
airplay2tv doctor
airplay2tv doctor -d "Living Room TV"
airplay2tv doctor -i sample.mkv
```

Required checks (contribute to the exit code):

- `ffmpeg` on PATH
- `ffprobe` on PATH
- Local address selection (can the host choose a LAN-facing IP?)
- Backend dependency availability (`pyatv` and `rokuecp` importable); a missing
  required backend dependency fails the check and prints the install command

Advisory checks (printed but do not affect exit code):

- AirPlay/backend discovery: number of devices found
- Roku SSDP stats: probes, valid responses, duplicates, malformed (plus an
  interface-fallback note when no outbound interface could be selected)
- Per-device pairing state for discovered devices
- Media-prep dry run for `-i FILE` (inspect + decide, no ffmpeg run)

Exit code 0 when all required checks pass; 1 when any required check fails.

#### Direct-IP probe with `--device <IP>`

When `--device` is a bare IPv4 address, `doctor` performs a direct HTTP GET
probe against `<ip>:8060` for four ECP endpoints instead of relying on SSDP
discovery:

```bash
source source_me.sh && python3 stream.py doctor --device 192.168.1.42
# or: airplay2tv doctor --device 192.168.1.42
```

For each endpoint (`/query/device-info`, `/query/active-app`, `/query/apps`,
`/query/media-player`) a per-endpoint status line is printed, for example:

```
[INFO] ECP device-info: HTTP 200
[WARN] ECP apps: HTTP 403
```

On a 200 response from `/query/device-info`, the following fields are
extracted and printed:

- `ecp-setting-mode` (e.g. `limited` or `full`)
- `friendly-device-name`
- `power-mode` (e.g. `Ready` or `PowerOn`)

A summary line distinguishes "direct ECP reachable (limited mode)" from
"direct ECP not reachable". When SSDP discovery finds zero valid devices
but direct ECP succeeds, doctor prints:

```
[INFO] Roku discovery: SSDP not seen, but direct ECP reachable at 192.168.1.42 -- use --device 192.168.1.42
```

This is also the resolution path for `--device <IP>` in the stream action:
when `--device` is a bare IP literal and no discovered device already
matches, each active backend's `resolve_address` is tried, bypassing SSDP
discovery entirely. This is useful when SSDP is silent (e.g. `ecp-setting-mode`
is `limited`).

Useful over SSH or before a scheduled run:

```bash
source source_me.sh && python3 stream.py doctor && python3 stream.py -i nightly.mkv --default-device AA:BB:...
# or: airplay2tv doctor && airplay2tv -i nightly.mkv --default-device AA:BB:...
```

## Media preparation

The pipeline inspects the input file with `ffprobe` and decides how to
prepare it for the selected device, unless a mode is forced with
`--passthrough` or `--transcode`.

### Automatic decision rules

| Codecs supported? | Container supported? | Decision |
| --- | --- | --- |
| YES | YES | passthrough (original file served directly) |
| YES | NO | remux (stream copy into MP4, no quality loss) |
| NO | either | transcode (H.264/AAC baseline MP4) |

### Supported media matrix

| Device | Containers | Video codecs | Audio codecs |
| --- | --- | --- | --- |
| Apple TV (AirPlay) | mp4, mov, m4v | H.264, H.265/HEVC | AAC |
| Roku (ECP) | mp4, mov, m4v | H.264 only | AAC |

H.265 files sent to a Roku are transcoded to H.264 (the test Roku TV did not
pass H.265 through the Roku Media Player). H.265 sent to Apple TV passes
through untouched.

The transcode target is a portable MP4 with H.264 video (libx264, veryfast
preset, CRF 23) and 160 kbps AAC audio. The same command works on macOS and
Debian with no hardware encoders.

Forcing `--passthrough` on a file the device cannot play raises an error.
Forcing `--transcode` always runs ffmpeg regardless of the device profile.

## Config and credentials files

### Config file

Path: `~/.config/airplay2tv/config.yaml`

Stores non-secret preferences: saved device records (name, backend,
identifier, address) and the default device identifier. Created automatically
on `--save-device` or `--default-device`. Honors `XDG_CONFIG_HOME` when set.

### Credentials file

Path: `~/.config/airplay2tv/credentials.yaml`

Mode: 0600 (owner read/write only). The tool asserts this mode on every write
and warns when it finds looser permissions. Stores AirPlay pairing credentials
(the opaque pyatv credential string). Do not share or commit this file.
Honors `XDG_CONFIG_HOME` when set.

## Headless and SSH use

The stream action pairs inline only when `stdin` is a TTY. Without a TTY the
tool raises an error pointing at `airplay2tv pair`:

```
error: device 'Living Room TV' needs pairing. Run: airplay2tv pair
```

Pre-pair on an interactive session before running headless:

```bash
# On a machine with a terminal (source checkout)
source source_me.sh && python3 stream.py pair -d "Living Room TV"

# Later, in a cron job or SSH session (no TTY needed)
source source_me.sh && python3 stream.py -i movie.mp4 --default-device AA:BB:...

# Or with Homebrew install
airplay2tv pair -d "Living Room TV"
airplay2tv -i movie.mp4 --default-device AA:BB:...
```

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Success. |
| 1 | A typed error (no devices, pairing required, ffmpeg failure, etc.). |
| 2 | Internal error or unrecognized subcommand. |
