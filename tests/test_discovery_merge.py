"""Tests for discovery aggregation and device picker.

Covers:
- discover_all merges results from multiple fake backends concurrently.
- discover_all tolerates a backend that raises an exception (zero contribution).
- discover_all tolerates a backend that returns an empty list.
- devicepick.render: numbered list with correct fields.
- devicepick.render: duplicate-name disambiguation via address.
- devicepick.select: match by exact name.
- devicepick.select: match by exact identifier.
- devicepick.select: raises clearly on not-found.
- devicepick.select: raises on ambiguous match.
"""

# Standard Library
import asyncio

# local repo modules
import airplay2tv.devicepick
import airplay2tv.backends.base
import airplay2tv.discovery.aggregate


#============================================
def _make_device(
	name: str,
	backend: str = "fake",
	identifier: str = "id-1",
	address: str = "192.168.1.1",
) -> airplay2tv.backends.base.Device:
	"""Build a Device with caller-supplied fields, using defaults for the rest."""
	return airplay2tv.backends.base.Device(
		name=name,
		backend=backend,
		identifier=identifier,
		address=address,
	)


#============================================
class FakeBackend(airplay2tv.backends.base.Backend):
	"""Minimal fake backend returning a fixed list of Device objects.

	The constructor accepts an optional callable that, when supplied, is called
	during discover() instead of returning devices; this lets tests simulate an
	exception from a backend.
	"""

	def __init__(
		self,
		devices: list[airplay2tv.backends.base.Device] | None = None,
		raise_exc: Exception | None = None,
	) -> None:
		# Store devices as a list; default to empty
		self._devices: list[airplay2tv.backends.base.Device] = devices if devices is not None else []
		self._raise_exc = raise_exc

	async def discover(self) -> list[airplay2tv.backends.base.Device]:
		if self._raise_exc is not None:
			raise self._raise_exc
		return list(self._devices)

	async def media_profile(self) -> airplay2tv.backends.base.MediaProfile:
		return airplay2tv.backends.base.MediaProfile(
			containers=frozenset({"mp4"}),
			video_codecs=frozenset({"h264"}),
			audio_codecs=frozenset({"aac"}),
		)

	async def play(self, device: airplay2tv.backends.base.Device, media_url: str, media: object) -> None:
		pass

	async def stop(self, device: airplay2tv.backends.base.Device) -> None:
		pass

	async def status(self, device: airplay2tv.backends.base.Device) -> airplay2tv.backends.base.PlaybackStatus:
		return airplay2tv.backends.base.PlaybackStatus(state="stopped")

	async def needs_pairing(self, device: airplay2tv.backends.base.Device) -> bool:
		return False

	async def pair(
		self,
		device: airplay2tv.backends.base.Device,
		prompt_pin: object,
	) -> airplay2tv.backends.base.PairingRecord:
		return airplay2tv.backends.base.PairingRecord(
			identifier=device.identifier,
			backend=device.backend,
			credential="fake-cred",
		)

	async def is_paired(self, device: airplay2tv.backends.base.Device) -> airplay2tv.backends.base.PairingState:
		return airplay2tv.backends.base.PairingState.PAIRED


#============================================
def test_discover_all_merges_multiple_backends() -> None:
	"""discover_all returns combined devices from two backends."""
	device_a = _make_device("Alpha", identifier="a-1", address="10.0.0.1")
	device_b = _make_device("Beta", identifier="b-1", address="10.0.0.2")
	backend_a = FakeBackend(devices=[device_a])
	backend_b = FakeBackend(devices=[device_b])

	result = asyncio.run(
		airplay2tv.discovery.aggregate.discover_all([backend_a, backend_b], timeout=5.0)
	)

	assert device_a in result
	assert device_b in result


def test_discover_all_tolerates_backend_that_raises() -> None:
	"""discover_all ignores a backend that raises; others still contribute."""
	good_device = _make_device("Good", identifier="g-1")
	good_backend = FakeBackend(devices=[good_device])
	bad_backend = FakeBackend(raise_exc=RuntimeError("network failure"))

	result = asyncio.run(
		airplay2tv.discovery.aggregate.discover_all([good_backend, bad_backend], timeout=5.0)
	)

	assert good_device in result


def test_discover_all_tolerates_backend_that_returns_empty() -> None:
	"""discover_all handles a backend returning no devices."""
	device = _make_device("OnlyOne", identifier="o-1")
	present_backend = FakeBackend(devices=[device])
	empty_backend = FakeBackend(devices=[])

	result = asyncio.run(
		airplay2tv.discovery.aggregate.discover_all([present_backend, empty_backend], timeout=5.0)
	)

	assert device in result


def test_discover_all_empty_backends_list() -> None:
	"""discover_all returns an empty list when given no backends."""
	result = asyncio.run(
		airplay2tv.discovery.aggregate.discover_all([], timeout=5.0)
	)
	assert result == []


#============================================
def test_render_numbered_list() -> None:
	"""render produces a numbered list with the expected fields."""
	device = _make_device("Living Room", backend="airplay", identifier="uuid-abc", address="10.0.0.5")
	output = airplay2tv.devicepick.render([device])

	# Must contain the 1-based index
	assert "1." in output
	# Must contain key device fields
	assert "Living Room" in output
	assert "airplay" in output
	assert "uuid-abc" in output
	assert "10.0.0.5" in output


def test_render_duplicate_name_disambiguation() -> None:
	"""render appends the address when two devices share the same name."""
	device_a = _make_device("Family Room", identifier="id-a", address="192.168.1.10")
	device_b = _make_device("Family Room", identifier="id-b", address="192.168.1.20")
	output = airplay2tv.devicepick.render([device_a, device_b])

	# Both addresses must appear so the user can distinguish the two
	assert "192.168.1.10" in output
	assert "192.168.1.20" in output


