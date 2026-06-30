"""System-readiness checks for airplay2tv.

Prints PASS/FAIL lines to stdout for every check so the output is readable
over an unattended SSH session. Returns non-zero when any REQUIRED check
(ffmpeg, ffprobe, or local address selection) fails.

The contract for the CLI entry point is:

    run_checks(device=None, input_file=None) -> int

A non-zero return code means at least one required check failed.
"""

# Standard Library
import asyncio
import shutil
import urllib.request
import urllib.error

# PIP3 modules
import defusedxml.ElementTree  # safe XML parser; avoids XXE/billion-laughs attacks

# local repo modules
import airplay2tv.errors as errors
import airplay2tv.netutil as netutil
import airplay2tv.media as media
import airplay2tv.credentials as credentials
import airplay2tv.backends.registry as registry
import airplay2tv.backends.base as base
import airplay2tv.discovery.aggregate as aggregate
import airplay2tv.discovery.roku_ssdp as roku_ssdp


# Sample LAN target used only to exercise the UDP route-selection trick.
# No packets are sent to this address; the OS uses it to pick the interface.
_SAMPLE_LAN_TARGET = "192.168.1.1"

# Discovery listen window in seconds. Kept short so `doctor` exits quickly.
_DISCOVERY_TIMEOUT = 3.0

# Roku ECP port and probe timeout in seconds.
_ECP_PORT = 8060
_ECP_TIMEOUT = 4.0

# ECP endpoints to probe in order.
_ECP_ENDPOINTS = [
	"/query/device-info",
	"/query/active-app",
	"/query/apps",
	"/query/media-player",
]


#============================================
def _looks_like_ip(value: str) -> bool:
	"""Return True when value looks like a bare IPv4 address.

	Args:
		value: The string to test.

	Returns:
		True when value has exactly four dot-separated numeric segments.
	"""
	parts = value.split(".")
	if len(parts) != 4:
		return False
	# Each segment must be a digit-only string.
	for part in parts:
		if not part.isdigit():
			return False
	return True


#============================================
def _ecp_get(url: str) -> tuple[int, bytes]:
	"""Perform a single HTTP GET against an ECP URL and return status + body.

	HTTP 403 is captured as a normal status, not raised. Any other
	urllib.error.HTTPError is also captured and returned as its status code.
	A URLError (connection refused, timeout) is returned as status 0.

	Args:
		url: Full URL to GET (e.g. "http://192.168.1.50:8060/query/device-info").

	Returns:
		A (status_code, body_bytes) tuple. status_code is 0 on connection error.
	"""
	# Only allow http:// scheme; reject anything else before opening the connection.
	if not url.startswith("http://"):
		return (0, b"")
	try:
		# Scheme validated above; only http:// reaches this line. nosec B310
		req = urllib.request.urlopen(url, timeout=_ECP_TIMEOUT)  # nosec B310
	except urllib.error.HTTPError as exc:
		# Capture 403 and other HTTP errors without crashing.
		return (exc.code, b"")
	except urllib.error.URLError:
		return (0, b"")
	# Read the body and close.
	body = req.read()
	status = req.status
	req.close()
	return (status, body)


#============================================
def _extract_ecp_device_fields(body: bytes) -> dict[str, str]:
	"""Parse the ECP /query/device-info XML body and extract key fields.

	Extracts 'ecp-setting-mode', 'friendly-device-name', and 'power-mode' when present.

	Args:
		body: Raw XML bytes from the device-info endpoint.

	Returns:
		A dict with the extracted field names as keys and their text as values.
		Missing fields are absent from the returned dict.
	"""
	fields: dict[str, str] = {}
	if not body:
		return fields
	# Parse XML with defusedxml to guard against XXE and billion-laughs attacks.
	# An invalid body returns an empty dict without crashing.
	try:
		root = defusedxml.ElementTree.fromstring(body)
	except defusedxml.ElementTree.ParseError:
		return fields
	# Walk direct children and collect the three diagnostic fields.
	for child in root:
		tag = child.tag
		if tag in ("ecp-setting-mode", "friendly-device-name", "power-mode"):
			text = child.text
			if text is not None:
				fields[tag] = text.strip()
	return fields


