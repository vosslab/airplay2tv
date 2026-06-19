"""Async SSDP discovery for Roku devices via M-SEARCH (clean-room from the ECP protocol).

Roku devices advertise their External Control Protocol (ECP) service over SSDP.
A program sends a multicast M-SEARCH query to 239.255.255.250:1900 with
ST roku:ecp; each responding device returns an HTTP 200 datagram carrying a
Location header (the ECP base URL, e.g. http://192.168.1.134:8060/) and a USN
header (the device serial as uuid:roku:ecp:<serial>). UPnP header names are
case-insensitive.

This module exposes a pure, network-free parser (parse_response) so the
tolerant header handling can be unit tested with raw bytes, plus an async
discover() built on asyncio.DatagramProtocol that drives a real M-SEARCH and
returns normalized RokuResponder records alongside DiscoveryStats.
"""

# Standard Library
import socket
import asyncio
import dataclasses
import urllib.parse


# SSDP multicast group address and port (industry IETF standard).
SSDP_MULTICAST_ADDR = "239.255.255.250"
SSDP_MULTICAST_PORT = 1900

# Search target that selects Roku ECP responders only.
ROKU_SEARCH_TARGET = "roku:ecp"

# Multicast TTL of 2 keeps the probe on the local network while crossing a
# single router hop, matching common SSDP client behavior.
SSDP_MULTICAST_TTL = 2


#============================================
@dataclasses.dataclass
class RokuResponder:
	"""One normalized Roku ECP responder parsed from an SSDP 200 reply.

	Attributes:
		location: Full ECP base URL from the Location header.
		ip: Host extracted from the Location URL (what the control client needs).
		port: Port from the Location URL, defaulting to the ECP port 8060.
		usn: Unique Service Name (uuid:roku:ecp:<serial>); the dedupe key.
		st: Search Target echoed by the device (expected roku:ecp).
		server: Server header value, or None when absent.
		cache_control: Cache-Control header value, or None when absent.
		headers: Raw header dict with original (case-preserved) header names.
	"""
	location: str
	ip: str
	port: int
	usn: str
	st: str
	server: str | None
	cache_control: str | None
	headers: dict[str, str]


#============================================
@dataclasses.dataclass
class DiscoveryStats:
	"""Counters describing one discover() run.

	Attributes:
		probes_sent: Number of M-SEARCH datagrams transmitted.
		valid_responses: Count of unique, accepted Roku responders.
		duplicates: Count of accepted replies whose USN was already seen.
		malformed: Count of replies that failed parsing or were not roku:ecp.
		timed_out: Wall-clock listen duration in seconds for this run.
	"""
	probes_sent: int = 0
	valid_responses: int = 0
	duplicates: int = 0
	malformed: int = 0
	timed_out: float = 0.0


#============================================
def _split_status_and_headers(text: str) -> tuple[str, dict[str, str]]:
	"""Split a raw SSDP reply into its status line and a header dict.

	Header names are kept verbatim as dict keys so callers can inspect the
	original casing; lookups are done case-insensitively via _find_header.
	"""
	# Normalize line endings, then separate the start line from header lines.
	normalized = text.replace("\r\n", "\n").replace("\r", "\n")
	lines = normalized.split("\n")
	status_line = lines[0].strip()
	headers: dict[str, str] = {}
	# Walk header lines until the first blank line that ends the header block.
	for line in lines[1:]:
		if line.strip() == "":
			break
		if ":" not in line:
			# A non-blank header line without a colon is malformed; skip it.
			continue
		name, value = line.split(":", 1)
		headers[name.strip()] = value.strip()
	result = (status_line, headers)
	return result


#============================================
def _find_header(headers: dict[str, str], target_name: str) -> str | None:
	"""Return a header value by case-insensitive name, or None when absent.

	UPnP header names are case-insensitive, so Location, LOCATION, and location
	must all match the same logical header.
	"""
	target_lower = target_name.lower()
	for name, value in headers.items():
		if name.lower() == target_lower:
			return value
	return None


#============================================
def _is_ok_status(status_line: str) -> bool:
	"""Return True when the SSDP start line reports an HTTP 200 status."""
	# A valid reply start line looks like: HTTP/1.1 200 OK
	parts = status_line.split()
	is_ok = len(parts) >= 2 and parts[0].upper().startswith("HTTP/") and parts[1] == "200"
	return is_ok


