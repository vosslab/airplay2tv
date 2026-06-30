# CODE_ARCHITECTURE.md

High-level design, major components, and data flow for airplay2tv.

## Design goals

- One command streams any local file to any AirPlay or Roku receiver on the LAN.
- The core (CLI, orchestration, media pipeline, HTTP server) is backend-agnostic.
  Backend-specific libraries (pyatv, rokuecp) are confined to their own modules.
- Async orchestration drives discovery, pairing, and playback; a separate
  threaded HTTP server serves the file without blocking the event loop.

## Component overview

```
+-----------------------------+
|  CLI (cli.py)               |  argparse, dispatch, error rendering
+-----------------------------+
              |
              v
+-----------------------------+
|  Orchestrator (app.py)      |  run(), run_stream(), run_devices(),
|                             |  run_doctor(), run_pair()
+-----------------------------+
    |       |       |       |
    v       v       v       v
+-------+ +-----+ +------+ +--------+
|media  | |http | |net   | |device  |
|.py    | |server| |util  | |pick.py |
+-------+ +-----+ +------+ +--------+
    |                           |
    v                           v
+-------+          +------------------------+
|ffmpeg | (ext)    |  Discovery (aggregate) |
|ffprobe|          +------------------------+
+-------+               |          |
                         v          v
               +-----------+  +----------+
               | AirPlay   |  | Roku     |
               | backend   |  | backend  |
               | (pyatv)   |  | (rokuecp)|
               +-----------+  +----------+
                    |                |
                    v                v
           +------------------+ +-----------------+
           | credentials.yaml | | roku_ssdp.py    |
           | config.yaml      | | (SSDP discovery)|
           +------------------+ +-----------------+
```

## Layer descriptions

### CLI layer (`airplay2tv/cli.py`)

Parses command-line arguments with argparse. Defines the stream-action flags
(`-i`, `-d`, `--bind`, `--save-device`, `--default-device`, `--passthrough`,
`--transcode`) and the three subcommands (`pair`, `doctor`, `devices`). Calls
`logging_setup.configure`, then dispatches to `app.run`. Maps any
`Airplay2tvError` to a single readable stderr line with exit code 1; unexpected
exceptions propagate unchanged.

### Orchestration layer (`airplay2tv/app.py`)

`run(args)` is a synchronous dispatcher: async actions (stream, devices) are
driven through `asyncio.run` here; the sync subcommand handlers (doctor, pair)
run their own event loops internally, keeping exactly one running loop active
at a time.

The stream action flow:

1. `aggregate.discover_all` runs every backend's `discover()` concurrently
   under a 7 s wall-clock budget.
1a. `resolve_known_address` handles two direct-IP cases that bypass discovery:
    (a) `--device <ip>` when the IP is not already in the discovered list, and
    (b) a saved/default device whose stored address discovery did not surface.
    In both cases `resolve_via_backends` probes each backend's
    `resolve_address(ip)` and uses the first non-None result. This path works
    when SSDP is silent (for example when the Roku `ecp-setting-mode` is `limited`).
2. `select_device` resolves the target (explicit flag, saved default, or
   interactive picker).
3. `backend_for_device` matches the device's backend key to an active instance.
4. `ensure_paired` inline-pairs on a TTY or raises `PairingRequiredError`.
5. `media.prepare` produces the file to serve (passthrough/remux/transcode).
6. `httpserver.serve` starts a threaded range-capable HTTP server.
7. `backend.play` hands the URL to the device.
8. `persist_device` writes the device record and default id when requested.
9. `wait_for_interrupt` parks until Ctrl+C; on interrupt `backend.stop` is
   awaited, then a `finally` block shuts the server and removes the temp dir.

### Backend contract (`airplay2tv/backends/base.py`)

Defines the interface every backend implements:

- `Backend` ABC: `discover`, `resolve_address`, `media_profile`, `play`, `stop`,
  `status`, `needs_pairing`, `is_paired`, `pair`.
- Data classes: `Device`, `MediaProfile`, `PlaybackStatus`, `PairingRecord`.
- `PairingState` enum: `PAIRED`, `NOT_PAIRED`, `NEEDS_REFRESH`.

