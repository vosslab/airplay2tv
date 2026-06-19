#!/usr/bin/env python3
"""Debian portability smoke test for airplay2tv.

Exercises the portable building blocks of airplay2tv end-to-end without real
TV hardware or any macOS-only API. Every code path exercised here is portable
and runs identically on macOS (test platform) and Debian with ffmpeg installed:

  - CLI entry point:   python3 stream.py --help
  - Doctor subcommand: python3 stream.py doctor
  - Fixture generation: tests/e2e/e2e_make_fixtures.py (lavfi, libx264, libx265)
  - Media inspect + decide: airplay2tv.media.inspect / decide (ffprobe, pure logic)
  - Media prepare remux/transcode: airplay2tv.media.prepare (libx264, stdlib tmp)
  - HTTP range server: airplay2tv.httpserver.serve (stdlib ThreadingHTTPServer)
  - Fake-backend app stream flow: FakeBackend + app.run_stream skeleton

Portability checklist -- none of these macOS-only APIs are used:
  - No AVFoundation or VideoToolbox hardware encoders (libx264 only).
  - No py-applescript or AppKit imports.
  - No macOS-specific paths (/Library, ~/Library).
  - Config path uses XDG_CONFIG_HOME (or ~/.config), not ~/Library/Application Support.
  - Credentials stored to ~/.config/airplay2tv/credentials.yaml, mode 0600.
  - HTTP server is stdlib ThreadingHTTPServer (no CFNetwork, no Bonjour).
  - Network interface selection uses a UDP socket trick (stdlib), not SystemConfiguration.

Run with:  source source_me.sh && python3 tests/e2e/e2e_debian_smoke.py
Exit code: 0 on all PASS, non-zero on any FAIL.
"""

# Standard Library
import os
import sys
import shutil
import tempfile
import threading
import subprocess
import urllib.request

# Locate the repo root and put it on sys.path so the airplay2tv package
# imports cleanly when invoked directly as python3 tests/e2e/e2e_debian_smoke.py.
REPO_ROOT = subprocess.run(
	['git', 'rev-parse', '--show-toplevel'],
	capture_output=True, text=True, check=True,
).stdout.strip()
if REPO_ROOT not in sys.path:
	sys.path.insert(0, REPO_ROOT)

# local repo modules
import airplay2tv.media as media
import airplay2tv.httpserver as httpserver
import airplay2tv.backends.base as base


# Results accumulator: list of (step_name, passed: bool, detail: str)
_RESULTS: list[tuple[str, bool, str]] = []


#============================================
def record(step: str, passed: bool, detail: str = '') -> None:
	"""Append a step result to _RESULTS and print the PASS/FAIL line.

	Args:
		step: Short name for the step being reported.
		passed: True when the step succeeded.
		detail: Optional extra detail appended to the output line.
	"""
	label = 'PASS' if passed else 'FAIL'
	line = f'[{label}] {step}'
	if detail:
		line += f': {detail}'
	print(line)
	_RESULTS.append((step, passed, detail))


#============================================
def have_ffmpeg() -> bool:
	"""Return True when both ffmpeg and ffprobe are on PATH.

	Args:
		None

	Returns:
		True when both binaries are present, False otherwise.
	"""
	ffmpeg_ok = shutil.which('ffmpeg') is not None
	ffprobe_ok = shutil.which('ffprobe') is not None
	return ffmpeg_ok and ffprobe_ok


#============================================
def roku_profile() -> base.MediaProfile:
	"""Return the H.264/AAC-only Roku-like media profile used for prepare tests.

	Args:
		None

	Returns:
		A MediaProfile that accepts mp4/mov/m4v containers with h264 video and aac audio.
	"""
	profile = base.MediaProfile(
		containers={'mp4', 'mov', 'm4v'},
		video_codecs={'h264'},
		audio_codecs={'aac'},
	)
	return profile


#============================================
def run_subprocess(command: list[str], step: str) -> bool:
	"""Run a subprocess command and record the PASS/FAIL result.

	Captures stdout and stderr. Records PASS when returncode is 0, FAIL
	otherwise.

	Args:
		command: The command argument list to run.
		step: Short name for the step, passed to record().

	Returns:
		True when the subprocess exited 0, False otherwise.
	"""
	completed = subprocess.run(command, capture_output=True, text=True)
	passed = completed.returncode == 0
	detail = ''
	if not passed:
		# Include the first line of stderr to help diagnose the failure.
		first_line = completed.stderr.strip().splitlines()
		if first_line:
			detail = first_line[0]
		else:
			detail = f'exit code {completed.returncode}'
	record(step, passed, detail)
	return passed


