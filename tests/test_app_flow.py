"""App-flow tests for backend-key matching, device selection, persistence,
and CLI error mapping.

These exercise the synchronous, offline parts of the orchestration layer
(`airplay2tv.app`) and the top-level error mapping in `airplay2tv.cli`. A
`FakeBackend` stands in for real receivers so nothing here touches pyatv,
rokuecp, or the network.
"""

# Standard Library
import asyncio
import argparse
import collections.abc

# PIP3 modules
import pytest

# local repo modules
import airplay2tv.app as app
import airplay2tv.cli as cli
import airplay2tv.config as config
import airplay2tv.errors as errors
import airplay2tv.backends.base as base


#============================================
class FakeBackend(base.Backend):
	"""Minimal backend with a declared backend_key and one fixed device."""

	backend_key = "fake"

	#--------------------------------------------
	async def discover(self) -> list[base.Device]:
		return [_make_device()]

	#--------------------------------------------
	async def media_profile(self) -> base.MediaProfile:
		return base.MediaProfile(
			containers={"mp4"},
			video_codecs={"h264"},
			audio_codecs={"aac"},
		)

	#--------------------------------------------
	async def play(self, device: base.Device, media_url: str, media: object) -> None:
		return None

	#--------------------------------------------
	async def stop(self, device: base.Device) -> None:
		return None

	#--------------------------------------------
	async def status(self, device: base.Device) -> base.PlaybackStatus:
		return base.PlaybackStatus(state="idle")

	#--------------------------------------------
	async def needs_pairing(self, device: base.Device) -> bool:
		return False

	#--------------------------------------------
	async def pair(
		self,
		device: base.Device,
		prompt_pin: collections.abc.Callable[[], str],
	) -> base.PairingRecord:
		return base.PairingRecord(
			identifier=device.identifier,
			backend=self.backend_key,
			credential={"token": "x"},
		)

	#--------------------------------------------
	async def is_paired(self, device: base.Device) -> base.PairingState:
		return base.PairingState.PAIRED


#============================================
def _make_device(
	name: str = "Living Room",
	backend: str = "fake",
	identifier: str = "fake-001",
	address: str = "192.0.2.10",
) -> base.Device:
	device = base.Device(
		name=name,
		backend=backend,
		identifier=identifier,
		address=address,
	)
	return device


#============================================
def _args(**overrides: object) -> argparse.Namespace:
	"""Build a stream-action namespace with selectable overrides."""
	values = {
		"device": None,
		"default_device": None,
		"save_device": False,
		"debug": False,
	}
	values.update(overrides)
	return argparse.Namespace(**values)


#============================================
class ResolvingBackend(FakeBackend):
	"""FakeBackend that resolves a known IP directly via resolve_address."""

	#--------------------------------------------
	async def resolve_address(self, address: str) -> base.Device | None:
		# Stamp the probed IP onto a device so the IP-selection path is visible.
		return _make_device(identifier="resolved-001", address=address)


#============================================
def test_resolve_known_address_uses_ip_device_with_empty_discovery() -> None:
	# A bare-IP --device with empty discovery resolves through the backend.
	backend = ResolvingBackend()
	args = _args(device="192.0.2.55")
	chosen = asyncio.run(app.resolve_known_address([backend], args, []))
	assert chosen is not None
	assert chosen.address == "192.0.2.55"
	assert chosen.identifier == "resolved-001"


#============================================
def test_resolve_known_address_skips_non_ip_device(
	tmp_path: object,
	monkeypatch: object,
) -> None:
	# A --device that is a name, not an IP, leaves the resolve path untouched.
	# Isolate config so the stored-default branch sees an empty store.
	monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
	backend = ResolvingBackend()
	args = _args(device="Living Room")
	chosen = asyncio.run(app.resolve_known_address([backend], args, []))
	assert chosen is None


#============================================
def test_resolve_known_address_skips_already_discovered_ip(
	tmp_path: object,
	monkeypatch: object,
) -> None:
	# An IP that discovery already surfaced is selected normally, not re-probed.
	monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
	backend = ResolvingBackend()
	args = _args(device="192.0.2.10")
	discovered = [_make_device(address="192.0.2.10")]
	chosen = asyncio.run(app.resolve_known_address([backend], args, discovered))
	assert chosen is None