The contract imports nothing from pyatv, rokuecp, or other airplay2tv modules,
keeping the interface stable and protocol-free.

### AirPlay backend (`airplay2tv/backends/airplay.py`)

The sole importer of pyatv. Uses mDNS discovery via `pyatv.scan` (5 s window),
AirPlay pairing via `pyatv.pair` (begin/pin/finish), and URL-based streaming
via `atv.stream.play_url`. Credentials are loaded from the credentials store
and applied via `config.set_credentials` before each connection. The connection
is opened fresh per control call and closed synchronously with `atv.close()`.

### Roku backend (`airplay2tv/backends/roku_ecp.py`)

The sole importer of rokuecp. Discovers via the SSDP module (`roku_ssdp.py`),
reads device info from `rokuecp.Roku.update()`, and launches playback by
POSTing to the Roku Media Player channel (app id 2213) via
`roku.launch("2213", {contentId: url, mediaType: "movie"})`. Roku ECP requires
no PIN; the real access gate is the TV setting
"Settings > System > Advanced system settings > Control by mobile apps".
A 403 response is translated to `DeviceUnreachableError` naming that setting.

### Discovery (`airplay2tv/discovery/`)

- `aggregate.py`: `discover_all(backends, timeout, on_backend_done=None)` runs
  every backend's `discover()` concurrently via `asyncio.gather` under a shared
  `asyncio.wait_for` timeout, and returns a `DiscoveryResult(devices, failures)`.
  A backend that raises, times out, or returns `None` produces a visible
  `BackendFailure(backend, reason)` instead of silently contributing zero. The
  optional `on_backend_done` callback fires as each backend finishes, which the
  app uses to narrate scan progress on stderr.
- `discovery_result.py`: the frozen `DiscoveryResult` (devices plus failures)
  and `BackendFailure` (backend key, reason) carriers shared by the aggregate
  and app layers.
- `roku_ssdp.py`: async SSDP M-SEARCH over UDP (`asyncio.DatagramProtocol`).
  Parses UPnP response headers case-insensitively, dedupes by USN, and
  returns `(responders, DiscoveryStats)`.

### Media pipeline (`airplay2tv/media.py`)

Three-stage pipeline:

1. `inspect(path)` runs `ffprobe -print_format json -show_format -show_streams`
   and parses the JSON into a `MediaInfo` (container, video_codec, audio_codec,
   duration).
2. `decide(info, profile, mode_override)` is a pure function: passthrough when
   the container and both codecs match the profile, remux when codecs match but
   container does not, transcode otherwise.
3. `prepare(path, profile, tmpdir, on_progress, cancel_event, mode_override)`
   runs the decided ffmpeg path. Remux uses `-c copy`; transcode uses libx264
   at CRF 23 veryfast with 160 kbps AAC. Progress is reported via a
   `on_progress(fraction)` callback. A `cancel_event` terminates ffmpeg and
   removes the partial output.

### HTTP server (`airplay2tv/httpserver.py`)

`serve(path, bind_host, advertised_host)` starts a `ThreadingHTTPServer`
in a daemon thread that serves one file with full byte-range support (HEAD,
GET, 206 Partial Content, 416 Range Not Satisfiable). The returned URL uses
`advertised_host` so the device can reach the file even when the server
binds to all interfaces. `shutdown(server, thread)` stops the server and
joins the thread.

### Network utilities (`airplay2tv/netutil.py`)

- `local_ip_for(target)`: determines the routable LAN interface IP by
  UDP-connecting to the target without sending any packets (the OS picks the
  outbound interface).
- `pick_free_port(start)`: returns the first bindable TCP port in a bounded
  sweep.

### Config and credentials stores

- `config.py`: reads/writes `~/.config/airplay2tv/config.yaml` (non-secret
  preferences: saved device records, default device id). Writes atomically via
  `tempfile.mkstemp` + `os.replace`. Honors `XDG_CONFIG_HOME`.
- `credentials.py`: reads/writes `~/.config/airplay2tv/credentials.yaml`
  (AirPlay pairing credentials). Mode 0600 asserted on every write. Warns
  on looser permissions. Concurrent writers serialized by `fcntl.flock` on
  a companion lock file. Honors `XDG_CONFIG_HOME`.

