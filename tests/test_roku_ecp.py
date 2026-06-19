"""Unit tests for the Roku ECP backend against a local fake ECP responder.

No real Roku is contacted. A stdlib http.server stands in for the device on
127.0.0.1: it records every request path so launch/remote URL building can be
asserted, and it returns canned ECP XML so rokuecp.Roku.update() succeeds. A
separate fake always replies 403 to prove the disabled-"Control by mobile apps"
path raises DeviceUnreachableError.

These tests also assert that the third-party rokuecp client is imported only by
the backend module, keeping it the sole importer per the module contract.
"""

# Standard Library
import http.server
import asyncio
import threading

# PIP3 modules
import pytest

# local repo modules
import airplay2tv.errors
import airplay2tv.backends.base
import airplay2tv.backends.roku_ecp as roku_ecp


# Canned ECP XML responses. xmltodict parses these into the dict shapes the
# rokuecp client expects (device-info, active-app, media-player).
DEVICE_INFO_XML = (
	"<device-info>"
	"<udn>uuid-test</udn>"
	"<serial-number>SERIAL123</serial-number>"
	"<model-name>Sharp Roku TV</model-name>"
	"<model-number>4T-C65DL7UR</model-number>"
	"<user-device-name>Living Room TV</user-device-name>"
	"<power-mode>PowerOn</power-mode>"
	"<is-tv>false</is-tv>"
	"</device-info>"
)

# Installed apps list returned on a full update (first update() call).
APPS_XML = (
	"<apps>"
	'<app id="2213" type="appl" version="1.0">Roku Media Player</app>'
	"</apps>"
)

# Active app is the Roku Media Player (id 2213), not a tvinput, so update() also
# queries the media player for its state.
ACTIVE_APP_PLAYING_XML = (
	"<active-app>"
	'<app id="2213">Roku Media Player</app>'
	"</active-app>"
)

# A media-player query reporting active playback.
MEDIA_PLAYER_PLAY_XML = (
	'<player state="play">'
	"<position>30000 ms</position>"
	"<duration>120000 ms</duration>"
	"</player>"
)

# A media-player query reporting a paused session.
MEDIA_PLAYER_PAUSE_XML = (
	'<player state="pause">'
	"<position>5000 ms</position>"
	"<duration>60000 ms</duration>"
	"</player>"
)

# A media-player query with no active session (state close maps to idle).
MEDIA_PLAYER_IDLE_XML = '<player state="close" error="false"></player>'


#============================================
def _make_handler(recorded_paths: list[str], media_player_xml: str, status_code: int) -> type:
	"""Build a BaseHTTPRequestHandler class bound to test state.

	The handler records each request path into recorded_paths and answers ECP
	queries with canned XML. When status_code is 403 every request is refused so
	the disabled-control path can be exercised.

	Args:
		recorded_paths: List the handler appends each requested path to.
		media_player_xml: XML body returned for /query/media-player.
		status_code: 200 for the normal fake, 403 for the refusing fake.

	Returns:
		A handler class suitable for http.server.ThreadingHTTPServer.
	"""

	class _Handler(http.server.BaseHTTPRequestHandler):
		#--------------------------------------------
		def log_message(self, *args: object) -> None:
			# Silence the default stderr request logging during tests.
			return

		#--------------------------------------------
		def _send_xml(self, body: str) -> None:
			encoded = body.encode("utf-8")
			self.send_response(200)
			self.send_header("Content-Type", "application/xml")
			self.send_header("Content-Length", str(len(encoded)))
			self.end_headers()
			self.wfile.write(encoded)

		#--------------------------------------------
		def _route(self) -> None:
			# Record the path so launch/remote URL building can be asserted.
			recorded_paths.append(self.path)
			# The refusing fake replies 403 to every request.
			if status_code == 403:
				self.send_response(403)
				self.send_header("Content-Type", "text/plain")
				self.end_headers()
				self.wfile.write(b"forbidden")
				return
			# The path before any query string selects the canned response.
			route = self.path.split("?", 1)[0]
			if route == "/query/device-info":
				self._send_xml(DEVICE_INFO_XML)
				return
			if route == "/query/active-app":
				self._send_xml(ACTIVE_APP_PLAYING_XML)
				return
			if route == "/query/media-player":
				self._send_xml(media_player_xml)
				return
			if route == "/query/apps":
				self._send_xml(APPS_XML)
				return
			# launch/* and keypress/* return an empty 200 like a real device.
			self.send_response(200)
			self.send_header("Content-Length", "0")
			self.end_headers()

		#--------------------------------------------
		def do_GET(self) -> None:
			self._route()

		#--------------------------------------------
		def do_POST(self) -> None:
			self._route()

	return _Handler


