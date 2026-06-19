#!/usr/bin/env python3
"""E2E checks for the Roku ECP backend against a local fake ECP responder.

No real Roku is contacted. A stdlib http.server stands in for the device on
127.0.0.1: it records every request path so launch/remote URL building can be
asserted, and it returns canned ECP XML so rokuecp.Roku.update() succeeds. A
separate fake always replies 403 to prove the disabled-"Control by mobile apps"
path raises DeviceUnreachableError.

Run directly:
    source source_me.sh && python3 tests/e2e/e2e_roku_ecp.py
"""

# Standard Library
import http.server
import asyncio
import sys
import threading
import subprocess

# This runner executes outside pytest, so the pyproject pythonpath does not
# apply. Locate the repo root and put it on sys.path so the airplay2tv package
# imports cleanly when invoked directly as python3 tests/e2e/e2e_roku_ecp.py.
REPO_ROOT = subprocess.run(
	['git', 'rev-parse', '--show-toplevel'],
	capture_output=True, text=True, check=True,
).stdout.strip()
if REPO_ROOT not in sys.path:
	sys.path.insert(0, REPO_ROOT)

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
def _patch_roku_port(port: int) -> tuple:
	"""Force rokuecp.Roku constructed inside the backend onto the fake port.

	The backend constructs rokuecp.Roku(host=...) with the default ECP port 8060.
	The fake server runs on an OS-assigned port, so this wraps the Roku class to
	inject the test port while leaving every other argument untouched.

	Returns:
		A tuple of (real_roku_class,) so the caller can restore it in a finally.
	"""
	real_roku = roku_ecp.rokuecp.Roku

	def _factory(*args: object, **kwargs: object) -> object:
		kwargs["port"] = port
		return real_roku(*args, **kwargs)

	setattr(roku_ecp.rokuecp, "Roku", _factory)
	return (real_roku,)


#============================================
def _restore_roku_port(saved: tuple) -> None:
	"""Restore the real rokuecp.Roku class after a patch."""
	real_roku = saved[0]
	setattr(roku_ecp.rokuecp, "Roku", real_roku)


#============================================
def check_play_posts_media_player_launch_with_url() -> None:
	"""play() POSTs launch/2213 carrying the served URL as contentId."""
	server, thread, host, port, recorded = _start_fake()
	saved = _patch_roku_port(port)
	try:
		backend = roku_ecp.RokuEcpBackend()
		device = _device_for(port)
		media_url = "http://127.0.0.1:3500/sample.mp4"
		asyncio.run(backend.play(device, media_url, media=object()))
		# Exactly one launch request to the Media Player app id should be recorded.
		launch_paths = [p for p in recorded if p.startswith("/launch/2213")]
		assert len(launch_paths) == 1
		# The served URL must be url-encoded into the contentId query param.
		assert "contentId=http%3A%2F%2F127.0.0.1%3A3500%2Fsample.mp4" in launch_paths[0]
		assert "mediaType=movie" in launch_paths[0]
	finally:
		_restore_roku_port(saved)
		_stop_fake(server, thread)


#============================================
def check_stop_sends_home_keypress() -> None:
	"""stop() sends the Home remote key via a keypress POST."""
	server, thread, host, port, recorded = _start_fake()
	saved = _patch_roku_port(port)
	try:
		backend = roku_ecp.RokuEcpBackend()
		device = _device_for(port)
		asyncio.run(backend.stop(device))
		# rokuecp maps the "home" remote key to a keypress/Home request.
		assert any(p.startswith("/keypress/Home") for p in recorded)
	finally:
		_restore_roku_port(saved)
		_stop_fake(server, thread)


#============================================
def check_status_maps_playing() -> None:
	"""status() maps an active play session to state 'playing' with timing."""
	server, thread, host, port, recorded = _start_fake(MEDIA_PLAYER_PLAY_XML)
	saved = _patch_roku_port(port)
	try:
		backend = roku_ecp.RokuEcpBackend()
		device = _device_for(port)
		status = asyncio.run(backend.status(device))
		assert status.state == "playing"
		# 30000 ms / 120000 ms convert to 30 s and 120 s.
		assert status.position == 30.0
		assert status.duration == 120.0
	finally:
		_restore_roku_port(saved)
		_stop_fake(server, thread)


