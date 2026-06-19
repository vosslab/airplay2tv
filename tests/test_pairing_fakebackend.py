"""Tests for airplay2tv.pairing using an injected FakeBackend.

All tests run offline: no pyatv, no rokuecp, no real device, no real filesystem
credentials.  The FakeBackend simulates a 4-digit PIN challenge; monkeypatching
`airplay2tv.pairing.prompt_pin` and the credentials layer lets the tests assert
on prompt behavior and record storage without any I/O.
"""

# Standard Library
import pathlib
import argparse
import collections.abc

# PIP3 modules
import pytest

# local repo modules
import airplay2tv.pairing as pairing
import airplay2tv.backends.base as base
import airplay2tv.credentials as credentials


#============================================
class FakePairingBackend(base.Backend):
	"""Simulates a backend that requires a 4-digit PIN pairing challenge."""

	#--------------------------------------------
	def __init__(self, initial_state: base.PairingState = base.PairingState.NOT_PAIRED) -> None:
		self.backend_key = "fakepair"
		self._initial_state = initial_state
		# Track whether pair() was called so tests can assert on it.
		self.pair_called: bool = False

	#--------------------------------------------
	async def discover(self) -> list[base.Device]:
		device = base.Device(
			name="Test TV",
			backend="fakepair",
			identifier="fakepair-001",
			address="192.0.2.20",
			model="FakePairTV",
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
		return None

	#--------------------------------------------
	async def stop(self, device: base.Device) -> None:
		return None

	#--------------------------------------------
	async def status(self, device: base.Device) -> base.PlaybackStatus:
		return base.PlaybackStatus(state="idle")

	#--------------------------------------------
	async def needs_pairing(self, device: base.Device) -> bool:
		return True

	#--------------------------------------------
	async def pair(
		self,
		device: base.Device,
		prompt_pin: collections.abc.Callable[[], str],
	) -> base.PairingRecord:
		# Simulate the TV showing a 4-digit PIN and waiting for the user to read it.
		self.pair_called = True
		# Call prompt_pin as the real backend would when the PIN appears on screen.
		_entered = prompt_pin()
		# Return a synthetic credential that records the entered code.
		record = base.PairingRecord(
			identifier=device.identifier,
			backend=device.backend,
			credential=f"fake-credential-{_entered}",
		)
		return record

	#--------------------------------------------
	async def is_paired(self, device: base.Device) -> base.PairingState:
		return self._initial_state


#============================================
def _make_args(device: str | None = "fakepair-001") -> argparse.Namespace:
	"""Build a minimal pair-subcommand namespace."""
	args = argparse.Namespace(
		command="pair",
		device=device,
	)
	return args


#============================================
def _install_fake_backend(monkeypatch: pytest.MonkeyPatch, backend: FakePairingBackend) -> None:
	"""Patch registry and discovery so only the fake backend is visible."""
	monkeypatch.setattr(pairing.registry, "active_backends", lambda: [backend])

	async def fake_discover_all(backends: list, timeout: object) -> list:
		# Delegate to the single fake backend to keep device data consistent.
		if not backends:
			return []
		return await backends[0].discover()

	monkeypatch.setattr(pairing.aggregate, "discover_all", fake_discover_all)


#============================================
def test_pairing_prompts_and_saves_record(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
	"""run() calls prompt_pin, saves a credential, and returns 0."""
	backend = FakePairingBackend(initial_state=base.PairingState.NOT_PAIRED)
	_install_fake_backend(monkeypatch, backend)

	# Intercept prompt_pin so no real stdin is touched.
	prompted: list[int] = []
	def fake_prompt_pin() -> str:
		prompted.append(1)
		return "1234"
	monkeypatch.setattr(pairing, "prompt_pin", fake_prompt_pin)

	# Intercept credentials.save_record to capture the saved record.
	saved: list[base.PairingRecord] = []
	monkeypatch.setattr(credentials, "save_record", lambda r: saved.append(r))

	exit_code = pairing.run(_make_args())

	# prompt_pin was called exactly once (the backend asked for the code)
	assert len(prompted) == 1
	# a record was persisted with the expected credential payload
	assert len(saved) == 1
	assert saved[0].identifier == "fakepair-001"
	assert exit_code == 0


#============================================
def test_already_paired_skips_prompt_and_returns_zero(monkeypatch: pytest.MonkeyPatch) -> None:
	"""run() skips prompt_pin when the device is already paired and a record exists."""
	backend = FakePairingBackend(initial_state=base.PairingState.PAIRED)
	_install_fake_backend(monkeypatch, backend)

	# A stored record must exist for the already-paired branch to trigger.
	stored = base.PairingRecord(
		identifier="fakepair-001",
		backend="fakepair",
		credential="pre-existing-cred",
	)
	monkeypatch.setattr(credentials, "get_record", lambda ident, bk: stored)

	# prompt_pin must not be called; tracking the call count proves it.
	prompted: list[int] = []
	def unexpected_prompt() -> str:
		prompted.append(1)
		return "9999"
	monkeypatch.setattr(pairing, "prompt_pin", unexpected_prompt)

	exit_code = pairing.run(_make_args())

	# No PIN was requested because the device was already paired.
	assert len(prompted) == 0
	assert exit_code == 0


#============================================
def test_find_backend_exact_key_match() -> None:
	"""_find_backend matches by backend_key only; single-backend fallback removed."""
	backend = FakePairingBackend()
	# backend_key is "fakepair"; device.backend must equal it to match
	device = base.Device(
		name="Test TV",
		backend="fakepair",
		identifier="fp-001",
		address="192.0.2.1",
	)
	result = pairing._find_backend([backend], device)
	assert result is backend


#============================================
def test_find_backend_mismatched_key_returns_none() -> None:
	"""_find_backend returns None when device.backend does not match any active backend.

	This mirrors app.backend_for_device which also raises on a key mismatch.
	The single-backend fallback that was in the old code would have silently
	returned the one backend; now both code paths surface the mismatch.
	"""
	backend = FakePairingBackend()
	# backend_key is "fakepair" but device.backend is "unknown"
	device = base.Device(
		name="Mystery TV",
		backend="unknown",
		identifier="myst-001",
		address="192.0.2.2",
	)
	result = pairing._find_backend([backend], device)
	assert result is None
