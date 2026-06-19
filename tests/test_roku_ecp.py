"""Pure-function tests for the Roku ECP backend.

These tests cover logic that needs no real socket or server: param building,
media profile shape, pairing state, and import isolation. All run in well under
one second with no network I/O.

Server-bound round-trip checks (launch, stop, status, resolve_address) live in
tests/e2e/e2e_roku_ecp.py where real asyncio/HTTP round-trips belong.
"""

# Standard Library
import asyncio

# local repo modules
import airplay2tv.backends.base
import airplay2tv.backends.roku_ecp as roku_ecp


#============================================
def _device_for(port: int) -> airplay2tv.backends.base.Device:
	"""Build a Device addressed at loopback for the fake server."""
	device = airplay2tv.backends.base.Device(
		name="Living Room TV",
		backend="roku-ecp",
		identifier="uuid:roku:ecp:SERIAL123",
		address="127.0.0.1",
		model="Sharp Roku TV",
	)
	return device


#============================================
def test_build_launch_params_uses_contentid_and_movie() -> None:
	"""play() builds contentId=<url> and the hardcoded mediaType=movie."""
	backend = roku_ecp.RokuEcpBackend()
	params = backend._build_launch_params("http://10.0.0.5:3500/clip.mp4")
	assert params["contentId"] == "http://10.0.0.5:3500/clip.mp4"
	assert params["mediaType"] == "movie"


#============================================
def test_media_profile_h264_aac_mp4_family() -> None:
	"""The Roku profile allows H.264 only, AAC audio, and the MP4 container set."""
	backend = roku_ecp.RokuEcpBackend()
	profile = asyncio.run(backend.media_profile())
	assert "h264" in profile.video_codecs
	# H.265 transcodes down on the user's TV, so it is not passthrough-capable.
	assert "hevc" not in profile.video_codecs
	assert "h265" not in profile.video_codecs
	assert "aac" in profile.audio_codecs
	assert {"mp4", "mov", "m4v"}.issubset(profile.containers)


#============================================
def test_needs_pairing_false_and_paired() -> None:
	"""Roku ECP needs no pairing and reports the PAIRED state."""
	backend = roku_ecp.RokuEcpBackend()
	device = _device_for(0)
	assert asyncio.run(backend.needs_pairing(device)) is False
	state = asyncio.run(backend.is_paired(device))
	assert state is airplay2tv.backends.base.PairingState.PAIRED


#============================================
def test_pair_returns_trivial_record() -> None:
	"""pair() returns an ECP-allowed record without invoking prompt_pin."""
	backend = roku_ecp.RokuEcpBackend()
	device = _device_for(0)

	def _no_pin() -> str:
		# This callback must never be called for Roku ECP pairing.
		raise AssertionError("prompt_pin must not be called for Roku ECP")

	record = asyncio.run(backend.pair(device, _no_pin))
	assert record.backend == "roku-ecp"
	assert record.identifier == device.identifier
	assert record.credential == {"ecp": "allowed"}


#============================================
def test_status_from_media_none_position_duration_no_type_error() -> None:
	"""_status_from_media with None position and duration must not raise TypeError.

	Finding 8 (MEDIUM): a live stream or device firmware that omits position or
	duration returns a MediaState with those fields set to None. The guard
	float(v) if v is not None else None must prevent the unconditional float()
	call from raising TypeError.
	"""
	import unittest.mock as mock

	backend = roku_ecp.RokuEcpBackend()
	# Build a minimal MediaState-like object with None position and duration.
	media = mock.MagicMock()
	media.paused = False
	media.position = None
	media.duration = None
	# Before the fix this raised TypeError; after the fix it returns None fields.
	status = backend._status_from_media(media)
	assert status.state == "playing"
	assert status.position is None
	assert status.duration is None


#============================================
def test_rokuecp_imported_only_in_backend_module() -> None:
	"""rokuecp is imported by the backend module and not by sibling core modules.

	The backend is the sole intended importer of the third-party client. This
	walks the airplay2tv package source and asserts no other module imports
	rokuecp directly.
	"""
	# Standard Library
	import os
	import pathlib

	# Locate the airplay2tv package directory next to the backends sub-package.
	backends_dir = pathlib.Path(roku_ecp.__file__).resolve().parent
	package_dir = backends_dir.parent
	offenders: list[str] = []
	for root, _dirs, files in os.walk(package_dir):
		for name in files:
			if not name.endswith(".py"):
				continue
			path = pathlib.Path(root) / name
			# The backend module is the one allowed importer.
			if path.resolve() == pathlib.Path(roku_ecp.__file__).resolve():
				continue
			text = path.read_text(encoding="utf-8")
			if "import rokuecp" in text or "from rokuecp" in text:
				offenders.append(str(path))
	assert offenders == [], f"rokuecp imported outside the backend: {offenders}"