#============================================
def check_status_maps_paused() -> None:
	"""status() maps a paused session to state 'paused'."""
	server, thread, host, port, recorded = _start_fake(MEDIA_PLAYER_PAUSE_XML)
	saved = _patch_roku_port(port)
	try:
		backend = roku_ecp.RokuEcpBackend()
		device = _device_for(port)
		status = asyncio.run(backend.status(device))
		assert status.state == "paused"
	finally:
		_restore_roku_port(saved)
		_stop_fake(server, thread)


#============================================
def check_status_maps_idle_when_no_session() -> None:
	"""status() maps an inactive player (no MediaState) to state 'idle'."""
	server, thread, host, port, recorded = _start_fake(MEDIA_PLAYER_IDLE_XML)
	saved = _patch_roku_port(port)
	try:
		backend = roku_ecp.RokuEcpBackend()
		device = _device_for(port)
		status = asyncio.run(backend.status(device))
		assert status.state == "idle"
	finally:
		_restore_roku_port(saved)
		_stop_fake(server, thread)


#============================================
def check_play_403_raises_device_unreachable() -> None:
	"""A 403 on launch raises DeviceUnreachableError naming the TV setting."""
	server, thread, host, port, recorded = _start_fake(status_code=403)
	saved = _patch_roku_port(port)
	raised: airplay2tv.errors.DeviceUnreachableError | None = None
	try:
		backend = roku_ecp.RokuEcpBackend()
		device = _device_for(port)
		try:
			asyncio.run(backend.play(device, "http://127.0.0.1:3500/x.mp4", media=object()))
		except airplay2tv.errors.DeviceUnreachableError as exc:
			raised = exc
	finally:
		_restore_roku_port(saved)
		_stop_fake(server, thread)
	# The 403 path must have been exercised.
	assert raised is not None, "Expected DeviceUnreachableError but none was raised"
	# The message must direct the user to the Control by mobile apps setting.
	assert "Control by mobile apps" in str(raised)


#============================================
def check_resolve_address_builds_device_from_device_info() -> None:
	"""resolve_address probes device-info and builds a Device from the fields.

	The direct-IP path must work without SSDP: a successful device-info read at
	a known address yields a Device whose identifier is the serial number, name
	is the friendly device name, model is the model name, and address is the IP
	passed in.
	"""
	server, thread, host, port, recorded = _start_fake()
	saved = _patch_roku_port(port)
	try:
		backend = roku_ecp.RokuEcpBackend()
		device = asyncio.run(backend.resolve_address(host))
		assert device is not None
		assert device.backend == "roku-ecp"
		assert device.address == host
		# DEVICE_INFO_XML carries serial SERIAL123, name Living Room TV, model Sharp.
		assert device.identifier == "SERIAL123"
		assert device.name == "Living Room TV"
		assert device.model == "Sharp Roku TV"
	finally:
		_restore_roku_port(saved)
		_stop_fake(server, thread)


#============================================
def check_resolve_address_returns_none_when_unreachable() -> None:
	"""resolve_address returns None when device-info cannot be read (403)."""
	server, thread, host, port, recorded = _start_fake(status_code=403)
	saved = _patch_roku_port(port)
	try:
		backend = roku_ecp.RokuEcpBackend()
		device = asyncio.run(backend.resolve_address(host))
		assert device is None
	finally:
		_restore_roku_port(saved)
		_stop_fake(server, thread)


#============================================
def main() -> int:
	"""Run all Roku ECP E2E checks; return 0 on all-pass, non-zero on any failure."""
	checks = [
		check_play_posts_media_player_launch_with_url,
		check_stop_sends_home_keypress,
		check_status_maps_playing,
		check_status_maps_paused,
		check_status_maps_idle_when_no_session,
		check_play_403_raises_device_unreachable,
		check_resolve_address_builds_device_from_device_info,
		check_resolve_address_returns_none_when_unreachable,
	]
	failures = 0
	for check in checks:
		name = check.__name__
		try:
			check()
			print(f"PASS  {name}")
		except Exception as exc:
			print(f"FAIL  {name}: {exc}")
			failures += 1
	# Summary line.
	total = len(checks)
	passed = total - failures
	print(f"\n{passed}/{total} checks passed")
	return 0 if failures == 0 else 1


if __name__ == "__main__":
	raise SystemExit(main())