#============================================
def test_looks_like_ip_distinguishes_ip_from_name() -> None:
	# IP literals are recognized; device names and ids are not.
	assert app.looks_like_ip("192.168.2.61") is True
	assert app.looks_like_ip("Living Room TV") is False


#============================================
def test_backend_for_device_matches_by_key() -> None:
	# The device's stamped key selects the owning backend by exact match.
	backend = FakeBackend()
	device = _make_device()
	resolved = app.backend_for_device([backend], device)
	assert resolved is backend


#============================================
def test_backend_for_device_unknown_key_raises() -> None:
	# A device whose backend nobody owns is a defect, not a silent fallback.
	backend = FakeBackend()
	device = _make_device(backend="nobody-owns-this")
	with pytest.raises(errors.Airplay2tvError):
		app.backend_for_device([backend], device)


#============================================
def test_select_device_uses_reachable_default(monkeypatch: object) -> None:
	# A --default-device that is discoverable skips the picker entirely.
	def explode(*_a: object, **_k: object) -> base.Device:
		raise AssertionError("picker must not run when the default is reachable")

	monkeypatch.setattr(app.devicepick, "select", explode)
	devices = [_make_device(identifier="other"), _make_device(identifier="fake-001")]
	chosen = app.select_device(_args(default_device="fake-001"), devices)
	assert chosen.identifier == "fake-001"


#============================================
def test_select_device_falls_back_when_default_unreachable(
	monkeypatch: object,
	capsys: object,
) -> None:
	# An unreachable default prints a notice and defers to the picker on a TTY.
	# Simulate a TTY so the headless guard does not fire.
	monkeypatch.setattr(app.sys.stdin, "isatty", lambda: True)
	picked = _make_device(identifier="picked")

	def fake_select(devices: list, requested: object) -> base.Device:
		return picked

	monkeypatch.setattr(app.devicepick, "select", fake_select)
	devices = [_make_device(identifier="present")]
	chosen = app.select_device(_args(default_device="missing-id"), devices)
	captured = capsys.readouterr()
	assert chosen is picked
	assert "not reachable" in captured.err


#============================================
def test_persist_device_saves_and_sets_default(
	tmp_path: object,
	monkeypatch: object,
) -> None:
	# --save-device with a matching --default-device writes the record and marks
	# it the stored default so a later no-flag run reuses it.
	monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
	# Seed an on-disk config so config.load() reads a fresh dict from disk
	# instead of the shared module-level default (see HANDOFF: config.load bug).
	config.save({"version": 1, "devices": [], "default_device_id": None})
	device = _make_device()
	args = _args(save_device=True, default_device=device.identifier)
	app.persist_device(args, device)
	loaded = config.load()
	assert config.get_device(loaded, device.identifier) is not None
	assert config.get_default_device_id(loaded) == device.identifier


#============================================
def test_persist_device_noop_without_flags(
	tmp_path: object,
	monkeypatch: object,
) -> None:
	# With neither flag set, nothing is written: no config file is created.
	monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
	app.persist_device(_args(), _make_device())
	config_file = tmp_path / "airplay2tv" / "config.yaml"
	assert not config_file.exists()


#============================================
def test_dispatch_maps_known_error_to_exit_one(capsys: object) -> None:
	# A deliberate Airplay2tvError becomes one readable stderr line, exit 1.
	class FakeApp:
		def run(self, args: object) -> int:
			raise errors.DeviceUnreachableError("device is off")

	code = cli.dispatch(FakeApp(), _args())
	captured = capsys.readouterr()
	assert code == 1
	assert "device is off" in captured.err


#============================================
def test_dispatch_lets_unexpected_error_propagate() -> None:
	# An unexpected (non-Airplay2tvError) bug must not be swallowed.
	class FakeApp:
		def run(self, args: object) -> int:
			raise RuntimeError("real bug")

	with pytest.raises(RuntimeError):
		cli.dispatch(FakeApp(), _args())
