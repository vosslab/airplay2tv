"""Async orchestration layer that routes the CLI to the requested action.

`run(args)` is the synchronous dispatcher `cli.main()` calls. It inspects
`args.command` and dispatches:

- None / "stream": discover, pick a device, pair if needed, prepare the media,
  serve it over HTTP, start playback, and wait until the user presses Ctrl+C.
- "devices": discover and print the numbered device list.
- "doctor": delegate to `airplay2tv.doctor.run_checks`.
- "pair": delegate to `airplay2tv.pairing.run`.

`run` is synchronous so each handler owns its own event-loop lifetime. The
async actions (stream, devices) are driven through `asyncio.run` here; the
synchronous subcommand handlers (doctor, pair) run their own `asyncio.run`
internally, so wrapping the whole dispatch in one loop would nest event loops
and fail. Keeping `run` synchronous keeps exactly one running loop at a time.

The stream action owns two real resources -- a running HTTP server and a temp
directory holding prepared media -- and releases both on every exit path
(success, failure after prepare, failure after serve, or Ctrl+C) through a
single `finally` block, so a failure mid-flow never leaks a server thread or a
transcode file.
"""

# Standard Library
import sys
import asyncio
import shutil
import logging
import tempfile
import threading
import importlib
import ipaddress

# local repo modules
import airplay2tv.media as media
import airplay2tv.config as config
import airplay2tv.netutil as netutil
import airplay2tv.errors as errors
import airplay2tv.httpserver as httpserver
import airplay2tv.devicepick as devicepick
import airplay2tv.backends.base as base
import airplay2tv.backends.registry as registry
import airplay2tv.discovery.aggregate as aggregate


# Wall-clock seconds allowed for all backend discoveries to complete together.
# Set above the AirPlay backend's 5 s mDNS scan window so a full scan finishes
# inside the shared budget; a too-tight budget cancels the scan mid-flight and
# reports zero devices even when a receiver is present.
DISCOVERY_TIMEOUT = 7.0

logger = logging.getLogger(__name__)


#============================================
def run(args: object) -> int:
	"""Route the parsed CLI arguments to the matching action.

	The `command` attribute (None for the default stream action) selects the
	handler. Every handler returns a process exit code: 0 on success, non-zero
	on a handled failure. This dispatcher is synchronous: the async actions are
	driven through `asyncio.run` here, and the synchronous subcommand handlers
	run their own loop internally, so only one event loop is ever active.

	Args:
		args: The argparse.Namespace from `cli.parse_args()`. Typed loosely as
			`object` because the namespace shape is owned by `cli.py`.

	Returns:
		The integer exit code for the process.
	"""
	# getattr keeps this tolerant of a namespace built without a subparser.
	command = getattr(args, "command", None)
	if command in (None, "stream"):
		exit_code = asyncio.run(run_stream(args))
		return exit_code
	if command == "devices":
		exit_code = asyncio.run(run_devices(args))
		return exit_code
	if command == "doctor":
		exit_code = run_doctor(args)
		return exit_code
	if command == "pair":
		exit_code = run_pair(args)
		return exit_code
	# A command argparse accepted but this layer does not handle is a defect.
	print(f"unknown command: {command}", file=sys.stderr)
	return 2


#============================================
async def run_devices(args: object) -> int:
	"""Discover receivers and print the numbered device list.

	Args:
		args: The parsed CLI namespace (unused fields ignored).

	Returns:
		0 when devices are found, non-zero when none are reachable.
	"""
	devices = await aggregate.discover_all(registry.active_backends(), DISCOVERY_TIMEOUT)
	if not devices:
		print(no_devices_message(), file=sys.stderr)
		return 1
	print(devicepick.render(devices))
	return 0


#============================================
def run_doctor(args: object) -> int:
	"""Delegate environment checks to the doctor module.

	The doctor module is imported lazily so the stream and devices actions do
	not pay for its import and so `--help` works before doctor.py exists.

	Contract: `doctor.run_checks(device: str | None = None,
	input_file: str | None = None) -> int`.

	Args:
		args: The parsed CLI namespace; `device` and `input_file` are optional.

	Returns:
		The exit code from `doctor.run_checks`, or 2 when doctor is unavailable.
	"""
	doctor = lazy_import("airplay2tv.doctor")
	if doctor is None:
		print("doctor is not yet available", file=sys.stderr)
		return 2
	device = getattr(args, "device", None)
	input_file = getattr(args, "input_file", None)
	exit_code = doctor.run_checks(device=device, input_file=input_file)
	return exit_code


