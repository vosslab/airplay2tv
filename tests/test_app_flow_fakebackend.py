"""Full stream-flow test for `app.run` driven by an injected fake backend.

The test wires a `FakeBackend` (no pyatv, no rokuecp, no real device) and stubs
the two side-effecting helpers `app.run_stream` calls -- `media.prepare` and
`httpserver.serve` -- so the flow runs offline with no ffmpeg and no real
socket. It asserts the user-visible behavior: playback is started against the
advertised URL, and on a clean exit the server is shut down and the temp media
directory is removed.
"""

# Standard Library
import os
import types
import argparse
import threading
import collections.abc

# PIP3 modules
import pytest

# local repo modules
import airplay2tv.app as app
import airplay2tv.media as media
import airplay2tv.backends.base as base
import airplay2tv.discovery.discovery_result as discovery_result


#============================================
class FakeBackend(base.Backend):
	"""In-memory backend that records the play() call and reports paired."""

	#--------------------------------------------
	def __init__(self) -> None:
		self.backend_key = "fake"
		self.play_calls: list[tuple[str, object]] = []

	#--------------------------------------------
	async def discover(self) -> list[base.Device]:
		device = base.Device(
			name="Living Room",
			backend="fake",
			identifier="fake-001",
			address="192.0.2.10",
			model="FakeTV",
		)
		return [device]

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
		# record the URL and prepared media so the test can assert on them
		self.play_calls.append((media_url, media_obj))

	#--------------------------------------------
	async def stop(self, device: base.Device) -> None:
		return None

	#--------------------------------------------
	async def status(self, device: base.Device) -> base.PlaybackStatus:
		return base.PlaybackStatus(state="playing")

	#--------------------------------------------
	async def needs_pairing(self, device: base.Device) -> bool:
		return False

	#--------------------------------------------
	async def pair(
		self,
		device: base.Device,
		prompt_pin: collections.abc.Callable[[], str],
	) -> base.PairingRecord:
		return base.PairingRecord(identifier=device.identifier, backend="fake", credential={})

	#--------------------------------------------
	async def is_paired(self, device: base.Device) -> base.PairingState:
		return base.PairingState.PAIRED


#============================================
class RecordingServer:
	"""Stand-in for the httpserver server object; records shutdown calls."""

	def __init__(self) -> None:
		self.shut_down = False


#============================================
def make_args() -> argparse.Namespace:
	"""Build a minimal stream-action namespace with no subcommand."""
	args = argparse.Namespace(
		command=None,
		input_file="/does/not/matter.mkv",
		device="fake-001",
		bind_host=None,
		save_device=False,
		media_mode=None,
		verbose=False,
		debug=False,
	)
	return args


#============================================
def install_stubs(
	monkeypatch: pytest.MonkeyPatch,
	backend: FakeBackend,
	server: RecordingServer,
	prepared: media.PreparedMedia,
) -> dict:
	"""Patch the app's external calls so the flow runs offline.

	Returns a record dict the test inspects for the served path and the
	directory that existed while serving.
	"""
	record: dict = {}
	monkeypatch.setattr(app.registry, "active_backends", lambda: [backend])

	def fake_prepare(
		args: object,
		profile: object,
		temp_dir: str,
		cancel_event: threading.Event,
	) -> media.PreparedMedia:
		# the temp dir must exist when prepare runs, mirroring real behavior
		record["temp_dir_during_prepare"] = temp_dir
		record["temp_dir_existed"] = os.path.isdir(temp_dir)
		return prepared

	monkeypatch.setattr(app, "prepare_media", fake_prepare)

	def fake_serve(path: str, bind_host: str, advertised_host: str) -> tuple:
		record["served_path"] = path
		record["advertised_host"] = advertised_host
		thread = types.SimpleNamespace()
		url = f"http://{advertised_host}:3500/media.mp4"
		return (url, server, thread)

	monkeypatch.setattr(app.httpserver, "serve", fake_serve)

	def fake_shutdown(srv: object, thread: object) -> None:
		srv.shut_down = True

	monkeypatch.setattr(app.httpserver, "shutdown", fake_shutdown)
	monkeypatch.setattr(app.netutil, "local_ip_for", lambda target: "192.0.2.2")
	# Return immediately instead of blocking on a Ctrl+C wait.
	monkeypatch.setattr(app, "wait_for_interrupt", lambda: None)
	return record


#============================================
def test_stream_run_starts_playback_and_returns_zero(monkeypatch: pytest.MonkeyPatch) -> None:
	backend = FakeBackend()
	server = RecordingServer()
	prepared = media.PreparedMedia(path="/tmp/prepared.mp4", content_type="video/mp4")  # nosec B108 - test fixture path, not a real tempfile
	install_stubs(monkeypatch, backend, server, prepared)

	exit_code = app.run(make_args())

	# playback was started exactly once against the advertised URL
	assert len(backend.play_calls) == 1
	played_url, played_media = backend.play_calls[0]
	assert played_url == "http://192.0.2.2:3500/media.mp4"
	assert played_media is prepared
	assert exit_code == 0


#============================================
def test_stream_run_cleans_up_after_success(monkeypatch: pytest.MonkeyPatch) -> None:
	backend = FakeBackend()
	server = RecordingServer()
	prepared = media.PreparedMedia(path="/tmp/prepared.mp4", content_type="video/mp4")  # nosec B108 - test fixture path, not a real tempfile
	record = install_stubs(monkeypatch, backend, server, prepared)

	app.run(make_args())

	# the server was shut down and the temp media dir was removed on exit
	assert server.shut_down is True
	assert record["temp_dir_existed"] is True
	assert not os.path.exists(record["temp_dir_during_prepare"])


#============================================
def test_stream_run_no_devices_returns_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.setattr(app.registry, "active_backends", lambda: [])
	monkeypatch.setattr(app.aggregate, "discover_all", _empty_discover)

	exit_code = app.run(make_args())

	assert exit_code != 0


#============================================
async def _empty_discover(
	backends: list,
	timeout: object,
	on_backend_done: object = None,
) -> discovery_result.DiscoveryResult:
	# stand-in discover_all that finds nothing, regardless of backends passed
	return discovery_result.DiscoveryResult(devices=[], failures=[])
