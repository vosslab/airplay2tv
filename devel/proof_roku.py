#!/usr/bin/env python3
"""
Hardware proof script for Roku Media Player casting via the ECP protocol.

This is a throwaway devel/ proof, not a product backend. It retires the
highest project risk before the M3 Roku backend is built by answering, on
REAL hardware, exactly what M3 needs:

  - The working launch endpoint and app id (Roku Media Player = 2213).
  - The correct deep-link parameter spelling and casing. Roku's own docs
    are inconsistent (they show both contentId/mediaType and
    contentID/MediaType), so this script tries BOTH casings and reports
    which one produced real playback.
  - The exact rokuecp method and argument names used for control, taken
    from OTHER_REPOS/python-rokuecp (not invented).

It SSDP-discovers the Roku (ST: roku:ecp), parses the Location header,
GETs /query/device-info and /query/apps, serves a small MP4 locally,
launches app 2213 with the deep-link params, and confirms ACTUAL playback
via /query/active-app and /query/media-player (state="play"), not an HTTP
200 alone.

The user must run this on a machine on the same LAN as the Roku and then
tee the output into docs/active_plans/reports/. We cannot run it here
because there is no device.

Raw curl equivalents (the user can test these by hand):

  curl "http://<roku-ip>:8060/query/device-info"
  curl "http://<roku-ip>:8060/query/apps"
  # casing A (lowercase id, lowercase media type):
  curl -d '' "http://<roku-ip>:8060/launch/2213?contentId=<url>&mediaType=mp4"
  # casing B (uppercase ID, uppercase Media Type, matches the ECP doc curl):
  curl -d '' "http://<roku-ip>:8060/launch/2213?contentID=<url>&MediaType=mp4"
  curl "http://<roku-ip>:8060/query/active-app"
  curl "http://<roku-ip>:8060/query/media-player"
"""

# Standard Library
import time
import socket
import asyncio
import argparse
import threading
import http.server
import socketserver
import urllib.error
import urllib.request
from urllib.parse import quote

# PIP3 modules
import rokuecp


# Roku Media Player channel/app id. This is the built-in app that plays a
# direct media URL passed as a deep-link content id.
ROKU_MEDIA_PLAYER_APP_ID = "2213"

# SSDP multicast endpoint and the Roku-specific search target.
SSDP_MULTICAST_ADDR = "239.255.255.250"
SSDP_MULTICAST_PORT = 1900
ROKU_SSDP_TARGET = "roku:ecp"

# Module-level access log shared with the HTTP server thread; append-only.
HTTP_ACCESS_LOG: list[str] = []


#============================================
# Minimal local HTTP server that logs every request and Range header.
#============================================

class RangeLoggingHandler(http.server.SimpleHTTPRequestHandler):
	"""Serve a single MP4 file and record each request plus its Range header."""

	def log_message(self, format_str: str, *log_args: object) -> None:
		"""Record one access-log line into the shared HTTP_ACCESS_LOG."""
		# Compose a plain client + request line for the evidence log.
		client = self.client_address[0]
		line = f"{client} - {format_str % log_args}"
		HTTP_ACCESS_LOG.append(line)

	def do_GET(self) -> None:
		"""Handle GET, recording the Range header the Roku sent."""
		# Capture the Range header verbatim; Roku Media Player issues
		# partial-content GETs, and proving that is part of the evidence.
		range_header = self.headers.get("Range")
		if range_header is not None:
			HTTP_ACCESS_LOG.append(f"RANGE {self.path} -> {range_header}")
		else:
			HTTP_ACCESS_LOG.append(f"RANGE {self.path} -> <none>")
		super().do_GET()


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
	"""Threaded HTTP server so range requests can overlap the launch call."""

	# Daemon threads so the process can exit cleanly at the end.
	daemon_threads = True
	# Allow immediate rebinding of the port across repeated proof runs.
	allow_reuse_address = True


