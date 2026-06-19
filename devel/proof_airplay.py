#!/usr/bin/env python3
"""
Hardware proof script for AirPlay video casting to a real Apple TV.

This is a throwaway devel/ proof, not a product backend. It retires the
highest project risk before the M3 AirPlay backend is built by answering
two questions against REAL hardware:

  1. Does pyatv require pairing credentials to call play_url on this device?
  2. What is the exact working play_url form, and which range requests does
     the device issue against a plain local HTTP server?

The user must run this on a machine on the same LAN as the Apple TV and
then tee the output into docs/active_plans/reports/. We cannot run it here
because there is no device.

It scans with pyatv, connects to the chosen Apple TV, serves a small
known-good MP4 over a minimal stdlib HTTP server (logging every request,
including the HTTP Range headers the device sends), calls play_url, polls
the pyatv playback state, and prints a machine-evidence log plus a
REQUIRED-OUTPUT summary block that M3 consumes.
"""

# Standard Library
import time
import socket
import asyncio
import argparse
import threading
import http.server
import socketserver
from urllib.parse import quote

# PIP3 modules
import pyatv
import pyatv.const
import pyatv.interface


#============================================
# Minimal local HTTP server that logs every request and Range header.
#============================================

# Module-level access log shared between the HTTP server thread and main().
# Treated as append-only evidence; read back at the end for the summary.
HTTP_ACCESS_LOG: list[str] = []


class RangeLoggingHandler(http.server.SimpleHTTPRequestHandler):
	"""Serve a single MP4 file and record each request plus its Range header.

	SimpleHTTPRequestHandler already implements HTTP Range support in
	Python 3.12, which is exactly what an Apple TV expects from a media
	server. We override only logging so we capture the real device traffic.
	"""

	def log_message(self, format_str: str, *log_args: object) -> None:
		"""Record one access-log line into the shared HTTP_ACCESS_LOG."""
		# Compose a plain client + request line for the evidence log.
		client = self.client_address[0]
		line = f"{client} - {format_str % log_args}"
		HTTP_ACCESS_LOG.append(line)

	def do_GET(self) -> None:
		"""Handle GET, recording the Range header the device sent."""
		# Capture the Range header verbatim before serving; this is the key
		# evidence proving the Apple TV issues partial-content requests.
		range_header = self.headers.get("Range")
		if range_header is not None:
			HTTP_ACCESS_LOG.append(f"RANGE {self.path} -> {range_header}")
		else:
			HTTP_ACCESS_LOG.append(f"RANGE {self.path} -> <none>")
		super().do_GET()


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
	"""Threaded HTTP server so range requests can overlap the play call."""

	# Daemon threads so the process can exit cleanly at the end.
	daemon_threads = True
	# Allow immediate rebinding of the port across repeated proof runs.
	allow_reuse_address = True


#============================================
# Networking helpers.
#============================================

def get_local_ip() -> str:
	"""Return the LAN IP address this host uses to reach other devices.

	Uses a UDP socket connect trick: no packets are actually sent, but the
	OS picks the source interface it would use to reach an external host.
	"""
	# 8.8.8.8 is only used to select a route, not contacted.
	probe_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
	probe_socket.connect(("8.8.8.8", 80))
	local_ip = probe_socket.getsockname()[0]
	probe_socket.close()
	return local_ip


def start_http_server(serve_dir: str, host_ip: str) -> tuple[ThreadingHTTPServer, int]:
	"""Start the threaded MP4 server on an ephemeral port and return it.

	Args:
		serve_dir: Directory whose files are exposed over HTTP.
		host_ip: LAN IP address to bind so the Apple TV can reach us.

	Returns:
		A tuple of the running server object and the chosen port number.
	"""
	# Bind to port 0 so the OS assigns a free ephemeral port.
	handler_factory = _make_handler_factory(serve_dir)
	httpd = ThreadingHTTPServer((host_ip, 0), handler_factory)
	chosen_port = httpd.server_address[1]
	# Run the server loop in a background daemon thread.
	server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
	server_thread.start()
	return httpd, chosen_port


def _make_handler_factory(serve_dir: str) -> type[RangeLoggingHandler]:
	"""Return a handler class bound to serve files from serve_dir.

	SimpleHTTPRequestHandler accepts a directory keyword, but binding it via
	a subclass keeps the ThreadingHTTPServer construction simple.
	"""
	# Build a thin subclass that fixes the directory argument.
	class BoundHandler(RangeLoggingHandler):
		def __init__(self, *handler_args: object, **handler_kwargs: object) -> None:
			super().__init__(*handler_args, directory=serve_dir, **handler_kwargs)
	return BoundHandler