#============================================
def _start_fake(media_player_xml: str = MEDIA_PLAYER_PLAY_XML, status_code: int = 200) -> tuple:
	"""Start a fake ECP server on a free localhost port.

	Returns:
		A tuple of (server, thread, host, port, recorded_paths). The caller must
		shut the server down and join the thread.
	"""
	recorded_paths: list[str] = []
	handler = _make_handler(recorded_paths, media_player_xml, status_code)
	# Port 0 lets the OS pick a free port; bind to loopback only.
	server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
	thread = threading.Thread(target=server.serve_forever, daemon=True)
	thread.start()
	host, port = server.server_address[0], server.server_address[1]
	return server, thread, host, port, recorded_paths


#============================================
def _stop_fake(server: http.server.ThreadingHTTPServer, thread: threading.Thread) -> None:
	"""Shut a fake ECP server down and join its serving thread."""
	server.shutdown()
	server.server_close()
	thread.join(timeout=5)


#============================================
def _device_for(port: int) -> airplay2tv.backends.base.Device:
	"""Build a Device addressed at loopback for the fake server."""
	device = airplay2tv.backends.base.Device(
		name="Living Room TV",
		backend="roku-ecp",
		identifier="uuid:roku:ecp:SERIAL123",
		address="127.0.0.1",
		model="Sharp Roku TV",
	)
	return device


#============================================
def _patch_roku_port(monkeypatch: pytest.MonkeyPatch, port: int) -> None:
	"""Force rokuecp.Roku constructed inside the backend onto the fake port.

	The backend constructs rokuecp.Roku(host=...) with the default ECP port 8060.
	The fake server runs on an OS-assigned port, so this wraps the Roku class to
	inject the test port while leaving every other argument untouched.
	"""
	real_roku = roku_ecp.rokuecp.Roku

	def _factory(*args: object, **kwargs: object) -> object:
		kwargs["port"] = port
		return real_roku(*args, **kwargs)

	monkeypatch.setattr(roku_ecp.rokuecp, "Roku", _factory)


#============================================
def test_build_launch_params_uses_contentid_and_movie() -> None:
	"""play() builds contentId=<url> and the hardcoded mediaType=movie."""
	backend = roku_ecp.RokuEcpBackend()
	params = backend._build_launch_params("http://10.0.0.5:3500/clip.mp4")
	assert params["contentId"] == "http://10.0.0.5:3500/clip.mp4"
	assert params["mediaType"] == "movie"


#============================================
def test_play_posts_media_player_launch_with_url(monkeypatch: pytest.MonkeyPatch) -> None:
	"""play() POSTs launch/2213 carrying the served URL as contentId."""
	server, thread, host, port, recorded = _start_fake()
	_patch_roku_port(monkeypatch, port)
	backend = roku_ecp.RokuEcpBackend()
	device = _device_for(port)
	media_url = "http://127.0.0.1:3500/sample.mp4"
	asyncio.run(backend.play(device, media_url, media=object()))
	_stop_fake(server, thread)
	# Exactly one launch request to the Media Player app id should be recorded.
	launch_paths = [p for p in recorded if p.startswith("/launch/2213")]
	assert len(launch_paths) == 1
	# The served URL must be url-encoded into the contentId query param.
	assert "contentId=http%3A%2F%2F127.0.0.1%3A3500%2Fsample.mp4" in launch_paths[0]
	assert "mediaType=movie" in launch_paths[0]


