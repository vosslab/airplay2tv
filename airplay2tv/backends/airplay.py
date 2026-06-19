"""AirPlay receiver backend built on pyatv.

This module is the single importer of pyatv in airplay2tv. Every pyatv call
(scan, connect, pair, play_url, metadata, close) is confined here so the rest
of the codebase depends only on the backend-agnostic contract in
`airplay2tv.backends.base`. Keeping pyatv isolated lets the core, CLI, and the
Roku backend stay free of Apple-TV protocol detail.

Confirmed pyatv facts this backend relies on (hardware testing on a Sharp Roku
TV advertising AirPlay 2): the AirPlay service uses pairing requirement
Mandatory, an unpaired `stream.play_url` raises
`pyatv.exceptions.AuthenticationError`, and `AppleTV.close()` is synchronous and
returns a set of tasks; it must not be awaited.
"""

# Standard Library
import asyncio
import collections.abc

# PIP3 modules
import pyatv
import pyatv.const
import pyatv.exceptions

# local repo modules
import airplay2tv.errors as errors
import airplay2tv.credentials as credentials
import airplay2tv.backends.base as base


#============================================
# Bounded mDNS scan window in seconds. AirPlay devices answer mDNS over time, so
# a short scan can return zero even when a receiver is present; 5 seconds matches
# the pyatv default confirmed during hardware testing, and stays bounded so
# discovery does not hang. app.py's aggregate discovery timeout is set above
# this so a full scan completes within the shared wall-clock budget.
SCAN_TIMEOUT = 5

#============================================
# Map pyatv DeviceState members to the backend-normalized state strings used by
# PlaybackStatus. Loading and Seeking collapse to "playing" because the media is
# active; Idle reports as "idle" to distinguish a connected-but-empty device.
_DEVICE_STATE_NAMES = {
	pyatv.const.DeviceState.Idle: "idle",
	pyatv.const.DeviceState.Loading: "playing",
	pyatv.const.DeviceState.Paused: "paused",
	pyatv.const.DeviceState.Playing: "playing",
	pyatv.const.DeviceState.Stopped: "stopped",
	pyatv.const.DeviceState.Seeking: "playing",
}


