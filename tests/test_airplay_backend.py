"""Unit tests for the AirPlay backend in airplay2tv/backends/airplay.py.

Every pyatv touchpoint is replaced with `unittest.mock`, so these tests need no
Apple TV, no network, and no AirPlay PIN. They verify discovery mapping, the
play path (load credentials + call play_url + synchronous close), the
missing-credentials failure, and the backend-isolation rule that pyatv is
imported only inside the AirPlay backend module.

Live AirPlay playback cannot be exercised here because it requires the user to
enter the on-screen pairing PIN (deferred per hardware testing findings). These
tests prove the control-flow logic against a mocked pyatv surface instead.
"""

# Standard Library
import asyncio
import unittest.mock as mock

# PIP3 modules
import pytest

# local repo modules
import pyatv.const
import pyatv.exceptions
import airplay2tv.errors as errors
import airplay2tv.backends.base as base
import airplay2tv.backends.airplay as airplay


#============================================
def _make_device() -> base.Device:
	"""Build a stable AirPlay device for the control-path tests.

	Returns:
		A `base.Device` whose identifier the credential lookups key on.
	"""
	device = base.Device(
		name="Living Room",
		backend="airplay",
		identifier="airplay-001",
		address="192.0.2.10",
		model="Apple TV 4K",
	)
	return device


#============================================
def _make_config(identifier: str, name: str, address: str, model: str) -> mock.MagicMock:
	"""Build a mock pyatv config exposing the attributes the backend reads.

	Args:
		identifier: Stable per-device identifier the scan returns.
		name: Human-readable device name.
		address: Device IP; the backend stringifies it.
		model: Model string the backend reads via device_info.model_str.

	Returns:
		A `MagicMock` shaped like a pyatv BaseConfig.
	"""
	config = mock.MagicMock()
	config.identifier = identifier
	config.name = name
	config.address = address
	config.device_info.model_str = model
	return config


#============================================
def test_discover_maps_configs_to_devices() -> None:
	# two fake AirPlay configs the scan returns
	config_a = _make_config("id-a", "Bedroom", "192.0.2.11", "Apple TV HD")
	config_b = _make_config("id-b", "Kitchen", "192.0.2.12", "Apple TV 4K")

	async def fake_scan(loop: object, **kwargs: object) -> list:
		# the backend restricts the scan to the AirPlay protocol
		assert kwargs["protocol"] == pyatv.const.Protocol.AirPlay
		return [config_a, config_b]

	backend = airplay.AirPlayBackend()
	with mock.patch.object(airplay.pyatv, "scan", side_effect=fake_scan):
		devices = asyncio.run(backend.discover())

	assert len(devices) == 2
	assert devices[0].name == "Bedroom"
	assert devices[0].backend == "airplay"
	assert devices[0].identifier == "id-a"
	assert devices[0].address == "192.0.2.11"
	assert devices[0].model == "Apple TV HD"
	assert devices[1].identifier == "id-b"


#============================================
def test_media_profile_accepts_apple_codecs() -> None:
	backend = airplay.AirPlayBackend()
	profile = asyncio.run(backend.media_profile())
	# Apple TV decodes HEVC alongside H.264 with AAC audio
	assert "hevc" in profile.video_codecs
	assert "h264" in profile.video_codecs
	assert "aac" in profile.audio_codecs
	assert "mp4" in profile.containers


#============================================
def test_play_loads_credentials_and_calls_play_url() -> None:
	device = _make_device()
	config = _make_config(device.identifier, device.name, device.address, device.model)

	# a stored pairing record drives the AirPlay credential
	record = base.PairingRecord(
		identifier=device.identifier,
		backend="airplay",
		credential="stored-credential-string",
	)

	# the connected pyatv device; close() is synchronous and returns a set
	atv = mock.MagicMock()
	atv.close.return_value = set()
	atv.stream.play_url = mock.AsyncMock()

	async def fake_scan(loop: object, **kwargs: object) -> list:
		return [config]

	async def fake_connect(conf: object, loop: object) -> object:
		return atv

	backend = airplay.AirPlayBackend()
	with mock.patch.object(airplay.credentials, "get_record", return_value=record) as get_record, \
		mock.patch.object(airplay.pyatv, "scan", side_effect=fake_scan), \
		mock.patch.object(airplay.pyatv, "connect", side_effect=fake_connect):
		asyncio.run(backend.play(device, "http://192.0.2.75:56811/sample.mp4", object()))

	# credentials looked up by (identifier, backend)
	get_record.assert_called_once_with(device.identifier, "airplay")
	# the stored credential is applied to the AirPlay service
	config.set_credentials.assert_called_once_with(
		pyatv.const.Protocol.AirPlay, "stored-credential-string"
	)
	# the served URL is handed to the device
	atv.stream.play_url.assert_awaited_once_with("http://192.0.2.75:56811/sample.mp4")


