"""Unit tests for airplay2tv/netutil.py local IP and port utilities."""

# Standard Library
import socket

# local repo modules
import airplay2tv.netutil


#============================================
def is_ipv4(text: str) -> bool:
	"""Return True when text parses as a dotted-quad IPv4 address."""
	# inet_aton raises OSError on a non-IPv4 string; treat that as False.
	try:
		socket.inet_aton(text)
	except OSError:
		return False
	return True


#============================================
def test_local_ip_for_target_returns_ipv4() -> None:
	# A documentation/test-net target the kernel can route without sending.
	chosen = airplay2tv.netutil.local_ip_for('192.0.2.1')
	assert is_ipv4(chosen)


#============================================
def test_local_ip_for_public_target_not_loopback() -> None:
	# Routing toward a public IP selects the real outbound interface,
	# which must not be the loopback address.
	chosen = airplay2tv.netutil.local_ip_for('8.8.8.8')
	assert chosen != '127.0.0.1'


#============================================
def test_pick_free_port_returns_bindable_port() -> None:
	port = airplay2tv.netutil.pick_free_port(start=3500)
	# The returned port must itself accept a fresh bind right now.
	confirm_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	bound = airplay2tv.netutil.try_bind(confirm_socket, port)
	confirm_socket.close()
	assert bound is True


#============================================
def test_pick_free_port_skips_occupied_start() -> None:
	# Hold a port so the sweep must skip past it to a higher free port.
	holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	holder.bind(('127.0.0.1', 0))
	held_port = holder.getsockname()[1]
	chosen = airplay2tv.netutil.pick_free_port(start=held_port)
	holder.close()
	# The held port is taken, so the chosen port must differ and be higher.
	assert chosen > held_port
