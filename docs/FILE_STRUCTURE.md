# FILE_STRUCTURE.md

Directory layout and what each file does in the airplay2tv repo.

## Repo root

```
airplay2tv/           Python package (the CLI and all runtime code)
devel/                Hardware-proof scripts and developer utilities
docs/                 Project documentation
HomebrewFormula/      Homebrew formula for optional tap-based install
tests/                pytest unit tests and non-pytest E2E tests
.gitignore
Brewfile              Homebrew system dependencies (ffmpeg)
AGENTS.md             Agent instructions and repo-specific workflow rules
LICENSE
README.md
VERSION
pip_requirements.txt  Runtime Python dependencies
pip_requirements-dev.txt  Developer Python dependencies (pytest)
pyproject.toml        Package metadata, build config, and pytest options
source_me.sh          Activates the Python environment for local runs
REPO_TYPE             Repo-type marker (token: python)
```

## `airplay2tv/` package

```
airplay2tv/
  __init__.py         Package docstring only; no logic.
  __main__.py         Entry point for `python3 -m airplay2tv` and
                      `python3 airplay2tv`.
  cli.py              argparse surface: stream-action flags, pair/doctor/devices
                      subcommands, logging flags, dispatch, error rendering.
  app.py              Synchronous dispatcher and async stream orchestration:
                      discover -> pick -> pair -> prepare -> serve -> play ->
                      wait -> cleanup.
  media.py            Media inspection (ffprobe) and preparation (ffmpeg):
                      inspect(), decide(), prepare(). Passthrough, remux, and
                      H.264/AAC transcode paths.
  httpserver.py       Threaded range-capable HTTP server (ThreadingHTTPServer).
                      serve() / shutdown(). Handles HEAD, full GET, 206, 416.
  netutil.py          local_ip_for(): routable LAN interface IP via UDP connect.
                      pick_free_port(): first bindable TCP port.
  config.py           Non-secret settings: saved device records, default device
                      id. Reads/writes ~/.config/airplay2tv/config.yaml
                      atomically. Honors XDG_CONFIG_HOME.
  credentials.py      Pairing records: saves/loads ~/.config/airplay2tv/
                      credentials.yaml at mode 0600. Concurrent writes serialized
                      by fcntl.flock. Warns on loose permissions.
  devicepick.py       render(): numbered device list. select(): by name/id or
                      interactive prompt. Disambiguates duplicate names.
  doctor.py           run_checks(device, input_file): PASS/FAIL/INFO/WARN output
                      for ffmpeg, ffprobe, address, discovery, pairing, media.
  errors.py           Typed error hierarchy: Airplay2tvError, PairingRequiredError,
                      DeviceUnreachableError, UnsupportedMediaError,
                      PreparationError, CredentialsError.
  logging_setup.py    configure(verbose, debug): sets root log level and exposes
                      show_tracebacks() for the CLI dispatch layer.
  pairing.py          run(args): pair subcommand entry point. Discovers devices,
                      checks for existing record, runs PIN handshake, saves record.

  backends/
    __init__.py       Package docstring only; no logic.
    base.py           Backend-agnostic contract: Backend ABC, Device, MediaProfile,
                      PlaybackStatus, PairingRecord, PairingState.
    registry.py       active_backends(): lazily imports and instantiates each
                      concrete backend from BACKEND_SPECS.
    airplay.py        AirPlayBackend: sole importer of pyatv. mDNS discovery (5 s),
                      AirPlay PIN pairing, URL streaming via play_url.
    roku_ecp.py       RokuEcpBackend: sole importer of rokuecp. SSDP discovery,
                      ECP launch/stop/status. No PIN; 403 -> DeviceUnreachableError.

  discovery/
    __init__.py       Package docstring only; no logic.
    aggregate.py      discover_all(backends, timeout): concurrent gather over all
                      backends under a shared asyncio timeout.
    roku_ssdp.py      async SSDP M-SEARCH over UDP. Parses UPnP responses, dedupes
                      by USN, returns (responders, DiscoveryStats).
```

## `tests/`