#============================================
def test_play_closes_without_awaiting() -> None:
	# close() returns a plain set (not awaitable); awaiting it would raise TypeError
	device = _make_device()
	config = _make_config(device.identifier, device.name, device.address, device.model)
	record = base.PairingRecord(
		identifier=device.identifier,
		backend="airplay",
		credential="cred",
	)

	atv = mock.MagicMock()
	# a real awaited close() would crash on a set; use a sentinel set here
	close_sentinel = {"task-set"}
	atv.close.return_value = close_sentinel
	atv.stream.play_url = mock.AsyncMock()

	async def fake_scan(loop: object, **kwargs: object) -> list:
		return [config]

	async def fake_connect(conf: object, loop: object) -> object:
		return atv

	backend = airplay.AirPlayBackend()
	with mock.patch.object(airplay.credentials, "get_record", return_value=record), \
		mock.patch.object(airplay.pyatv, "scan", side_effect=fake_scan), \
		mock.patch.object(airplay.pyatv, "connect", side_effect=fake_connect):
		asyncio.run(backend.play(device, "http://host/sample.mp4", object()))

	# close() was called exactly once and its return value was never awaited
	atv.close.assert_called_once_with()


#============================================
def test_play_without_record_raises_pairing_required() -> None:
	device = _make_device()
	backend = airplay.AirPlayBackend()
	# no stored record: get_record returns None
	with mock.patch.object(airplay.credentials, "get_record", return_value=None):
		with pytest.raises(errors.PairingRequiredError):
			asyncio.run(backend.play(device, "http://host/sample.mp4", object()))


#============================================
def test_play_authentication_error_raises_pairing_required() -> None:
	device = _make_device()
	config = _make_config(device.identifier, device.name, device.address, device.model)
	record = base.PairingRecord(
		identifier=device.identifier,
		backend="airplay",
		credential="stale-credential",
	)

	atv = mock.MagicMock()
	atv.close.return_value = set()
	# play_url rejects the stale credential as observed during hardware testing
	atv.stream.play_url = mock.AsyncMock(
		side_effect=pyatv.exceptions.AuthenticationError("not authenticated")
	)

	async def fake_scan(loop: object, **kwargs: object) -> list:
		return [config]

	async def fake_connect(conf: object, loop: object) -> object:
		return atv

	backend = airplay.AirPlayBackend()
	with mock.patch.object(airplay.credentials, "get_record", return_value=record), \
		mock.patch.object(airplay.pyatv, "scan", side_effect=fake_scan), \
		mock.patch.object(airplay.pyatv, "connect", side_effect=fake_connect):
		with pytest.raises(errors.PairingRequiredError):
			asyncio.run(backend.play(device, "http://host/sample.mp4", object()))

	# even on the failure path, close() is still called once and not awaited
	atv.close.assert_called_once_with()


#============================================
def test_status_maps_playing_metadata() -> None:
	device = _make_device()
	config = _make_config(device.identifier, device.name, device.address, device.model)
	record = base.PairingRecord(
		identifier=device.identifier,
		backend="airplay",
		credential="cred",
	)

	# pyatv Playing metadata: playing state, 12s into a 100s clip
	playing = mock.MagicMock()
	playing.device_state = pyatv.const.DeviceState.Playing
	playing.position = 12
	playing.total_time = 100

	atv = mock.MagicMock()
	atv.close.return_value = set()
	atv.metadata.playing = mock.AsyncMock(return_value=playing)

	async def fake_scan(loop: object, **kwargs: object) -> list:
		return [config]

	async def fake_connect(conf: object, loop: object) -> object:
		return atv

	backend = airplay.AirPlayBackend()
	with mock.patch.object(airplay.credentials, "get_record", return_value=record), \
		mock.patch.object(airplay.pyatv, "scan", side_effect=fake_scan), \
		mock.patch.object(airplay.pyatv, "connect", side_effect=fake_connect):
		status = asyncio.run(backend.status(device))

	assert status.state == "playing"
	assert status.position == 12.0
	assert status.duration == 100.0