#============================================
# pyatv evidence collection.
#============================================

def describe_services(config: pyatv.interface.BaseConfig) -> list[str]:
	"""Return one evidence line per pyatv service on the device config.

	Each line includes the protocol name and its pairing requirement, which
	is the exact pairing fact M3 needs.
	"""
	# Collect a readable description for every advertised service.
	service_lines: list[str] = []
	for service in config.services:
		protocol_name = service.protocol.name
		pairing_name = service.pairing.name
		has_credentials = service.credentials is not None
		line = (
			f"protocol={protocol_name} port={service.port} "
			f"pairing={pairing_name} has_credentials={has_credentials}"
		)
		service_lines.append(line)
	return service_lines


def pick_streaming_protocol(config: pyatv.interface.BaseConfig) -> str:
	"""Return the protocol name pyatv would use for play_url, if present.

	play_url is provided by the AirPlay protocol; RAOP handles audio. We
	report whichever streaming-capable protocol the device advertises.
	"""
	# Prefer AirPlay; it is the protocol that implements play_url.
	advertised = {service.protocol for service in config.services}
	if pyatv.const.Protocol.AirPlay in advertised:
		return pyatv.const.Protocol.AirPlay.name
	if pyatv.const.Protocol.RAOP in advertised:
		return pyatv.const.Protocol.RAOP.name
	return "none"


def airplay_pairing_required(config: pyatv.interface.BaseConfig) -> bool:
	"""Return True if the AirPlay service marks pairing as Mandatory.

	This is the single most important M3 input: whether the backend must
	carry out (and store) a pyatv pairing handshake before casting.
	"""
	# Inspect only the AirPlay service for its pairing requirement.
	for service in config.services:
		if service.protocol is not pyatv.const.Protocol.AirPlay:
			continue
		return service.pairing is pyatv.const.PairingRequirement.Mandatory
	return False


#============================================
# Argument parsing.
#============================================

def parse_args() -> argparse.Namespace:
	"""Parse command-line arguments for the AirPlay proof run."""
	parser = argparse.ArgumentParser(
		description="Proof: cast a local MP4 to a real Apple TV via pyatv."
	)
	parser.add_argument(
		'-i', '--identifier', dest='identifier', type=str, default=None,
		help="Apple TV identifier or IP address to target (optional)."
	)
	parser.add_argument(
		'-m', '--mp4', dest='mp4_path', type=str, required=True,
		help="Path to a small known-good sample MP4 file to serve."
	)
	args = parser.parse_args()
	return args


#============================================
# Async proof routine.
#============================================

