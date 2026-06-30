"""Roku receiver backend driving the External Control Protocol (ECP) via rokuecp.

This module is the sole importer of the third-party `rokuecp` client in
airplay2tv. It implements the frozen `Backend` contract from
`airplay2tv.backends.base` for Roku devices: discovery reuses the clean-room
SSDP probe in `airplay2tv.discovery.roku_ssdp`, and all control (launch, remote
keys, status) goes through `rokuecp.Roku`, an async context manager.

Playback uses the Roku Media Player channel (app id 2213) via
`roku.launch(app_id, params)`, which POSTs `launch/{id}?{urlencode(params)}`.

Pairing: Roku ECP uses no PIN. The real gate is the TV setting
"Control by mobile apps"; when it is disabled the device returns HTTP 403 on ECP
control calls (and also suppresses the roku:ecp SSDP response). The backend
surfaces that 403 as `errors.DeviceUnreachableError` with a message naming the
exact setting to enable, rather than pretending a pairing handshake is needed.

Live-launch status: the exact launch param casing was not confirmed on hardware
because the 403 blocked the proof before any launch ran. See the
ASSUMPTION comment on `play`.
"""

# Standard Library
import logging
import collections.abc

# PIP3 modules
import rokuecp

# local repo modules
import airplay2tv.errors
import airplay2tv.backends.base
import airplay2tv.discovery.roku_ssdp


# Roku Media Player channel app id; the built-in player that streams a URL.
ROKU_MEDIA_PLAYER_APP_ID = "2213"

# The Settings path the user must enable for ECP control to be permitted. A 403
# from any ECP call means this setting is off.
CONTROL_SETTING_PATH = (
	"Settings > System > Advanced system settings > Control by mobile apps"
)


#============================================
def _is_forbidden(exc: rokuecp.RokuError) -> bool:
	"""Return True when a RokuError represents an HTTP 403 from the device.

	`rokuecp` raises RokuError for any 4xx/5xx response. The message is
	"HTTP <status>" and, for HTTP errors, a second positional arg is a dict that
	carries a "status-code" key. Both are checked so a 403 is detected whether or
	not the structured detail dict is present.
	"""
	# Prefer the structured status-code from the detail dict when present.
	for arg in exc.args:
		if isinstance(arg, dict) and arg.get("status-code") == 403:
			return True
	# Fall back to the human-readable "HTTP 403" message form.
	message = str(exc.args[0]) if exc.args else ""
	is_403 = message.strip() == "HTTP 403"
	return is_403


#============================================
def _forbidden_error() -> airplay2tv.errors.DeviceUnreachableError:
	"""Build the DeviceUnreachableError describing the disabled ECP setting."""
	# Tell the user exactly which TV setting unblocks ECP control.
	message = (
		"Roku refused the request (HTTP 403). Enable "
		+ CONTROL_SETTING_PATH
		+ " on the Roku, then try again."
	)
	error = airplay2tv.errors.DeviceUnreachableError(message)
	return error


