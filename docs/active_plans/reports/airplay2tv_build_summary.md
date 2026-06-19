# airplay2tv build summary

Handoff report for the first complete implementation of airplay2tv, built by
delegated subagents against the approved plan
`i-am-thinking-of-eager-dolphin.md` while the user was away. Every claim below
traces to repo evidence: the modules under `airplay2tv/`, the tests under
`tests/`, the M1 hardware findings in
[airplay2tv_m1_proof.md](airplay2tv_m1_proof.md), and the changelog entry under
`## 2026-06-17` in [docs/CHANGELOG.md](../../CHANGELOG.md).

## What shipped

### Core package modules

- `airplay2tv/cli.py`: argparse surface and `main()`. Stream-action flags plus
  the `pair`, `doctor`, and `devices` subcommands; calls `logging_setup.configure`
  then dispatches through `app.run`.
- `airplay2tv/app.py`: synchronous dispatcher `run(args) -> int` routing on
  `args.command`. Drives the full async stream flow (discover, select, inline
  pairing, prepare, serve, play, status banner, Ctrl+C stop) with a single
  `finally` that shuts down the HTTP server and removes the temp media dir on
  every exit path.
- `airplay2tv/media.py`: `inspect` (ffprobe JSON), pure `decide`
  (passthrough/remux/transcode against a `MediaProfile`), and ffmpeg-backed
  `prepare` with progress, cancellation, partial-output cleanup, and a disk-space
  check before transcode.
- `airplay2tv/httpserver.py`: threaded single-file server with full HTTP Range
  support (HEAD, full GET, 206, open-ended Range, 416) and a clean `shutdown`.
- `airplay2tv/netutil.py`: `local_ip_for(target)` and `pick_free_port(start)`.
- `airplay2tv/discovery/aggregate.py` and `airplay2tv/discovery/roku_ssdp.py`:
  concurrent multi-backend discovery and clean-room Roku SSDP probe + parser.
- `airplay2tv/devicepick.py`: device list rendering and selection (by
  name/identifier or interactive picker).
- `airplay2tv/config.py`: non-secret settings (device records, default device id)
  at `~/.config/airplay2tv/config.yaml`, atomic writes, deep-copied defaults.
- `airplay2tv/credentials.py`: pairing-record store at
  `~/.config/airplay2tv/credentials.yaml`, 0600 mode enforced, loose-mode warning.
- `airplay2tv/doctor.py`: `run_checks` PASS/FAIL/INFO/WARN for ffmpeg, ffprobe,
  address selection, backend/discovery counts, Roku SSDP stats, and pairing state.
- `airplay2tv/errors.py`: `Airplay2tvError` base plus `UnsupportedMediaError`,
  `PreparationError`, `PairingRequiredError`, `DeviceUnreachableError`.
- `airplay2tv/logging_setup.py`: log-level configuration and debug-traceback gate.

### Backends and pairing

- `airplay2tv/backends/base.py`: frozen backend contract (`Device`,
  `MediaProfile`, `PlaybackStatus`, `PairingRecord`, `PairingState`, and the async
  `Backend` ABC with a `backend_key` class attribute).
- `airplay2tv/backends/airplay.py`: `AirPlayBackend`, the sole importer of pyatv.
  Scan/connect/`play_url`/stop/status and the pyatv AirPlay PIN handshake.
- `airplay2tv/backends/roku_ecp.py`: `RokuEcpBackend`, the sole importer of
  rokuecp, layered on the owned SSDP discovery. Launches Roku Media Player
  (`launch/2213`); ECP uses no PIN; ECP HTTP 403 maps to `DeviceUnreachableError`
  naming the TV "Control by mobile apps" setting.
- `airplay2tv/backends/registry.py`: construction-only `active_backends()` that
  lazily imports each concrete backend.
- `airplay2tv/pairing.py`: `run(args)` pair entry point with a stdin
  `prompt_pin()` helper.

### CLI surface

- Stream action (default / `stream`): `-i/--input`, `-d/--device`, `--bind`,
  `--save-device`, `--default-device`, `-v/--verbose`, `--debug`, and a
  mutually-exclusive `--passthrough`/`--transcode` media-mode group (default
  automatic).
- Subcommands: `pair`, `doctor` (with `-i/--input` and `-d/--device`), `devices`.
- `--save-device` persists the played device; `--default-device` matching the
  played identifier also sets the stored default id, in one atomic config write.

### Packaging, docs, and E2E

- `pyproject.toml`: `[project.scripts]` console script
  `airplay2tv = "airplay2tv.cli:main"`, `[build-system]` (setuptools), and a
  pytest `pythonpath` setting.
- `HomebrewFormula/airplay2tv.rb`: formula depending on ffmpeg and python@3.12
  (placeholder sha256 values pending a real release archive).
- Manifests: `pip_requirements.txt` (adds rokuecp, pyyaml), `Brewfile`
  (`brew "ffmpeg"`).
- Docs: `docs/USAGE.md`, `docs/CODE_ARCHITECTURE.md`, `docs/FILE_STRUCTURE.md`,
  `docs/INSTALL.md`, `README.md` first paragraph and quick start.