#============================================
def run_pair(args: object) -> int:
	"""Delegate the interactive pairing flow to the pairing module.

	The pairing module is imported lazily; when the module is absent a clear
	"not yet available" message is printed rather than a traceback.

	Contract: `pairing.run(args) -> int`.

	Args:
		args: The parsed CLI namespace passed straight through to pairing.

	Returns:
		The exit code from `pairing.run`, or 2 when pairing is unavailable.
	"""
	pairing = lazy_import("airplay2tv.pairing")
	if pairing is None:
		print("pair is not yet available", file=sys.stderr)
		return 2
	exit_code = pairing.run(args)
	return exit_code


#============================================
def lazy_import(module_path: str) -> object | None:
	"""Import a module by dotted path, returning None when it does not exist.

	A subcommand handler built in a later workstream may not exist yet. A
	genuinely missing module returns None so the caller can print a clear
	message; any other import-time failure propagates so real bugs surface.

	Args:
		module_path: The dotted module path to import.

	Returns:
		The imported module, or None when the module does not exist yet.
	"""
	# Only a truly absent module is swallowed; ImportError from a broken module
	# would carry a name, but ModuleNotFoundError.name names the missing target.
	try:
		module = importlib.import_module(module_path)
	except ModuleNotFoundError as exc:
		if exc.name == module_path:
			return None
		raise
	return module


#============================================
async def run_stream(args: object) -> int:
	"""Discover, pick, pair, prepare, serve, and play, then wait for Ctrl+C.

	This is the default action. It owns an HTTP server and a temp directory of
	prepared media; both are released in the `finally` block on every exit path.

	Args:
		args: The parsed CLI namespace. Reads `device`, `default_device`,
			`input_file`, `bind_host`, `media_mode`, and `save_device`.

	Returns:
		0 on a clean run, non-zero when no devices are reachable.
	"""
	backends = registry.active_backends()
	devices = await aggregate.discover_all(backends, DISCOVERY_TIMEOUT)
	# Before relying on discovery, try the direct-IP / saved-address path: a
	# known IP must work even when SSDP is silent. resolve_known_address returns
	# a Device when a backend resolves a known address, or None to fall through.
	device = await resolve_known_address(backends, args, devices)
	if device is None:
		if not devices:
			print(no_devices_message(), file=sys.stderr)
			return 1
		device = select_device(args, devices)
	# Find the backend instance that owns the selected device by its key.
	backend = backend_for_device(backends, device)
	await ensure_paired(backend, device)
	# A temp dir holds any prepared (remuxed or transcoded) output. It is
	# created before the try so the finally can always remove it.
	temp_dir = tempfile.mkdtemp(prefix="airplay2tv-")
	server = None
	server_thread = None
	# Hoist cancel_event here so the KeyboardInterrupt handler can signal
	# an in-flight ffmpeg transcode to terminate and clean its partial output.
	cancel_event = threading.Event()
	try:
		profile = await backend.media_profile()
		prepared = prepare_media(args, profile, temp_dir, cancel_event)
		# Build the advertised URL from the routable local interface IP so the
		# device can reach the server even when it binds to all interfaces.
		advertised_host = netutil.local_ip_for(device.address)
		bind_host = getattr(args, "bind_host", None) or "0.0.0.0"  # nosec B104 - LAN server binds all interfaces by design; advertised URL uses specific LAN IP
		url, server, server_thread = httpserver.serve(
			prepared.path,
			bind_host=bind_host,
			advertised_host=advertised_host,
		)
		await backend.play(device, url, prepared)
		# Persist the chosen device only after playback actually started, so a
		# device that never played is never written to the config.
		persist_device(args, device)
		print(status_banner(device, url))
		# Block until Ctrl+C.
		wait_for_interrupt()
		return 0
	except KeyboardInterrupt:
		# Set cancel_event first so _run_ffmpeg (if still active) terminates
		# and removes its partial output before the finally shutil.rmtree runs.
		cancel_event.set()
		print("\nStopping playback...")
		await backend.stop(device)
		return 0
	finally:
		# Release both owned resources on every exit path: success, an
		# exception after prepare, an exception after serve, or Ctrl+C.
		if server is not None and server_thread is not None:
			httpserver.shutdown(server, server_thread)
		shutil.rmtree(temp_dir, ignore_errors=True)