### Supporting modules

- `airplay2tv/devicepick.py`: renders a numbered device list; resolves a device
  by name, identifier, or interactive numbered prompt. Disambiguates duplicate
  names by appending the address.
- `airplay2tv/pairing.py`: `run(args) -> int` entry point for the `pair`
  subcommand. Discovers devices, selects one, checks for an existing record,
  runs the PIN handshake, and saves the record.
- `airplay2tv/doctor.py`: `run_checks(device, input_file) -> int` prints
  PASS/FAIL/INFO/WARN lines. Required checks (ffmpeg, ffprobe, address, and
  backend dependency availability via `registry.backend_availability()`) affect
  the exit code; advisory checks (discovered device count, SSDP stats, pairing
  state, media dry-run) do not.
- `airplay2tv/errors.py`: typed error hierarchy: `Airplay2tvError` (base),
  `UnsupportedMediaError`, `PreparationError`, `PairingRequiredError`,
  `DeviceUnreachableError`, `CredentialsError`.
- `airplay2tv/logging_setup.py`: configures the root logger level (WARNING /
  INFO / DEBUG) from the `--verbose` / `--debug` flags.
- `airplay2tv/backends/registry.py`: `active_backends()` walks `BACKEND_SPECS`,
  lazily imports and instantiates each concrete backend class, and raises
  `Airplay2tvError` naming the missing pip package and the install command when a
  required backend dependency (`pyatv`, `rokuecp`) is absent. `pyatv` and
  `rokuecp` are required, not optional, so a missing one fails loud instead of
  silently dropping the backend. `backend_availability()` is the non-raising
  probe `doctor` uses to report each backend's state.

### Entry points

Two routes reach `airplay2tv.cli.main()`:

- `stream.py` (repo-root launcher): thin shim that prepends the repo root to
  `sys.path` and calls `airplay2tv.cli.main()`. Use from a source checkout:
  `source source_me.sh && python3 stream.py -i movie.mp4`.
- `airplay2tv` console script: generated from the `[project.scripts]` entry in
  `pyproject.toml` (`airplay2tv = "airplay2tv.cli:main"`) when the Homebrew
  formula installs the package. The pyproject packaging exists to support that
  packaged install; airplay2tv is run as an app, not imported as a PyPI library.

## Data flow (stream action)

```
cli.main()
  -> app.run(args)
       -> aggregate.discover_all(backends, 7s)
            -> AirPlayBackend.discover()  [pyatv.scan, mDNS, 5s]
            -> RokuEcpBackend.discover()  [roku_ssdp.discover, SSDP UDP]
       -> resolve_known_address(backends, args, devices)
            -> resolve_via_backends(backends, ip)  [on bare --device IP or
               stored address not in discovered list; skips SSDP]
       -> select_device(args, devices)    [--device / default-id / picker]
       -> backend_for_device(backends, device)
       -> ensure_paired(backend, device)  [inline PIN on TTY]
       -> media.prepare(input, profile, tmpdir, ...)
            -> ffprobe (inspect)
            -> ffmpeg (remux or transcode, optional)
       -> netutil.local_ip_for(device.address)
       -> httpserver.serve(path, bind, advertised)
            -> ThreadingHTTPServer (daemon thread, range-capable)
       -> backend.play(device, url, prepared)
            AirPlay: pyatv.connect -> atv.stream.play_url(url)
            Roku:    rokuecp.Roku.launch("2213", {contentId, mediaType})
       -> persist_device(args, device)    [--save-device / --default-device]
       -> wait_for_interrupt()            [Ctrl+C -> backend.stop]
  -> finally: httpserver.shutdown + shutil.rmtree(tmpdir)
```

## Async / threading model

- The `asyncio` event loop is owned by each top-level handler (`asyncio.run`).
- The HTTP server runs in a `threading.Thread` (daemon=True) so it does not
  block the event loop.
- `wait_for_interrupt` parks in `threading.Event().wait()` until
  `KeyboardInterrupt` is delivered; `backend.stop` is then awaited while the
  event loop is still alive before the `finally` block runs.
- Only one event loop is active at a time: the dispatch layer (`app.run`) is
  synchronous; each handler that needs async drives its own `asyncio.run`.
