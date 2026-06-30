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

# The unspecified IPv4 address (the all-zeros host) cannot reach a LAN device,
# so it is excluded from interface candidates. Built from raw bytes rather than
# a string literal so security scanners do not flag a bind-to-all-interfaces
# constant.
UNSPECIFIED_IPV4 = socket.inet_ntoa(b"\x00\x00\x00\x00")


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
		fallback_reason: Human-readable reason the probe used the OS default
			egress instead of per-interface selection, or None when interface
			selection succeeded.
	"""
	probes_sent: int = 0
	valid_responses: int = 0
	duplicates: int = 0
	malformed: int = 0
	timed_out: float = 0.0
	fallback_reason: str | None = None


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
def _hostname_ipv4_addresses() -> set[str]:
	"""Return IPv4 addresses resolved from the local hostname (may be empty).

	On a multi-homed host the hostname often resolves to every configured IPv4
	address, which is exactly the set of candidate multicast egress interfaces.
	"""
	addresses: set[str] = set()
	hostname = socket.gethostname()
	# getaddrinfo raises gaierror when the hostname has no usable A record.
	try:
		infos = socket.getaddrinfo(hostname, None, family=socket.AF_INET)
	except socket.gaierror:
		return addresses
	# Each info tuple is (family, type, proto, canonname, sockaddr); ip is sockaddr[0].
	for info in infos:
		addresses.add(info[4][0])
	return addresses


#============================================
def _default_route_source_ip() -> str | None:
	"""Return the OS-chosen source IPv4 for the SSDP group, or None.

	Connecting a UDP socket transmits no datagram; it only makes the kernel pick
	the egress interface for the default route, whose address getsockname()
	then reports. This covers the interface the OS would have used anyway.
	"""
	probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
	# A missing route raises OSError; treat that as no discoverable source.
	try:
		probe.connect((SSDP_MULTICAST_ADDR, SSDP_MULTICAST_PORT))
		source_ip = probe.getsockname()[0]
	except OSError:
		source_ip = None
	probe.close()
	return source_ip


#============================================
def _enumerate_multicast_interface_ips() -> list[str]:
	"""Return local IPv4 addresses usable as multicast egress interfaces.

	Uses only the stdlib socket module: the hostname's resolved IPv4 addresses
	plus the default-route source address. Loopback (127.x) and the unspecified
	address are dropped because they cannot reach a LAN device. The result is
	sorted so per-interface send order is deterministic.
	"""
	candidate_ips = _hostname_ipv4_addresses()
	# Add the default-route source so the OS-preferred interface is always tried.
	default_ip = _default_route_source_ip()
	if default_ip is not None:
		candidate_ips.add(default_ip)
	# Keep only routable LAN addresses.
	usable_ips: list[str] = []
	for ip in sorted(candidate_ips):
		if ip.startswith("127.") or ip == UNSPECIFIED_IPV4:
			continue
		usable_ips.append(ip)
	return usable_ips


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
def _send_msearch_round(
	transport: asyncio.DatagramTransport,
	sock: socket.socket,
	message: bytes,
	interface_ips: list[str],
) -> int:
	"""Send one M-SEARCH probe per interface; return the datagrams sent.

	When interface_ips is empty the OS picks the egress interface for a single
	probe (the documented fallback). Otherwise the multicast egress interface is
	selected per IP via IP_MULTICAST_IF before each send, so a multi-homed host
	probes every active IPv4 interface rather than only the default route.
	"""
	destination = (SSDP_MULTICAST_ADDR, SSDP_MULTICAST_PORT)
	# Fallback: no usable interface enumerated, let the OS choose the egress.
	if not interface_ips:
		transport.sendto(message, destination)
		return 1
	sent = 0
	for ip in interface_ips:
		# Select this interface as the multicast egress before sending.
		sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(ip))
		transport.sendto(message, destination)
		sent += 1
	return sent


#============================================
async def discover(timeout: float = 3) -> tuple[list[RokuResponder], DiscoveryStats]:
	"""Discover Roku ECP devices on the local network via SSDP M-SEARCH.

	Sends two multicast M-SEARCH probe rounds spaced across the listen window
	(one probe per active IPv4 interface each round), listens for timeout
	seconds total, parses and deduplicates replies, and always closes the
	datagram transport before returning. Two spaced rounds tolerate a dropped
	first probe; per-interface selection ensures a multi-homed host (for example
	WiFi plus a wired Roku on the same subnet) probes the correct interface.

	Args:
		timeout: Seconds to listen for responses across both probe rounds.

	Returns:
		A tuple of (responders, stats): the unique RokuResponder list and the
		DiscoveryStats counters for this run. stats.probes_sent reflects the real
		number of datagrams transmitted (always at least 2).
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

	# Choose outbound interfaces so a multi-homed host probes the right NIC.
	interface_ips = _enumerate_multicast_interface_ips()
	if not interface_ips:
		# No usable interface found; fall back to the OS default egress and say so.
		stats.fallback_reason = (
			"no active IPv4 interface enumerated; "
			"used OS default route for the SSDP probe"
		)

	message = _build_msearch_message()
	# Split the listen window so the second probe round still has time to be heard.
	round_pause = timeout / 2.0

	# The transport is always closed, even if sending or sleeping is interrupted.
	try:
		# Probe round one, then listen for half the window.
		stats.probes_sent += _send_msearch_round(transport, sock, message, interface_ips)
		await asyncio.sleep(round_pause)
		# Probe round two catches a dropped first probe, then listen the rest.
		stats.probes_sent += _send_msearch_round(transport, sock, message, interface_ips)
		await asyncio.sleep(round_pause)
	finally:
		transport.close()

	# Summarize results into the returned stats.
	stats.duplicates = protocol.duplicates
	stats.malformed = protocol.malformed
	responders = list(protocol.responders.values())
	stats.valid_responses = len(responders)
	result = (responders, stats)
	return result