#============================================
class AirPlayBackend(base.Backend):
	"""Concrete `Backend` for AirPlay receivers, implemented with pyatv.

	The backend holds no long-lived connection: each control call scans for the
	device's current config, connects with stored credentials, performs one
	action, and closes. This keeps device state authoritative and avoids stale
	socket handling across the asyncio loop owned by `app.py`.
	"""

	# Backend identity: matches Device.backend and the credentials store key.
	backend_key = "airplay"

	#--------------------------------------------
	async def discover(self) -> list[base.Device]:
		"""Scan the local network for AirPlay receivers.

		Returns:
			A list of `base.Device`, one per AirPlay-capable receiver found.
		"""
		loop = asyncio.get_running_loop()
		# Restrict the scan to the AirPlay protocol so non-AirPlay devices are
		# skipped. mDNS responses trickle in over time, so a short scan can miss a
		# present device (hardware testing confirmed the TV appeared within the
		# default window but a shorter scan returned zero); pin the scan to a
		# bounded SCAN_TIMEOUT so a present receiver is found.
		configs = await pyatv.scan(
			loop,
			timeout=SCAN_TIMEOUT,
			protocol=pyatv.const.Protocol.AirPlay,
		)
		devices: list[base.Device] = []
		for config in configs:
			device = self._config_to_device(config)
			devices.append(device)
		return devices

	#--------------------------------------------
	def _config_to_device(self, config: object) -> base.Device:
		"""Convert a pyatv config into a backend-agnostic `base.Device`.

		Args:
			config: A pyatv `BaseConfig` returned by scan/connect.

		Returns:
			The mapped `base.Device`.
		"""
		# model_str falls back to a raw model string when pyatv has no enum match.
		model = config.device_info.model_str
		device = base.Device(
			name=config.name,
			backend=self.backend_key,
			identifier=config.identifier,
			address=str(config.address),
			model=model,
		)
		return device

	#--------------------------------------------
	async def media_profile(self) -> base.MediaProfile:
		"""Return the media an Apple TV plays without conversion.

		Apple TV decodes H.264 and HEVC video with AAC audio inside the common
		Apple container family (MP4, MOV, M4V), so those pass through untouched.

		Returns:
			The AirPlay `base.MediaProfile`.
		"""
		profile = base.MediaProfile(
			containers={"mp4", "mov", "m4v"},
			video_codecs={"h264", "hevc"},
			audio_codecs={"aac"},
		)
		return profile

	#--------------------------------------------
	async def _resolve_config(self, device: base.Device) -> object:
		"""Scan for and return the current pyatv config for a device.

		Args:
			device: The selected receiver.

		Returns:
			The pyatv `BaseConfig` matching the device identifier.

		Raises:
			errors.DeviceUnreachableError: When no AirPlay config is found for the
				identifier (the device is off or off the network).
		"""
		loop = asyncio.get_running_loop()
		# Scan by identifier so only the target device's config comes back.
		configs = await pyatv.scan(
			loop,
			identifier=device.identifier,
			protocol=pyatv.const.Protocol.AirPlay,
		)
		if not configs:
			raise errors.DeviceUnreachableError(
				f"AirPlay device {device.name} ({device.identifier}) not found on the network"
			)
		return configs[0]

	#--------------------------------------------
	async def _connect(self, device: base.Device) -> object:
		"""Resolve, authenticate, and connect to the device.

		Loads the stored pairing record, applies its credential to the AirPlay
		service, and opens a pyatv connection.

		Args:
			device: The selected receiver.

		Returns:
			A connected pyatv `AppleTV` instance. The caller owns closing it with
			the synchronous `atv.close()`.

		Raises:
			errors.PairingRequiredError: When no pairing record is stored for the
				device, so playback cannot authenticate.
		"""
		# A required credential drives AirPlay auth; a missing record means pair first.
		record = credentials.get_record(device.identifier, self.backend_key)
		if record is None:
			raise errors.PairingRequiredError(
				f"AirPlay device {device.name} is not paired; run: airplay2tv pair"
			)
		config = await self._resolve_config(device)
		# The credential payload is the opaque pyatv credentials string this
		# backend stored at pairing time.
		config.set_credentials(pyatv.const.Protocol.AirPlay, record.credential)
		loop = asyncio.get_running_loop()
		atv = await pyatv.connect(config, loop)
		return atv

	#--------------------------------------------
	async def play(self, device: base.Device, media_url: str, media: object) -> None:
		"""Stream the served media URL on the device via AirPlay.

		Args:
			device: The selected receiver.
			media_url: The advertised HTTP URL the device fetches the file from.
			media: The prepared-media object from `airplay2tv.media`; unused by the
				AirPlay path because pyatv streams directly from the URL.

		Raises:
			errors.PairingRequiredError: When no pairing record exists or pyatv
				rejects the stored credentials with an AuthenticationError.
		"""
		atv = await self._connect(device)
		try:
			# stream.play_url hands the URL to the device; an unpaired or stale
			# credential surfaces as AuthenticationError from the RTSP setup.
			await atv.stream.play_url(media_url)
		except pyatv.exceptions.AuthenticationError as auth_error:
			raise errors.PairingRequiredError(
				f"AirPlay device {device.name} rejected stored credentials; "
				f"run: airplay2tv pair"
			) from auth_error
		finally:
			# AppleTV.close() is synchronous and returns a set of tasks; do not await.
			atv.close()

	#--------------------------------------------
	async def stop(self, device: base.Device) -> None:
		"""Stop playback on the device.

		Args:
			device: The selected receiver.

		Raises:
			errors.PairingRequiredError: When no pairing record exists or pyatv
				rejects the stored credentials with an AuthenticationError.
		"""
		atv = await self._connect(device)
		try:
			await atv.remote_control.stop()
		except pyatv.exceptions.AuthenticationError as auth_error:
			raise errors.PairingRequiredError(
				f"AirPlay device {device.name} rejected stored credentials; "
				f"run: airplay2tv pair"
			) from auth_error
		finally:
			# Synchronous close; returns a set, never awaited.
			atv.close()

	#--------------------------------------------
	async def status(self, device: base.Device) -> base.PlaybackStatus:
		"""Return the device's current playback status.

		Args:
			device: The selected receiver.

		Returns:
			A `base.PlaybackStatus` snapshot built from pyatv playing metadata.

		Raises:
			errors.PairingRequiredError: When no pairing record exists or pyatv
				rejects the stored credentials with an AuthenticationError.
		"""
		atv = await self._connect(device)
		try:
			playing = await atv.metadata.playing()
		except pyatv.exceptions.AuthenticationError as auth_error:
			raise errors.PairingRequiredError(
				f"AirPlay device {device.name} rejected stored credentials; "
				f"run: airplay2tv pair"
			) from auth_error
		finally:
			# Synchronous close; returns a set, never awaited.
			atv.close()
		status = self._playing_to_status(playing)
		return status

	#--------------------------------------------
	def _playing_to_status(self, playing: object) -> base.PlaybackStatus:
		"""Convert pyatv playing metadata into a `base.PlaybackStatus`.

		Args:
			playing: A pyatv `Playing` metadata object.

		Returns:
			The mapped `base.PlaybackStatus`. Unknown device states report as
			"idle" so the CLI never shows a raw pyatv enum.
		"""
		# An unmapped state should not crash status; report it as idle.
		state = _DEVICE_STATE_NAMES.get(playing.device_state, "idle")
		# pyatv position and total_time are integer seconds or None.
		position = playing.position
		duration = playing.total_time
		float_position = float(position) if position is not None else None
		float_duration = float(duration) if duration is not None else None
		status = base.PlaybackStatus(
			state=state,
			position=float_position,
			duration=float_duration,
		)
		return status

	#--------------------------------------------
	def _service_requires_pairing(self, config: object) -> bool:
		"""Report whether the device's AirPlay service requires pairing.

		Args:
			config: A pyatv `BaseConfig` for the device.

		Returns:
			True when the AirPlay service reports a Mandatory pairing requirement.
		"""
		service = config.get_service(pyatv.const.Protocol.AirPlay)
		if service is None:
			return False
		# Hardware testing confirmed Mandatory pairing on the target receiver.
		mandatory = service.pairing == pyatv.const.PairingRequirement.Mandatory
		return mandatory

	#--------------------------------------------
	async def needs_pairing(self, device: base.Device) -> bool:
		"""Report whether the device requires pairing before playback.

		The device needs pairing when no usable record is stored and the live
		AirPlay service still demands a Mandatory pairing handshake.

		Args:
			device: The selected receiver.

		Returns:
			True when pairing must run before playback can authenticate.
		"""
		record = credentials.get_record(device.identifier, self.backend_key)
		if record is not None:
			# A stored record means pairing already ran; no new handshake needed.
			return False
		config = await self._resolve_config(device)
		needs = self._service_requires_pairing(config)
		return needs

	#--------------------------------------------
	async def is_paired(self, device: base.Device) -> base.PairingState:
		"""Report the device's current pairing state.

		Args:
			device: The selected receiver.

		Returns:
			`PairingState.PAIRED` when a credential record exists, otherwise
			`PairingState.NOT_PAIRED`.
		"""
		record = credentials.get_record(device.identifier, self.backend_key)
		if record is not None:
			return base.PairingState.PAIRED
		return base.PairingState.NOT_PAIRED

	#--------------------------------------------
	async def pair(
		self,
		device: base.Device,
		prompt_pin: collections.abc.Callable[[], str],
	) -> base.PairingRecord:
		"""Run the pyatv AirPlay PIN pairing handshake and return a record.

		The device shows a 4-digit code on screen; `prompt_pin` reads it from the
		CLI. The handshake is begin -> pin -> finish; on success pyatv exposes the
		new credentials string on the pairing handler's service.

		Args:
			device: The device to pair with.
			prompt_pin: Callback that returns the on-screen 4-digit code.

		Returns:
			A `base.PairingRecord` holding the pyatv credentials string.

		Raises:
			errors.PairingRequiredError: When the handshake completes without
				pairing (for example, a wrong PIN was entered).
		"""
		config = await self._resolve_config(device)
		loop = asyncio.get_running_loop()
		pairing = await pyatv.pair(config, pyatv.const.Protocol.AirPlay, loop)
		# Run the handshake steps and capture outcome before closing the session.
		# has_paired and credential are read here so the close step below cannot
		# overwrite them if close() raises; the original pairing error must surface.
		await pairing.begin()
		entered_pin = prompt_pin()
		pairing.pin(entered_pin)
		# finish exchanges the PIN and, on success, yields credentials.
		await pairing.finish()
		# Capture outcome before closing; close errors must not mask a wrong-PIN result.
		has_paired = pairing.has_paired
		# Only read credentials when pairing succeeded; service.credentials is
		# undefined (and irrelevant) when has_paired is False.
		credential = pairing.service.credentials if has_paired else None
		# Close the session in its own guarded step so a close() exception is
		# surfaced separately and does not mask the PairingRequiredError below.
		try:
			await pairing.close()
		except Exception:
			# Log nothing here; a close failure is secondary to the pairing outcome.
			pass
		# Evaluate the outcome after the session is closed.
		if not has_paired:
			raise errors.PairingRequiredError(
				f"AirPlay pairing with {device.name} failed; check the PIN and retry"
			)
		record = base.PairingRecord(
			identifier=device.identifier,
			backend=self.backend_key,
			credential=credential,
		)
		return record