#============================================
def backend_for_device(
	backends: list[base.Backend],
	device: base.Device,
) -> base.Backend:
	"""Return the backend instance whose key matches the device's backend.

	Every concrete backend declares a single `backend_key` class attribute and
	stamps that same value onto every `Device.backend` it emits, so a device is
	matched to its owning backend by exact key with no guesswork or fallback.

	Args:
		backends: The active backend instances.
		device: The selected device carrying its owning backend key.

	Returns:
		The matching Backend instance.

	Raises:
		Airplay2tvError: When no active backend owns the device's backend key.
	"""
	for candidate in backends:
		# Exact match: the device's stamped key against the backend's class key.
		if candidate.backend_key == device.backend:
			return candidate
	message = ""
	message += f"no active backend owns device backend {device.backend!r}"
	raise errors.Airplay2tvError(message)


#============================================
async def ensure_paired(backend: base.Backend, device: base.Device) -> None:
	"""Pair the device inline on a TTY, or raise pointing at `airplay2tv pair`.

	When the backend reports the device needs pairing and it is not already
	paired, pair inline if a controlling TTY can read the on-screen code.
	Without a TTY, raise PairingRequiredError so a headless run fails clearly.

	Args:
		backend: The backend that owns the device.
		device: The selected device.

	Raises:
		PairingRequiredError: When pairing is required but no TTY is available.
	"""
	if not await backend.needs_pairing(device):
		return
	if await backend.is_paired(device) == base.PairingState.PAIRED:
		return
	if not sys.stdin.isatty():
		message = ""
		message += f"device {device.name!r} needs pairing. "
		message += "Run: airplay2tv pair"
		raise errors.PairingRequiredError(message)
	# Inline pairing: the backend drives the handshake and calls prompt_pin to
	# read the 4-digit code the device shows on screen.
	record = await backend.pair(device, prompt_pin)
	save_pairing(record)


#============================================
def prompt_pin() -> str:
	"""Read the 4-digit on-screen pairing code from terminal stdin.

	Returns:
		The entered code with surrounding whitespace stripped.
	"""
	# The backend validates the code with the device; this only reads input.
	entered = input("Enter the 4-digit code shown on the device: ").strip()
	return entered


#============================================
def save_pairing(record: base.PairingRecord) -> None:
	"""Persist a pairing record through the credentials store.

	The credentials module is imported lazily so the stream and devices actions
	pay for it only when a pairing actually happens.

	Args:
		record: The pairing record returned by the backend.
	"""
	credentials = importlib.import_module("airplay2tv.credentials")
	credentials.save_record(record)


#============================================
def prepare_media(
	args: object,
	profile: base.MediaProfile,
	temp_dir: str,
	cancel_event: threading.Event,
) -> media.PreparedMedia:
	"""Inspect and prepare the input file for the selected backend profile.

	Progress is reported to the logger. The caller passes cancel_event so a
	KeyboardInterrupt during a long transcode can signal ffmpeg to terminate
	and clean its partial output before the temp dir is removed.

	Args:
		args: The parsed CLI namespace; reads `input_file` and `media_mode`.
		profile: The selected backend's media profile.
		temp_dir: The directory prepared output is written into.
		cancel_event: A threading.Event owned by run_stream; setting it signals
			an in-flight ffmpeg process to stop and remove its partial output.

	Returns:
		The PreparedMedia naming the file to serve and its content type.
	"""
	input_file = getattr(args, "input_file", None)
	mode_override = getattr(args, "media_mode", None)

	# Report ffmpeg progress as a percentage to the debug log; the CLI is not
	# attached to a progress bar at this layer.
	def on_progress(fraction: float) -> None:
		logger.debug("media preparation %.0f%%", fraction * 100.0)

	prepared = media.prepare(
		input_file,
		profile,
		temp_dir,
		on_progress,
		cancel_event,
		mode_override=mode_override,
	)
	return prepared


