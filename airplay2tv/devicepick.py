"""Device list rendering and interactive selection for the airplay2tv picker.

Provides two public callables:

- `render(devices)` -- builds a numbered list string for display.
- `select(devices, requested)` -- resolves a Device from an optional name/id
  flag or, when running on a TTY, an interactive numbered prompt.
"""

# Standard Library
import sys

# local repo modules
import airplay2tv.backends.base


#============================================
def render(devices: list[airplay2tv.backends.base.Device]) -> str:
	"""Build a numbered device list string suitable for terminal display.

	Each line shows the 1-based index, device name, backend, identifier, and
	address.  When two or more devices share the same name the address is
	appended to each entry that has a duplicate name, so the user can tell them
	apart.

	Args:
		devices: Ordered list of discovered Device objects.

	Returns:
		A multi-line string.  An empty list produces an empty string.
	"""
	if not devices:
		return ""

	# Identify names that appear more than once so they can be disambiguated
	name_counts: dict[str, int] = {}
	for device in devices:
		name_counts[device.name] = name_counts.get(device.name, 0) + 1
	duplicate_names: set[str] = {name for name, count in name_counts.items() if count > 1}

	lines: list[str] = []
	for index, device in enumerate(devices, start=1):
		# Show address in parentheses when the name is shared with another device
		if device.name in duplicate_names:
			display_name = f"{device.name} ({device.address})"
		else:
			display_name = device.name
		line = f"{index}. {display_name}  [{device.backend}]  id={device.identifier}  addr={device.address}"
		lines.append(line)

	return "\n".join(lines)


#============================================
def select(
	devices: list[airplay2tv.backends.base.Device],
	requested: str | None,
) -> airplay2tv.backends.base.Device:
	"""Resolve a Device from a name/identifier flag or an interactive prompt.

	Resolution rules:

	1. If `requested` is given, match by exact name or exact identifier.
	   - Exactly one match: return it.
	   - More than one match: raise ValueError naming the ambiguity.
	   - No match: raise ValueError naming the missing device.

	2. If `requested` is None and the process has a controlling TTY
	   (``sys.stdin.isatty()``), display the numbered list and prompt for a
	   1-based index.  Invalid input causes a re-prompt.

	3. If `requested` is None and there is no TTY, raise ValueError.

	Args:
		devices: Ordered list of discovered Device objects.  Must be non-empty;
			callers are responsible for checking and reporting zero devices.
		requested: Exact device name or identifier from the --device flag, or
			None to fall back to the interactive prompt.

	Returns:
		The chosen Device.

	Raises:
		ValueError: When `requested` matches no device, matches multiple devices
			ambiguously, or when there is no TTY and `requested` is None.
	"""
	if not devices:
		raise ValueError("No devices available to select from.")

	if requested is not None:
		# Collect all devices matching by name or identifier
		matches = [d for d in devices if d.name == requested or d.identifier == requested]
		if not matches:
			raise ValueError(
				f"No device found matching name or identifier {requested!r}. "
				"Run without --device to see available devices."
			)
		if len(matches) > 1:
			# Ambiguous: the same name or identifier matches multiple entries
			names = ", ".join(f"{d.name!r} (id={d.identifier})" for d in matches)
			raise ValueError(
				f"Device {requested!r} is ambiguous; it matches multiple devices: {names}."
			)
		return matches[0]

	# No --device given: need a TTY for interactive selection
	if not sys.stdin.isatty():
		raise ValueError(
			"No --device given and no controlling TTY. "
			"Pass --device <name-or-id> to select non-interactively."
		)

	# Interactive numbered prompt
	print(render(devices))
	while True:
		raw = input("Select device number: ").strip()
		# Validate that the input is a digit string in range
		if raw.isdigit():
			choice = int(raw)
			if 1 <= choice <= len(devices):
				return devices[choice - 1]
		print(f"Please enter a number between 1 and {len(devices)}.")