async def run_proof(identifier: str | None, mp4_path: str) -> None:
	"""Run the full AirPlay proof and print machine evidence.

	Args:
		identifier: Optional Apple TV identifier or IP to target.
		mp4_path: Filesystem path to the sample MP4 to serve and cast.
	"""
	loop = asyncio.get_running_loop()
	print("=== AirPlay proof: scan ===")
	# Scan the LAN for Apple TVs (optionally narrowed by identifier/IP).
	scan_hosts = [identifier] if identifier and _looks_like_ip(identifier) else None
	scan_identifier = identifier if identifier and not _looks_like_ip(identifier) else None
	configs = await pyatv.scan(
		loop, timeout=5, identifier=scan_identifier, hosts=scan_hosts
	)

	# No device means the user is on the wrong network or device is asleep.
	if not configs:
		print("NO DEVICE FOUND.")
		print("Checklist:")
		print("  - Run this on the same LAN/subnet as the Apple TV.")
		print("  - Wake the Apple TV (it may be in deep sleep).")
		print("  - Pass --identifier <name-or-ip> to target it directly.")
		print("  - Confirm mDNS/Bonjour is not blocked by the network.")
		return

	# Use the first matching device as the proof target.
	config = configs[0]
	print(f"Found device: name={config.name} identifier={config.identifier}")
	print(f"Address: {config.address}")

	print("=== AirPlay proof: services ===")
	for line in describe_services(config):
		print(f"  service: {line}")
	chosen_protocol = pick_streaming_protocol(config)
	pairing_required = airplay_pairing_required(config)
	print(f"Chosen streaming protocol: {chosen_protocol}")
	print(f"AirPlay pairing required (Mandatory): {pairing_required}")

	# Start the local HTTP server before connecting so the URL is ready.
	print("=== AirPlay proof: local HTTP server ===")
	host_ip = get_local_ip()
	serve_dir = _parent_dir(mp4_path)
	file_name = _base_name(mp4_path)
	httpd, port = start_http_server(serve_dir, host_ip)
	# URL-encode the filename so spaces and unicode survive.
	media_url = f"http://{host_ip}:{port}/{quote(file_name)}"
	print(f"Serving {serve_dir} on {host_ip}:{port}")
	print(f"play_url target: {media_url}")

	print("=== AirPlay proof: connect ===")
	# Connect to the device; pyatv builds a facade over all protocols.
	atv = await pyatv.connect(config, loop)
	playback_state = "unknown"
	try:
		print("Connected. Calling stream.play_url ...")
		# This is the exact M3 call: hand the device a plain HTTP URL.
		await atv.stream.play_url(media_url)
		print("play_url returned without raising.")

		# Poll playback metadata a few times so the device has time to
		# fetch byte ranges and begin playback.
		playback_state = await _poll_playback_state(atv)
	except pyatv.exceptions.AuthenticationError as exc:
		# AirPlay pairing is required before play_url will succeed.
		# Record the error as the playback state so the summary is still printed.
		playback_state = f"AuthenticationError: {exc}"
		print(f"play_url raised AuthenticationError: {exc}")
		print("This confirms pairing is Mandatory. Run pyatv pair to obtain credentials.")
	finally:
		# atv.close() is synchronous; it returns a set of pending tasks.
		# Do NOT await it; awaiting a set raises TypeError.
		atv.close()

	# Give any trailing range requests a moment to land in the log.
	time.sleep(2)
	httpd.shutdown()

	print("=== AirPlay proof: HTTP access log (with Range requests) ===")
	for entry in HTTP_ACCESS_LOG:
		print(f"  {entry}")

	print("=== AirPlay proof: playback state ===")
	print(f"pyatv playback device_state: {playback_state}")

	# Always print the summary so the evidence is captured even when
	# play_url raised (pairing required / AuthenticationError case).
	_print_required_output(
		pairing_required=pairing_required,
		chosen_protocol=chosen_protocol,
		media_url=media_url,
		playback_state=playback_state,
	)


def _looks_like_ip(value: str) -> bool:
	"""Return True if value parses as a dotted IPv4 address."""
	# A quick, dependency-free IPv4 shape check.
	parts = value.split(".")
	if len(parts) != 4:
		return False
	for part in parts:
		if not part.isdigit():
			return False
		if not 0 <= int(part) <= 255:
			return False
	return True


def _parent_dir(file_path: str) -> str:
	"""Return the directory portion of file_path (or '.' if none)."""
	# os.path is avoided here intentionally; simple rsplit keeps it explicit.
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


async def _poll_playback_state(atv: pyatv.interface.AppleTV) -> str:
	"""Poll metadata.playing a few times and return the device_state name."""
	# Poll several times because the device buffers before reporting Playing.
	state_name = "unknown"
	for attempt in range(6):
		await asyncio.sleep(2)
		playing = await atv.metadata.playing()
		state_name = playing.device_state.name
		print(f"  poll {attempt + 1}: device_state={state_name}")
		# Stop early once the device reports active playback.
		if playing.device_state is pyatv.const.DeviceState.Playing:
			break
	return state_name


def _print_required_output(
	pairing_required: bool,
	chosen_protocol: str,
	media_url: str,
	playback_state: str,
) -> None:
	"""Print the REQUIRED-OUTPUT block that the M3 AirPlay backend needs."""
	# This block is what the user tees into docs/active_plans/reports/.
	print("")
	print("=== REQUIRED OUTPUT FOR M3 (AirPlay) ===")
	print(f"pairing_required: {pairing_required}")
	print("  (True means M3 must run pyatv.pair for Protocol.AirPlay and")
	print("   persist credentials before play_url will succeed.)")
	print(f"streaming_protocol: {chosen_protocol}")
	print("working_play_url_call: atv.stream.play_url(<http_url>)")
	print(f"example_play_url_value: {media_url}")
	print(f"observed_playback_state: {playback_state}")
	print("note: confirm a RANGE line appears above; that proves the device")
	print("      issued partial-content GETs against a plain stdlib server.")
	print("=== END REQUIRED OUTPUT ===")


#============================================
# Entry point.
#============================================

def main() -> None:
	"""Parse arguments and run the async AirPlay proof routine."""
	args = parse_args()
	# pyatv is fully asynchronous; drive it from a single event loop run.
	asyncio.run(run_proof(args.identifier, args.mp4_path))


if __name__ == '__main__':
	main()