#============================================
async def resolve_known_address(
	backends: list[base.Backend],
	args: object,
	devices: list[base.Device],
) -> base.Device | None:
	"""Resolve a known IP or stored address directly, bypassing discovery.

	Two cases use a direct device-info probe so a known device works even when
	SSDP is silent:

	1. `--device <ip>`: when the value is an IP literal and no discovered device
	   already matches it, probe each backend's resolve_address(ip) and use the
	   first Device that resolves.
	2. A saved/default device whose stored config record carries an address that
	   discovery did not surface: probe resolve_address on that stored address
	   before the run falls back to the picker.

	Args:
		backends: The active backend instances.
		args: The parsed CLI namespace; reads `device` and `default_device`.
		devices: The devices discovery surfaced (may be empty).

	Returns:
		A resolved Device, or None to let the normal selection path run.
	"""
	# Case 1: an explicit --device that is a bare IP literal.
	requested = getattr(args, "device", None)
	if requested is not None and looks_like_ip(requested):
		# Only bypass discovery when the IP is not already a discovered device.
		if not _matches_address(devices, requested):
			resolved = await resolve_via_backends(backends, requested)
			if resolved is not None:
				return resolved
	# Case 2: a default/saved device with a stored address discovery missed.
	stored = stored_default_record(args)
	if stored is not None:
		address = stored["address"]
		identifier = stored["identifier"]
		# Skip the probe when discovery already surfaced this saved device.
		if find_by_identifier(devices, identifier) is None and address:
			resolved = await resolve_via_backends(backends, address)
			if resolved is not None:
				return resolved
	return None


#============================================
async def resolve_via_backends(
	backends: list[base.Backend],
	address: str,
) -> base.Device | None:
	"""Return the first Device any backend resolves for an address, or None.

	Each active backend gets a chance to probe the address directly through its
	resolve_address hook; the base implementation returns None so a backend with
	no direct-probe path is safely skipped.

	Args:
		backends: The active backend instances.
		address: The host or IP to probe.

	Returns:
		The first resolved Device, or None when no backend resolves the address.
	"""
	for backend in backends:
		device = await backend.resolve_address(address)
		if device is not None:
			return device
	return None


#============================================
def looks_like_ip(value: str) -> bool:
	"""Report whether a string is a literal IPv4 or IPv6 address.

	A bare IP literal in --device means the user is naming a device by address
	rather than by discovered name or id, which is the signal to try the direct
	device-info probe instead of an exact match against discovered devices.

	Args:
		value: The --device value to classify.

	Returns:
		True when value parses as an IP address literal, False otherwise.
	"""
	# ipaddress.ip_address raises ValueError for any non-IP string (names, ids).
	try:
		ipaddress.ip_address(value)
	except ValueError:
		return False
	return True


#============================================
def _matches_address(devices: list[base.Device], address: str) -> bool:
	"""Report whether a discovered device already lives at the given address."""
	for device in devices:
		if device.address == address:
			return True
	return False


#============================================
def stored_default_record(args: object) -> dict | None:
	"""Return the stored config record for the default/saved device, or None.

	The default device id comes from `--default-device` when set, otherwise from
	the saved default in the config. The matching device record (carrying its
	stored address) is returned so resolve_known_address can probe that address
	when discovery did not surface the device.

	Args:
		args: The parsed CLI namespace; reads `default_device`.

	Returns:
		The stored device record dict, or None when there is no usable default.
	"""
	default_id = getattr(args, "default_device", None)
	current = config.load()
	if default_id is None:
		default_id = config.get_default_device_id(current)
	if default_id is None:
		return None
	record = config.get_device(current, default_id)
	return record