#============================================
def test_pair_runs_handshake_and_returns_record() -> None:
	device = _make_device()
	config = _make_config(device.identifier, device.name, device.address, device.model)

	# the pyatv pairing handler: begin -> pin -> finish -> credentials
	pairing = mock.MagicMock()
	pairing.begin = mock.AsyncMock()
	pairing.finish = mock.AsyncMock()
	pairing.close = mock.AsyncMock()
	pairing.has_paired = True
	pairing.service.credentials = "fresh-credential-string"

	async def fake_scan(loop: object, **kwargs: object) -> list:
		return [config]

	async def fake_pair(conf: object, protocol: object, loop: object) -> object:
		# pairing runs against the AirPlay protocol
		assert protocol == pyatv.const.Protocol.AirPlay
		return pairing

	def supply_pin() -> str:
		return "1234"

	backend = airplay.AirPlayBackend()
	with mock.patch.object(airplay.pyatv, "scan", side_effect=fake_scan), \
		mock.patch.object(airplay.pyatv, "pair", side_effect=fake_pair):
		record = asyncio.run(backend.pair(device, supply_pin))

	# the entered PIN was handed to the handler and the handshake finished
	pairing.pin.assert_called_once_with("1234")
	pairing.finish.assert_awaited_once()
	assert record.identifier == device.identifier
	assert record.backend == "airplay"
	assert record.credential == "fresh-credential-string"


#============================================
def test_pair_close_raising_does_not_mask_pairing_error() -> None:
	"""A close() exception must not swallow a wrong-PIN PairingRequiredError.

	Finding 3 (HIGH): if has_paired is False and pairing.close() also raises,
	the pairing error is the one the caller cares about. The close error is
	secondary and must be silenced so the original failure surfaces.
	"""
	device = _make_device()
	config = _make_config(device.identifier, device.name, device.address, device.model)

	# The handshake completes but the PIN was wrong: has_paired is False.
	pairing = mock.MagicMock()
	pairing.begin = mock.AsyncMock()
	pairing.finish = mock.AsyncMock()
	# close() also raises to simulate a session teardown failure.
	pairing.close = mock.AsyncMock(side_effect=RuntimeError("close failed"))
	pairing.has_paired = False

	async def fake_scan(loop: object, **kwargs: object) -> list:
		return [config]

	async def fake_pair(conf: object, protocol: object, loop: object) -> object:
		return pairing

	def supply_pin() -> str:
		return "9999"

	backend = airplay.AirPlayBackend()
	with mock.patch.object(airplay.pyatv, "scan", side_effect=fake_scan), \
		mock.patch.object(airplay.pyatv, "pair", side_effect=fake_pair):
		with pytest.raises(errors.PairingRequiredError):
			asyncio.run(backend.pair(device, supply_pin))


#============================================
def test_is_paired_reflects_stored_record() -> None:
	device = _make_device()
	record = base.PairingRecord(
		identifier=device.identifier,
		backend="airplay",
		credential="cred",
	)
	backend = airplay.AirPlayBackend()

	with mock.patch.object(airplay.credentials, "get_record", return_value=record):
		paired = asyncio.run(backend.is_paired(device))
	assert paired == base.PairingState.PAIRED

	with mock.patch.object(airplay.credentials, "get_record", return_value=None):
		unpaired = asyncio.run(backend.is_paired(device))
	assert unpaired == base.PairingState.NOT_PAIRED


#============================================
def test_pyatv_imported_only_in_airplay_backend() -> None:
	# Backend isolation: pyatv must be confined to the AirPlay backend module.
	# Every other airplay2tv source file must avoid importing pyatv so the core,
	# CLI, and Roku backend stay free of Apple-TV protocol detail.
	import os
	import airplay2tv

	package_dir = os.path.dirname(airplay2tv.__file__)
	offenders: list[str] = []
	for root, _dirs, files in os.walk(package_dir):
		for filename in files:
			if not filename.endswith(".py"):
				continue
			path = os.path.join(root, filename)
			# the AirPlay backend is the one allowed importer of pyatv
			if os.path.abspath(path) == os.path.abspath(airplay.__file__):
				continue
			with open(path, "r", encoding="ascii") as fh:
				source = fh.read()
			# flag any direct pyatv import in a non-AirPlay module
			if "import pyatv" in source:
				offenders.append(path)
	assert offenders == [], f"pyatv imported outside the AirPlay backend: {offenders}"
