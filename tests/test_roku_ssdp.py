"""Unit tests for the network-free Roku SSDP parser and dedupe behavior."""

# Standard Library
import socket

# PIP3 modules
import pytest

# local repo modules
import airplay2tv.discovery.roku_ssdp as roku_ssdp


#============================================
def make_reply(
	*,
	status: str = "HTTP/1.1 200 OK",
	location: str | None = "http://192.168.1.134:8060/",
	usn: str | None = "uuid:roku:ecp:P0A070000007",
	st: str | None = "roku:ecp",
	cache_control: str | None = "max-age=3600",
	server: str | None = "Roku UPnP/1.0 MiniUPnPd/1.4",
	location_name: str = "Location",
) -> bytes:
	"""Build a raw SSDP reply with CRLF line endings for parser tests.

	Headers set to None are omitted so each tolerated/rejected case can be
	expressed by dropping a single header.
	"""
	lines = [status]
	if cache_control is not None:
		lines.append(f"Cache-Control: {cache_control}")
	if st is not None:
		lines.append(f"ST: {st}")
	if location is not None:
		lines.append(f"{location_name}: {location}")
	if usn is not None:
		lines.append(f"USN: {usn}")
	if server is not None:
		lines.append(f"Server: {server}")
	lines.append("")
	lines.append("")
	raw = "\r\n".join(lines).encode("ascii")
	return raw


#============================================
def test_valid_response_extracts_ip_and_port() -> None:
	responder = roku_ssdp.parse_response(make_reply())
	assert responder is not None
	assert responder.ip == "192.168.1.134"
	assert responder.port == 8060


#============================================
def test_usn_carried_through() -> None:
	responder = roku_ssdp.parse_response(make_reply())
	assert responder is not None
	assert responder.usn == "uuid:roku:ecp:P0A070000007"


#============================================
def test_header_names_are_case_insensitive() -> None:
	# UPnP allows any casing; LOCATION must still populate the location field.
	responder = roku_ssdp.parse_response(make_reply(location_name="LOCATION"))
	assert responder is not None
	assert responder.location == "http://192.168.1.134:8060/"


#============================================
def test_missing_cache_control_is_tolerated() -> None:
	responder = roku_ssdp.parse_response(make_reply(cache_control=None))
	assert responder is not None
	assert responder.cache_control is None


#============================================
def test_malformed_reply_is_rejected() -> None:
	# A reply with no recognizable status line or headers is not a responder.
	responder = roku_ssdp.parse_response(b"this is not an http reply at all")
	assert responder is None


#============================================
def test_non_roku_search_target_is_rejected() -> None:
	# Another SSDP service (e.g. a generic UPnP root device) must be skipped.
	responder = roku_ssdp.parse_response(make_reply(st="upnp:rootdevice"))
	assert responder is None


#============================================
def test_missing_location_is_rejected() -> None:
	responder = roku_ssdp.parse_response(make_reply(location=None))
	assert responder is None


#============================================
def test_non_200_status_is_rejected() -> None:
	responder = roku_ssdp.parse_response(make_reply(status="HTTP/1.1 404 Not Found"))
	assert responder is None


#============================================
def test_default_port_when_location_has_no_port() -> None:
	# The ECP default port 8060 is used when the Location URL omits a port.
	responder = roku_ssdp.parse_response(make_reply(location="http://10.0.0.5/"))
	assert responder is not None
	assert responder.port == 8060


#============================================
def test_duplicate_usn_is_deduped_by_protocol() -> None:
	# Two replies sharing one USN yield a single responder and one duplicate.
	protocol = roku_ssdp._RokuSSDPProtocol()
	addr = ("192.168.1.134", 1900)
	protocol.datagram_received(make_reply(), addr)
	protocol.datagram_received(make_reply(), addr)
	assert len(protocol.responders) == 1
	assert protocol.duplicates == 1


