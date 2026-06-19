"""Cleanup and pairing-guard tests for the app stream flow.

These tests confirm `app.run_stream` releases both owned resources -- the temp
media directory and the HTTP server -- on every failure path, and that an
unpaired device on a headless (no-TTY) run raises PairingRequiredError instead
of hanging on a PIN prompt. All side-effecting calls are stubbed so the flow
runs offline with no ffmpeg, no socket, and no real device.
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
import airplay2tv.errors as errors
import airplay2tv.backends.base as base


#============================================
class FakeBackend(base.Backend):
	"""Configurable backend: control pairing state and whether play() fails."""

	#--------------------------------------------
	def __init__(self, paired: bool = True, play_raises: bool = False) -> None:
		self.backend_key = "fake"
		self.paired = paired
		self.play_raises = play_raises

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
		return base.MediaProfile(
			containers={"mp4"},
			video_codecs={"h264"},
			audio_codecs={"aac"},
		)

	#--------------------------------------------
	async def play(self, device: base.Device, media_url: str, media_obj: object) -> None:
		if self.play_raises:
			raise errors.Airplay2tvError("simulated playback failure")

	#--------------------------------------------
	async def stop(self, device: base.Device) -> None:
		return None

	#--------------------------------------------
	async def status(self, device: base.Device) -> base.PlaybackStatus:
		return base.PlaybackStatus(state="playing")

	#--------------------------------------------
	async def needs_pairing(self, device: base.Device) -> bool:
		return True

	#--------------------------------------------
	async def pair(
		self,
		device: base.Device,
		prompt_pin: collections.abc.Callable[[], str],
	) -> base.PairingRecord:
		return base.PairingRecord(identifier=device.identifier, backend="fake", credential={})

	#--------------------------------------------
	async def is_paired(self, device: base.Device) -> base.PairingState:
		if self.paired:
			return base.PairingState.PAIRED
		return base.PairingState.NOT_PAIRED


#============================================
class RecordingServer:
	"""Stand-in server object whose shutdown() flips a flag."""

	def __init__(self) -> None:
		self.shut_down = False


#============================================
def make_args() -> argparse.Namespace:
	"""Build a minimal stream-action namespace selecting the fake device."""
	return argparse.Namespace(
		command=None,
		input_file="/does/not/matter.mkv",
		device="fake-001",
		bind_host=None,
		save_device=False,
		media_mode=None,
		verbose=False,
		debug=False,
	)


#============================================
def patch_common(monkeypatch: pytest.MonkeyPatch, backend: FakeBackend) -> None:
	"""Patch the backend registry, network, and the Ctrl+C wait."""
	monkeypatch.setattr(app.registry, "active_backends", lambda: [backend])
	monkeypatch.setattr(app.netutil, "local_ip_for", lambda target: "192.0.2.2")
	monkeypatch.setattr(app, "wait_for_interrupt", lambda: None)


#============================================
def test_temp_removed_when_prepare_fails(monkeypatch: pytest.MonkeyPatch) -> None:
	backend = FakeBackend(paired=True)
	patch_common(monkeypatch, backend)
	captured: dict = {}

	def failing_prepare(
		args: object,
		profile: object,
		temp_dir: str,
		cancel_event: threading.Event,
	) -> None:
		captured["temp_dir"] = temp_dir
		raise errors.PreparationError("simulated prepare failure")

	monkeypatch.setattr(app, "prepare_media", failing_prepare)

	with pytest.raises(errors.PreparationError):
		app.run(make_args())

	# the temp dir created before prepare must be gone after the failure
	assert not os.path.exists(captured["temp_dir"])


#============================================
def test_temp_removed_and_server_shutdown_when_play_fails(monkeypatch: pytest.MonkeyPatch) -> None:
	backend = FakeBackend(paired=True, play_raises=True)
	patch_common(monkeypatch, backend)
	server = RecordingServer()
	captured: dict = {}
	prepared = media.PreparedMedia(path="/tmp/prepared.mp4", content_type="video/mp4")  # nosec B108 - test fixture path, not a real tempfile

	def fake_prepare(
		args: object,
		profile: object,
		temp_dir: str,
		cancel_event: threading.Event,
	) -> media.PreparedMedia:
		captured["temp_dir"] = temp_dir
		return prepared

	monkeypatch.setattr(app, "prepare_media", fake_prepare)

	def fake_serve(path: str, bind_host: str, advertised_host: str) -> tuple:
		thread = types.SimpleNamespace()
		return ("http://192.0.2.2:3500/media.mp4", server, thread)

	monkeypatch.setattr(app.httpserver, "serve", fake_serve)
	monkeypatch.setattr(app.httpserver, "shutdown", lambda srv, thread: setattr(srv, "shut_down", True))

	with pytest.raises(errors.Airplay2tvError):
		app.run(make_args())

	# a failure after serve must still shut the server and remove the temp dir
	assert server.shut_down is True
	assert not os.path.exists(captured["temp_dir"])


#============================================
def test_unpaired_headless_raises_pairing_required(monkeypatch: pytest.MonkeyPatch) -> None:
	backend = FakeBackend(paired=False)
	patch_common(monkeypatch, backend)
	# force the headless path: no controlling TTY to read a PIN
	monkeypatch.setattr(app.sys.stdin, "isatty", lambda: False)

	with pytest.raises(errors.PairingRequiredError):
		app.run(make_args())


#============================================
def test_keyboard_interrupt_during_prepare_sets_cancel_event_and_cleans_temp(
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	# Finding 1 (HIGH): a Ctrl+C during prepare_media must set cancel_event so an
	# in-flight ffmpeg is signalled to terminate before the temp dir is removed.
	backend = FakeBackend(paired=True)
	patch_common(monkeypatch, backend)
	captured: dict = {}

	def fake_prepare(
		args: object,
		profile: object,
		temp_dir: str,
		cancel_event: threading.Event,
	) -> media.PreparedMedia:
		# Record both the temp_dir and the cancel_event handed to prepare.
		captured["temp_dir"] = temp_dir
		captured["cancel_event"] = cancel_event
		raise KeyboardInterrupt

	monkeypatch.setattr(app, "prepare_media", fake_prepare)

	# run_stream wraps asyncio.run; call run() which dispatches to run_stream.
	app.run(make_args())

	# The cancel_event must be set before shutil.rmtree so ffmpeg can stop.
	assert captured["cancel_event"].is_set()
	# The temp dir must be gone after the interrupt.
	assert not os.path.exists(captured["temp_dir"])


#============================================
def test_headless_unreachable_default_raises_clear_error(
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	# Finding 9 (MED): when --default-device names an id that is not on the
	# network and there is no TTY, select_device must raise Airplay2tvError
	# with an actionable message rather than a raw ValueError from the picker.
	backend = FakeBackend(paired=True)
	# Registry returns the fake backend whose device has identifier "fake-001".
	monkeypatch.setattr(app.registry, "active_backends", lambda: [backend])
	# Force headless: no controlling TTY.
	monkeypatch.setattr(app.sys.stdin, "isatty", lambda: False)

	# Build an args namespace whose --default-device id is NOT in the discovered
	# device list so select_device hits the unreachable fallback path.
	args = argparse.Namespace(
		command=None,
		input_file="/does/not/matter.mkv",
		device=None,
		default_device="absent-device-id",
		bind_host=None,
		save_device=False,
		media_mode=None,
		verbose=False,
		debug=False,
	)

	with pytest.raises(errors.Airplay2tvError) as exc_info:
		app.run(args)

	# The error message must be actionable: mention --device or pair.
	assert "--device" in str(exc_info.value) or "pair" in str(exc_info.value)
