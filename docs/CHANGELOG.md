# CHANGELOG.md

## 2026-06-18

### Additions and New Features

- Added repo-root launcher `stream.py`: a thin shim that prepends the repo root to
  `sys.path` and calls `airplay2tv.cli.main()` (shebang on line 1, executable bit set).
  This is the canonical way to run the tool from a source checkout.
- Added `tests/e2e/e2e_entry_smoke.sh`: smoke check that invokes `stream.py --help` and
  asserts exit 0.
- Added `build_parser()` helper to `airplay2tv/cli.py`: factors parser construction out of
  `main()`; `--help` now ends with a worked-examples epilog (`RawDescriptionHelpFormatter`,
  `%(prog)s` so the examples match the launcher the user invoked).
- Added `tests/test_cli.py`: one focused offline test asserting `run_stream` raises
  `Airplay2tvError` before any device discovery when `-i/--input` is missing
  (discovery-spy assertion).

### Behavior or Interface Changes

- Bare invocation (`stream.py` or `airplay2tv` with no arguments) now prints full help and
  exits 0 instead of a terse usage line.
- `app.run_stream` fails fast with a typed `Airplay2tvError` ("no input file: pass
  -i/--input PATH") before device discovery when `-i/--input` is missing; previously the
  error surfaced late inside `media.prepare`.
- `python3 -m airplay2tv` is no longer a supported entry point; use `stream.py` from a
  source checkout or the `airplay2tv` console script.

### Fixes and Maintenance

- Documentation now presents airplay2tv as an app you run (clone-and-run `stream.py`, or the
  Homebrew-installed `airplay2tv` console script), not a PyPI library to `pip install` and
  `import`. Refreshed `README.md`, `docs/INSTALL.md`, `docs/USAGE.md`,
  `docs/CODE_ARCHITECTURE.md`, and `docs/FILE_STRUCTURE.md`; `INSTALL.md` leads with
  clone-and-run and lists Homebrew as the packaged-install alternative.
- `tests/e2e/e2e_debian_smoke.py` invokes `python3 stream.py` instead of
  `python3 -m airplay2tv` so it works after `__main__.py` removal.
- `HomebrewFormula/airplay2tv.rb` drops the manual `-m airplay2tv` wrapper and relies on
  pip's generated `airplay2tv` console script; its `license` field corrected to MIT.
- Bumped `[build-system] requires` from `setuptools>=68` to `setuptools>=78` so the PEP 639
  SPDX `license = "MIT"` field is valid at build time.
- Completed `[project]` metadata in `pyproject.toml`: added `readme`, `authors` (name only,
  no email), `[project.urls]`, and `license = "MIT"`.
- Corrected the README license line from "GPL-3.0-or-later" to MIT and filled the
  `LICENSE.MIT.md` copyright holder ("Dr. Neil R Voss") to match the committed MIT license.
- Reworded the stale "before app.py exists" rationale in `airplay2tv/cli.py` docstrings to
  the real reason for the lazy import (keeping `--help` off app.py's heavier imports).

### Removals and Deprecations

- Removed `airplay2tv/__main__.py`; `python3 -m airplay2tv` is no longer supported. Use
  `stream.py` (source checkout) or the `airplay2tv` console script.

### Decisions and Failures

- Project license confirmed MIT: the committed `LICENSE` has always been MIT; the README
  claim of GPL was wrong. Aligned README, `pyproject.toml`, the Homebrew formula, and the
  `LICENSE.MIT.md` copyright line to MIT.
- Decided airplay2tv is distributed as a runnable app, not a PyPI import package: docs no
  longer advertise `pip install airplay2tv` or `import airplay2tv`. The pyproject
  console-script and metadata remain only so the Homebrew formula can install the command.

### Developer Tests and Notes

- A pre-merge multi-reviewer audit pruned two brittle pytests (asserting on the help-text
  string and the formatter class) and stripped an unnecessary 50-line `FakeBackend` scaffold
  from `tests/test_cli.py`, leaving the single fail-before-discovery invariant.
- Verification: `pytest tests/` = 972 passed; `tests/e2e/e2e_debian_smoke.py` all 8 steps
  pass; `tests/e2e/e2e_entry_smoke.sh` passes; `tests/test_markdown_links.py` green.

## 2026-06-17

### Additions and New Features

- Created `docs/TROUBLESHOOTING.md` (docset-updater remaining-docs audit): symptom/cause/fix
  bullets for AirPlay "not authenticated" (run `airplay2tv pair`), Roku SSDP silent (use
  `--device <ip>` to bypass SSDP), Roku ECP HTTP 403 / limited mode (wake TV and enable
  Settings > System > Advanced system settings > Control by mobile apps), ffmpeg/ffprobe
  not found (install via Homebrew or apt), and media will not play / wrong codec (use
  `--transcode`). References `airplay2tv doctor` and `airplay2tv doctor --device <ip>` as
  the primary diagnostic. ASCII only, sentence-case headings, relative links.

- Enhanced `airplay2tv/doctor.py` with a direct-IP Roku ECP probe: when `--device` is a bare
  IPv4 address, `run_checks` performs direct HTTP GET probes against `<ip>:8060` for four ECP
  endpoints (`/query/device-info`, `/query/active-app`, `/query/apps`, `/query/media-player`) and
  prints a per-endpoint line with the HTTP status (e.g. `[INFO] ECP device-info: HTTP 200`,
  `[WARN] ECP apps: HTTP 403`). On a 200 device-info response, extracts and prints
  `ecp-setting-mode`, `friendly-device-name`, and `power-mode`. Prints a summary distinguishing
  "direct ECP reachable (limited mode)" from "direct ECP not reachable". When SSDP discovery
  finds zero valid devices but direct ECP is reachable, prints `[INFO] Roku discovery: SSDP not
  seen, but direct ECP reachable at <ip> -- use --device <ip>`. When limited mode and
  power-mode=Ready are both present (TV in networked standby), prints an advisory note explaining
  the 403 ambiguity and suggesting a retest with the TV awake. Uses `defusedxml` for safe XML
  parsing (guards XXE/billion-laughs); scheme-validates the URL before `urlopen` (`nosec B310`).
  Added `defusedxml` to `pip_requirements.txt`. No changes to app.py or backends.
- Added 7 new offline pytest tests in `tests/test_doctor.py`: per-endpoint 200/403 mix prints
  correct lines and ecp-setting-mode/friendly-device-name/power-mode fields; SSDP-zero + ECP
  reachable triggers the `--device <ip>` hint; connection error prints "not reachable" summary;
  `_extract_ecp_device_fields` parses all three fields from XML; empty body returns empty dict;
  name (non-IP) device filter does not trigger any ECP probe; limited+Ready advisory note printed
  when both conditions hold. Full suite: 953 passed.

- Added a Roku direct-IP / saved-device resolution path so a known IP works even when SSDP
  (roku:ecp) is silent (hardware evidence: ECP device-info returns 200 at a known IP while SSDP
  discovery returns nothing, because discovery and control are independent). New
  `RokuEcpBackend.resolve_address(address)` GETs `http://<address>:8060/query/device-info` via the
  rokuecp client and, on a successful read, builds a `Device` (backend `roku-ecp`, identifier from
  the device serial number with the address as fallback, name from the friendly device name, model
  from model-name/model-number); it returns None when the address is unreachable or control is
  blocked (403). Added a safe default `Backend.resolve_address(address) -> None` on the base
  contract so non-Roku backends are always callable from the IP path. rokuecp stays imported only
  in `roku_ecp.py`.
- Added `airplay2tv.app.resolve_known_address`, `resolve_via_backends`, `looks_like_ip`, and
  `stored_default_record` helpers (WP-ROKU-DIRECT-IP): before relying on discovery, the stream
  action probes a known address directly. When `--device` is a bare IP literal that no discovered
  device already matches, each active backend's `resolve_address` is tried and the first resolved
  Device is used. When a default/saved device has a stored config address that discovery did not
  surface, that address is probed before falling back to the picker.
- Added Roku direct-IP and app IP-selection tests: `tests/test_roku_ecp.py` asserts
  `resolve_address` builds the right Device from device-info and returns None on a 403;
  `tests/test_app_flow.py` asserts a bare-IP `--device` with empty discovery selects the
  backend-resolved Device, skips a non-IP `--device`, skips an IP discovery already surfaced, and
  that `looks_like_ip` distinguishes IP literals from device names. Full suite: 946 passed.

- Created `docs/USAGE.md` (WP-DOCS): complete CLI reference covering every flag and subcommand,
  the first-run inline pair-and-play flow, repeat-run no-prompt flow, device selection order,
  `--save-device` / `--default-device` persistence, the supported media matrix
  (Apple TV: H.264+H.265/AAC MP4; Roku: H.264/AAC, H.265 transcodes to H.264),
  the config and credentials file paths, headless/SSH pre-pair workflow, and exit codes.
  Replaced the stale starter-repo-template stub that described `reset_repo.py`.
- Created `docs/CODE_ARCHITECTURE.md` (WP-DOCS): high-level component overview with an ASCII
  diagram of the layered architecture (CLI -> orchestrator -> media/httpserver/netutil/devicepick
  -> backend contract -> AirPlay backend / Roku backend -> discovery / config / credentials).
  Describes the async/threading model (one event loop at a time, threaded HTTP server), the
  media pipeline (inspect/decide/prepare), and the full stream-action data flow from
  `cli.main()` to `finally` cleanup.
- Created `docs/FILE_STRUCTURE.md` (WP-DOCS): directory map of every module in `airplay2tv/`,
  `tests/`, `devel/`, `docs/`, and `HomebrewFormula/` with a one-line description of each
  file's role. Includes the generated/gitignored paths table.

- Created `tests/e2e/e2e_debian_smoke.py` (WP-DEBIAN-SMOKE): 8-step portability smoke that runs end-to-end on macOS and Debian with ffmpeg installed; no real TV hardware or macOS-only API required. Steps: `python3 stream.py --help` exits 0; `stream.py doctor` exits 0; `e2e_make_fixtures.py` produces 3 lavfi fixtures; `airplay2tv.media.inspect` + `decide` returns `passthrough` for h264 and `transcode` for hevc; `media.prepare` completes a remux (MKV->MP4) and a transcode (HEVC->H.264 MP4); `httpserver.serve` answers a Range request with 206; `FakeBackend` app-stream flow (discover+prepare+serve+range) runs end-to-end. All 8 steps PASS in under 30 s. Shebang on line 1, executable bit set; pyflakes clean.

- Created `tests/test_app_flow.py` (WS-APP-FINALIZE): 8 offline pytest tests using a `FakeBackend` (declares `backend_key = "fake"`; no pyatv/rokuecp/network). Covers `app.backend_for_device` exact-key match and unknown-key raise; `app.select_device` skipping the picker for a reachable `--default-device` and falling back with a stderr notice when the default id is not discoverable; `app.persist_device` writing the record and the stored default id under `--save-device` + matching `--default-device`, and writing nothing (no config file created) without flags; and `cli.dispatch` mapping `Airplay2tvError` to exit code 1 with one stderr line while letting an unexpected `RuntimeError` propagate. All pass in 0.04 s.
- Added `airplay2tv.app.select_device`, `find_by_identifier`, and `persist_device` helpers (WS-APP-FINALIZE): `select_device` resolves the target in order `--device` (exact) -> reachable `--default-device` -> reachable saved default id -> interactive picker, printing a clear notice and falling back to discovery when a preferred id is not on the network; `persist_device` writes the chosen device after a successful play and also marks it the stored default when `--default-device` named it.
- Added `airplay2tv.cli.dispatch(app, args)` (WS-APP-FINALIZE): runs `app.run(args)` and maps any `Airplay2tvError` to a single readable `error: <message>` line on stderr with exit code 1, printing the full traceback only under `--debug`; unexpected exceptions propagate unchanged so real bugs surface.

- Created `airplay2tv/pairing.py` (WS-PAIR): `run(args) -> int` entry point called by `app.run_pair`; drives an `asyncio.run(_async_run(args))` loop that discovers all backends, selects a device via `devicepick.select`, checks `credentials.get_record` + `backend.is_paired` to short-circuit when already paired, otherwise calls `backend.pair(device, prompt_pin)`, persists the returned `PairingRecord` via `credentials.save_record`, and prints success. Reusable `prompt_pin()` helper reads from stdin with the message "Enter the 4-digit code shown on the TV:" and strips whitespace. No shebang (library module). All functions carry full type hints using builtin generics; no `typing` module.
- Created `tests/test_pairing_fakebackend.py` (WS-PAIR): 2 offline pytest tests using `FakePairingBackend` (simulates a PIN challenge), monkeypatched `pairing.prompt_pin`, and monkeypatched `credentials.save_record`/`get_record`. `test_pairing_prompts_and_saves_record` verifies prompt_pin is called once and a record is saved; `test_already_paired_skips_prompt_and_returns_zero` verifies no prompt occurs when `is_paired` returns PAIRED and a stored record exists. Both pass in 0.03 s.

- Added `[project.scripts]` entry `airplay2tv = "airplay2tv.cli:main"` to `pyproject.toml` (WP-PACKAGING): makes `pip install .` wire the `airplay2tv` console script to `airplay2tv.cli:main`. Added minimal `[build-system]` block (`setuptools>=68`) so the `[project.scripts]` table is valid for PEP 517 builds.
- Created `HomebrewFormula/airplay2tv.rb` (WP-PACKAGING): formula with `depends_on "ffmpeg"` and `depends_on "python@3.12"`, installs `pip_requirements.txt` resources (pyatv, rokuecp, pyyaml) and the package itself into the Homebrew python@3.12 prefix without a virtualenv, then links a thin `bin/airplay2tv` wrapper that execs `python3.12 -m airplay2tv`. Placeholder sha256 values require updating to a real release archive before publishing.
- Created `docs/INSTALL.md` (WP-PACKAGING): setup instructions for macOS Homebrew (no virtualenv, pip into Homebrew python@3.12 site-packages, optional formula install) and Debian/Ubuntu (`apt install ffmpeg python3 python3-pip` plus `pip3 install -r pip_requirements.txt`). Includes a dependencies table.
- Added H1 title and first prose paragraph to `README.md` (WP-PACKAGING): satisfies `tests/test_readme_first_paragraph.py` (was 0 lines, 2 test failures). Paragraph is pure prose, 194 chars, no repo name, no links. Added Quick start section and links to `docs/INSTALL.md` and `docs/USAGE.md`.

- Created `airplay2tv/doctor.py` (WP-DOCTOR): `run_checks(device=None, input_file=None) -> int` prints PASS/FAIL/INFO/WARN lines for: ffmpeg on PATH (shutil.which), ffprobe on PATH, local address selection (netutil.local_ip_for to 192.168.1.1), active backend count (registry.active_backends), AirPlay/backend discovery count (aggregate.discover_all), Roku SSDP stats (probes_sent/valid/duplicates/malformed/timeout via roku_ssdp.discover), per-device pairing state (paired/not paired/pairing needs refresh via credentials.get_record), and an optional media-prep dry run (inspect + decide per backend profile) when input_file is given. device filter narrows the per-device pairing report to matching name or identifier (case-insensitive). Required checks (ffmpeg, ffprobe, address) contribute to the return code; advisory checks (discovery, pairing, media dry-run) print WARN/INFO but do not affect the exit code. asyncio.run drives the async discovery; no shebang (library module).
- Created `tests/test_doctor.py`: 4 offline unit tests using monkeypatch covering all-pass returns 0, ffmpeg-absent returns non-zero, device filter limits per-device output, and address-fail returns non-zero. All 4 pass in 0.02 s.

- Created `tests/e2e/e2e_make_fixtures.py` (WP-FIXTURES): E2E fixture generator that uses ffmpeg lavfi testsrc + sine to produce three deterministic sub-1MB media files in `tests/fixtures/` (gitignored): `sample_h264.mp4` (H.264/AAC, drives passthrough), `sample_h264.mkv` (H.264/AAC in Matroska, drives remux), and `sample_hevc.mp4` (H.265/HEVC, drives transcode against Roku profile). Verifies codec via ffprobe and prints path/size/codec for each fixture. Exits non-zero with a clear message if ffmpeg is missing. Added `tests/fixtures/` to `.gitignore`.
- Added `devel/proof_airplay.py` (WP-PROOF-AIRPLAY, M1): hardware-proof script that scans with pyatv, connects to a real Apple TV, serves a sample MP4 over a minimal stdlib threaded HTTP server (logging the device's HTTP Range requests), calls `atv.stream.play_url(url)`, polls `metadata.playing().device_state`, and reports the pyatv services list with each service's `PairingRequirement`. Prints a REQUIRED-OUTPUT block (whether AirPlay pairing is Mandatory + the working play_url form) for the M3 AirPlay backend. Throwaway devel proof; the user must run it on real hardware.
- Added `devel/proof_roku.py` (WP-PROOF-ROKU, M1): hardware-proof script that SSDP-discovers a Roku (ST roku:ecp via raw UDP M-SEARCH), parses Location, GETs `/query/device-info` and `/query/apps` (confirming app 2213 is present), serves a sample MP4 locally, launches Roku Media Player via `rokuecp.Roku.launch(app_id, params)` trying BOTH documented param casings (`contentId`/`mediaType` and `contentID`/`MediaType`), and confirms real playback via `/query/active-app` and `/query/media-player` (`state="play"`, not HTTP 200 alone). Prints raw curl equivalents in the docstring and a REQUIRED-OUTPUT block (launch endpoint, app id, working casing, exact rokuecp method/arg names + sample responses) for the M3 Roku backend. Throwaway devel proof; the user must run it on real hardware.
- Created `airplay2tv/` Python package skeleton with one-line-docstring `__init__.py`.
- Created `airplay2tv/backends/` sub-package with one-line-docstring `__init__.py`.
- Created `airplay2tv/discovery/` sub-package with one-line-docstring `__init__.py`.
- Created `pyproject.toml` with minimal `[project]` table: name, version 26.06, description, requires-python >=3.12.
- Created `airplay2tv/backends/base.py`: the frozen backend contract. Dataclasses `Device`, `MediaProfile`, `PlaybackStatus`, `PairingRecord`; `PairingState` enum (PAIRED, NOT_PAIRED, NEEDS_REFRESH); async `Backend` ABC (`discover`, `media_profile`, `play`, `stop`, `status`, `needs_pairing`, `pair`, `is_paired`). Imports nothing from other airplay2tv modules and nothing from pyatv/rokuecp; `play`'s `media` arg is typed `object` since `media.py` owns its concrete type.
- Created `tests/test_backend_contract.py`: a `FakeBackend(Backend)` implementing every abstract method with a simulated 4-digit PIN challenge via the `prompt_pin` callback, asserting the ABC is satisfiable and the pairing handshake exercises the callback.
- Created `airplay2tv/netutil.py` (WP-NETUTIL): `local_ip_for(target)` returns the routable LAN-facing interface IP by UDP-dialing the target without sending packets; `pick_free_port(start=3500)` returns the first bindable TCP port and raises after a bounded sweep.
- Created `airplay2tv/httpserver.py` (WP-HTTP-RANGE): `serve(path, bind_host, advertised_host)` starts a threaded `ThreadingHTTPServer` serving a single file with full range support (HEAD, full GET, valid 206 Range, open-ended Range, 416 out-of-range); the returned URL is built from `advertised_host` while the server binds to `bind_host`. `shutdown(server, thread)` stops the server and joins the serving thread.
- Created `tests/test_netutil.py` and `tests/test_httpserver.py`: unit tests for the netutil functions and the full HTTP range matrix, including a no-thread-leak check after shutdown.
- Created `airplay2tv/discovery/roku_ssdp.py` (WP-ROKU-SSDP): async `discover(timeout=3)` over `asyncio.DatagramProtocol` plus a pure, network-free `parse_response()` parser. Parser reads UPnP header names case-insensitively, tolerates a missing Cache-Control, rejects non-200 / non-`roku:ecp` / Location-less replies, and dedupes by USN. `RokuResponder` carries location, ip, port, usn, st, server, cache_control, and the raw header dict; `DiscoveryStats` reports probes_sent, valid_responses, duplicates, malformed, and timed_out. The datagram transport is always closed via `finally`. Clean-room from the ECP protocol behavior (no python-roku code copied).
- Created `tests/test_roku_ssdp.py`: 14 offline unit tests covering the valid response, case-insensitive headers, missing Cache-Control, malformed reply, non-Roku ST, missing Location, non-200 status, default ECP port, and USN dedupe.
- Created `airplay2tv/config.py` (WP-CONFIG): non-secret settings only. `load() -> dict` reads `~/.config/airplay2tv/config.yaml` (honoring `XDG_CONFIG_HOME`); a missing file returns an empty default without error. `save(config)` writes atomically via `tempfile.mkstemp` + `os.replace` in the same directory. Helpers: `add_device`, `get_device`, `get_default_device_id`, `set_default_device_id`. Stores device records (name, backend, identifier, address) and a default device id only; no credential payload.
- Created `tests/test_config.py`: 5 pytest tests covering load-missing yields empty config, save+load round-trip, atomic save leaves no .tmp files, default-device get/set, and that the saved YAML file contains no credential-like key.
- Created `airplay2tv/credentials.py` (WP-CREDENTIALS): pairing record storage. `load() -> dict[tuple[str,str], PairingRecord]` reads `~/.config/airplay2tv/credentials.yaml` (honoring `XDG_CONFIG_HOME`); a missing file returns an empty dict without error; a file with permissions looser than 0600 is loaded but triggers a `logging.WARNING` advising `chmod 600`. `save_record(record)` merges the new record into the existing store and writes atomically (temp file + `os.replace`) with mode 0600 asserted before rename and after. `get_record(identifier, backend)` returns the matching `PairingRecord` or `None`. Stores only credential/pairing data; no device preferences. Imports `PairingRecord` from `airplay2tv.backends.base`; does not redefine it.
- Created `tests/test_credentials.py`: 7 pytest tests covering load-missing returns empty dict; save+load round-trip for a string credential; file mode is 0600 after save; a pre-existing 0644 file triggers a warning and still loads; credentials file path ends with `credentials.yaml` (not `config.yaml`); `get_record` returns `None` for an absent device; `get_record` returns the saved `PairingRecord`.
- Created `airplay2tv/logging_setup.py` (WP-CLI-SKELETON): `configure(verbose, debug)` sets the root log level (WARNING normally, INFO under verbose, DEBUG under debug) and records a module-level `DEBUG_ENABLED` flag; `show_tracebacks()` reports it so the CLI prints full tracebacks only under debug.
- Created `airplay2tv/backends/registry.py` (WS-CORE-IFACE registry portion): `active_backends() -> list[Backend]` walks `BACKEND_SPECS`, imports each concrete backend lazily, and skips a not-yet-built backend with a DEBUG log line rather than raising. Construction-only, no business logic. Returns `[]` today because `airplay.py`/`roku_ecp.py` (M3) are not implemented; a TODO points at those tasks.
- Created `airplay2tv/cli.py` (WP-CLI-SKELETON): argparse surface with the stream-action flags (`-i/--input` dest input_file, `-d/--device` dest device, `--bind` dest bind_host, `--save-device` dest save_device store_true, `--default-device` dest default_device, `-v/--verbose` dest verbose store_true, `--debug` dest debug store_true) and a mutually-exclusive media-mode group (`--passthrough`/`--transcode` to dest media_mode store_const, default None meaning automatic). Subcommands `pair`, `doctor`, `devices`. `main()` calls `logging_setup.configure` then `asyncio.run(app.run(args))`, importing `airplay2tv.app` lazily so `--help` works before `app.py` exists.
- Created `airplay2tv/__main__.py` (WP-CLI-SKELETON, runnable entry): `#!/usr/bin/env python3` shebang on line 1, executable bit set, imports `airplay2tv.cli` and calls `main()`. It is the package entry point so `python3 airplay2tv --help` and `python3 -m airplay2tv` both work.
- Created `airplay2tv/errors.py`: minimal typed error hierarchy with base `Airplay2tvError` and subclasses `UnsupportedMediaError` (forced passthrough of media the device cannot play) and `PreparationError` (ffmpeg remux/transcode failure or low disk space). Lets the CLI catch one base type and print readable one-line messages.
- Created `airplay2tv/media.py` (WP-MEDIA-INSPECT, WP-MEDIA-PREPARE): `MediaInfo` dataclass (container, video_codec, audio_codec, duration) and `PreparedMedia` dataclass (served path, content_type); `inspect(path)` parses `ffprobe -v quiet -print_format json -show_format -show_streams` output with direct `dict[key]` access; pure `decide(info, profile, mode_override=None)` returns `passthrough`/`remux`/`transcode` against a backend `MediaProfile` (codecs+container in profile -> passthrough; codecs in profile, container not -> remux; otherwise transcode), with `mode_override='transcode'` always transcoding and `mode_override='passthrough'` raising `UnsupportedMediaError` when the profile rejects the file; `prepare(path, profile, tmpdir, on_progress, cancel_event, mode_override=None) -> PreparedMedia` runs the decided ffmpeg path into `tmpdir` (remux `-c copy`, transcode to the portable MP4 H.264 via libx264 / AAC baseline identical on macOS and Debian), parses `-progress pipe:1` `out_time_ms` into a clamped [0,1] fraction for `on_progress`, honors `cancel_event` by terminating ffmpeg, removes partial output on every cancel/failure path, and checks free disk space before a transcode. The ISO BMFF family (`mov`/`mp4`/`m4v`, which ffprobe reports as `mov` first even for .mp4) maps to `video/mp4` content type.
- Created `tests/test_media_decision.py`: 9 pure pytest cases (no ffmpeg) exercising `decide` against an AirPlay profile (H.264+H.265/AAC) and a Roku profile (H.264/AAC) -- including H.265 vs Roku -> transcode, H.265 vs AirPlay -> passthrough, H.265 MKV vs AirPlay -> remux, forced-passthrough on Roku H.265 raising `UnsupportedMediaError`, and forced-transcode always returning transcode.
- Created `tests/e2e/e2e_media_prepare.py` (WP-MEDIA-PREPARE): non-pytest E2E that generates tiny lavfi fixtures (MP4 H.264, MKV H.264, MP4 H.265) and exercises the real ffmpeg-backed `prepare()` passthrough, remux, and transcode paths, asserting outputs exist (transcode output reinspected as H.264/AAC) and that a pre-set `cancel_event` raises `PreparationError` and leaves the temp dir empty. Bootstraps the repo root onto `sys.path` via `git rev-parse` since it runs outside pytest.
- Created `airplay2tv/backends/airplay.py` (WP-BACKEND-AIRPLAY, M3): `AirPlayBackend(Backend)`, the sole importer of pyatv. `discover()` calls `pyatv.scan(protocol=AirPlay)` and maps each config to `base.Device` (name, backend "airplay", identifier, address, model from `device_info.model_str`). `media_profile()` returns containers mp4/mov/m4v, video h264/hevc, audio aac (Apple TV decodes HEVC). Each control call scans by identifier, applies the stored credential via `config.set_credentials(Protocol.AirPlay, ...)`, and `pyatv.connect`s: `play()` calls `atv.stream.play_url(media_url)`, `stop()` calls `atv.remote_control.stop()`, `status()` maps `atv.metadata.playing()` (`device_state`, `position`, `total_time`) to `PlaybackStatus`. A missing pairing record (`credentials.get_record` returns None) and a `pyatv.exceptions.AuthenticationError` both raise `errors.PairingRequiredError`. Cleanup uses the synchronous `atv.close()` (returns a set) and never awaits it. `pair()` runs the pyatv AirPlay handshake (`pyatv.pair` -> `begin()` -> `pin(prompt_pin())` -> `finish()`), reads `pairing.service.credentials` on success, and returns a `PairingRecord`; `needs_pairing`/`is_paired` derive from the stored record plus the service's Mandatory pairing requirement.
- Created `tests/test_airplay_backend.py` (WP-BACKEND-AIRPLAY): 10 offline pytest tests with pyatv fully mocked via `unittest.mock` (no hardware, no PIN). Covers discover mapping, media-profile codecs, play loading credentials by (identifier, backend) and awaiting `play_url`, play closing without awaiting `close()`, missing-record raising `PairingRequiredError`, `AuthenticationError` raising `PairingRequiredError` while still closing, status metadata mapping, the pair handshake returning a record, `is_paired` reflecting the stored record, and a backend-isolation walk asserting `import pyatv` appears in no airplay2tv module except `airplay.py`.
- Created `airplay2tv/backends/roku_ecp.py` (WP-BACKEND-ROKU, M3): `RokuEcpBackend(Backend)`, the sole importer of `rokuecp`. `discover()` runs `roku_ssdp.discover()` and maps each responder to `base.Device` (backend "roku-ecp", identifier = SSDP USN, address = responder IP), reading friendly name and model from a short-lived `rokuecp.Roku.update()` device-info; a responder whose update is blocked still yields a Device named by its IP. `media_profile()` returns containers mp4/mov/m4v, video h264 ONLY (the user's Roku TV transcodes H.265 down), audio aac. `play()` POSTs `launch/2213` (Roku Media Player) with params `contentId=<served URL>`, `mediaType="movie"` (movie hardcoded). `stop()` sends the `home` remote key. `status()` maps `update().media` (a rokuecp `MediaState`) to `PlaybackStatus` (playing/paused with position+duration in seconds, or idle when no session). Roku ECP uses no PIN: `needs_pairing` is False, `is_paired` is PAIRED, and `pair()` returns a trivial `PairingRecord` with credential `{"ecp": "allowed"}` without invoking `prompt_pin`. Any ECP HTTP 403 (detected via `rokuecp.RokuError` status-code/message) is translated into `errors.DeviceUnreachableError` whose message names "Settings > System > Advanced system settings > Control by mobile apps"; other `RokuError`s are wrapped as `DeviceUnreachableError` too. A module-level `RokuBackend = RokuEcpBackend` alias lets `backends.registry.BACKEND_SPECS` (which names `RokuBackend`) resolve the class without editing the registry. DOCUMENTED ASSUMPTION in `play`: the launch param casing `contentId`/`mediaType` is the default but is UNVERIFIED on hardware (M1's 403 blocked every launch); confirm on a live launch once "Control by mobile apps" is enabled, and retry with `contentID`/`MediaType` if a 200 does not actually start playback.
- Created `airplay2tv/errors.py` addition: `DeviceUnreachableError(Airplay2tvError)` raised when a backend cannot reach or control a device (the Roku backend raises it on ECP HTTP 403, naming the TV setting to enable).
- Created `tests/test_roku_ecp.py` (WP-BACKEND-ROKU): 11 offline pytest tests driving the backend against a local stdlib `http.server` fake ECP responder (no real Roku), via `asyncio.run()` since pytest-asyncio is not installed. The fake records request paths and serves canned ECP XML (device-info, active-app, apps, media-player). Covers launch param building (`contentId`/`mediaType=movie`), `play()` POSTing `launch/2213?contentId=<url-encoded>&mediaType=movie`, `stop()` sending `keypress/Home`, status mapping (playing/paused/idle), a 403 fake raising `DeviceUnreachableError` whose message names "Control by mobile apps", the H.264-only/AAC/MP4-family profile, `needs_pairing` False + PAIRED, the trivial pair record that never calls `prompt_pin`, and a package walk asserting `rokuecp` is imported only by `roku_ecp.py`.

- Created `airplay2tv/app.py` (WS-APP): synchronous dispatcher `run(args) -> int` routing on `args.command`. None/`stream` runs the full async stream flow: `aggregate.discover_all(registry.active_backends(), DISCOVERY_TIMEOUT)` (empty -> clear message + non-zero), `devicepick.select`, inline pairing when the backend needs it and stdin is a TTY (`backend.pair(device, prompt_pin)` then `credentials.save_record`) else `PairingRequiredError` pointing at `airplay2tv pair`, `media.prepare` into a `tempfile.mkdtemp` dir, `netutil.local_ip_for` + `httpserver.serve(bind_host=args.bind_host or "0.0.0.0", advertised_host=local_ip)`, `backend.play(device, url, prepared)`, a status banner (device name + stream URL + "Press Ctrl+C to stop."), and a Ctrl+C wait. A single `finally` shuts the server down and removes the temp media dir on every exit path (success, failure after prepare, failure after serve, Ctrl+C). `--save-device` persists the device via `config` after playback starts. `devices` prints `devicepick.render` and returns 0. `doctor` lazily imports `airplay2tv.doctor` and returns `run_checks(device, input_file)`. `pair` lazily imports `airplay2tv.pairing` (handles a not-yet-built module with a clear message). `backend_for_device` matches the device's backend key against each backend's `backend_key` instance attribute or `BACKEND_KEY` module constant, falling back to the sole active backend.
- Added `airplay2tv/errors.py` addition: `PairingRequiredError(Airplay2tvError)` raised when a device needs PIN pairing but no controlling TTY is available; the message points the user at `airplay2tv pair`.
- Created `tests/test_app_flow_fakebackend.py` and `tests/test_app_cleanup.py` (WS-APP): 6 offline pytest tests injecting a `FakeBackend` (no pyatv/rokuecp/hardware) and stubbing `media.prepare`, `httpserver.serve/shutdown`, and `netutil.local_ip_for`. Cover a full stream run starting playback against the advertised URL and returning 0, server shutdown + temp-dir removal on clean exit, no-devices returning non-zero, temp-dir removal when prepare fails, temp-dir removal + server shutdown when play fails after serve, and a non-interactive unpaired device raising `PairingRequiredError`.

### Behavior or Interface Changes

- The stream action now tries a direct address probe before falling back to the picker
  (WP-ROKU-DIRECT-IP): `app.run_stream` calls `resolve_known_address(backends, args, devices)` first;
  a bare-IP `--device` not already among discovered devices, or a default/saved device whose stored
  address discovery missed, is resolved through the backend `resolve_address` hook and used directly.
  When the IP path yields nothing, the prior discovery + `select_device` picker behavior is unchanged
  (the no-devices message still fires only when nothing resolves and discovery is empty). This makes a
  known Roku IP usable when SSDP is silent without changing name/id selection.

- Unified the backend-key convention on a single `backend_key` class attribute (WS-APP-FINALIZE): added `backend_key: str = ""` to the `Backend` ABC in `airplay2tv/backends/base.py`; replaced the module-level `BACKEND_KEY = "airplay"` constant in `airplay2tv/backends/airplay.py` with a `backend_key = "airplay"` class attribute (internal references now use `self.backend_key`); moved the Roku backend's `self.backend_key = "roku-ecp"` from `__init__` to a `backend_key = "roku-ecp"` class attribute in `airplay2tv/backends/roku_ecp.py`. Each backend stamps its `backend_key` onto every `Device.backend` it emits. `app.backend_for_device` now matches `device.backend` to `candidate.backend_key` by exact equality and raises `Airplay2tvError` on no match; removed the fragile `backend_key()` helper (which probed for an instance attribute then a module `BACKEND_KEY`) and the single-active-backend fallback guess.
- Wired `--default-device` and the stored default into the stream action (WS-APP-FINALIZE): `app.run_stream` now selects the device via `select_device`, which skips the interactive picker when an explicit `--device`, a `--default-device` id, or the saved `config.default_device_id` names a discoverable device, and prints a "Default device ... is not reachable right now; falling back to discovery." notice on stderr before deferring to the picker when the preferred id is absent. Previously `--default-device` was parsed but ignored.
- Persist on success now covers both record and default (WS-APP-FINALIZE): the stream action calls `persist_device` after `backend.play` returns, replacing the prior `save_device` call. `--save-device` writes the device record; a `--default-device` matching the played device's identifier also sets `config.default_device_id`, both in one atomic config write.
- Stop playback on Ctrl+C and show a status banner (WS-APP-FINALIZE): `app.run_stream` now wraps `wait_for_interrupt()` in a `KeyboardInterrupt` handler that prints "Stopping playback..." and awaits `backend.stop(device)` while the event loop is still alive, then the existing `finally` block releases the HTTP server and temp media. The status banner (device name, served URL, "Press Ctrl+C to stop.") prints once playback starts.
- Raised `app.DISCOVERY_TIMEOUT` from 5.0 s to 7.0 s and pinned the AirPlay scan to a bounded 5 s window (WS-APP-FINALIZE): `airplay2tv/backends/airplay.py` `discover()` now passes `timeout=SCAN_TIMEOUT` (5 s, a new module constant matching the pyatv default and the M1 hardware proof) to `pyatv.scan`. The aggregate discovery budget sits above the scan window so a full mDNS scan completes inside the shared `asyncio.wait_for`; the prior 5.0 s aggregate budget raced the 5 s default scan and could cancel it mid-flight, reporting zero devices even when a receiver was present (live doctor found 0 where the M1 proof found the TV).

- Changed `airplay2tv.app.run` from a coroutine to a synchronous dispatcher and `airplay2tv/cli.py` `main()` to call `app.run(args)` directly (no longer `asyncio.run(app.run(args))`) (WS-APP): the doctor and pair subcommand handlers run their own `asyncio.run` internally, so wrapping the whole dispatch in one event loop nested loops and failed with "asyncio.run() cannot be called from a running event loop". The app now drives only the async stream/devices actions through `asyncio.run`, keeping exactly one running loop at a time. `main()` now propagates the handler exit code via `sys.exit`.
- Extended `airplay2tv/cli.py` subparsers (WS-APP): each subcommand (`pair`, `doctor`, `devices`) now carries the shared `-v/--verbose` and `--debug` flags (added via a new `add_logging_arguments` helper) so `main()` can always read `verbose` and `debug`; `pair` and `doctor` carry `-d/--device` and `doctor` also carries `-i/--input` (dest `input_file`) for `doctor.run_checks`.
- Updated `pip_requirements.txt`: added `rokuecp` (Roku ECP client) and `pyyaml` (YAML parsing).
- Updated `Brewfile`: changed bare token `ffmpeg` to proper Homebrew syntax `brew "ffmpeg"`.
- Added `[tool.pytest.ini_options]` to `pyproject.toml` with `pythonpath = ["."]` so tests import the `airplay2tv` package directly from the repo root without an editable install.

### Fixes and Maintenance

- Removed planning-scaffolding tags (WS-PAIR, WP-AIRPLAY, WP-ROKU, M1, M3) from
  shipped code comments and docstrings in `airplay2tv/app.py`,
  `airplay2tv/backends/registry.py`, `airplay2tv/backends/roku_ecp.py`,
  `airplay2tv/backends/airplay.py`, and `tests/test_airplay_backend.py`. Technical
  facts were preserved; only the milestone and workstream labels were removed.
- Added `defusedxml` to `docs/INSTALL.md` dependencies table and to the
  `HomebrewFormula/airplay2tv.rb` resource list.
- Documented `airplay2tv doctor --device <IP>` direct-ECP probe behavior in
  `docs/USAGE.md`: per-endpoint status, extracted fields
  (`ecp-setting-mode`/`power-mode`/`friendly-device-name`), SSDP-vs-direct
  summary, and the direct-IP bypass path for the stream action.
- Corrected `docs/INSTALL.md` and `docs/USAGE.md` (setup-install-usage-docs pass):
  fixed two wrong GitHub clone URLs (`neilvoss/airplay2tv` -> `vosslab/airplay2tv`);
  fixed macOS verify command from `python3 airplay2tv --help` to
  `python3 -m airplay2tv --help`; fixed Quick start command in `docs/USAGE.md` from
  `python3 airplay2tv` to `python3 -m airplay2tv`; updated `-d` flag description to
  note that a bare IPv4 address is also accepted (confirmed in `app.py` `looks_like_ip`).
- Standardized `README.md` (readme-docs pass): fixed quick-start command from
  `python3 airplay2tv --input movie.mp4` to `source source_me.sh && python3 -m airplay2tv -i movie.mp4`;
  added `docs/CODE_ARCHITECTURE.md` to the Documentation links section; moved
  Documentation section before Quick start for scannability.
- Added `resolve_address` to the Backend contract method list in
  `docs/CODE_ARCHITECTURE.md`; added `CredentialsError` to the error hierarchy
  note in both `docs/CODE_ARCHITECTURE.md` and `docs/FILE_STRUCTURE.md`; added
  direct-IP resolution path note to the stream action flow description.
- Updated `docs/active_plans/reports/airplay2tv_build_summary.md`: corrected
  test count from 919 to 953 and replaced the stale "audit folder is empty" note
  with a link to the existing audit file.
- Updated `README.md` quick-start command to use
  `source source_me.sh && python3 airplay2tv` to match `docs/AGENTS.md` and
  `docs/USAGE.md`.
- `airplay2tv/cli.py`: replaced `sys.exit(exit_code)` with
  `raise SystemExit(exit_code)` per repo style (prefer raise over sys.exit).
- `airplay2tv/doctor.py`: narrowed `except Exception` in `_run_media_dry_run` to
  `except errors.PreparationError`; added `import airplay2tv.errors` to support
  the narrowed clause. Unexpected non-PreparationError exceptions now propagate
  instead of being silently printed.

- Fixed signature-drift regression in `tests/e2e/e2e_headless_pair_play.py`: the
  `fake_prepare` stub inside `install_offline_stubs` was missing the `cancel_event:
  threading.Event` 4th parameter added to `app.prepare_media` in the Ctrl+C audit fix,
  causing `TypeError: fake_prepare() takes 3 positional arguments but 4 were given`.
  Updated the stub signature to match the real `prepare_media` signature
  (`args, profile, temp_dir, cancel_event`) with full type hints. Added `import threading`
  to the Standard Library imports block. All 13 E2E sub-cases now pass (exit 0).

- Fixed `airplay2tv/media.py` `decide()` empty-codec defect (audit finding 4, HIGH): `_codecs_supported` previously treated an empty codec token (a missing stream, or a present stream whose `codec_name` ffprobe did not report) as supported, so a video-only or codec-missing file was served passthrough without conversion. Tightened the rule so an empty required codec is not in any profile and therefore unsupported; because an unknown codec cannot be served as-is or fixed by a stream-copy remux, `decide()` now routes an empty required codec to `transcode`. Documented the rule in `_codecs_supported` and the `decide()` docstring. Added `tests/test_media_decision.py` cases for empty audio codec, empty video codec, and both-empty in a supported container, asserting `transcode` (not passthrough/remux).
- Fixed `airplay2tv/media.py` `prepare()` remux disk-space gap (audit finding 14, LOW): `_check_disk_space` ran only before transcode, but a large remux writes a comparably sized new file into tmpdir. Added the same headroom check before the remux branch so a short-on-space remux raises `PreparationError` before any ffmpeg process starts. Updated `_check_disk_space` docstring and the `DISK_SPACE_HEADROOM` comment to cover both modes. Added `tests/test_media_decision.py::test_remux_disk_check_raises_when_space_short` (monkeypatches `shutil.disk_usage` to report insufficient free space and `media._run_ffmpeg` to fail if invoked; asserts `PreparationError`).
- Documented `airplay2tv/media.py` `_consume_progress` cancellation-latency bound (audit finding 13, LOW): added a docstring note that `cancel_event` is checked once per ffmpeg progress line, so the worst-case delay between setting the event and terminating the process is one progress-update interval (roughly 0.5-1 s), not unbounded. No behavior change.

- Fixed finding 2 (HIGH) in `airplay2tv/credentials.py`: `save_record` now holds an exclusive
  `fcntl.flock` on a companion lock file (`credentials.yaml.lock`) across the entire
  load-merge-write window, preventing two concurrent callers from silently discarding each
  other's records. The atomic temp-file replace and 0600 mode are unchanged. Added
  `CredentialsError` subclass to `airplay2tv/errors.py` for malformed-file diagnostics.
  Fixed finding 11 (LOW): `load()` now raises `CredentialsError` with the file path when
  the top-level YAML value is not a list (e.g. a hand-edited dict), replacing a bare
  `KeyError` on `entry["identifier"]`. Added two new tests to `tests/test_credentials.py`:
  `test_concurrent_save_both_records_survive` (two threads; both records present after join)
  and `test_load_non_list_yaml_raises_credentials_error` (dict YAML triggers `CredentialsError`).
  All 9 credential tests pass in 0.03 s.

- Added `pytest.MonkeyPatch`, `pathlib.Path`, `pytest.LogCaptureFixture` type annotations to all
  unannotated pytest fixture parameters in `tests/test_app_cleanup.py`,
  `tests/test_app_flow_fakebackend.py`, `tests/test_config.py`, `tests/test_credentials.py`,
  `tests/test_httpserver.py`, `tests/test_pairing_fakebackend.py`, and `tests/test_roku_ecp.py`;
  added `-> None` / return annotations to all `test_*` and helper functions (`patch_common`,
  `failing_prepare`, `fake_prepare`, `fake_serve`, `fake_shutdown`, `_install_fake_backend`,
  `fake_discover_all`, `_make_handler`, `_start_fake`, `served_file`); added missing `import pytest`
  and `import pathlib` where needed. Satisfies `tests/test_function_typing.py` gate (136 pass).
- Added `# nosec` suppression comments to intentional security patterns: `B104` (bind `"0.0.0.0"`)
  in `airplay2tv/app.py`, `tests/test_httpserver.py`, `tests/test_app_cleanup.py`, and
  `tests/test_app_flow_fakebackend.py`; `B310` (urlopen) in `devel/proof_roku.py` and
  `tests/e2e/e2e_debian_smoke.py`; `B108` (hardcoded `/tmp` path) in
  `tests/e2e/e2e_headless_pair_play.py`. Each comment includes a short justification string.
  Satisfies `tests/test_bandit_security.py` gate (68 pass). Full suite: 919 passed.

- Fixed `airplay2tv/config.py` `load()` shallow-copy defect: replaced `dict(DEFAULT_CONFIG)` with `copy.deepcopy(DEFAULT_CONFIG)` so the returned `devices` list is always a fresh object; the first caller to `add_device` on a no-file config can no longer mutate the shared module-level `DEFAULT_CONFIG["devices"]` and leak state into later callers or tests. Added regression test `test_two_independent_loads_do_not_share_devices_list` to `tests/test_config.py` (adds a device to one load result, asserts the other stays empty). 459 tests pass, 1 skipped.

- `pip_requirements-dev.txt` already contained `pytest`; no change required.
- Applied review cleanups to M2 modules: added `# Standard Library` / `# PIP3 modules` import headings and reduced `except` body to two lines in `airplay2tv/config.py`; narrowed `addr: tuple` to `tuple[str, int]` in `airplay2tv/discovery/roku_ssdp.py`; replaced `asyncio.get_event_loop()` with `asyncio.get_running_loop()` in `devel/proof_airplay.py`; added module docstring to `tests/test_netutil.py`; fixed `_make_config_dir` param annotation to `pathlib.Path` in `tests/test_config.py`.
- Fixed `devel/proof_airplay.py` (WP-PROOF-AIRPLAY): `atv.close()` is synchronous in pyatv (returns `Set[asyncio.Task]`); removed the `await` that caused `TypeError: object set can't be used in 'await' expression`. Added a focused `except pyatv.exceptions.AuthenticationError` inside the try/finally so the REQUIRED-OUTPUT summary block is always printed even when `play_url` raises (pairing mandatory case); `playback_state` is set to the error string so the summary captures the evidence.
- Fixed `devel/proof_roku.py` (WP-PROOF-ROKU): added `import urllib.error`; wrapped `ecp_get` call sites for `/query/device-info` and `/query/apps` with a two-line `try/except urllib.error.HTTPError`; added `_handle_ecp_forbidden(exc, host)` helper that checks for code 403, prints a clear message directing the user to enable Settings > System > Advanced system settings > Control by mobile apps on the Roku, prints a partial REQUIRED-OUTPUT block with the host and blocked status, and raises `SystemExit(1)` so the script exits non-zero without a traceback. Non-403 HTTPErrors are re-raised so unexpected errors still surface.

- Fixed `airplay2tv/backends/airplay.py` `pair()` (finding 3, HIGH): restructured so
  `has_paired` and `credential` are captured before `pairing.close()` is called. `close()` now
  runs in its own guarded `try/except Exception: pass` step so a teardown failure cannot swallow
  the `PairingRequiredError` raised when the PIN is wrong. Added
  `test_pair_close_raising_does_not_mask_pairing_error` to `tests/test_airplay_backend.py`:
  `close()` is mocked to raise `RuntimeError`; `has_paired=False`; asserts `PairingRequiredError`
  surfaces, not the close error.

- Fixed `airplay2tv/backends/roku_ecp.py` `_status_from_media()` (finding 8, MEDIUM): guarded
  each `float()` call with `float(v) if v is not None else None` so a live stream or device
  firmware that omits position or duration no longer raises `TypeError`. Added
  `test_status_from_media_none_position_duration_no_type_error` to `tests/test_roku_ecp.py`:
  a mock `MediaState` with `position=None` and `duration=None` produces a `PlaybackStatus`
  with `position=None` and `duration=None` without raising.

- Added TODO comment to `airplay2tv/backends/roku_ecp.py` `_build_launch_params()` (finding 7,
  MEDIUM comment-only): documents that if a live launch returns HTTP 200 but does not start
  playback, the caller should retry with alternate casing `contentID`/`MediaType` instead of
  `contentId`/`mediaType`; the current casing was not verified on hardware during M1 because the
  403 blocked every launch attempt.

- Fixed finding 10 (LOW): removed the single-backend fallback from `pairing._find_backend`.
  The old fallback returned the one active backend when no `backend_key` matched, while
  `app.backend_for_device` raises on any key mismatch; a device with a mismatched backend field
  would behave differently depending on which code path ran. `_find_backend` now performs an
  exact `backend_key` match only and returns `None` on mismatch, matching
  `app.backend_for_device`. Added two tests to `tests/test_pairing_fakebackend.py`:
  `test_find_backend_exact_key_match` (correct key returns the backend) and
  `test_find_backend_mismatched_key_returns_none` (wrong key returns None, not the single backend).

- Fixed finding 6 (MEDIUM): changed `airplay2tv/discovery/aggregate.py` `discover_all` from a
  single shared `asyncio.wait_for` wrapping the whole gather to per-backend `asyncio.wait_for`
  calls inside `_safe_discover`. A slow backend can no longer cancel a fast backend's
  in-progress `discover()` coroutine mid-gather; each backend times out independently.
  Updated docstring: `timeout` is now documented as a per-backend limit, not a total budget.
  Added `test_slow_backend_does_not_cancel_fast_backend` to `tests/test_discovery_merge.py`:
  a `SlowBackend` sleeping 0.5 s times out under a 0.05 s per-backend limit while a
  `FakeBackend` still contributes its device to the merged result; runs in under 0.1 s.

- Added comment at the multi-range branch in `airplay2tv/httpserver.py`
  `parse_range_header` (finding 12, LOW): explains that a comma-containing multi-range
  request returns 416 by design (single-range only per plan scope) so reviewers know
  the 416 is intentional, not a bug. No behavior change.

- Fixed `airplay2tv/app.py` `run_stream` KeyboardInterrupt-during-prepare gap (finding 1,
  HIGH): hoisted `cancel_event` creation from `prepare_media` into `run_stream` so the
  `except KeyboardInterrupt` handler can call `cancel_event.set()` before
  `backend.stop(device)`, signalling any in-flight ffmpeg transcode to terminate and
  remove its partial output. `prepare_media` now accepts `cancel_event` as a parameter.
  Updated all monkeypatched `prepare_media` stubs in `tests/test_app_cleanup.py` and
  `tests/test_app_flow_fakebackend.py` to accept the new parameter. Added
  `test_keyboard_interrupt_during_prepare_sets_cancel_event_and_cleans_temp` to
  `tests/test_app_cleanup.py`: monkeypatches `prepare_media` to raise `KeyboardInterrupt`,
  asserts `cancel_event.is_set()` and temp dir is removed.

- Fixed `airplay2tv/app.py` `select_device` headless-unreachable-default gap (finding 9,
  MEDIUM): when `--default-device` names an identifier not on the network and there is no
  TTY, `select_device` now raises `Airplay2tvError("no device selected and no terminal to
  prompt; pass --device or pair first")` instead of falling through to
  `devicepick.select(devices, None)` which raised a raw `ValueError`. Added
  `test_headless_unreachable_default_raises_clear_error` to `tests/test_app_cleanup.py`:
  patches `isatty` to False and `--default-device` to an absent id, asserts
  `Airplay2tvError` with message containing `--device` or `pair`. Updated
  `test_select_device_falls_back_when_default_unreachable` in `tests/test_app_flow.py` to
  patch `isatty` to True so the TTY fallback path is tested separately. 940 tests pass.

- Refreshed `docs/CODE_ARCHITECTURE.md` and `docs/FILE_STRUCTURE.md` (arch-docs pass):
  corrected the stream action flow description -- `resolve_known_address` handles two
  cases (bare `--device <ip>` not in discovered list, and saved/default device whose
  stored address discovery missed); updated the data-flow diagram to show
  `resolve_known_address` -> `resolve_via_backends` as a step between
  `aggregate.discover_all` and `select_device`; added `fcntl.flock` note to the
  `credentials.py` description in both docs; added the two missing e2e scripts
  (`e2e_debian_smoke.py` and `e2e_headless_pair_play.py`) to the `tests/e2e/`
  section of `FILE_STRUCTURE.md`. No regressions to `resolve_address` or
  `CredentialsError` entries already present.

### Decisions and Failures

- Plan contradiction resolved (WP-CLI-SKELETON): the plan lists both the `airplay2tv/` package directory and a same-named `airplay2tv` root entry script at the repo root, which cannot coexist at one filesystem path. Resolved by making the runnable entry `airplay2tv/__main__.py`; `python3 airplay2tv` runs the package's `__main__.py`, satisfying the `airplay2tv --help` acceptance command without a name collision. `__main__.py` prepends the repo root to `sys.path` so the absolute import `airplay2tv.cli` resolves when run as `python3 airplay2tv` (the directory, not the repo root, is on the path by default); this is a harmless no-op under `python3 -m airplay2tv`.
- Subcommand dispatch routes through `app.run(args)` (which inspects `args.command`) rather than per-subcommand handler modules, keeping CLI scaffolding inside the WP-CLI-SKELETON boundary and out of the unbuilt `app.py`/command layer.
- Latent `airplay2tv/config.py` defect surfaced during WS-APP-FINALIZE and left for the config owner: `config.load()` returns `dict(DEFAULT_CONFIG)`, a shallow copy whose `devices` list is the shared module-level list. The first caller to `add_device` on a freshly defaulted (no-file) config mutates `DEFAULT_CONFIG["devices"]` in place, which then leaks into later callers (it contaminated `tests/test_config.py` when an app-flow persist test ran first). config.py is outside the WS-APP-FINALIZE boundary, so `tests/test_app_flow.py` works around it by seeding an on-disk config before exercising persist; the durable fix (deep-copy the default in `config.load`) belongs to the config owner.

### Developer Tests and Notes

- WP-DISCOVERY (WS-DISCOVERY, M3): `airplay2tv/discovery/aggregate.py` -- `discover_all(backends, timeout)` runs every backend's `discover()` concurrently via `asyncio.gather` under a shared `asyncio.wait_for` timeout; a backend that raises or returns nothing contributes zero devices; the merged flat list is returned.
- WP-DISCOVERY (WS-DISCOVERY, M3): `airplay2tv/devicepick.py` -- `render(devices)` produces a numbered list (name, backend, identifier, address); duplicate names are disambiguated by appending the address in parentheses. `select(devices, requested)` resolves by exact name or identifier when `requested` is given (raises `ValueError` on not-found or ambiguous match); falls back to interactive stdin/stdout prompt when `requested` is None and a TTY is present; raises `ValueError` when no TTY and no `requested`.
- `tests/test_discovery_merge.py`: 12 offline pytest tests covering discover_all merge, backend-exception tolerance, empty-backend tolerance, render numbering, duplicate-name disambiguation, select-by-name, select-by-identifier, not-found error, ambiguous-match error, and no-TTY error. All 12 pass.
- Wrote the M1 hardware-proof findings report `docs/active_plans/reports/airplay2tv_m1_proof.md` from the real Sharp Roku TV proof runs (AirPlay pairing Mandatory; Roku ECP gated by "Control by mobile apps"); required inputs for the M3 backends.
- Wrote the build-summary handoff report [active_plans/reports/airplay2tv_build_summary.md](active_plans/reports/airplay2tv_build_summary.md): what shipped, test evidence (919 passed; four E2E smokes pass), the verified-vs-deferred matrix, and the required user actions for live AirPlay PIN pairing and the Roku "Control by mobile apps" re-run.
- WP-HEADLESS-SMOKE (WS-HEADLESS-SMOKE): `tests/e2e/e2e_headless_pair_play.py` -- headless pair-then-play E2E (not pytest) driving `app.run` with a `HeadlessPairBackend` (subclass of `backends.base.Backend`) injected via `app.registry.active_backends`, and offline stubs for `app.prepare_media`, `app.httpserver.serve/shutdown`, `app.netutil.local_ip_for`, and `app.wait_for_interrupt`. Case 1 (first run) feeds a 4-digit PIN through an in-memory fake stdin (TTY claim), asserts the pairing record is written under a tmp `XDG_CONFIG_HOME`, and that playback proceeds; case 2 (second run, fresh backend) finds the saved record via the real credentials store and plays with zero prompts. Prints PASS/FAIL per case and exits 0 on success. Seam matches the existing `tests/test_app_flow_fakebackend.py` and `tests/test_pairing_fakebackend.py` FakeBackend pattern; no package code changed.
- Read-only edge-case audit covering eight seams (app.py, airplay.py, roku_ecp.py, media.py, httpserver.py, pairing.py, credentials.py, aggregate.py); 14 findings (4 HIGH, 5 MEDIUM, 5 LOW) written to [active_plans/audits/airplay2tv_edge_case_audit.md](active_plans/audits/airplay2tv_edge_case_audit.md). No code changed.
- Direct-IP ECP re-probe (2026-06-18, source 192.168.2.75 -> 192.168.2.61:8060, no SSDP) recorded in [active_plans/reports/airplay2tv_m1_proof.md](active_plans/reports/airplay2tv_m1_proof.md) and [active_plans/reports/airplay2tv_build_summary.md](active_plans/reports/airplay2tv_build_summary.md): device-info and active-app return 200, apps/media-player/keypress return 403, SSDP silent. Corrected the Roku framing into three separate statuses (AirPlay pairing Mandatory; Roku direct ECP reachable but limited with launch UNVERIFIED; Roku SSDP discovery silent) and marked the 403 cause UNRESOLVED rather than claiming "Control by mobile apps" is off. Docs only.
