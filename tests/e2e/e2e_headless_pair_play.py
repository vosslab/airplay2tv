#!/usr/bin/env python3
"""Headless pair-then-play E2E for the default stream flow.

Drives `airplay2tv.app.run` end to end with a FakeBackend standing in for the
real receiver backends, so no pyatv, no rokuecp, no ffmpeg, and no real socket
or device are needed. The flow is exercised twice against a throwaway
XDG_CONFIG_HOME so the real user config and credentials are never touched:

  Case 1 (first run, needs pairing): the FakeBackend reports the device needs
  pairing and has no stored record, so `app.ensure_paired` reads a 4-digit code
  from a piped/fake stdin and `app.save_pairing` writes the credential under the
  tmp XDG_CONFIG_HOME. Playback then proceeds against the advertised URL.

  Case 2 (second run, already paired): the same FakeBackend now finds the saved
  pairing record (its `is_paired` is backed by the real credentials store), so
  the PIN prompt is never invoked. Playback proceeds with no prompt.

Headless guarantees verified here:

  - The 4-digit code is read from stdin only (no GUI surface, no terminal
    device handle): the prompt callback is fed from an in-memory fake stdin.
  - The pairing record lands on disk under the tmp XDG_CONFIG_HOME, proving the
    real user config is untouched.
  - The second run issues zero prompts.

Injection seam (matches tests/test_app_flow_fakebackend.py and
tests/test_pairing_fakebackend.py): a FakeBackend subclass of
`airplay2tv.backends.base.Backend` is installed by replacing
`app.registry.active_backends`, and the side-effecting helpers
(`app.prepare_media`, `app.httpserver.serve`, `app.httpserver.shutdown`,
`app.netutil.local_ip_for`, `app.wait_for_interrupt`) are replaced with offline
stubs. Pairing flows through the real `app.ensure_paired` -> `app.pair` ->
`app.save_pairing` -> `airplay2tv.credentials.save_record` path, so the saved
record is a real file write under the tmp XDG_CONFIG_HOME.

Run with:  source source_me.sh && python3 tests/e2e/e2e_headless_pair_play.py
Exits 0 when both cases pass, non-zero otherwise.
"""

# Standard Library
import io
import os
import sys
import types
import tempfile
import argparse
import threading
import subprocess
import collections.abc

# This runner executes outside pytest, so the pyproject pythonpath does not
# apply. Locate the repo root and put it on sys.path so the airplay2tv package
# imports cleanly when invoked directly as python3 tests/e2e/e2e_headless_pair_play.py.
REPO_ROOT = subprocess.run(
	['git', 'rev-parse', '--show-toplevel'],
	capture_output=True, text=True, check=True,
).stdout.strip()
if REPO_ROOT not in sys.path:
	sys.path.insert(0, REPO_ROOT)

# local repo modules
import airplay2tv.app as app
import airplay2tv.media as media
import airplay2tv.config as config
import airplay2tv.credentials as credentials
import airplay2tv.backends.base as base


# Stable device identity reused across both runs so the second run finds the
# record the first run saved.
DEVICE_NAME = "Living Room TV"
DEVICE_KEY = "fakepair"
DEVICE_ID = "fakepair-headless-001"
DEVICE_ADDR = "192.0.2.30"
ONSCREEN_PIN = "4271"