#============================================
def step_help() -> bool:
	"""Run `python3 stream.py --help` and verify it exits 0.

	Args:
		None

	Returns:
		True when the command exits 0.
	"""
	# Use stream.py from the repo root as the portable CLI entry point.
	stream_py = os.path.join(REPO_ROOT, 'stream.py')
	command = ['python3', stream_py, '--help']
	return run_subprocess(command, 'cli --help exits 0')


#============================================
def step_doctor() -> bool:
	"""Run `python3 stream.py doctor` and verify it exits 0.

	Doctor returns 0 when ffmpeg, ffprobe, and local address selection all pass.
	It prints PASS/FAIL/INFO/WARN lines; we capture all output and verify the
	exit code. On a machine without ffmpeg this step fails with a clear message.

	Args:
		None

	Returns:
		True when doctor exits 0.
	"""
	stream_py = os.path.join(REPO_ROOT, 'stream.py')
	command = ['python3', stream_py, 'doctor']
	return run_subprocess(command, 'doctor exits 0 (ffmpeg+ffprobe+address pass)')


#============================================
def step_make_fixtures() -> bool:
	"""Run e2e_make_fixtures.py to produce the 3 lavfi fixture files.

	Expects the fixtures to land in tests/fixtures/ under the repo root.
	Verifies that all three expected fixture files exist and are non-empty.

	Args:
		None

	Returns:
		True when all three fixture files exist and are non-empty.
	"""
	fixtures_script = os.path.join(REPO_ROOT, 'tests', 'e2e', 'e2e_make_fixtures.py')
	completed = subprocess.run(
		['python3', fixtures_script],
		capture_output=True, text=True,
	)
	# The script may already succeed from a prior run; allow both 0 exits.
	script_ok = completed.returncode == 0
	if not script_ok:
		first_line = completed.stderr.strip().splitlines()
		detail = first_line[0] if first_line else f'exit code {completed.returncode}'
		record('fixture generation (lavfi)', False, detail)
		return False
	# Verify all three expected output files exist and are non-empty.
	fixtures_dir = os.path.join(REPO_ROOT, 'tests', 'fixtures')
	expected = ['sample_h264.mp4', 'sample_h264.mkv', 'sample_hevc.mp4']
	missing = []
	for name in expected:
		fpath = os.path.join(fixtures_dir, name)
		if not os.path.isfile(fpath) or os.path.getsize(fpath) == 0:
			missing.append(name)
	passed = len(missing) == 0
	detail = '' if passed else f'missing or empty: {missing}'
	record('fixture generation (lavfi)', passed, detail)
	return passed


#============================================
def step_media_inspect_decide() -> bool:
	"""Inspect a fixture with ffprobe and verify decide() returns a sane mode.

	Uses the h264 MP4 fixture (passthrough for the Roku profile) and the HEVC MP4
	fixture (transcode for the Roku profile). Both must match the expected
	decision.

	Args:
		None

	Returns:
		True when both inspect and decide return the expected values.
	"""
	fixtures_dir = os.path.join(REPO_ROOT, 'tests', 'fixtures')
	h264_path = os.path.join(fixtures_dir, 'sample_h264.mp4')
	hevc_path = os.path.join(fixtures_dir, 'sample_hevc.mp4')

	profile = roku_profile()

	# Inspect the H.264 MP4.
	h264_info = media.inspect(h264_path)
	assert h264_info.video_codec == 'h264', f'expected h264 got {h264_info.video_codec}'
	assert h264_info.audio_codec == 'aac', f'expected aac got {h264_info.audio_codec}'
	assert h264_info.container == 'mov', f'expected mov got {h264_info.container}'
	h264_decision = media.decide(h264_info, profile)
	assert h264_decision == 'passthrough', f'expected passthrough got {h264_decision}'

	# Inspect the HEVC MP4 -- codec not in the Roku profile -> transcode.
	hevc_info = media.inspect(hevc_path)
	assert hevc_info.video_codec == 'hevc', f'expected hevc got {hevc_info.video_codec}'
	hevc_decision = media.decide(hevc_info, profile)
	assert hevc_decision == 'transcode', f'expected transcode got {hevc_decision}'

	record('media inspect + decide (h264->passthrough, hevc->transcode)', True)
	return True