- E2E smokes under `tests/e2e/`: `e2e_headless_pair_play.py`,
  `e2e_debian_smoke.py`, `e2e_media_prepare.py`, `e2e_make_fixtures.py`.
- Hardware-proof scripts under `devel/`: `proof_airplay.py`, `proof_roku.py`.

## Test evidence

Full pytest suite (`source source_me.sh && pytest tests/ -q | tail -3`):

```
953 passed
```

E2E smoke results (run individually, all offline; no real TV hardware):

- `e2e_debian_smoke.py`: `8/8 passed, 0 failed` (`PASS: all steps passed`).
- `e2e_headless_pair_play.py`: `ALL CASES PASSED` (first-run pair-and-play and
  second-run no-prompt replay).
- `e2e_make_fixtures.py`: produced the three lavfi fixtures
  (`sample_h264.mp4`, `sample_h264.mkv`, `sample_hevc.mp4`).
- `e2e_media_prepare.py`: `ALL MEDIA PREPARE E2E CASES PASSED` (passthrough,
  remux, transcode, and a cancellation-cleanup case).

## Verified vs deferred

| Behavior | Status | Evidence |
| --- | --- | --- |
| Media inspect/decide (passthrough/remux/transcode) | Verified | `test_media_decision.py`, debian smoke |
| ffmpeg remux + transcode produce portable MP4 | Verified | `e2e_media_prepare.py`, debian smoke |
| HTTP Range server (206/416/open-ended) | Verified | `test_httpserver.py`, debian smoke |
| Multi-backend discovery merge + device pick | Verified | `test_discovery_merge.py` |
| Roku SSDP parse (case-insensitive, dedupe, malformed) | Verified | `test_roku_ssdp.py` |
| Config + credentials round-trips, 0600 mode | Verified | `test_config.py`, `test_credentials.py` |
| AirPlay backend control + pair handshake (pyatv mocked) | Verified | `test_airplay_backend.py` |
| Roku ECP launch/stop/status, 403 -> error (fake ECP) | Verified | `test_roku_ecp.py` |
| App stream flow + cleanup, inline pairing gating | Verified | `test_app_flow*.py`, `test_app_cleanup.py` |
| Headless first-run pair then no-prompt replay | Verified | `e2e_headless_pair_play.py` |
| Live AirPlay PIN playback on real Apple TV | Deferred | M1: AirPlay pairing Mandatory, `AuthenticationError` on unpaired `play_url` |
| Roku direct ECP reachability (device-info, active-app) | Verified on hardware | 2026-06-18 re-probe: GET 200 direct to TV IP, no SSDP |
| Live Roku Media Player launch + exact param casing | Deferred | 2026-06-18: `launch` is in the gated class (403); UNVERIFIED |

The deferred items are blocked by real-hardware preconditions, not by missing
code. The three statuses below are tracked SEPARATELY:

- AirPlay: pairing is Mandatory; an unpaired `play_url` raises
  `AuthenticationError`. The AirPlay backend is built against the confirmed pyatv
  API along the pairing-required path.
- Roku direct ECP control: reachable over the LAN by direct IP. `device-info`
  and `active-app` return 200; `apps`, `media-player`, and `keypress` return 403.
  `launch` is in the gated class and is UNVERIFIED. The cause of the 403s is
  UNRESOLVED; `ecp-setting-mode=limited` is consistent with (but not proof of)
  the "Control by mobile apps" setting being off. The user's working Roku mobile
  app shows a control path exists, so this report does NOT claim mobile-app
  control is off.
- Roku SSDP discovery: silent (0 valid responses). This is a DISCOVERY issue,
  independent from ECP control reachability; a known IP still works via the
  direct-IP / `--device` path.

The Roku launch param casing (`contentId`/`mediaType` vs `contentID`/`MediaType`)
remains a documented assumption in `roku_ecp.py` because no launch has been
exercised on hardware. See
[airplay2tv_m1_proof.md](airplay2tv_m1_proof.md) for the 2026-06-18 direct-IP
re-probe evidence.

## Required user actions on return

1. At the TV, run the stream command and enter the AirPlay PIN shown on screen to
   complete first-run pairing. M1 confirmed AirPlay pairing is Mandatory, so the
   first live play needs the PIN handshake with the user present.
2. On the Roku TV, the gated ECP endpoints (`apps`, `media-player`, `keypress`,
   and `launch`) returned 403 during the 2026-06-18 direct-IP re-probe while
   `device-info` and `active-app` returned 200. The 403 cause is UNRESOLVED;
   `ecp-setting-mode=limited` is consistent with the "Control by mobile apps"
   setting being off but is not proof. Check Settings > System > Advanced system
   settings > Control by mobile apps, then re-run `devel/proof_roku.py` (or probe
   the TV IP directly) to confirm Media Player URL playback and capture the exact
   launch param casing.
3. The git index is staged with the fixed files; the commit is the human's to
   make. The user's `.mp4` files remain untracked.

## Known follow-ups

- The edge-case and coverage audit is at
  [docs/active_plans/audits/airplay2tv_edge_case_audit.md](../audits/airplay2tv_edge_case_audit.md).
- The Homebrew formula sha256 values are placeholders pending a real release
  archive.
- Roku launch param casing stays a documented assumption until the hardware
  re-run in action 2 confirms it.