def test_render_unique_names_no_address_appended() -> None:
	"""render does not append duplicate-disambiguation for unique names."""
	device_a = _make_device("Kitchen", identifier="id-a", address="192.168.1.10")
	device_b = _make_device("Bedroom", identifier="id-b", address="192.168.1.20")
	output = airplay2tv.devicepick.render([device_a, device_b])

	# Address still present via addr= field; just verify name not wrapped in parens
	# A unique name line should not show (address) immediately after the name
	assert "Kitchen (192.168.1.10)" not in output
	assert "Bedroom (192.168.1.20)" not in output


#============================================
def test_select_by_name() -> None:
	"""select returns the device matching the exact requested name."""
	device = _make_device("Office TV", identifier="off-1", address="10.0.0.9")
	result = airplay2tv.devicepick.select([device], requested="Office TV")
	assert result is device


def test_select_by_identifier() -> None:
	"""select returns the device matching the exact requested identifier."""
	device = _make_device("Den TV", identifier="den-uuid-42", address="10.0.0.7")
	result = airplay2tv.devicepick.select([device], requested="den-uuid-42")
	assert result is device


def test_select_raises_on_not_found() -> None:
	"""select raises ValueError with a clear message when no match is found."""
	device = _make_device("Lounge", identifier="lg-1")
	try:
		airplay2tv.devicepick.select([device], requested="Nonexistent")
		assert False, "Expected ValueError"
	except ValueError as exc:
		# The error message should name the missing requested string
		assert "Nonexistent" in str(exc)


def test_select_raises_on_ambiguous_match() -> None:
	"""select raises ValueError when multiple devices share the same name."""
	device_a = _make_device("Shared", identifier="s-a", address="10.0.0.1")
	device_b = _make_device("Shared", identifier="s-b", address="10.0.0.2")
	try:
		airplay2tv.devicepick.select([device_a, device_b], requested="Shared")
		assert False, "Expected ValueError"
	except ValueError as exc:
		# Error message should indicate ambiguity
		assert "ambiguous" in str(exc).lower() or "multiple" in str(exc).lower()


def test_select_no_tty_no_requested_raises() -> None:
	"""select raises ValueError when requested is None and stdin has no TTY."""
	device = _make_device("Bedroom TV", identifier="bed-1")
	# The test runner has no TTY (sys.stdin.isatty() returns False in pytest),
	# so calling select with requested=None must raise.
	try:
		airplay2tv.devicepick.select([device], requested=None)
		assert False, "Expected ValueError"
	except ValueError as exc:
		assert "tty" in str(exc).lower() or "--device" in str(exc).lower()


#============================================
class SlowBackend(airplay2tv.backends.base.Backend):
	"""Backend that sleeps for a configurable delay before returning devices.

	Used to verify that a slow backend's timeout does not cancel fast backends.
	"""

	def __init__(
		self,
		delay: float,
		devices: list[airplay2tv.backends.base.Device] | None = None,
	) -> None:
		# delay in seconds before discover() returns
		self._delay = delay
		self._devices: list[airplay2tv.backends.base.Device] = devices if devices is not None else []

	async def discover(self) -> list[airplay2tv.backends.base.Device]:
		# Simulate a slow network scan; will be cancelled by per-backend timeout
		await asyncio.sleep(self._delay)
		return list(self._devices)

	async def media_profile(self) -> airplay2tv.backends.base.MediaProfile:
		return airplay2tv.backends.base.MediaProfile(
			containers=frozenset({"mp4"}),
			video_codecs=frozenset({"h264"}),
			audio_codecs=frozenset({"aac"}),
		)

	async def play(self, device: airplay2tv.backends.base.Device, media_url: str, media: object) -> None:
		pass

	async def stop(self, device: airplay2tv.backends.base.Device) -> None:
		pass

	async def status(self, device: airplay2tv.backends.base.Device) -> airplay2tv.backends.base.PlaybackStatus:
		return airplay2tv.backends.base.PlaybackStatus(state="stopped")

	async def needs_pairing(self, device: airplay2tv.backends.base.Device) -> bool:
		return False

	async def pair(
		self,
		device: airplay2tv.backends.base.Device,
		prompt_pin: object,
	) -> airplay2tv.backends.base.PairingRecord:
		return airplay2tv.backends.base.PairingRecord(
			identifier=device.identifier,
			backend=device.backend,
			credential="fake-cred",
		)

	async def is_paired(self, device: airplay2tv.backends.base.Device) -> airplay2tv.backends.base.PairingState:
		return airplay2tv.backends.base.PairingState.PAIRED


def test_slow_backend_does_not_cancel_fast_backend() -> None:
	"""A slow backend timing out does not prevent fast backends from contributing.

	With the per-backend asyncio.wait_for approach, each backend has its own
	timeout.  The fast backend returns its device before the timeout; the slow
	backend is cancelled by its own timeout and contributes nothing.  The merged
	result contains only the fast backend's device.
	"""
	fast_device = _make_device("Fast TV", identifier="fast-1", address="10.0.0.1")
	# fast backend returns immediately; slow backend takes 0.5 s
	fast_backend = FakeBackend(devices=[fast_device])
	# 0.5 s sleep exceeds the 0.05 s per-backend timeout; will time out
	slow_backend = SlowBackend(delay=0.5, devices=[])

	result = asyncio.run(
		airplay2tv.discovery.aggregate.discover_all(
			[fast_backend, slow_backend],
			timeout=0.05,
		)
	)

	# The fast backend's device must be present despite the slow backend timing out
	assert fast_device in result