#============================================
# Networking helpers.
#============================================

def get_local_ip() -> str:
	"""Return the LAN IP address this host uses to reach other devices."""
	# 8.8.8.8 is only used to select a route, not contacted.
	probe_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
	probe_socket.connect(("8.8.8.8", 80))
	local_ip = probe_socket.getsockname()[0]
	probe_socket.close()
	return local_ip


def _make_handler_factory(serve_dir: str) -> type[RangeLoggingHandler]:
	"""Return a handler class bound to serve files from serve_dir."""
	# Build a thin subclass that fixes the directory argument.
	class BoundHandler(RangeLoggingHandler):
		def __init__(self, *handler_args: object, **handler_kwargs: object) -> None:
			super().__init__(*handler_args, directory=serve_dir, **handler_kwargs)
	return BoundHandler


def start_http_server(serve_dir: str, host_ip: str) -> tuple[ThreadingHTTPServer, int]:
	"""Start the threaded MP4 server on an ephemeral port and return it."""
	# Bind to port 0 so the OS assigns a free ephemeral port.
	handler_factory = _make_handler_factory(serve_dir)
	httpd = ThreadingHTTPServer((host_ip, 0), handler_factory)
	chosen_port = httpd.server_address[1]
	# Run the server loop in a background daemon thread.
	server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
	server_thread.start()
	return httpd, chosen_port


#============================================
# SSDP discovery (ST: roku:ecp).
#============================================

def ssdp_discover_roku() -> str | None:
	"""Discover a Roku via SSDP and return its base URL from Location.

	Sends an M-SEARCH for ST roku:ecp and parses the Location header of the
	first matching reply. Returns the base http://ip:port URL or None.
	"""
	# Build the M-SEARCH datagram exactly as Roku ECP discovery expects.
	msearch = (
		"M-SEARCH * HTTP/1.1\r\n"
		f"HOST: {SSDP_MULTICAST_ADDR}:{SSDP_MULTICAST_PORT}\r\n"
		'MAN: "ssdp:discover"\r\n'
		"MX: 3\r\n"
		f"ST: {ROKU_SSDP_TARGET}\r\n"
		"\r\n"
	)

	# Open a UDP socket, broaden TTL, and allow a short receive window.
	udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
	udp_socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
	udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
	udp_socket.settimeout(4)
	udp_socket.sendto(msearch.encode("ascii"), (SSDP_MULTICAST_ADDR, SSDP_MULTICAST_PORT))

	# Read replies until the timeout; return the first Roku Location.
	location = _read_ssdp_location(udp_socket)
	udp_socket.close()
	return location


def _read_ssdp_location(udp_socket: socket.socket) -> str | None:
	"""Read SSDP replies and return the first roku:ecp Location, if any."""
	# Loop receiving datagrams until the socket times out.
	deadline = time.time() + 4
	while time.time() < deadline:
		raw = _recv_ssdp(udp_socket)
		if raw is None:
			break
		text = raw.decode("ascii", errors="replace")
		# Only accept replies that advertise the Roku ECP search target.
		if ROKU_SSDP_TARGET not in text.lower() and "roku" not in text.lower():
			continue
		location = _parse_header(text, "location")
		if location is not None:
			return location.strip()
	return None


def _recv_ssdp(udp_socket: socket.socket) -> bytes | None:
	"""Receive one SSDP datagram, or None on timeout."""
	# A timeout simply means no more replies arrived in the window.
	try:
		data, _addr = udp_socket.recvfrom(2048)
	except socket.timeout:
		return None
	return data


def _parse_header(text: str, header_name: str) -> str | None:
	"""Return the value of a case-insensitive HTTP-style header from text."""
	# SSDP replies are line-oriented HTTP headers; scan for the name.
	target = header_name.lower() + ":"
	for line in text.split("\r\n"):
		if line.lower().startswith(target):
			return line.split(":", 1)[1].strip()
	return None