#============================================
def parse_response(raw: bytes | str) -> RokuResponder | None:
	"""Parse one raw SSDP reply into a RokuResponder, or None when unusable.

	This is the pure, network-free core of discovery. It tolerates:
	  - case-insensitive header names (UPnP requirement),
	  - a missing Cache-Control header (stored as None),
	  - a missing Server header (stored as None).
	It rejects (returns None) for:
	  - non-200 or unparseable status lines,
	  - replies missing a Location or USN header,
	  - replies whose ST is not roku:ecp.

	Args:
		raw: The datagram payload as bytes or a decoded string.

	Returns:
		A RokuResponder on success, otherwise None.
	"""
	# Decode bytes leniently; SSDP replies are ASCII HTTP headers.
	if isinstance(raw, bytes):
		text = raw.decode("utf-8", errors="replace")
	else:
		text = raw

	status_line, headers = _split_status_and_headers(text)

	# Reject anything that is not a clean HTTP 200 reply.
	if not _is_ok_status(status_line):
		return None

	# Location and USN are required; without either the reply is unusable.
	location = _find_header(headers, "Location")
	usn = _find_header(headers, "USN")
	if location is None or usn is None:
		return None

	# Only accept Roku ECP responders; reject other SSDP services.
	st = _find_header(headers, "ST")
	if st is None or st.strip().lower() != ROKU_SEARCH_TARGET:
		return None

	# Extract ip and port from the Location URL; default port to ECP 8060.
	parsed_url = urllib.parse.urlparse(location.strip())
	ip = parsed_url.hostname
	if ip is None:
		# A Location with no parseable host is malformed.
		return None
	port = parsed_url.port if parsed_url.port is not None else 8060

	# Cache-Control and Server are optional metadata.
	cache_control = _find_header(headers, "Cache-Control")
	server = _find_header(headers, "Server")

	responder = RokuResponder(
		location=location.strip(),
		ip=ip,
		port=port,
		usn=usn.strip(),
		st=st.strip(),
		server=server,
		cache_control=cache_control,
		headers=headers,
	)
	return responder


#============================================
class _RokuSSDPProtocol(asyncio.DatagramProtocol):
	"""Datagram protocol that collects and normalizes Roku SSDP replies.

	Parsing happens per datagram so the listen window is never blocked. Results
	are deduplicated by USN; duplicate and malformed counts are tracked for the
	caller's DiscoveryStats.
	"""

	#--------------------------------------------
	def __init__(self) -> None:
		# Map of USN -> RokuResponder for the first sighting of each device.
		self.responders: dict[str, RokuResponder] = {}
		self.duplicates = 0
		self.malformed = 0
		self.transport: asyncio.DatagramTransport | None = None

	#--------------------------------------------
	def connection_made(self, transport: asyncio.BaseTransport) -> None:
		# Store the transport so discover() can send the probe and close it.
		self.transport = transport  # type: ignore[assignment]

	#--------------------------------------------
	def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
		# Parse each reply; a None result means malformed or non-Roku.
		responder = parse_response(data)
		if responder is None:
			self.malformed += 1
			return
		# Dedupe by USN: keep the first sighting, count later ones as duplicates.
		if responder.usn in self.responders:
			self.duplicates += 1
			return
		self.responders[responder.usn] = responder


#============================================
def _build_msearch_message() -> bytes:
	"""Build the SSDP M-SEARCH request datagram for Roku ECP discovery."""
	# Assemble the request line and headers with CRLF separators per HTTP/SSDP.
	host = f"{SSDP_MULTICAST_ADDR}:{SSDP_MULTICAST_PORT}"
	lines = [
		"M-SEARCH * HTTP/1.1",
		f"HOST: {host}",
		'MAN: "ssdp:discover"',
		f"ST: {ROKU_SEARCH_TARGET}",
		"MX: 3",
		"",
		"",
	]
	message = "\r\n".join(lines)
	encoded = message.encode("ascii")
	return encoded


#============================================
def _make_multicast_socket() -> socket.socket:
	"""Create a non-blocking UDP socket configured for SSDP multicast."""
	sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
	# Allow rapid reuse so repeated discovery runs do not fail to bind.
	sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
	# Limit multicast reach to the local network plus one router hop.
	sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, SSDP_MULTICAST_TTL)
	sock.setblocking(False)
	return sock


#============================================
async def discover(timeout: float = 3) -> tuple[list[RokuResponder], DiscoveryStats]:
	"""Discover Roku ECP devices on the local network via SSDP M-SEARCH.

	Sends one multicast M-SEARCH probe, listens for timeout seconds, parses and
	deduplicates replies, and always closes the datagram transport before
	returning.

	Args:
		timeout: Seconds to listen for responses after sending the probe.

	Returns:
		A tuple of (responders, stats): the unique RokuResponder list and the
		DiscoveryStats counters for this run.
	"""
	loop = asyncio.get_running_loop()
	sock = _make_multicast_socket()

	# Bind the protocol to the socket; create_datagram_endpoint owns the socket.
	transport, protocol = await loop.create_datagram_endpoint(
		_RokuSSDPProtocol,
		sock=sock,
	)

	stats = DiscoveryStats()
	stats.timed_out = float(timeout)

	# The transport is always closed, even if sending or sleeping is interrupted.
	try:
		message = _build_msearch_message()
		transport.sendto(message, (SSDP_MULTICAST_ADDR, SSDP_MULTICAST_PORT))
		stats.probes_sent = 1
		# Passively collect replies for the listen window.
		await asyncio.sleep(timeout)
	finally:
		transport.close()

	# Summarize results into the returned stats.
	stats.duplicates = protocol.duplicates
	stats.malformed = protocol.malformed
	responders = list(protocol.responders.values())
	stats.valid_responses = len(responders)
	result = (responders, stats)
	return result
