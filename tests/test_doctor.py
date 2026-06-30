"""Unit tests for airplay2tv.doctor.run_checks.

All external dependencies (shutil.which, netutil.local_ip_for,
registry.active_backends, aggregate.discover_all, roku_ssdp.discover,
credentials.get_record, doctor._ecp_get) are monkeypatched so the tests
run offline with no real network or ffmpeg.
"""

# PIP3 modules
import pytest

# local repo modules
import airplay2tv.doctor as doctor
import airplay2tv.backends.base as base
import airplay2tv.discovery.roku_ssdp as roku_ssdp
import airplay2tv.discovery.discovery_result as discovery_result


#============================================
def _make_device(name: str = "Living Room TV", backend: str = "airplay") -> base.Device:
	"""Build a minimal Device fixture."""
	device = base.Device(
		name=name,
		backend=backend,
		identifier="aa:bb:cc:dd:ee:ff",
		address="192.168.1.50",
	)
	return device


#============================================
def _make_stats(valid: int = 1) -> roku_ssdp.DiscoveryStats:
	"""Build a DiscoveryStats fixture with one valid response."""
	stats = roku_ssdp.DiscoveryStats(
		probes_sent=1,
		valid_responses=valid,
		duplicates=0,
		malformed=0,
		timed_out=3.0,
	)
	return stats


#============================================
def _patch_all_pass(monkeypatch: pytest.MonkeyPatch, device: base.Device) -> None:
	"""Monkeypatch every external call so all checks report success."""
	# ffmpeg and ffprobe found on PATH
	monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
	# Local address succeeds
	monkeypatch.setattr(
		"airplay2tv.netutil.local_ip_for",
		lambda target: "192.168.1.10",
	)
	# active_backends returns an empty list (no real backends needed for PASS)
	monkeypatch.setattr(
		"airplay2tv.backends.registry.active_backends",
		lambda: [],
	)
	# discover_all returns the supplied device wrapped in a DiscoveryResult
	async def _fake_discover_all(
		backends: list,
		timeout: float,
	) -> discovery_result.DiscoveryResult:
		return discovery_result.DiscoveryResult(devices=[device], failures=[])
	monkeypatch.setattr(
		"airplay2tv.discovery.aggregate.discover_all",
		_fake_discover_all,
	)
	# roku_ssdp.discover returns one valid response
	async def _fake_roku_discover(timeout: float = 3) -> tuple:
		return ([], _make_stats(valid=1))
	monkeypatch.setattr(
		"airplay2tv.discovery.roku_ssdp.discover",
		_fake_roku_discover,
	)
	# credentials.get_record returns a valid paired record
	monkeypatch.setattr(
		"airplay2tv.credentials.get_record",
		lambda identifier, backend: base.PairingRecord(
			identifier=identifier,
			backend=backend,
			credential="fake-credential",
		),
	)


#============================================
def test_run_checks_all_pass(
	monkeypatch: pytest.MonkeyPatch,
	capsys: pytest.CaptureFixture,
) -> None:
	"""run_checks returns 0 when ffmpeg, ffprobe, and address checks all pass."""
	device = _make_device()
	_patch_all_pass(monkeypatch, device)

	result = doctor.run_checks()

	assert result == 0
	captured = capsys.readouterr()
	assert "[PASS] ffmpeg on PATH" in captured.out
	assert "[PASS] ffprobe on PATH" in captured.out
	assert "[PASS] local address selection" in captured.out


#============================================
def test_run_checks_ffmpeg_missing_returns_nonzero(
	monkeypatch: pytest.MonkeyPatch,
	capsys: pytest.CaptureFixture,
) -> None:
	"""run_checks returns 1 when ffmpeg is absent (a required check fails)."""
	device = _make_device()
	_patch_all_pass(monkeypatch, device)

	# Override which so ffmpeg is absent but ffprobe is present
	def _which_no_ffmpeg(name: str) -> str | None:
		if name == "ffmpeg":
			return None
		return f"/usr/bin/{name}"

	monkeypatch.setattr("shutil.which", _which_no_ffmpeg)

	result = doctor.run_checks()

	assert result != 0
	captured = capsys.readouterr()
	assert "[FAIL] ffmpeg on PATH" in captured.out
	assert "[PASS] ffprobe on PATH" in captured.out