#============================================
def _probe_ecp(ip: str) -> dict[str, object]:
	"""Probe a Roku at <ip>:8060 on all four ECP endpoints and return results.

	Prints a per-endpoint line with the HTTP status for each probe, e.g.:
		[INFO] ECP device-info: HTTP 200
		[WARN] ECP apps: HTTP 403

	On device-info HTTP 200 also prints ecp-setting-mode, friendly-device-name,
	and power-mode. When limited mode and power-mode=Ready are both reported (the
	TV is in networked standby), an advisory note explains the 403 ambiguity.

	Args:
		ip: IPv4 address of the Roku to probe (no port, no scheme).

	Returns:
		A dict with keys:
			"reachable": bool -- True when device-info returned HTTP 200.
			"limited": bool   -- True when ecp-setting-mode == "limited".
			"ip": str         -- The probed IP address.
	"""
	base_url = f"http://{ip}:{_ECP_PORT}"
	device_info_status = 0
	device_fields: dict[str, str] = {}

	for endpoint in _ECP_ENDPOINTS:
		# Strip the leading /query/ prefix to get a short label (e.g. "device-info").
		label = endpoint.removeprefix("/query/")
		url = base_url + endpoint
		status, body = _ecp_get(url)
		# Choose INFO or WARN based on whether the request succeeded.
		if status == 200:
			level = "INFO"
		else:
			level = "WARN"
		print(f"[{level}] ECP {label}: HTTP {status}")
		# Only device-info carries the metadata fields we need.
		if endpoint == "/query/device-info" and status == 200:
			device_info_status = status
			device_fields = _extract_ecp_device_fields(body)
			# Print the extracted diagnostic fields when available.
			if "ecp-setting-mode" in device_fields:
				print(f"[INFO]   ecp-setting-mode: {device_fields['ecp-setting-mode']}")
			if "friendly-device-name" in device_fields:
				print(f"[INFO]   friendly-device-name: {device_fields['friendly-device-name']}")
			if "power-mode" in device_fields:
				print(f"[INFO]   power-mode: {device_fields['power-mode']}")

	reachable = device_info_status == 200
	limited = device_fields.get("ecp-setting-mode") == "limited"
	power_mode = device_fields.get("power-mode", "")
	# When the device is reachable in limited mode with power-mode=Ready,
	# print an advisory note to explain the 403s without drawing a firm conclusion.
	if reachable and limited and power_mode == "Ready":
		print(
			"[INFO] ECP reachable, limited mode "
			f"(power-mode={power_mode}, ecp-setting-mode=limited). "
			"Control endpoints (apps/media-player/keypress) returned 403. "
			"This may be standby, restricted ECP mode, or a setting; "
			"retest with the TV awake (power-mode=PowerOn, Home screen)."
		)
	return {"reachable": reachable, "limited": limited, "ip": ip}


#============================================
def _label(passed: bool) -> str:
	"""Return a PASS or FAIL label string.

	Args:
		passed: True when the check succeeded.

	Returns:
		The string "PASS" or "FAIL".
	"""
	if passed:
		return "PASS"
	return "FAIL"


#============================================
def _check_ffmpeg() -> bool:
	"""Return True when the ffmpeg binary is on PATH.

	Args:
		None

	Returns:
		True when shutil.which finds ffmpeg, False otherwise.
	"""
	found = shutil.which("ffmpeg") is not None
	return found


#============================================
def _check_ffprobe() -> bool:
	"""Return True when the ffprobe binary is on PATH.

	Args:
		None

	Returns:
		True when shutil.which finds ffprobe, False otherwise.
	"""
	found = shutil.which("ffprobe") is not None
	return found


#============================================
def _check_local_address() -> tuple[bool, str]:
	"""Try local_ip_for against a sample LAN target.

	Args:
		None

	Returns:
		A (passed, address) tuple. passed is True when the call succeeds;
		address is the returned IP or an error description on failure.
	"""
	# OSError is raised when the network is unavailable (e.g. no default route).
	try:
		address = netutil.local_ip_for(_SAMPLE_LAN_TARGET)
	except OSError as exc:
		return (False, str(exc))
	return (True, address)