#============================================
def test_distinct_usns_are_kept_separately() -> None:
	protocol = roku_ssdp._RokuSSDPProtocol()
	addr = ("192.168.1.134", 1900)
	protocol.datagram_received(make_reply(usn="uuid:roku:ecp:AAA"), addr)
	protocol.datagram_received(make_reply(usn="uuid:roku:ecp:BBB"), addr)
	assert len(protocol.responders) == 2
	assert protocol.duplicates == 0


#============================================
def test_protocol_counts_malformed_replies() -> None:
	protocol = roku_ssdp._RokuSSDPProtocol()
	addr = ("192.168.1.99", 1900)
	protocol.datagram_received(b"garbage payload", addr)
	assert protocol.malformed == 1
	assert len(protocol.responders) == 0


#============================================
def test_msearch_message_targets_roku_ecp() -> None:
	# The probe must address the SSDP group and request the roku:ecp target.
	message = roku_ssdp._build_msearch_message()
	text = message.decode("ascii")
	assert "ST: roku:ecp" in text
	assert "239.255.255.250:1900" in text


#============================================
def test_multicast_socket_is_udp_and_nonblocking() -> None:
	sock = roku_ssdp._make_multicast_socket()
	assert sock.type == socket.SOCK_DGRAM
	assert sock.getblocking() is False
	sock.close()


#============================================
def test_enumerate_drops_loopback_and_unspecified(monkeypatch: pytest.MonkeyPatch) -> None:
	# Loopback and 0.0.0.0 cannot reach a LAN device, so they are filtered out.
	monkeypatch.setattr(
		roku_ssdp,
		"_hostname_ipv4_addresses",
		lambda: {"127.0.0.1", "192.168.1.50"},
	)
	monkeypatch.setattr(
		roku_ssdp, "_default_route_source_ip", lambda: roku_ssdp.UNSPECIFIED_IPV4
	)
	ips = roku_ssdp._enumerate_multicast_interface_ips()
	assert "127.0.0.1" not in ips
	assert roku_ssdp.UNSPECIFIED_IPV4 not in ips
	assert "192.168.1.50" in ips


#============================================
def test_send_round_selects_each_interface() -> None:
	# Each interface IP must drive one IP_MULTICAST_IF select plus one send.
	transport = _FakeTransport()
	sock = _FakeSocket()
	message = roku_ssdp._build_msearch_message()
	sent = roku_ssdp._send_msearch_round(transport, sock, message, ["192.168.1.50", "10.0.0.9"])
	assert sent == 2
	assert len(sock.multicast_if_calls) == 2
	assert len(transport.sent) == 2


#============================================
def test_send_round_falls_back_to_default_egress() -> None:
	# With no interfaces, one probe is sent and no interface is selected.
	transport = _FakeTransport()
	sock = _FakeSocket()
	message = roku_ssdp._build_msearch_message()
	sent = roku_ssdp._send_msearch_round(transport, sock, message, [])
	assert sent == 1
	assert len(sock.multicast_if_calls) == 0
	assert len(transport.sent) == 1


#============================================
class _FakeTransport:
	"""Minimal datagram transport that records sends and closure."""

	def __init__(self) -> None:
		self.sent: list[tuple[bytes, tuple[str, int]]] = []
		self.closed = False

	def sendto(self, data: bytes, addr: tuple[str, int]) -> None:
		self.sent.append((data, addr))

	def close(self) -> None:
		self.closed = True


#============================================
class _FakeSocket:
	"""Minimal socket recording IP_MULTICAST_IF selections for assertions."""

	def __init__(self) -> None:
		self.multicast_if_calls: list[bytes] = []

	def setsockopt(self, level: int, optname: int, value: bytes) -> None:
		# Record only the multicast egress selections; ignore other options.
		if optname == socket.IP_MULTICAST_IF:
			self.multicast_if_calls.append(value)

	def close(self) -> None:
		pass