def base_url_to_host(base_url: str) -> str:
	"""Extract the bare host (IP) from a Roku base URL like http://ip:8060/."""
	# Strip the scheme then the path/port to leave just the host address.
	without_scheme = base_url.split("://", 1)[-1]
	host_and_rest = without_scheme.split("/", 1)[0]
	host = host_and_rest.split(":", 1)[0]
	return host


#============================================
# Raw ECP queries (stdlib, for verbatim response capture).
#============================================

def ecp_get(host: str, path: str) -> str:
	"""GET an ECP query path from the Roku and return the raw XML body."""
	# Build the full ECP URL and fetch the verbatim XML for the evidence log.
	url = f"http://{host}:8060{path}"
	with urllib.request.urlopen(url, timeout=5) as response:  # nosec B310 - local LAN hardware probe; URL is always http://<roku-ip>:8060/
		body = response.read().decode("utf-8", errors="replace")
	return body


def apps_contains_media_player(apps_xml: str) -> bool:
	"""Return True if the /query/apps XML lists the Roku Media Player app id."""
	# A simple substring check on the app id attribute is enough evidence.
	return f'id="{ROKU_MEDIA_PLAYER_APP_ID}"' in apps_xml


#============================================
# Argument parsing.
#============================================

def parse_args() -> argparse.Namespace:
	"""Parse command-line arguments for the Roku proof run."""
	parser = argparse.ArgumentParser(
		description="Proof: cast a local MP4 to a real Roku via ECP / rokuecp."
	)
	parser.add_argument(
		'-i', '--ip', dest='roku_ip', type=str, default=None,
		help="Roku IP address to target (skips SSDP discovery if given)."
	)
	parser.add_argument(
		'-m', '--mp4', dest='mp4_path', type=str, required=True,
		help="Path to a small known-good sample MP4 file to serve."
	)
	args = parser.parse_args()
	return args


#============================================
# Error helpers.
#============================================

def _handle_ecp_forbidden(exc: urllib.error.HTTPError, host: str) -> None:
	"""Print a clear action message for HTTP 403 and exit non-zero.

	A 403 on ECP endpoints means the Roku's "Control by mobile apps" setting
	is disabled. The user must enable it before the proof can continue.
	"""
	# Only handle 403; re-raise anything else so it surfaces naturally.
	if exc.code != 403:
		raise exc
	print(f"ECP control is restricted (HTTP 403 Forbidden) on {host}.")
	print("Enable: Settings > System > Advanced system settings > Control by mobile apps")
	print("Then re-run this script.")
	print("")
	print("=== REQUIRED OUTPUT FOR M3 (Roku) ===")
	print(f"ecp_host: {host}")
	print("ecp_status: BLOCKED (HTTP 403 -- Control by mobile apps is disabled)")
	print("=== END REQUIRED OUTPUT ===")
	raise SystemExit(1)


#============================================
# Async proof routine.
#============================================