#============================================
def _device_matches(device_obj: base.Device, filter_str: str) -> bool:
	"""Return True when a Device matches the caller-supplied filter string.

	The filter is compared case-insensitively against both the device name and
	the device identifier.

	Args:
		device_obj: The discovered Device to test.
		filter_str: The name or identifier substring to match.

	Returns:
		True when filter_str matches name or identifier (case-insensitive).
	"""
	lower = filter_str.lower()
	name_match = lower in device_obj.name.lower()
	id_match = lower in device_obj.identifier.lower()
	return name_match or id_match


#============================================
async def _run_discovery(
	backends: list[base.Backend],
) -> list[base.Device]:
	"""Run discover_all against the given backends and return found devices.

	Args:
		backends: Active Backend instances to query.

	Returns:
		Flat list of discovered Device objects.
	"""
	result = await aggregate.discover_all(backends, timeout=_DISCOVERY_TIMEOUT)
	return result.devices


#============================================
async def _run_roku_ssdp() -> roku_ssdp.DiscoveryStats:
	"""Run Roku SSDP discovery and return the DiscoveryStats.

	Args:
		None

	Returns:
		DiscoveryStats for the SSDP run.
	"""
	_responders, stats = await roku_ssdp.discover(timeout=_DISCOVERY_TIMEOUT)
	return stats


#============================================
async def _async_run_checks(
	device_filter: str | None,
	input_file: str | None,
) -> int:
	"""Async body of run_checks.

	Args:
		device_filter: Optional device name, identifier, or bare IP to narrow
			output. When it is a bare IPv4 address, a direct ECP probe is also
			performed against that IP.
		input_file: Optional media file path for the media-prep dry run.

	Returns:
		0 when all required checks pass, 1 otherwise.
	"""
	required_failures = 0

	# --- ffmpeg ---
	ffmpeg_ok = _check_ffmpeg()
	if not ffmpeg_ok:
		required_failures += 1
	print(f"[{_label(ffmpeg_ok)}] ffmpeg on PATH")

	# --- ffprobe ---
	ffprobe_ok = _check_ffprobe()
	if not ffprobe_ok:
		required_failures += 1
	print(f"[{_label(ffprobe_ok)}] ffprobe on PATH")

	# --- local address selection ---
	addr_ok, addr_value = _check_local_address()
	if not addr_ok:
		required_failures += 1
		print(f"[{_label(addr_ok)}] local address selection: {addr_value}")
	else:
		print(f"[{_label(addr_ok)}] local address selection: {addr_value}")

	# --- backend availability (required deps) ---
	# Use the non-raising probe so doctor reports a missing backend dependency
	# instead of aborting; a missing required backend counts as a failure.
	availability = registry.backend_availability()
	for item in availability:
		if item.available:
			print(f"[PASS] backend {item.package}: installed")
		else:
			required_failures += 1
			print(f"[FAIL] backend {item.package}: missing -- install: {item.install_command}")
	backends = [item.backend for item in availability if item.backend is not None]
	print(f"[INFO] active backends: {len(backends)}")

	devices = await _run_discovery(backends)
	# Apply device filter when provided.
	if device_filter is not None:
		devices = [d for d in devices if _device_matches(d, device_filter)]
	print(f"[{'PASS' if devices else 'WARN'}] AirPlay/backend discovery: {len(devices)} device(s) found")

	# --- Roku SSDP stats ---
	roku_stats = await _run_roku_ssdp()
	print(
		f"[INFO] Roku SSDP stats: "
		f"probes_sent={roku_stats.probes_sent} "
		f"valid={roku_stats.valid_responses} "
		f"duplicates={roku_stats.duplicates} "
		f"malformed={roku_stats.malformed} "
		f"timeout={roku_stats.timed_out:.1f}s"
	)
	# Surface the interface-selection fallback when SSDP could not pick a
	# specific outbound interface and used the OS default egress instead.
	if roku_stats.fallback_reason is not None:
		print(f"[INFO] Roku SSDP interface fallback: {roku_stats.fallback_reason}")

	# --- direct ECP probe when device_filter is a bare IP address ---
	ecp_result: dict[str, object] | None = None
	if device_filter is not None and _looks_like_ip(device_filter):
		ecp_result = _probe_ecp(device_filter)
		# Print a clear summary line describing the ECP reachability state.
		if ecp_result["reachable"]:
			if ecp_result["limited"]:
				summary = "direct ECP reachable (limited mode)"
			else:
				summary = "direct ECP reachable"
			print(f"[INFO] Roku ECP summary: {summary}")
		else:
			print(f"[WARN] Roku ECP summary: direct ECP not reachable at {device_filter}")
		# When SSDP found nothing but direct ECP is reachable, print a hint.
		if roku_stats.valid_responses == 0 and ecp_result["reachable"]:
			print(
				f"[INFO] Roku discovery: SSDP not seen, but direct ECP reachable at "
				f"{device_filter} -- use --device {device_filter}"
			)

	# --- per-device pairing state ---
	for device_obj in devices:
		pairing_label = _pairing_label(device_obj)
		print(f"[INFO]   device '{device_obj.name}' ({device_obj.backend}): {pairing_label}")

	# --- media-prep dry run ---
	# Doctor only probes local files with ffprobe; a remote URL is skipped with
	# a clear WARN line instead of attempting to inspect it.
	if input_file is not None and media.is_remote_url(input_file):
		print(
			f"[WARN] media dry run skipped: doctor checks local files only "
			f"(got URL {input_file})"
		)
	elif input_file is not None:
		await _run_media_dry_run(input_file, backends)

	if required_failures > 0:
		return 1
	return 0