#============================================
class RokuEcpBackend(airplay2tv.backends.base.Backend):
	"""Backend that controls Roku devices over the External Control Protocol.

	Discovery uses SSDP; control uses `rokuecp.Roku`. Each control call opens a
	short-lived `rokuecp.Roku` async context so no session is held open between
	operations. The backend key is "roku-ecp".
	"""

	# Backend identity: stamped onto every Device this backend emits and used as
	# the credentials store key. A class attribute (not set in __init__) so it
	# matches the single backend_key convention shared with the AirPlay backend.
	backend_key = "roku-ecp"

	#--------------------------------------------
	def __init__(self) -> None:
		self.logger = logging.getLogger(__name__)

	#--------------------------------------------
	async def discover(self) -> list[airplay2tv.backends.base.Device]:
		"""Find Roku ECP devices on the local network.

		Sends one SSDP M-SEARCH probe via roku_ssdp.discover(), then reads each
		responder's friendly name and model through a short-lived rokuecp.Roku
		update(). A responder whose update fails (for example a 403 because the
		control setting is off) still yields a Device using the SSDP USN and IP;
		the name and model are filled from device-info when available.
		"""
		# roku_ssdp.discover() returns (responders, stats); only responders matter.
		responders, _stats = await airplay2tv.discovery.roku_ssdp.discover()

		devices: list[airplay2tv.backends.base.Device] = []
		for responder in responders:
			device = await self._device_from_responder(responder)
			devices.append(device)
		return devices

	#--------------------------------------------
	async def resolve_address(
		self,
		address: str,
	) -> airplay2tv.backends.base.Device | None:
		"""Build a Device from a known IP by querying device-info directly.

		SSDP discovery (roku:ecp) is silent when "Control by mobile apps" is
		limited, but the device-info endpoint stays reachable at the known IP.
		This lets a user point at a Roku by IP even with SSDP silent: it GETs
		http://<address>:8060/query/device-info via the rokuecp client and, on a
		successful read, builds a Device. A device whose info read fails (no
		device at the address, or a non-200 response) yields None so the caller
		can fall through to discovery or another backend.

		The identifier prefers the device serial number (stable across reboots);
		when the serial is absent it falls back to the address so the Device
		still carries a non-empty identifier.

		Args:
			address: The host or IP to probe at the default ECP port.

		Returns:
			A Device addressed at the IP, or None when the address is unreachable
			or returns no usable device-info.
		"""
		roku_info = await self._safe_device_info(address)
		if roku_info is None:
			# No device-info read: unreachable, not a Roku, or control blocked.
			return None
		# Serial number is genuinely optional (the Roku may not report it); the
		# address is an intentional fallback so identifier is never empty.
		identifier = roku_info.serial_number or address
		# Friendly name is genuinely optional; the address is an intentional
		# fallback so name is never empty.
		name = roku_info.name or address
		# model_name is genuinely optional; model_number is an intentional
		# fallback so model still carries some identifying string when present.
		model = roku_info.model_name or roku_info.model_number
		device = airplay2tv.backends.base.Device(
			name=name,
			backend=self.backend_key,
			identifier=identifier,
			address=address,
			model=model,
		)
		return device

	#--------------------------------------------
	async def _device_from_responder(
		self,
		responder: airplay2tv.discovery.roku_ssdp.RokuResponder,
	) -> airplay2tv.backends.base.Device:
		"""Build one Device from an SSDP responder, reading name/model if possible.

		The USN is the stable identifier (it is the dedupe key in discovery and is
		always present on an accepted responder). The friendly name and model come
		from device-info via update(); when that call fails, the IP stands in for
		the name and the model is left None.
		"""
		name = responder.ip
		model: str | None = None

		# Read device-info opportunistically; control may be blocked by the TV.
		roku_info = await self._safe_device_info(responder.ip)
		if roku_info is not None:
			if roku_info.name:
				name = roku_info.name
			# model_name is genuinely optional; model_number is an intentional
			# fallback so model still carries some identifying string when present.
			model = roku_info.model_name or roku_info.model_number

		device = airplay2tv.backends.base.Device(
			name=name,
			backend=self.backend_key,
			identifier=responder.usn,
			address=responder.ip,
			model=model,
		)
		return device

	#--------------------------------------------
	async def _safe_device_info(self, host: str) -> rokuecp.Info | None:
		"""Return the rokuecp Info for a host, or None when control is blocked.

		Discovery should not crash on one unreachable or locked-down device, so a
		403 (control setting off) or any rokuecp transport error is logged at debug
		and reported as None instead of propagating.
		"""
		async with rokuecp.Roku(host=host) as roku:
			# A two-line try/except keeps one bad device from failing the scan.
			try:
				device = await roku.update()
			except rokuecp.RokuError as exc:
				self.logger.debug("device-info failed for %s: %s", host, exc)
				return None
		return device.info

	#--------------------------------------------
	async def media_profile(self) -> airplay2tv.backends.base.MediaProfile:
		"""Return the media the Roku Media Player plays without conversion.

		The user's Roku TV transcodes H.265 down, so only H.264 is treated as
		passthrough-capable here; H.265 is forced through the media pipeline. The
		Media Player accepts ISO BMFF containers (mp4, mov, m4v) with AAC audio.
		"""
		profile = airplay2tv.backends.base.MediaProfile(
			containers=frozenset({"mp4", "mov", "m4v"}),
			video_codecs=frozenset({"h264"}),
			audio_codecs=frozenset({"aac"}),
		)
		return profile

	#--------------------------------------------
	async def play(
		self,
		device: airplay2tv.backends.base.Device,
		media_url: str,
		media: object,
	) -> None:
		"""Launch the Roku Media Player on the served media URL.

		POSTs launch/2213 with the media URL as contentId and a hardcoded movie
		mediaType. The `media` arg (the prepared-media object) is unused here
		because the Roku player only needs the served URL.

		ASSUMPTION (confirm on a live launch once "Control by mobile apps" is
		enabled): the param keys use the casing contentId / mediaType. Roku docs
		also show contentID / MediaType in places; hardware testing could not
		verify which the device accepts because the 403 blocked every launch.
		The default chosen here is contentId / mediaType; if a live launch
		returns 200 but does not actually start playback, retry with
		contentID / MediaType.
		"""
		params = self._build_launch_params(media_url)
		async with rokuecp.Roku(host=device.address) as roku:
			# A two-line try/except converts the control-blocked 403 into a typed,
			# user-facing error and re-raises everything else unchanged.
			try:
				await roku.launch(ROKU_MEDIA_PLAYER_APP_ID, params)
			except rokuecp.RokuError as exc:
				raise self._translate(exc) from exc

	#--------------------------------------------
	def _build_launch_params(self, media_url: str) -> dict[str, str]:
		"""Build the Roku Media Player launch params for a served media URL.

		mediaType is hardcoded to "movie". The casing of these keys is the
		documented ASSUMPTION described on `play`.

		Hardware note: if a live launch returns HTTP 200 but does not start
		playback, retry with the alternate casing contentID/MediaType instead
		of the current contentId/mediaType. Both casings appear in Roku docs and
		the correct one was not confirmed on hardware (the 403 blocked every
		launch attempt before the ECP control setting was enabled).
		"""
		params = {
			"contentId": media_url,
			"mediaType": "movie",
		}
		return params

	#--------------------------------------------
	async def stop(self, device: airplay2tv.backends.base.Device) -> None:
		"""Stop playback by sending the Home remote key.

		The Media Player exits to the Roku home screen on Home, which is the
		simplest reliable stop for a launched player session.
		"""
		async with rokuecp.Roku(host=device.address) as roku:
			# Convert a control-blocked 403 into the typed error; re-raise others.
			try:
				await roku.remote("home")
			except rokuecp.RokuError as exc:
				raise self._translate(exc) from exc

	#--------------------------------------------
	async def status(
		self,
		device: airplay2tv.backends.base.Device,
	) -> airplay2tv.backends.base.PlaybackStatus:
		"""Return the device's current playback status from the media-player query.

		rokuecp.update() populates device.media (a MediaState) only when the
		player reports "play" or "pause"; otherwise media is None and the device is
		treated as idle.
		"""
		async with rokuecp.Roku(host=device.address) as roku:
			# Convert a control-blocked 403 into the typed error; re-raise others.
			try:
				roku_device = await roku.update()
			except rokuecp.RokuError as exc:
				raise self._translate(exc) from exc
		status = self._status_from_media(roku_device.media)
		return status

	#--------------------------------------------
	def _status_from_media(
		self,
		media: rokuecp.MediaState | None,
	) -> airplay2tv.backends.base.PlaybackStatus:
		"""Map a rokuecp MediaState (or None) to a PlaybackStatus.

		None media means no active player session (idle). A present MediaState
		reports paused vs playing plus position and duration in seconds.
		"""
		if media is None:
			# No active media session reported by the device.
			status = airplay2tv.backends.base.PlaybackStatus(state="idle")
			return status
		# media.paused distinguishes paused from playing; both carry position/dur.
		state = "paused" if media.paused else "playing"
		# Guard each float() call: live streams and some device firmware omit
		# position or duration, returning None; calling float(None) raises TypeError.
		float_position = float(media.position) if media.position is not None else None
		float_duration = float(media.duration) if media.duration is not None else None
		status = airplay2tv.backends.base.PlaybackStatus(
			state=state,
			position=float_position,
			duration=float_duration,
		)
		return status

	#--------------------------------------------
	async def needs_pairing(
		self,
		device: airplay2tv.backends.base.Device,
	) -> bool:
		"""Report whether the device requires pairing before playback.

		Roku ECP uses no PIN handshake, so pairing is never required. The real
		access gate is the "Control by mobile apps" TV setting, which is surfaced
		as a DeviceUnreachableError on a 403 at control time, not as pairing.
		"""
		return False

	#--------------------------------------------
	async def pair(
		self,
		device: airplay2tv.backends.base.Device,
		prompt_pin: collections.abc.Callable[[], str],
	) -> airplay2tv.backends.base.PairingRecord:
		"""Return a trivial pairing record; Roku ECP needs no PIN handshake.

		The prompt_pin callback is intentionally unused because the device never
		shows a code for ECP. The record notes that ECP control is allowed so the
		credentials store has a consistent entry shape across backends.
		"""
		record = airplay2tv.backends.base.PairingRecord(
			identifier=device.identifier,
			backend=self.backend_key,
			credential={"ecp": "allowed"},
		)
		return record

	#--------------------------------------------
	async def is_paired(
		self,
		device: airplay2tv.backends.base.Device,
	) -> airplay2tv.backends.base.PairingState:
		"""Report the device as paired; ECP requires no stored PIN credential."""
		return airplay2tv.backends.base.PairingState.PAIRED

	#--------------------------------------------
	def _translate(
		self,
		exc: rokuecp.RokuError,
	) -> airplay2tv.errors.Airplay2tvError:
		"""Translate a rokuecp error into a typed airplay2tv error.

		A 403 becomes a DeviceUnreachableError naming the control setting; any
		other RokuError is wrapped in DeviceUnreachableError carrying the original
		message so the CLI can render one readable line.
		"""
		if _is_forbidden(exc):
			return _forbidden_error()
		# Non-403 control failures (timeout, connection) are still unreachable.
		error = airplay2tv.errors.DeviceUnreachableError(str(exc))
		return error


# The registry (airplay2tv.backends.registry.BACKEND_SPECS) constructs this
# backend by the name "RokuBackend". RokuEcpBackend is the canonical class name
# used in the plan; this alias lets the registry resolve it without editing the
# registry module.
RokuBackend = RokuEcpBackend