#============================================
class HeadlessPairBackend(base.Backend):
	"""FakeBackend that simulates a 4-digit PIN challenge and a real record check.

	`is_paired` is backed by the live credentials store so the second run
	naturally reports PAIRED once the first run has written the record. `pair`
	calls the supplied prompt_pin callback exactly as a real backend would when
	the device shows its on-screen code, then returns a credential carrying the
	entered PIN.
	"""

	#--------------------------------------------
	def __init__(self) -> None:
		self.backend_key = DEVICE_KEY
		# Records every (url, media) the flow asked to play, for assertions.
		self.play_calls: list[tuple[str, object]] = []
		# Counts how many times the backend asked for an on-screen PIN.
		self.pair_calls = 0

	#--------------------------------------------
	def _device(self) -> base.Device:
		# Single stable device shared across discover and every other call.
		device = base.Device(
			name=DEVICE_NAME,
			backend=DEVICE_KEY,
			identifier=DEVICE_ID,
			address=DEVICE_ADDR,
			model="FakePairTV",
		)
		return device

	#--------------------------------------------
	async def discover(self) -> list[base.Device]:
		return [self._device()]

	#--------------------------------------------
	async def media_profile(self) -> base.MediaProfile:
		profile = base.MediaProfile(
			containers={"mp4"},
			video_codecs={"h264"},
			audio_codecs={"aac"},
		)
		return profile

	#--------------------------------------------
	async def play(self, device: base.Device, media_url: str, media_obj: object) -> None:
		# Record the URL and prepared media so the caller can assert playback ran.
		self.play_calls.append((media_url, media_obj))

	#--------------------------------------------
	async def stop(self, device: base.Device) -> None:
		return None

	#--------------------------------------------
	async def status(self, device: base.Device) -> base.PlaybackStatus:
		return base.PlaybackStatus(state="playing")

	#--------------------------------------------
	async def needs_pairing(self, device: base.Device) -> bool:
		# This device always requires pairing before playback.
		return True

	#--------------------------------------------
	async def pair(
		self,
		device: base.Device,
		prompt_pin: collections.abc.Callable[[], str],
	) -> base.PairingRecord:
		# The device shows a PIN and waits for the user to read it back; the core
		# supplies prompt_pin to read the 4-digit code from terminal stdin.
		self.pair_calls += 1
		entered = prompt_pin()
		record = base.PairingRecord(
			identifier=device.identifier,
			backend=device.backend,
			credential=f"fake-credential-{entered}",
		)
		return record

	#--------------------------------------------
	async def is_paired(self, device: base.Device) -> base.PairingState:
		# Back the pairing state with the real credentials store so the second
		# run reports PAIRED once the first run has saved the record.
		stored = credentials.get_record(device.identifier, device.backend)
		if stored is not None:
			return base.PairingState.PAIRED
		return base.PairingState.NOT_PAIRED


#============================================
class RecordingServer:
	"""Stand-in for the httpserver server object; records shutdown calls."""

	#--------------------------------------------
	def __init__(self) -> None:
		self.shut_down = False


#============================================
class FakeStdin:
	"""In-memory stdin that yields a scripted PIN line and reports a TTY.

	`app.ensure_paired` only pairs inline when `sys.stdin.isatty()` is true, and
	`app.prompt_pin` reads the code with `input()`, which pulls a line from
	`sys.stdin`. This fake provides both: a TTY claim (so inline pairing runs
	over what looks like an interactive terminal, e.g. an SSH session) and a
	readline that returns the on-screen code. No GUI or real terminal device is
	involved -- the code path is pure stdin/stdout.
	"""

	#--------------------------------------------
	def __init__(self, line: str) -> None:
		# input() strips the trailing newline; include one so readline behaves.
		self._buffer = io.StringIO(line + "\n")

	#--------------------------------------------
	def isatty(self) -> bool:
		return True

	#--------------------------------------------
	def readline(self) -> str:
		return self._buffer.readline()

	#--------------------------------------------
	def read(self, size: int = -1) -> str:
		return self._buffer.read(size)


#============================================
def make_stream_args() -> argparse.Namespace:
	"""Build a minimal default-stream namespace (no subcommand)."""
	args = argparse.Namespace(
		command=None,
		input_file="/does/not/matter.mkv",
		device=DEVICE_ID,
		default_device=None,
		bind_host=None,
		save_device=False,
		media_mode=None,
		verbose=False,
		debug=False,
	)
	return args


