"""Backend-agnostic contract shared by every receiver backend.

This module is the single interface between the airplay2tv core (CLI, app
orchestration, media pipeline) and the concrete receiver backends (AirPlay via
pyatv, Roku via rokuecp). It defines the data carriers exchanged across that
boundary and the abstract `Backend` base class each backend implements.

The module deliberately imports nothing from other airplay2tv modules and
nothing from pyatv or rokuecp, so the contract stays stable and free of backend
detail. The `media` argument on `play` is typed loosely as `object` because the
concrete prepared-media type is owned by `airplay2tv.media`.
"""

# Standard Library
import abc
import enum
import dataclasses
import collections.abc


#============================================
@dataclasses.dataclass
class Device:
	"""A receiver discovered on the local network.

	Attributes:
		name: Human-readable device name shown in the picker.
		backend: Backend key that owns this device (for example "airplay").
		identifier: Stable per-backend unique id used to match saved devices.
		address: Routable host or IP the backend reaches the device at.
		model: Device model string; may be an empty string or None when the
			backend does not report a model.
	"""
	name: str
	backend: str
	identifier: str
	address: str
	model: str | None = None


#============================================
@dataclasses.dataclass
class MediaProfile:
	"""The set of media a backend can play without further conversion.

	Each field is a set of lowercase tokens. The media pipeline compares an
	inspected file against this profile to choose passthrough, remux, or
	transcode.

	Attributes:
		containers: Allowed container formats (for example "mp4", "mov").
		video_codecs: Allowed video codecs (for example "h264", "hevc").
		audio_codecs: Allowed audio codecs (for example "aac").
	"""
	containers: frozenset[str] | set[str]
	video_codecs: frozenset[str] | set[str]
	audio_codecs: frozenset[str] | set[str]


#============================================
@dataclasses.dataclass
class PlaybackStatus:
	"""A snapshot of a device's playback state.

	Attributes:
		state: Backend-normalized state string (for example "playing",
			"paused", "stopped", "idle").
		position: Current playback position in seconds, or None when unknown.
		duration: Total media duration in seconds, or None when unknown.
	"""
	state: str
	position: float | None = None
	duration: float | None = None


#============================================
@dataclasses.dataclass
class PairingRecord:
	"""The persisted pairing artifact for one device on one backend.

	This is the object `credentials.py` stores and reloads. The credential
	payload is opaque to the core: a backend supplies whatever it needs to
	re-authenticate (for example a pyatv credentials string, or a dict of Roku
	control details).

	Attributes:
		identifier: Device identifier this record pairs with (matches
			`Device.identifier`).
		backend: Backend key that produced this record.
		credential: Opaque credential payload, a string or a dict, whose shape
			is owned by the backend that created it.
	"""
	identifier: str
	backend: str
	credential: str | dict


#============================================
class PairingState(enum.Enum):
	"""Whether a device has a usable pairing record.

	Members:
		PAIRED: A valid pairing record exists and playback can proceed.
		NOT_PAIRED: No pairing record exists; the device needs pairing.
		NEEDS_REFRESH: A record exists but is stale and must be re-paired.
	"""
	PAIRED = "paired"
	NOT_PAIRED = "not_paired"
	NEEDS_REFRESH = "needs_refresh"


#============================================
class Backend(abc.ABC):
	"""Abstract contract every receiver backend implements.

	All methods are async because discovery, control, and pairing are I/O bound
	and run on the asyncio event loop owned by `app.py`. Concrete backends live
	in sibling modules (`airplay.py`, `roku_ecp.py`) and own their third-party
	clients; this base class stays import-clean.

	Class attributes:
		backend_key: The single backend identity string. Every concrete backend
			overrides this with its own key (for example "airplay" or
			"roku-ecp") and stamps the same value onto every `Device.backend` it
			emits, so `app.backend_for_device` matches a device to its owning
			backend by exact key with no guesswork. The base value is empty so a
			backend that forgets to set it never accidentally claims a device.
	"""

	# Concrete backends override this with their own identity string.
	backend_key: str = ""

	#--------------------------------------------
	@abc.abstractmethod
	async def discover(self) -> list[Device]:
		"""Find devices this backend can reach on the local network."""
		raise NotImplementedError

	#--------------------------------------------
	async def resolve_address(self, address: str) -> Device | None:
		"""Build a Device from a known host or IP without running discovery.

		A backend that can probe a device directly (for example Roku ECP, which
		reaches a TV at a known IP even when SSDP is silent) overrides this to
		query that address and return a Device on success, or None when the
		address is unreachable or is not a device this backend owns. The default
		returns None so a backend with no direct-probe path is always safe to
		call from the IP-selection flow.

		Args:
			address: The host or IP to probe directly.

		Returns:
			A Device for the address, or None when this backend cannot resolve it.
		"""
		return None

	#--------------------------------------------
	@abc.abstractmethod
	async def media_profile(self) -> MediaProfile:
		"""Return the media this backend plays without conversion."""
		raise NotImplementedError

	#--------------------------------------------
	@abc.abstractmethod
	async def play(self, device: Device, media_url: str, media: object) -> None:
		"""Start playback of the served media URL on the device.

		Args:
			device: The selected receiver.
			media_url: The advertised HTTP URL the device fetches the file from.
			media: The prepared-media object from `airplay2tv.media`; typed
				loosely as `object` because its concrete type is owned there.
		"""
		raise NotImplementedError

	#--------------------------------------------
	@abc.abstractmethod
	async def stop(self, device: Device) -> None:
		"""Stop playback on the device."""
		raise NotImplementedError

	#--------------------------------------------
	@abc.abstractmethod
	async def status(self, device: Device) -> PlaybackStatus:
		"""Return the device's current playback status."""
		raise NotImplementedError

	#--------------------------------------------
	@abc.abstractmethod
	async def needs_pairing(self, device: Device) -> bool:
		"""Report whether the device requires pairing before playback."""
		raise NotImplementedError

	#--------------------------------------------
	@abc.abstractmethod
	async def pair(
		self,
		device: Device,
		prompt_pin: collections.abc.Callable[[], str],
	) -> PairingRecord:
		"""Run this backend's pairing flow and return a pairing record.

		Args:
			device: The device to pair with.
			prompt_pin: Callback the CLI supplies to read the on-screen 4-digit
				code from terminal stdin; called when the device shows a PIN.
		"""
		raise NotImplementedError

	#--------------------------------------------
	@abc.abstractmethod
	async def is_paired(self, device: Device) -> PairingState:
		"""Report the device's current pairing state."""
		raise NotImplementedError
