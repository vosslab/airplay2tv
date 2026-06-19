# TROUBLESHOOTING.md

Start every diagnostic session with `airplay2tv doctor` (or
`airplay2tv doctor --device <ip>` when the device IP is already known).
It prints PASS/FAIL/INFO/WARN lines for ffmpeg, ffprobe, network, discovery,
and per-device pairing state, and returns exit code 1 when any required check
fails.

## AirPlay: not authenticated / playback refused

**Symptom.** `airplay2tv` exits with an error such as
"not authenticated" or "device needs pairing", or pyatv raises
`AuthenticationError` during `play_url`.

**Cause.** AirPlay uses a mandatory PIN-pairing handshake. Without a stored
pairing credential the device refuses every playback request. This is a
protocol requirement, not a network error.

**Fix.**

1. Run the interactive pair flow (requires a TTY):
   ```
   airplay2tv pair
   airplay2tv pair -d "Living Room TV"
   airplay2tv pair -d AA:BB:CC:DD:EE:FF
   ```
2. The TV shows a 4-digit code; type it and press Enter.
3. The pairing record is saved to `~/.config/airplay2tv/credentials.yaml`
   (mode 0600). Subsequent runs use the stored credential automatically.

For headless or SSH use, run `airplay2tv pair` once on an interactive terminal
before running unattended. See [docs/USAGE.md](USAGE.md) for the headless
pre-pair workflow.

## Roku: device not discovered (SSDP silent or intermittent)

**Symptom.** `airplay2tv` reports zero Roku devices, or Roku SSDP stats show
`valid=0` even though the TV is on the same subnet.

**Cause.** SSDP multicast responses from the Roku can be suppressed when the
TV is in standby, when the network switch filters multicast, or when
`ecp-setting-mode` is `limited` (the TV has "Control by mobile apps" disabled
and does not respond to SSDP probes).

**Fix.** Use the direct-IP path, which bypasses SSDP entirely:

```
airplay2tv -i FILE --device <roku-ip>
```

Run doctor with the IP to confirm ECP reachability:

```
airplay2tv doctor --device <roku-ip>
```

Doctor prints per-endpoint status lines (e.g. `[INFO] ECP device-info: HTTP 200`)
and a summary line. If SSDP returns nothing but ECP returns 200, doctor prints:

```
[INFO] Roku discovery: SSDP not seen, but direct ECP reachable at <ip> -- use --device <ip>
```

That confirms the direct-IP stream path will work for that address.

## Roku: ECP returns HTTP 403 (limited mode / Control by mobile apps)

**Symptom.** `airplay2tv doctor --device <ip>` shows
`ecp-setting-mode: limited`, `power-mode: Ready`, and ECP control endpoints
(`/query/apps`, `/query/media-player`, `keypress`) return HTTP 403.
The stream action raises a `DeviceUnreachableError` with the message
"Roku refused the request (HTTP 403). Enable
Settings > System > Advanced system settings > Control by mobile apps on the Roku."

**Cause.** The Roku TV is in networked standby (`power-mode=Ready`) or has ECP
control disabled. The `ecp-setting-mode=limited` field confirms restricted mode.
In this state device-info (read-only) returns 200 but all control endpoints
refuse with 403.

**Fix.**

1. Wake the TV to the Home screen so `power-mode` becomes `PowerOn`.
2. On the Roku: navigate to Settings > System > Advanced system settings >
   Control by mobile apps and enable it.
3. Retest:
   ```
   airplay2tv doctor --device <roku-ip>
   ```
   All four ECP endpoints should return HTTP 200 and
   `ecp-setting-mode` should no longer be `limited`.

## ffmpeg or ffprobe not found

**Symptom.** `airplay2tv doctor` prints `[FAIL] ffmpeg on PATH` or
`[FAIL] ffprobe on PATH` and returns exit code 1. The stream action cannot
inspect or prepare media.

**Cause.** ffmpeg and ffprobe are required external binaries that airplay2tv
does not bundle.

**Fix.**

- macOS (Homebrew): `brew install ffmpeg`
- Debian/Ubuntu: `sudo apt install ffmpeg`

Both `ffmpeg` and `ffprobe` are installed by the same package. After
installation, rerun `airplay2tv doctor` to confirm `[PASS]` for both.

## Media will not play / wrong codec on the device

**Symptom.** The stream action completes without error but the device shows
a black screen, reports an unsupported format, or the file is served as a
codec the device cannot decode (e.g. H.265 on a Roku).

**Cause.** The automatic pipeline (inspect + decide) chose passthrough or
remux, but the device cannot decode the video or audio codec in that file.
The Roku Media Player accepts H.264/AAC only; H.265 files should transcode
automatically, but a forced `--passthrough` override or an unusual codec
skips the conversion.

**Fix.** Force a transcode to the portable H.264/AAC MP4 baseline:

```
airplay2tv -i FILE --transcode
```

This always runs ffmpeg regardless of the auto-detected profile. The output
is a CRF-23 H.264 + 160 kbps AAC MP4, which plays on every supported device.

See [docs/USAGE.md](USAGE.md) for the full supported media matrix and
automatic decision rules.