#============================================
def step_media_prepare() -> bool:
	"""Run a real remux and transcode through airplay2tv.media.prepare.

	Remuxes the MKV fixture (H.264/AAC in Matroska) to an MP4 for the Roku
	profile, then transcodes the HEVC fixture to the portable H.264/AAC baseline.
	Checks that each produced file exists and has the expected codec.

	Args:
		None

	Returns:
		True when both prepare paths produce valid output.
	"""
	fixtures_dir = os.path.join(REPO_ROOT, 'tests', 'fixtures')
	mkv_path = os.path.join(fixtures_dir, 'sample_h264.mkv')
	hevc_path = os.path.join(fixtures_dir, 'sample_hevc.mp4')
	profile = roku_profile()

	# Remux: MKV H.264/AAC -> MP4 (same codecs, different container).
	with tempfile.TemporaryDirectory() as tmpdir:
		cancel = threading.Event()
		# No-op progress callback.
		prepared_remux = media.prepare(
			mkv_path, profile, tmpdir,
			lambda _f: None, cancel,
		)
		assert prepared_remux.path.endswith('remuxed.mp4'), (
			f'remux path unexpected: {prepared_remux.path}'
		)
		assert os.path.getsize(prepared_remux.path) > 0, 'remux output is empty'
		remux_info = media.inspect(prepared_remux.path)
		assert remux_info.video_codec == 'h264', (
			f'remux video codec: {remux_info.video_codec}'
		)
	record('media prepare remux (MKV->MP4)', True)

	# Transcode: HEVC MP4 -> portable H.264/AAC MP4.
	with tempfile.TemporaryDirectory() as tmpdir:
		cancel = threading.Event()
		prepared_tc = media.prepare(
			hevc_path, profile, tmpdir,
			lambda _f: None, cancel,
		)
		assert prepared_tc.path.endswith('transcoded.mp4'), (
			f'transcode path unexpected: {prepared_tc.path}'
		)
		assert os.path.getsize(prepared_tc.path) > 0, 'transcode output is empty'
		tc_info = media.inspect(prepared_tc.path)
		assert tc_info.video_codec == 'h264', (
			f'transcode video codec: {tc_info.video_codec}'
		)
	record('media prepare transcode (HEVC->H.264 MP4)', True)
	return True


#============================================
def step_http_range_server() -> bool:
	"""Start the HTTP range server, issue a Range request, assert 206.

	Binds the server to 127.0.0.1 on a free port, issues a GET with a
	Range: bytes=0-99 header via urllib, and asserts the response status is 206.
	Then shuts the server down cleanly.

	Args:
		None

	Returns:
		True when the server returns a 206 Partial Content response.
	"""
	fixtures_dir = os.path.join(REPO_ROOT, 'tests', 'fixtures')
	fixture_path = os.path.join(fixtures_dir, 'sample_h264.mp4')

	url, server, thread = httpserver.serve(fixture_path, '127.0.0.1', '127.0.0.1')

	passed = False
	detail = ''
	req = urllib.request.Request(url, headers={'Range': 'bytes=0-99'})
	try:
		# urllib raises HTTPError for non-2xx; 206 is 2xx so it arrives here.
		response = urllib.request.urlopen(req)  # nosec B310 - local controlled HTTP probe against the test httpserver
		status = response.status
		passed = status == 206
		detail = f'status={status}'
	except urllib.error.HTTPError as exc:
		passed = False
		detail = f'HTTPError {exc.code}'
	finally:
		httpserver.shutdown(server, thread)

	record('HTTP range server returns 206', passed, detail)
	return passed


#============================================
class FakeBackend(base.Backend):
	"""Minimal portable backend for the app-stream smoke flow.

	Declares backend_key='fake' and returns an H.264/AAC/MP4 media profile so
	a sample_h264.mp4 fixture is served as passthrough with no ffmpeg call.
	play() and stop() are no-ops so the smoke does not need a real device.
	"""

	backend_key = 'fake'

	#--------------------------------------------
	async def discover(self) -> list[base.Device]:
		"""Return a single fake device reachable at 127.0.0.1."""
		device = base.Device(
			name='Fake TV',
			backend=self.backend_key,
			identifier='fake-smoke-001',
			address='127.0.0.1',
		)
		return [device]

	#--------------------------------------------
	async def media_profile(self) -> base.MediaProfile:
		"""Return an H.264/AAC MP4 profile so the h264 fixture is passthrough."""
		profile = base.MediaProfile(
			containers={'mp4', 'mov', 'm4v'},
			video_codecs={'h264'},
			audio_codecs={'aac'},
		)
		return profile

	#--------------------------------------------
	async def play(self, device: base.Device, media_url: str, media_obj: object) -> None:
		"""Accept the play call as a no-op."""
		return None

	#--------------------------------------------
	async def stop(self, device: base.Device) -> None:
		"""Accept the stop call as a no-op."""
		return None

	#--------------------------------------------
	async def status(self, device: base.Device) -> base.PlaybackStatus:
		"""Return an idle status."""
		status = base.PlaybackStatus(state='idle')
		return status

	#--------------------------------------------
	async def needs_pairing(self, device: base.Device) -> bool:
		"""Report no pairing required so the stream flow does not prompt."""
		return False

	#--------------------------------------------
	async def pair(
		self,
		device: base.Device,
		prompt_pin: object,
	) -> base.PairingRecord:
		"""Return a dummy pairing record."""
		record_obj = base.PairingRecord(
			identifier=device.identifier,
			backend=self.backend_key,
			credential={'token': 'smoke'},
		)
		return record_obj

	#--------------------------------------------
	async def is_paired(self, device: base.Device) -> base.PairingState:
		"""Report PAIRED so no pairing prompt is shown."""
		return base.PairingState.PAIRED