```
tests/
  conftest.py                   pytest config: collect_ignore for e2e/ and playwright/.
  file_utils.py                 Shared helper: get_repo_root() via git rev-parse.
  TESTS_README.md               Test suite overview.

  # Infrastructure / style enforcement tests
  test_ascii_compliance.py      All tracked files use ASCII/ISO-8859-1 encoding.
  test_bandit_security.py       Bandit static security analysis.
  test_function_typing.py       Every def has full type annotations.
  test_import_dot.py            No relative imports (from . import).
  test_import_requirements.py   Every third-party import is in pip_requirements.txt.
  test_import_star.py           No wildcard imports (import *).
  test_indentation.py           Tabs-only indentation in Python files.
  test_init_files.py            __init__.py files contain only a docstring.
  test_markdown_links.py        Every local Markdown link resolves on GitHub.
  test_pyflakes_code_lint.py    pyflakes lint gate.
  test_pytest_hygiene.py        pytest hygiene rules.
  test_readme_first_paragraph.py  README.md first paragraph is pure prose <= 250 chars.
  test_shebangs.py              Shebang <-> executable bit consistency.
  test_whitespace.py            No trailing whitespace.

  # Unit and integration tests for airplay2tv modules
  test_airplay_backend.py       AirPlayBackend: discover, play, pair, status
                                (pyatv fully mocked).
  test_app_cleanup.py           run_stream cleanup: server/tmpdir freed on failure
                                and Ctrl+C.
  test_app_flow.py              run_stream: full flow, no-devices, persist.
  test_app_flow_fakebackend.py  run_stream against FakeBackend (no hardware).
  test_backend_contract.py      Backend ABC satisfiability with FakeBackend.
  test_config.py                config.load/save, add_device, default_device_id.
  test_credentials.py           credentials.load/save_record, mode 0600, get_record.
  test_discovery_merge.py       aggregate.discover_all, devicepick.render/select.
  test_doctor.py                doctor.run_checks: all-pass, ffmpeg absent,
                                device filter, address fail.
  test_httpserver.py            HTTP range matrix: HEAD, GET, 206, 416, shutdown.
  test_media_decision.py        media.decide: AirPlay/Roku profiles, H.265,
                                forced modes.
  test_netutil.py               netutil.local_ip_for, pick_free_port.
  test_pairing_fakebackend.py   pairing.run: PIN prompt and already-paired shortcut.
  test_roku_ecp.py              RokuEcpBackend against a local fake ECP HTTP server.
  test_roku_ssdp.py             roku_ssdp.parse_response: 14 cases.

  e2e/                          Non-pytest E2E scripts (excluded from pytest).
    e2e_debian_smoke.py         Smoke test on Debian/Ubuntu: installs deps, runs
                                airplay2tv --help, verifies exit code.
    e2e_headless_pair_play.py   Headless pairing + playback probe against a real
                                device; skips gracefully when no hardware is found.
    e2e_make_fixtures.py        Generate deterministic sub-1 MB fixture files
                                (sample_h264.mp4, sample_h264.mkv, sample_hevc.mp4)
                                using ffmpeg lavfi testsrc.
    e2e_media_prepare.py        Real ffmpeg-backed passthrough/remux/transcode paths;
                                cancel test.

  fixtures/                     Generated fixture files (gitignored; created by
                                e2e_make_fixtures.py).
    sample_h264.mp4
    sample_h264.mkv
    sample_hevc.mp4

  check_ascii_compliance.py*    Single-file ASCII/ISO-8859-1 check helper.
  fix_ascii_compliance.py*      Single-file ASCII fix helper.
  fix_whitespace.py*            Single-file trailing-whitespace fix helper.
```

## `devel/`

Hardware-proof and developer-only scripts. Not installed or propagated.

```
devel/
  proof_airplay.py    Hardware proof: scan with pyatv, connect to a real Apple TV,
                      serve a sample MP4, call play_url, and report pairing
                      requirements. Throwaway; run on real hardware only.
  proof_roku.py       Hardware proof: SSDP-discover a Roku, query device-info and
                      apps, serve a sample MP4, launch Roku Media Player.
                      Throwaway; run on real hardware only.
```

## `docs/`

```
docs/
  AUTHORS.md                 Primary maintainers (centrally maintained).
  CHANGELOG.md               Chronological change log grouped by date.
  CLAUDE_HOOK_USAGE_GUIDE.md Claude Code hook usage reference (centrally maintained).
  CODE_ARCHITECTURE.md       This repo's component design and data flow.
  E2E_TESTS.md               End-to-end test conventions (centrally maintained).
  FILE_STRUCTURE.md          This file.
  INSTALL.md                 Setup steps for macOS (Homebrew) and Debian/Ubuntu.
  MARKDOWN_STYLE.md          Markdown writing conventions (centrally maintained).
  PYTEST_STYLE.md            pytest test-writing rules (centrally maintained).
  PYTHON_STYLE.md            Python formatting and project conventions
                             (centrally maintained).
  REPO_STYLE.md              Repo-level organization rules (centrally maintained).
  USAGE.md                   CLI usage: flags, subcommands, media matrix, config paths.
  active_plans/              Working planning artifacts (in-flight plans, audits,
                             reports, decisions, workstreams).
```

## `HomebrewFormula/`

```
HomebrewFormula/
  airplay2tv.rb    Homebrew formula: depends_on ffmpeg + python@3.12, installs
                   pip_requirements.txt resources, links bin/airplay2tv wrapper.
                   Placeholder sha256 values; update before publishing.
```

## Generated and gitignored paths

| Path | Contents |
| --- | --- |
| `tests/fixtures/` | Fixture media files generated by `e2e_make_fixtures.py`. |
| `__pycache__/` | Python bytecode caches. |
| `*.pyc` | Compiled bytecode. |