async def run_proof(roku_ip: str | None, mp4_path: str) -> None:
	"""Run the full Roku proof and print machine evidence.

	Args:
		roku_ip: Optional Roku IP; when omitted, SSDP discovery is used.
		mp4_path: Filesystem path to the sample MP4 to serve and cast.
	"""
	print("=== Roku proof: discovery ===")
	host = _resolve_host(roku_ip)
	if host is None:
		_print_no_device_help()
		return
	print(f"Roku host: {host}")

	print("=== Roku proof: device-info ===")
	try:
		device_info_xml = ecp_get(host, "/query/device-info")
	except urllib.error.HTTPError as exc:
		_handle_ecp_forbidden(exc, host)
	print(device_info_xml.strip())

	print("=== Roku proof: apps (confirm app 2213 present) ===")
	try:
		apps_xml = ecp_get(host, "/query/apps")
	except urllib.error.HTTPError as exc:
		_handle_ecp_forbidden(exc, host)
	print(apps_xml.strip())
	media_player_present = apps_contains_media_player(apps_xml)
	print(f"Roku Media Player (app {ROKU_MEDIA_PLAYER_APP_ID}) present: {media_player_present}")

	# Start the local HTTP server before launching so the URL is ready.
	print("=== Roku proof: local HTTP server ===")
	host_ip = get_local_ip()
	serve_dir = _parent_dir(mp4_path)
	file_name = _base_name(mp4_path)
	httpd, port = start_http_server(serve_dir, host_ip)
	media_url = f"http://{host_ip}:{port}/{quote(file_name)}"
	print(f"Serving {serve_dir} on {host_ip}:{port}")
	print(f"media content URL: {media_url}")

	# Try both documented param casings and record which one plays.
	working_casing = await _try_both_casings(host, media_url)

	# Give any trailing range requests a moment to land in the log.
	time.sleep(2)
	httpd.shutdown()

	print("=== Roku proof: HTTP access log (with Range requests) ===")
	for entry in HTTP_ACCESS_LOG:
		print(f"  {entry}")

	_print_required_output(
		host=host,
		media_player_present=media_player_present,
		media_url=media_url,
		working_casing=working_casing,
	)


def _resolve_host(roku_ip: str | None) -> str | None:
	"""Return the Roku host, using the CLI IP or SSDP discovery."""
	# An explicit IP skips discovery entirely.
	if roku_ip is not None:
		return roku_ip
	print("No --ip given; running SSDP M-SEARCH for ST roku:ecp ...")
	base_url = ssdp_discover_roku()
	if base_url is None:
		return None
	print(f"SSDP Location: {base_url}")
	return base_url_to_host(base_url)


def _print_no_device_help() -> None:
	"""Print a clear checklist when no Roku is discovered."""
	# Discovery failure is almost always network scoping or sleep.
	print("NO DEVICE FOUND.")
	print("Checklist:")
	print("  - Run this on the same LAN/subnet as the Roku.")
	print("  - Wake the Roku (SSDP may be ignored in deep sleep).")
	print("  - Pass --ip <roku-ip> to skip discovery and target it directly.")
	print("  - Confirm SSDP multicast (UDP 1900) is not blocked.")


async def _try_both_casings(host: str, media_url: str) -> str | None:
	"""Launch app 2213 with each param casing; return the casing that plays.

	Roku's own docs show two casings. We try the lowercase form first, then
	the uppercase form, confirming ACTUAL playback each time via
	/query/active-app and /query/media-player. The first casing that yields
	state="play" wins.
	"""
	# Casing A: contentId / mediaType (lowercase). Casing B: contentID /
	# MediaType (uppercase, matching the ECP doc curl example).
	casings = [
		("contentId/mediaType", {"contentId": media_url, "mediaType": "mp4"}),
		("contentID/MediaType", {"contentID": media_url, "MediaType": "mp4"}),
	]

	working_casing: str | None = None
	for casing_label, params in casings:
		print(f"=== Roku proof: launch attempt ({casing_label}) ===")
		played = await _launch_and_confirm(host, params, casing_label)
		if played and working_casing is None:
			working_casing = casing_label
		# Pause between attempts so the Roku settles before the next launch.
		await asyncio.sleep(3)
	return working_casing