#============================================
def install_offline_stubs(backend: HeadlessPairBackend, server: RecordingServer) -> dict:
	"""Replace the app's side-effecting calls so the flow runs offline.

	Returns a record dict capturing the served path and advertised host so the
	caller can assert playback was wired correctly.
	"""
	record: dict = {}
	prepared = media.PreparedMedia(path="/tmp/prepared.mp4", content_type="video/mp4")  # nosec B108 - fake path for test fixture, no real file created here

	# Only the fake backend is active; no real pyatv/rokuecp discovery.
	app.registry.active_backends = lambda: [backend]

	def fake_prepare(
		args: object,
		profile: base.MediaProfile,
		temp_dir: str,
		cancel_event: threading.Event,
	) -> media.PreparedMedia:
		# Skip real ffmpeg; the temp dir exists here exactly as in the real flow.
		record["served_media"] = prepared
		return prepared

	app.prepare_media = fake_prepare

	def fake_serve(path: str, bind_host: str, advertised_host: str) -> tuple:
		# Skip the real socket; hand back a fake URL plus a recording server.
		record["served_path"] = path
		record["advertised_host"] = advertised_host
		thread = types.SimpleNamespace()
		url = f"http://{advertised_host}:3500/media.mp4"
		return (url, server, thread)

	app.httpserver.serve = fake_serve

	def fake_shutdown(srv: RecordingServer, thread: object) -> None:
		srv.shut_down = True

	app.httpserver.shutdown = fake_shutdown
	app.netutil.local_ip_for = lambda target: "192.0.2.2"
	# Return immediately instead of blocking on the Ctrl+C wait.
	app.wait_for_interrupt = lambda: None
	return record


#============================================
def install_fake_stdin() -> None:
	"""Point sys.stdin at the scripted fake so input() reads the PIN over a TTY."""
	sys.stdin = FakeStdin(ONSCREEN_PIN)


#============================================
def count_prompts() -> dict:
	"""Wrap app.prompt_pin so each on-screen-code read is counted.

	Returns a one-key dict whose "count" value is incremented every time the
	pairing flow asks for the code. The real prompt_pin still runs, so the read
	goes through stdin exactly as in production.
	"""
	tally = {"count": 0}
	real_prompt = app.prompt_pin

	def counting_prompt() -> str:
		tally["count"] += 1
		return real_prompt()

	app.prompt_pin = counting_prompt
	return tally


#============================================
def report(case: str, ok: bool, detail: str) -> bool:
	"""Print a PASS/FAIL line for one case and return the boolean unchanged."""
	status = "PASS" if ok else "FAIL"
	print(f"[{status}] {case}: {detail}")
	return ok


#============================================
def credentials_file_exists() -> bool:
	"""True when the credentials YAML exists under the tmp XDG_CONFIG_HOME."""
	xdg = os.environ["XDG_CONFIG_HOME"]
	path = os.path.join(xdg, "airplay2tv", "credentials.yaml")
	return os.path.exists(path)


#============================================
def run_first_run_case(backend: HeadlessPairBackend, prompt_tally: dict) -> bool:
	"""Case 1: a device needing pairing pairs from stdin, then playback proceeds."""
	server = RecordingServer()
	record = install_offline_stubs(backend, server)
	install_fake_stdin()

	# Sanity: no credential should exist before the first run pairs.
	if credentials_file_exists():
		return report("case1-first-run", False, "credentials file already existed before run")

	exit_code = app.run(make_stream_args())

	ok = True
	ok = report("case1-exit-code", exit_code == 0, f"app.run returned {exit_code}") and ok
	ok = report(
		"case1-pin-prompted",
		prompt_tally["count"] == 1,
		f"prompt_pin called {prompt_tally['count']} time(s)",
	) and ok
	ok = report(
		"case1-pair-called",
		backend.pair_calls == 1,
		f"backend.pair called {backend.pair_calls} time(s)",
	) and ok
	ok = report(
		"case1-record-saved",
		credentials_file_exists(),
		"pairing record written under tmp XDG_CONFIG_HOME",
	) and ok
	stored = credentials.get_record(DEVICE_ID, DEVICE_KEY)
	saved_ok = stored is not None and stored.credential == f"fake-credential-{ONSCREEN_PIN}"
	ok = report(
		"case1-record-payload",
		saved_ok,
		f"saved credential carries the entered PIN ({ONSCREEN_PIN})",
	) and ok
	played_ok = len(backend.play_calls) == 1 and backend.play_calls[0][0] == "http://192.0.2.2:3500/media.mp4"
	ok = report(
		"case1-playback-proceeded",
		played_ok,
		f"playback started against advertised URL ({len(backend.play_calls)} call(s))",
	) and ok
	ok = report(
		"case1-server-shutdown",
		server.shut_down is True and record["served_path"] == "/tmp/prepared.mp4",  # nosec B108 - comparing against a test fixture path string, not creating a tempfile
		"server shut down and prepared media served on clean exit",
	) and ok
	return ok