#============================================
def test_run_checks_device_filter_narrows_output(
	monkeypatch: pytest.MonkeyPatch,
	capsys: pytest.CaptureFixture,
) -> None:
	"""Device filter limits the per-device pairing report to matching devices."""
	device_match = _make_device(name="Bedroom Roku", backend="roku")
	device_other = _make_device(name="Kitchen TV", backend="airplay")

	# Make discover_all return both devices in a DiscoveryResult
	async def _fake_discover_all(
		backends: list,
		timeout: float,
	) -> discovery_result.DiscoveryResult:
		return discovery_result.DiscoveryResult(
			devices=[device_match, device_other],
			failures=[],
		)

	_patch_all_pass(monkeypatch, device_match)
	monkeypatch.setattr(
		"airplay2tv.discovery.aggregate.discover_all",
		_fake_discover_all,
	)

	result = doctor.run_checks(device="Bedroom Roku")

	assert result == 0
	captured = capsys.readouterr()
	# Only the matching device should appear in the per-device lines
	assert "Bedroom Roku" in captured.out
	assert "Kitchen TV" not in captured.out


#============================================
def test_run_checks_address_fail_returns_nonzero(
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	"""run_checks returns 1 when local_ip_for raises (no default route)."""
	device = _make_device()
	_patch_all_pass(monkeypatch, device)

	def _fail_ip(target: str) -> str:
		raise OSError("Network unreachable")

	monkeypatch.setattr("airplay2tv.netutil.local_ip_for", _fail_ip)

	result = doctor.run_checks()

	assert result != 0


#============================================
# ECP device-info XML body with limited mode, power-mode=Ready, and a friendly name.
# Matches the hardware evidence: ECP reachable but apps/media-player/keypress return 403.
_DEVICE_INFO_LIMITED_XML = (
	b"<root>"
	b"<ecp-setting-mode>limited</ecp-setting-mode>"
	b"<power-mode>Ready</power-mode>"
	b"<friendly-device-name>Living Room Roku</friendly-device-name>"
	b"</root>"
)

# ECP device-info XML body with full (non-limited) mode and power-mode=PowerOn.
_DEVICE_INFO_FULL_XML = (
	b"<root>"
	b"<ecp-setting-mode>full</ecp-setting-mode>"
	b"<power-mode>PowerOn</power-mode>"
	b"<friendly-device-name>Bedroom Roku</friendly-device-name>"
	b"</root>"
)


#============================================
def _patch_ecp(monkeypatch: pytest.MonkeyPatch, responses: dict[str, tuple[int, bytes]]) -> None:
	"""Monkeypatch doctor._ecp_get to return canned (status, body) pairs.

	Args:
		monkeypatch: The pytest monkeypatch fixture.
		responses: A dict mapping URL suffix (e.g. "/query/device-info") to
			(status_code, body_bytes). Unknown suffixes return (0, b"").
	"""
	def _fake_ecp_get(url: str) -> tuple[int, bytes]:
		# Match by suffix so we do not need to hardcode the IP/port.
		for suffix, result in responses.items():
			if url.endswith(suffix):
				return result
		return (0, b"")
	monkeypatch.setattr("airplay2tv.doctor._ecp_get", _fake_ecp_get)


#============================================
def test_ecp_probe_200_limited_prints_per_endpoint_and_fields(
	monkeypatch: pytest.MonkeyPatch,
	capsys: pytest.CaptureFixture,
) -> None:
	"""Per-endpoint lines and device fields are printed on a 200/403 mix."""
	device = _make_device()
	_patch_all_pass(monkeypatch, device)
	# Patch SSDP to return zero valid responses so the SSDP-not-seen hint fires.
	async def _fake_roku_discover_zero(timeout: float = 3) -> tuple:
		return ([], _make_stats(valid=0))
	monkeypatch.setattr(
		"airplay2tv.discovery.roku_ssdp.discover",
		_fake_roku_discover_zero,
	)
	# device-info returns 200 with limited XML; the other three return 403.
	_patch_ecp(monkeypatch, {
		"/query/device-info": (200, _DEVICE_INFO_LIMITED_XML),
		"/query/active-app": (403, b""),
		"/query/apps": (403, b""),
		"/query/media-player": (403, b""),
	})

	result = doctor.run_checks(device="192.168.1.50")

	assert result == 0
	out = capsys.readouterr().out
	# Per-endpoint status lines must be present.
	assert "[INFO] ECP device-info: HTTP 200" in out
	assert "[WARN] ECP active-app: HTTP 403" in out
	assert "[WARN] ECP apps: HTTP 403" in out
	assert "[WARN] ECP media-player: HTTP 403" in out
	# Extracted fields must appear.
	assert "ecp-setting-mode: limited" in out
	assert "friendly-device-name: Living Room Roku" in out
	# Summary must say limited mode.
	assert "direct ECP reachable (limited mode)" in out


#============================================
def test_ecp_probe_ssdp_zero_but_reachable_prints_hint(
	monkeypatch: pytest.MonkeyPatch,
	capsys: pytest.CaptureFixture,
) -> None:
	"""The SSDP-not-seen hint is printed when SSDP finds nothing but ECP is reachable."""
	device = _make_device()
	_patch_all_pass(monkeypatch, device)
	async def _fake_roku_discover_zero(timeout: float = 3) -> tuple:
		return ([], _make_stats(valid=0))
	monkeypatch.setattr(
		"airplay2tv.discovery.roku_ssdp.discover",
		_fake_roku_discover_zero,
	)
	_patch_ecp(monkeypatch, {
		"/query/device-info": (200, _DEVICE_INFO_FULL_XML),
		"/query/active-app": (200, b"<root/>"),
		"/query/apps": (403, b""),
		"/query/media-player": (403, b""),
	})

	doctor.run_checks(device="192.168.1.99")

	out = capsys.readouterr().out
	# The SSDP-not-seen hint must reference the probed IP and the --device flag.
	assert "SSDP not seen" in out
	assert "direct ECP reachable at 192.168.1.99" in out
	assert "--device 192.168.1.99" in out


#============================================
def test_ecp_probe_unreachable_prints_not_reachable(
	monkeypatch: pytest.MonkeyPatch,
	capsys: pytest.CaptureFixture,
) -> None:
	"""When device-info returns status 0 (connection error) the summary says not reachable."""
	device = _make_device()
	_patch_all_pass(monkeypatch, device)
	# All endpoints return status 0 (connection refused / timeout).
	_patch_ecp(monkeypatch, {})

	doctor.run_checks(device="10.0.0.99")

	out = capsys.readouterr().out
	assert "direct ECP not reachable at 10.0.0.99" in out


#============================================
def test_ecp_extract_device_fields_limited() -> None:
	"""_extract_ecp_device_fields parses ecp-setting-mode, power-mode, and friendly-device-name."""
	fields = doctor._extract_ecp_device_fields(_DEVICE_INFO_LIMITED_XML)
	assert fields["ecp-setting-mode"] == "limited"
	assert fields["power-mode"] == "Ready"
	assert fields["friendly-device-name"] == "Living Room Roku"


#============================================
def test_ecp_extract_device_fields_empty_body() -> None:
	"""_extract_ecp_device_fields returns an empty dict for an empty body."""
	fields = doctor._extract_ecp_device_fields(b"")
	assert fields == {}


#============================================
def test_ecp_no_probe_when_device_is_not_ip(
	monkeypatch: pytest.MonkeyPatch,
	capsys: pytest.CaptureFixture,
) -> None:
	"""No ECP probe lines are printed when the device filter is a name, not an IP."""
	device = _make_device(name="Living Room TV")
	_patch_all_pass(monkeypatch, device)
	# Ensure _ecp_get is never called by raising if it is.
	def _should_not_be_called(url: str) -> tuple[int, bytes]:
		raise AssertionError(f"_ecp_get should not be called for a name filter, got {url}")
	monkeypatch.setattr("airplay2tv.doctor._ecp_get", _should_not_be_called)

	result = doctor.run_checks(device="Living Room TV")

	assert result == 0
	out = capsys.readouterr().out
	# No ECP lines should appear.
	assert "ECP device-info" not in out


#============================================
def test_ecp_probe_limited_ready_prints_advisory_note(
	monkeypatch: pytest.MonkeyPatch,
	capsys: pytest.CaptureFixture,
) -> None:
	"""The standby advisory note is printed when limited mode AND power-mode=Ready."""
	device = _make_device()
	_patch_all_pass(monkeypatch, device)
	async def _fake_roku_discover_zero(timeout: float = 3) -> tuple:
		return ([], _make_stats(valid=0))
	monkeypatch.setattr(
		"airplay2tv.discovery.roku_ssdp.discover",
		_fake_roku_discover_zero,
	)
	# device-info has limited mode and power-mode=Ready (networked standby).
	_patch_ecp(monkeypatch, {
		"/query/device-info": (200, _DEVICE_INFO_LIMITED_XML),
		"/query/active-app": (403, b""),
		"/query/apps": (403, b""),
		"/query/media-player": (403, b""),
	})

	doctor.run_checks(device="192.168.1.50")

	out = capsys.readouterr().out
	# Power-mode field must appear as an INFO line.
	assert "power-mode: Ready" in out
	# The advisory note must mention both fields and suggest retesting.
	assert "power-mode=Ready" in out
	assert "ecp-setting-mode=limited" in out
	assert "retest" in out