#============================================
def select_device(args: object, devices: list[base.Device]) -> base.Device:
	"""Choose the target device, honoring an explicit, default, or saved id.

	Selection order, each falling through to the next when it yields nothing:

	1. `--device <name-or-id>`: matched exactly by devicepick.select.
	2. `--default-device <id>`: when that id is discoverable, use it; when it is
	   not, print a clear notice and fall back to discovery/selection.
	3. The saved default device id in the config: same discoverable-or-notice
	   rule as a `--default-device` id.
	4. Otherwise the interactive (or single-device) picker via devicepick.select.

	Args:
		args: The parsed CLI namespace; reads `device` and `default_device`.
		devices: The discovered devices to choose from (non-empty).

	Returns:
		The chosen Device.
	"""
	requested = getattr(args, "device", None)
	if requested is not None:
		# An explicit --device always wins and is matched exactly by the picker.
		return devicepick.select(devices, requested)
	# Prefer a --default-device id, then the saved default in the config.
	default_id = getattr(args, "default_device", None)
	if default_id is None:
		default_id = config.get_default_device_id(config.load())
	if default_id is not None:
		preferred = find_by_identifier(devices, default_id)
		if preferred is not None:
			# The saved/default device is on the network: skip the picker.
			return preferred
		# The preferred device is not discoverable right now; say so and fall
		# back to normal discovery/selection rather than failing the run.
		notice = ""
		notice += f"Default device {default_id!r} is not reachable right now; "
		notice += "falling back to discovery."
		print(notice, file=sys.stderr)
		# Headless runs have no terminal to prompt on: raise a clear error
		# so the user knows to pass --device or pair first, not a raw ValueError.
		if not sys.stdin.isatty():
			message = ""
			message += "no device selected and no terminal to prompt; "
			message += "pass --device or pair first"
			raise errors.Airplay2tvError(message)
	# No usable preference: defer to the normal picker (prompt or single device).
	return devicepick.select(devices, None)


#============================================
def find_by_identifier(
	devices: list[base.Device],
	identifier: str,
) -> base.Device | None:
	"""Return the discovered device matching an identifier, or None.

	Args:
		devices: The discovered devices.
		identifier: The device identifier to match exactly.

	Returns:
		The matching Device, or None when no discovered device matches.
	"""
	for device in devices:
		if device.identifier == identifier:
			return device
	return None


#============================================
def persist_device(args: object, device: base.Device) -> None:
	"""Persist the chosen device to the config after a successful play.

	Writes the device record when `--save-device` is set. When
	`--default-device` named this device's identifier, also marks it the default
	so a future run with no flags reuses it automatically. A single atomic config
	write covers both.

	Args:
		args: The parsed CLI namespace; reads `save_device` and `default_device`.
		device: The device that just started playing.
	"""
	save_device = getattr(args, "save_device", False)
	default_id = getattr(args, "default_device", None)
	make_default = default_id is not None and default_id == device.identifier
	if not save_device and not make_default:
		# Nothing to persist this run.
		return
	# Load, merge the record (and default), then write back atomically once.
	current = config.load()
	config.add_device(
		current,
		name=device.name,
		backend=device.backend,
		identifier=device.identifier,
		address=device.address,
	)
	if make_default:
		config.set_default_device_id(current, device.identifier)
	config.save(current)


#============================================
def wait_for_interrupt() -> None:
	"""Block until the user presses Ctrl+C.

	A long Event.wait() parks the thread cheaply until a KeyboardInterrupt is
	delivered, which propagates out of this call and into `run_stream`'s try so
	the finally block releases the server and temp media.
	"""
	# Event is never set, so this waits until a KeyboardInterrupt arrives.
	threading.Event().wait()


#============================================
def status_banner(device: base.Device, url: str) -> str:
	"""Build the user-facing status banner shown after playback starts.

	Args:
		device: The device playback was started on.
		url: The advertised stream URL the device is fetching from.

	Returns:
		A multi-line banner naming the device and stream URL.
	"""
	lines = []
	lines.append(f"Streaming to {device.name}")
	lines.append(f"Serving at {url}")
	lines.append("Press Ctrl+C to stop.")
	banner = "\n".join(lines)
	return banner


#============================================
def no_devices_message() -> str:
	"""Build the message shown when discovery finds no receivers.

	Returns:
		A short, actionable message for the user.
	"""
	message = ""
	message += "No receivers found on the local network. "
	message += "Check that the device is on and on the same network, "
	message += "then try: airplay2tv devices"
	return message