#============================================
def run_second_run_case(prompt_tally: dict) -> bool:
	"""Case 2: the saved record is found and playback proceeds with no prompt."""
	# A fresh backend instance proves the second run relies on the saved record,
	# not in-memory state carried over from the first backend.
	backend = HeadlessPairBackend()
	server = RecordingServer()
	install_offline_stubs(backend, server)
	# A fresh fake stdin: if any prompt fired, it would still read cleanly, so a
	# zero prompt count is the only proof that no prompt occurred.
	install_fake_stdin()

	prompts_before = prompt_tally["count"]
	exit_code = app.run(make_stream_args())
	prompts_after = prompt_tally["count"]

	ok = True
	ok = report("case2-exit-code", exit_code == 0, f"app.run returned {exit_code}") and ok
	ok = report(
		"case2-no-prompt",
		prompts_after == prompts_before,
		f"prompt_pin not called on the second run (delta {prompts_after - prompts_before})",
	) and ok
	ok = report(
		"case2-pair-skipped",
		backend.pair_calls == 0,
		f"backend.pair not called ({backend.pair_calls} call(s))",
	) and ok
	played_ok = len(backend.play_calls) == 1 and backend.play_calls[0][0] == "http://192.0.2.2:3500/media.mp4"
	ok = report(
		"case2-playback-proceeded",
		played_ok,
		f"playback started against advertised URL ({len(backend.play_calls)} call(s))",
	) and ok
	ok = report(
		"case2-server-shutdown",
		server.shut_down is True,
		"server shut down on clean exit",
	) and ok
	return ok


#============================================
def verify_real_config_untouched(tmp_xdg: str) -> bool:
	"""Confirm config.load/credentials paths resolve under the tmp XDG dir."""
	# Both stores derive their path from XDG_CONFIG_HOME, so the real user
	# config under ~/.config is never read or written during this run.
	cred_under_tmp = credentials._credentials_path().startswith(tmp_xdg)
	conf_under_tmp = config._config_path().startswith(tmp_xdg)
	ok = report(
		"isolation-paths-under-tmp",
		cred_under_tmp and conf_under_tmp,
		"credentials and config paths resolve under the tmp XDG_CONFIG_HOME",
	)
	return ok


#============================================
def main() -> int:
	"""Run both headless pair-then-play cases and report PASS/FAIL per case.

	Returns:
		0 when every case passes, 1 otherwise.
	"""
	# Isolate all on-disk state under a throwaway XDG_CONFIG_HOME so the real
	# user config and credentials are never touched.
	tmp_xdg = tempfile.mkdtemp(prefix="airplay2tv-e2e-xdg-")
	os.environ["XDG_CONFIG_HOME"] = tmp_xdg

	# A counting wrapper around the real prompt proves how many code reads happen
	# across both runs; the underlying read still goes through stdin.
	prompt_tally = count_prompts()

	results = []
	results.append(verify_real_config_untouched(tmp_xdg))

	backend = HeadlessPairBackend()
	results.append(run_first_run_case(backend, prompt_tally))
	results.append(run_second_run_case(prompt_tally))

	all_ok = all(results)
	summary = "ALL CASES PASSED" if all_ok else "ONE OR MORE CASES FAILED"
	print(f"\n{summary} (tmp config dir: {tmp_xdg})")
	exit_code = 0 if all_ok else 1
	return exit_code


if __name__ == '__main__':
	sys.exit(main())