#============================================
def test_stop_sends_home_keypress(monkeypatch: pytest.MonkeyPatch) -> None:
	"""stop() sends the Home remote key via a keypress POST."""
	server, thread, host, port, recorded = _start_fake()
	_patch_roku_port(monkeypatch, port)
	backend = roku_ecp.RokuEcpBackend()
	device = _device_for(port)
	asyncio.run(backend.stop(device))
	_stop_fake(server, thread)
	# rokuecp maps the "home" remote key to a keypress/Home request.
	assert any(p.startswith("/keypress/Home") for p in recorded)


#============================================
def test_status_maps_playing(monkeypatch: pytest.MonkeyPatch) -> None:
	"""status() maps an active play session to state 'playing' with timing."""
	server, thread, host, port, recorded = _start_fake(MEDIA_PLAYER_PLAY_XML)
	_patch_roku_port(monkeypatch, port)
	backend = roku_ecp.RokuEcpBackend()
	device = _device_for(port)
	status = asyncio.run(backend.status(device))
	_stop_fake(server, thread)
	assert status.state == "playing"
	# 30000 ms / 120000 ms convert to 30 s and 120 s.
	assert status.position == 30.0
	assert status.duration == 120.0


#============================================
def test_status_maps_paused(monkeypatch: pytest.MonkeyPatch) -> None:
	"""status() maps a paused session to state 'paused'."""
	server, thread, host, port, recorded = _start_fake(MEDIA_PLAYER_PAUSE_XML)
	_patch_roku_port(monkeypatch, port)
	backend = roku_ecp.RokuEcpBackend()
	device = _device_for(port)
	status = asyncio.run(backend.status(device))
	_stop_fake(server, thread)
	assert status.state == "paused"


#============================================
def test_status_maps_idle_when_no_session(monkeypatch: pytest.MonkeyPatch) -> None:
	"""status() maps an inactive player (no MediaState) to state 'idle'."""
	server, thread, host, port, recorded = _start_fake(MEDIA_PLAYER_IDLE_XML)
	_patch_roku_port(monkeypatch, port)
	backend = roku_ecp.RokuEcpBackend()
	device = _device_for(port)
	status = asyncio.run(backend.status(device))
	_stop_fake(server, thread)
	assert status.state == "idle"


#============================================
def test_play_403_raises_device_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
	"""A 403 on launch raises DeviceUnreachableError naming the TV setting."""
	server, thread, host, port, recorded = _start_fake(status_code=403)
	_patch_roku_port(monkeypatch, port)
	backend = roku_ecp.RokuEcpBackend()
	device = _device_for(port)
	raised: airplay2tv.errors.DeviceUnreachableError | None = None
	try:
		asyncio.run(backend.play(device, "http://127.0.0.1:3500/x.mp4", media=object()))
	except airplay2tv.errors.DeviceUnreachableError as exc:
		raised = exc
	_stop_fake(server, thread)
	assert raised is not None
	# The message must direct the user to the Control by mobile apps setting.
	assert "Control by mobile apps" in str(raised)