#============================================
def step_fake_backend_app_stream() -> bool:
	"""Exercise the portable app-stream building blocks with FakeBackend.

	Exercises the same code path that app.run_stream uses without the full
	asyncio event loop: discover -> media_profile -> prepare (passthrough) ->
	httpserver.serve -> Range request -> shutdown. Uses FakeBackend so no real
	device, pyatv, or rokuecp is needed.

	Args:
		None

	Returns:
		True when the full flow completes without error.
	"""
	import asyncio

	fixtures_dir = os.path.join(REPO_ROOT, 'tests', 'fixtures')
	fixture_path = os.path.join(fixtures_dir, 'sample_h264.mp4')

	backend = FakeBackend()

	#--------------------------------------------
	async def run_flow() -> str:
		"""Run the discovery + prepare + serve + request flow asynchronously.

		Returns:
			The result detail string: 'ok' on success or an error description.
		"""
		devices = await backend.discover()
		assert devices, 'FakeBackend.discover() returned no devices'
		device = devices[0]

		profile = await backend.media_profile()

		# Prepare the fixture -- h264 MP4 against an h264/aac/mp4 profile is passthrough.
		with tempfile.TemporaryDirectory() as tmpdir:
			cancel = threading.Event()
			prepared = media.prepare(
				fixture_path, profile, tmpdir,
				lambda _f: None, cancel,
			)
			# Passthrough: path must be the original file, no temp output written.
			assert prepared.path == os.path.abspath(fixture_path), (
				f'passthrough path mismatch: {prepared.path}'
			)

			# Start the HTTP server on localhost.
			url, server, thread = httpserver.serve(prepared.path, '127.0.0.1', '127.0.0.1')

			detail = 'ok'
			req = urllib.request.Request(url, headers={'Range': 'bytes=0-9'})
			try:
				response = urllib.request.urlopen(req)  # nosec B310 - local controlled HTTP probe against the test httpserver
				status = response.status
				if status != 206:
					detail = f'expected 206 got {status}'
			except urllib.error.HTTPError as exc:
				detail = f'HTTPError {exc.code}'
			finally:
				httpserver.shutdown(server, thread)

			# Simulate a backend play call (no-op with FakeBackend).
			await backend.play(device, url, prepared)

		return detail

	detail = asyncio.run(run_flow())
	passed = detail == 'ok'
	record('fake-backend app stream flow (discover+prepare+serve+range)', passed, detail)
	return passed


#============================================
def print_summary(results: list[tuple[str, bool, str]]) -> None:
	"""Print the summary table and overall PASS/FAIL.

	Args:
		results: The accumulated (step, passed, detail) tuples.
	"""
	total = len(results)
	passed = sum(1 for _s, p, _d in results if p)
	failed = total - passed
	print('')
	print(f'Results: {passed}/{total} passed, {failed} failed')
	if failed > 0:
		print('FAIL: one or more steps failed')
	else:
		print('PASS: all steps passed')


#============================================
def main() -> None:
	"""Run all Debian portability smoke steps in order.

	Exits 0 when all steps pass, 1 when any step fails. If ffmpeg is missing,
	prints a clear message and exits 1 immediately so CI can distinguish a
	missing-dependency failure from a code failure.

	Args:
		None

	Returns:
		None
	"""
	# Pre-flight: both ffmpeg and ffprobe must be on PATH.
	if not have_ffmpeg():
		print('ERROR: ffmpeg and/or ffprobe not found on PATH.')
		print('On Debian: sudo apt install ffmpeg')
		print('On macOS:  brew install ffmpeg')
		sys.exit(1)

	print('=== airplay2tv Debian portability smoke ===')
	print('')

	# Run steps in order; each step records its own PASS/FAIL.
	step_help()
	step_doctor()
	step_make_fixtures()
	step_media_inspect_decide()
	step_media_prepare()
	step_http_range_server()
	step_fake_backend_app_stream()

	print_summary(_RESULTS)

	# Exit non-zero when any step failed.
	any_failed = any(not p for _s, p, _d in _RESULTS)
	if any_failed:
		sys.exit(1)


#============================================
if __name__ == '__main__':
	main()