#============================================
def _pairing_label(device_obj: base.Device) -> str:
	"""Return a human-readable pairing-state description for a device.

	Looks up the pairing record from credentials. No backend.is_paired() call
	is made because the async backends may not be built yet; the credential
	store is the available ground truth.

	Args:
		device_obj: The discovered device.

	Returns:
		A short string: "paired", "not paired", or "pairing needs refresh".
	"""
	record = credentials.get_record(device_obj.identifier, device_obj.backend)
	if record is None:
		return "not paired"
	# A record exists; treat it as valid unless the credential is empty/falsy.
	if not record.credential:
		return "pairing needs refresh"
	return "paired"


#============================================
async def _run_media_dry_run(
	input_file: str,
	backends: list[base.Backend],
) -> None:
	"""Inspect input_file and print the decided preparation path per backend.

	Only inspect + decide are called; no ffmpeg is invoked. When ffprobe is
	absent or the file cannot be inspected, the failure is printed as a WARN
	line so the rest of doctor output is not suppressed.

	Args:
		input_file: Path to the media file to dry-run.
		backends: Active backends whose media profiles are queried.
	"""
	# Attempt inspect; a missing ffprobe or bad file raises PreparationError.
	try:
		info = media.inspect(input_file)
	except errors.PreparationError as exc:
		print(f"[WARN] media inspect failed for {input_file}: {exc}")
		return
	print(
		f"[INFO] media inspect: container={info.container} "
		f"video={info.video_codec} audio={info.audio_codec} "
		f"duration={info.duration:.1f}s"
	)
	# For each backend, query its media profile and decide.
	for backend in backends:
		# media_profile() is async; await it directly inside the running loop.
		profile = await backend.media_profile()
		decision = media.decide(info, profile)
		backend_name = type(backend).__name__
		print(f"[INFO]   {backend_name}: decision={decision}")


#============================================
def run_checks(
	device: str | None = None,
	input_file: str | None = None,
) -> int:
	"""Run all doctor checks and print PASS/FAIL/INFO/WARN lines to stdout.

	Required checks (ffmpeg, ffprobe, local address) contribute to the return
	code. Advisory checks (discovery, pairing, media dry-run) print WARN/INFO
	but do not affect the exit code.

	Args:
		device: Optional name or identifier substring; when given, only
			matching discovered devices appear in the per-device pairing report.
		input_file: Optional path to a media file; when given a dry run of
			inspect + decide is performed for each active backend profile.

	Returns:
		0 when all required checks pass, 1 when any required check fails.
	"""
	result = asyncio.run(_async_run_checks(device, input_file))
	return result