#============================================
def test_resolve_address_builds_device_from_device_info(
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	"""resolve_address probes device-info and builds a Device from the fields.

	The direct-IP path must work without SSDP: a successful device-info read at
	a known address yields a Device whose identifier is the serial number, name
	is the friendly device name, model is the model name, and address is the IP
	passed in.
	"""
	server, thread, host, port, recorded = _start_fake()
	_patch_roku_port(monkeypatch, port)
	backend = roku_ecp.RokuEcpBackend()
	device = asyncio.run(backend.resolve_address(host))
	_stop_fake(server, thread)
	assert device is not None
	assert device.backend == "roku-ecp"
	assert device.address == host
	# DEVICE_INFO_XML carries serial SERIAL123, name Living Room TV, model Sharp.
	assert device.identifier == "SERIAL123"
	assert device.name == "Living Room TV"
	assert device.model == "Sharp Roku TV"


#============================================
def test_resolve_address_returns_none_when_unreachable(
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	"""resolve_address returns None when device-info cannot be read (403)."""
	server, thread, host, port, recorded = _start_fake(status_code=403)
	_patch_roku_port(monkeypatch, port)
	backend = roku_ecp.RokuEcpBackend()
	device = asyncio.run(backend.resolve_address(host))
	_stop_fake(server, thread)
	assert device is None


#============================================
def test_media_profile_h264_aac_mp4_family() -> None:
	"""The Roku profile allows H.264 only, AAC audio, and the MP4 container set."""
	backend = roku_ecp.RokuEcpBackend()
	profile = asyncio.run(backend.media_profile())
	assert "h264" in profile.video_codecs
	# H.265 transcodes down on the user's TV, so it is not passthrough-capable.
	assert "hevc" not in profile.video_codecs
	assert "h265" not in profile.video_codecs
	assert "aac" in profile.audio_codecs
	assert {"mp4", "mov", "m4v"}.issubset(profile.containers)


#============================================
def test_needs_pairing_false_and_paired() -> None:
	"""Roku ECP needs no pairing and reports the PAIRED state."""
	backend = roku_ecp.RokuEcpBackend()
	device = _device_for(0)
	assert asyncio.run(backend.needs_pairing(device)) is False
	state = asyncio.run(backend.is_paired(device))
	assert state is airplay2tv.backends.base.PairingState.PAIRED


#============================================
def test_pair_returns_trivial_record() -> None:
	"""pair() returns an ECP-allowed record without invoking prompt_pin."""
	backend = roku_ecp.RokuEcpBackend()
	device = _device_for(0)

	def _no_pin() -> str:
		# This callback must never be called for Roku ECP pairing.
		raise AssertionError("prompt_pin must not be called for Roku ECP")

	record = asyncio.run(backend.pair(device, _no_pin))
	assert record.backend == "roku-ecp"
	assert record.identifier == device.identifier
	assert record.credential == {"ecp": "allowed"}


#============================================
def test_status_from_media_none_position_duration_no_type_error() -> None:
	"""_status_from_media with None position and duration must not raise TypeError.

	Finding 8 (MEDIUM): a live stream or device firmware that omits position or
	duration returns a MediaState with those fields set to None. The guard
	float(v) if v is not None else None must prevent the unconditional float()
	call from raising TypeError.
	"""
	import unittest.mock as mock

	backend = roku_ecp.RokuEcpBackend()
	# Build a minimal MediaState-like object with None position and duration.
	media = mock.MagicMock()
	media.paused = False
	media.position = None
	media.duration = None
	# Before the fix this raised TypeError; after the fix it returns None fields.
	status = backend._status_from_media(media)
	assert status.state == "playing"
	assert status.position is None
	assert status.duration is None


#============================================
def test_rokuecp_imported_only_in_backend_module() -> None:
	"""rokuecp is imported by the backend module and not by sibling core modules.

	The backend is the sole intended importer of the third-party client. This
	walks the airplay2tv package source and asserts no other module imports
	rokuecp directly.
	"""
	# Standard Library
	import os
	import pathlib

	# Locate the airplay2tv package directory next to the backends sub-package.
	backends_dir = pathlib.Path(roku_ecp.__file__).resolve().parent
	package_dir = backends_dir.parent
	offenders: list[str] = []
	for root, _dirs, files in os.walk(package_dir):
		for name in files:
			if not name.endswith(".py"):
				continue
			path = pathlib.Path(root) / name
			# The backend module is the one allowed importer.
			if path.resolve() == pathlib.Path(roku_ecp.__file__).resolve():
				continue
			text = path.read_text(encoding="utf-8")
			if "import rokuecp" in text or "from rokuecp" in text:
				offenders.append(str(path))
	assert offenders == [], f"rokuecp imported outside the backend: {offenders}"
