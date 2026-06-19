"""Interactive pairing flow for the `airplay2tv pair` subcommand.

Discovers all receivers, lets the user select one, and runs the backend's
pairing handshake.  If the selected device is already paired (backend reports
PAIRED and a credential record exists), the function reports that and exits
cleanly without prompting.

The pairing code is read from terminal stdin via a reusable `prompt_pin()`
helper so the flow works over SSH and in tests (monkeypatched stdin).
"""

# Standard Library
import sys
import asyncio
import logging

# local repo modules
import airplay2tv.credentials as credentials
import airplay2tv.devicepick as devicepick
import airplay2tv.backends.base as base
import airplay2tv.backends.registry as registry
import airplay2tv.discovery.aggregate as aggregate


# Wall-clock seconds allowed for backend discovery during the pair command.
DISCOVERY_TIMEOUT = 5.0

logger = logging.getLogger(__name__)


#============================================
def prompt_pin() -> str:
	"""Read the 4-digit pairing code from terminal stdin.

	Prints a clear prompt so the user knows what to type.  Works over SSH
	because it reads from the process stdin, not the terminal device directly.

	Args:
		None

	Returns:
		The entered code string with surrounding whitespace stripped.
	"""
	# input() writes the prompt to stdout so it appears before the cursor.
	entered = input("Enter the 4-digit code shown on the TV: ").strip()
	return entered


#============================================
def _find_backend(
	backends: list[base.Backend],
	device: base.Device,
) -> base.Backend | None:
	"""Return the backend instance that owns the device, or None.

	Matches strictly by backend_key so the behavior is identical to
	app.backend_for_device: a device whose backend field does not match
	any active backend returns None, even when only one backend is active.

	Args:
		backends: Active backend instances.
		device: The device whose owning backend is needed.

	Returns:
		The matching Backend instance, or None when no backend_key matches.
	"""
	for candidate in backends:
		# Backend key lives on the instance; no fallback for mismatches.
		candidate_key = getattr(candidate, "backend_key", None)
		if candidate_key == device.backend:
			return candidate
	# No backend declared a matching key; surface the mismatch to the caller.
	return None


#============================================
async def _pair_device(
	backend: base.Backend,
	device: base.Device,
) -> int:
	"""Run the full pair-or-skip logic for one device.

	Checks whether the device is already paired before prompting.  If paired,
	prints a message and returns 0.  Otherwise runs the backend handshake,
	saves the returned record, and prints success.

	Args:
		backend: The backend that owns the device.
		device: The device to pair with.

	Returns:
		0 on success or already-paired, non-zero on failure.
	"""
	# Check stored credential first so we can skip prompting if already paired.
	stored_record = credentials.get_record(device.identifier, device.backend)
	pairing_state = await backend.is_paired(device)

	# Both conditions must be true: backend reports PAIRED and a record exists.
	if pairing_state == base.PairingState.PAIRED and stored_record is not None:
		print(f"{device.name} is already paired.")
		return 0

	# Run the backend pairing handshake; the backend calls prompt_pin when it
	# displays a PIN on the TV and needs the user to read it back.
	print(f"Starting pairing with {device.name}...")
	record = await backend.pair(device, prompt_pin)

	# Persist the credential so future runs skip the handshake.
	credentials.save_record(record)
	print(f"Paired with {device.name} successfully.")
	return 0


#============================================
async def _async_run(args: object) -> int:
	"""Async body of `run`: discover, select, and pair.

	Args:
		args: The argparse.Namespace from `cli.parse_args()`.  Reads the
			optional `device` attribute to skip the interactive picker.

	Returns:
		The integer exit code for the process.
	"""
	backends = registry.active_backends()
	devices = await aggregate.discover_all(backends, DISCOVERY_TIMEOUT)
	if not devices:
		# Print a recovery hint so the user knows why pairing cannot continue.
		message = ""
		message += "No receivers found on the local network. "
		message += "Check that the device is on and on the same Wi-Fi, "
		message += "then try: airplay2tv devices"
		print(message, file=sys.stderr)
		return 1

	# Resolve a single device via the picker or the --device flag.
	requested_device = getattr(args, "device", None)
	device = devicepick.select(devices, requested_device)

	backend = _find_backend(backends, device)
	if backend is None:
		# This can only happen when multiple backends are active and none claims
		# the device; it indicates a registry/discovery inconsistency.
		print(
			f"No active backend owns device {device.name!r} (backend={device.backend!r}).",
			file=sys.stderr,
		)
		return 2

	exit_code = await _pair_device(backend, device)
	return exit_code


#============================================
def run(args: object) -> int:
	"""Entry point called by `app.run_pair` for the `pair` subcommand.

	Drives the async pairing flow via `asyncio.run` so the pairing command owns
	its own event-loop lifetime, consistent with how `doctor` and `stream` each
	manage their own loop.

	Args:
		args: The argparse.Namespace from `cli.parse_args()`.  Typed loosely as
			`object` because the namespace shape is owned by `cli.py`.

	Returns:
		The integer exit code for the process: 0 on success or already-paired,
		non-zero when discovery finds nothing, the backend is ambiguous, or the
		pairing handshake fails.
	"""
	exit_code = asyncio.run(_async_run(args))
	return exit_code