async def _launch_and_confirm(
	host: str,
	params: dict[str, str],
	casing_label: str,
) -> bool:
	"""Launch app 2213 with params via rokuecp and confirm real playback.

	Uses rokuecp.Roku.launch(app_id, params) for control (the real method
	name from python-rokuecp), then reads /query/active-app and
	/query/media-player to confirm state="play".

	Returns:
		True if the media player reports active playback.
	"""
	# rokuecp.Roku is an async context manager; launch() POSTs to
	# /launch/<app_id>?<urlencoded params> exactly like the ECP curl form.
	async with rokuecp.Roku(host) as roku:
		print(f"  calling rokuecp.Roku.launch({ROKU_MEDIA_PLAYER_APP_ID!r}, {params})")
		await roku.launch(ROKU_MEDIA_PLAYER_APP_ID, params)

	# Poll the raw query endpoints for verbatim evidence of playback.
	played = False
	for attempt in range(5):
		await asyncio.sleep(2)
		active_app_xml = ecp_get(host, "/query/active-app")
		media_player_xml = ecp_get(host, "/query/media-player")
		state = _parse_player_state(media_player_xml)
		print(f"  poll {attempt + 1}: media-player state={state}")
		print(f"    active-app: {_collapse(active_app_xml)}")
		print(f"    media-player: {_collapse(media_player_xml)}")
		# Real playback is state="play"; HTTP 200 alone is not enough.
		if state == "play":
			played = True
			break
	print(f"  casing {casing_label} produced playback: {played}")
	return played


def _parse_player_state(media_player_xml: str) -> str | None:
	"""Return the player state attribute from /query/media-player XML."""
	# The state lives in <player ... state="play"> as an attribute.
	marker = 'state="'
	start = media_player_xml.find(marker)
	if start == -1:
		return None
	start += len(marker)
	end = media_player_xml.find('"', start)
	if end == -1:
		return None
	return media_player_xml[start:end]


def _collapse(xml_text: str) -> str:
	"""Collapse XML whitespace into a single line for compact logging."""
	# Join split lines so each evidence entry stays on one log line.
	parts = [part.strip() for part in xml_text.split("\n") if part.strip()]
	return " ".join(parts)


def _parent_dir(file_path: str) -> str:
	"""Return the directory portion of file_path (or '.' if none)."""
	# Simple rsplit keeps the path handling explicit and dependency-free.
	if "/" not in file_path:
		return "."
	parent = file_path.rsplit("/", 1)[0]
	if parent == "":
		return "/"
	return parent


def _base_name(file_path: str) -> str:
	"""Return the final path component of file_path."""
	# Final component after the last slash is the served filename.
	return file_path.rsplit("/", 1)[-1]


def _print_required_output(
	host: str,
	media_player_present: bool,
	media_url: str,
	working_casing: str | None,
) -> None:
	"""Print the REQUIRED-OUTPUT block that the M3 Roku backend needs."""
	# This block is what the user tees into docs/active_plans/reports/.
	print("")
	print("=== REQUIRED OUTPUT FOR M3 (Roku) ===")
	print(f"launch_endpoint: http://{host}:8060/launch/{ROKU_MEDIA_PLAYER_APP_ID}")
	print(f"app_id: {ROKU_MEDIA_PLAYER_APP_ID}  (Roku Media Player)")
	print(f"app_present_in_query_apps: {media_player_present}")
	print(f"working_param_casing: {working_casing}")
	print("  (contentId/mediaType is lowercase; contentID/MediaType matches")
	print("   the casing shown in Roku's own ECP doc curl example.)")
	print(f"example_content_url: {media_url}")
	print("rokuecp_control_methods:")
	print("  rokuecp.Roku(host)                      -> async context manager")
	print("  await roku.launch(app_id, params)       -> POST /launch/<app_id>?<params>")
	print("  (raw ECP queries via stdlib here: /query/active-app, /query/media-player)")
	print("  rokuecp also exposes: await roku.update() -> Device with .app and .media")
	print("playback_confirmation: state=\"play\" from /query/media-player, not HTTP 200")
	print("note: confirm a RANGE line appears above; that proves the Roku")
	print("      issued partial-content GETs against a plain stdlib server.")
	print("=== END REQUIRED OUTPUT ===")


#============================================
# Entry point.
#============================================

def main() -> None:
	"""Parse arguments and run the async Roku proof routine."""
	args = parse_args()
	# rokuecp is fully asynchronous; drive it from a single event loop run.
	asyncio.run(run_proof(args.roku_ip, args.mp4_path))


if __name__ == '__main__':
	main()
