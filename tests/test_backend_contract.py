"""Contract test for the backend interface in airplay2tv/backends/base.py.

A `FakeBackend` implements every abstract method of the `Backend` ABC,
including a simulated 4-digit PIN challenge driven through the `prompt_pin`
callback. The tests confirm a concrete backend can be instantiated (so the ABC
abstract-method set is satisfiable) and that the pairing handshake exercises the
callback and returns a usable pairing record.
"""

# Standard Library
import asyncio
import collections.abc

# local repo modules
import airplay2tv.backends.base as base


#============================================
class FakeBackend(base.Backend):
	"""A minimal in-memory backend satisfying the full contract.

	It needs neither pyatv nor a real device, so it can drive app-flow and
	pairing tests offline.
	"""

	#--------------------------------------------
	def __init__(self) -> None:
		# the PIN the simulated device "displays" on screen
		self.displayed_pin = "1234"

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
	async def play(self, device: base.Device, media_url: str, media: object) -> None:
		# a real backend would dispatch playback here; the fake does nothing
		return None

	#--------------------------------------------
	async def stop(self, device: base.Device) -> None:
		return None

	#--------------------------------------------
	async def status(self, device: base.Device) -> base.PlaybackStatus:
		status = base.PlaybackStatus(state="playing", position=1.0, duration=10.0)
		return status

	#--------------------------------------------
	async def needs_pairing(self, device: base.Device) -> bool:
		return True

	#--------------------------------------------
	async def pair(
		self,
		device: base.Device,
		prompt_pin: collections.abc.Callable[[], str],
	) -> base.PairingRecord:
		# simulate the on-screen 4-digit challenge: read the code via the callback
		entered_pin = prompt_pin()
		# a real backend validates the code with the device; the fake compares
		if entered_pin != self.displayed_pin:
			raise ValueError("incorrect pairing code")
		record = base.PairingRecord(
			identifier=device.identifier,
			backend=device.backend,
			credential={"token": "fake-credential"},
		)
		return record

	#--------------------------------------------
	async def is_paired(self, device: base.Device) -> base.PairingState:
		return base.PairingState.NOT_PAIRED


#============================================
def test_fake_backend_satisfies_abc() -> None:
	# instantiation only succeeds when every abstract method is implemented
	backend = FakeBackend()
	assert isinstance(backend, base.Backend)


#============================================
def test_pairing_uses_prompt_pin_callback() -> None:
	backend = FakeBackend()
	device = asyncio.run(backend.discover())[0]

	# the CLI-supplied callback returns the 4-digit code the device shows
	def supply_pin() -> str:
		return backend.displayed_pin

	record = asyncio.run(backend.pair(device, supply_pin))
	assert record.identifier == device.identifier
