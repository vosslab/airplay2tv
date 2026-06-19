"""Local network helpers: routable interface IP and free TCP port selection."""

# Standard Library
import socket


#============================================
def local_ip_for(target: str) -> str:
	"""
	Return the local interface IP the OS would use to reach a target host.

	Opens a UDP socket and calls connect() toward the target. UDP connect
	does not send any packets; it only sets the socket's default peer, which
	makes the kernel pick the outbound interface. Reading getsockname() then
	reveals the LAN-facing source address, not 127.0.0.1, for a LAN target.

	Args:
		target: The destination host (IP address or resolvable name) that the
			advertised media URL must be reachable from.

	Returns:
		The dotted-quad local interface IP chosen to reach the target.
	"""
	# AF_INET + SOCK_DGRAM is a UDP socket; no packets leave on connect().
	udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
	# Port 9 (discard) is arbitrary; connect() only fixes the route, sends nothing.
	udp_socket.connect((target, 9))
	# getsockname() reports the local (source) side the kernel selected.
	local_address = udp_socket.getsockname()[0]
	udp_socket.close()
	return local_address


#============================================
def pick_free_port(start: int = 3500) -> int:
	"""
	Return the first bindable TCP port at or above start.

	Sweeps ports upward from start, attempting a real bind on the loopback
	interface for each candidate. The first port that binds cleanly is free
	and returned. A bounded sweep avoids an unbounded loop when every port in
	the range is taken.

	Args:
		start: The first port number to try. Defaults to 3500.

	Returns:
		The first port at or above start that accepts a TCP bind.

	Raises:
		RuntimeError: When no free port is found within the bounded sweep.
	"""
	# Bound the search so an exhausted range fails loudly rather than looping.
	sweep_size = 200
	for port in range(start, start + sweep_size):
		# A fresh socket per attempt; closing it releases the port immediately.
		probe_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		bound = try_bind(probe_socket, port)
		probe_socket.close()
		if bound:
			return port
	last_port = start + sweep_size - 1
	error_message = ''
	error_message += f'no free TCP port found in range {start}-{last_port}'
	raise RuntimeError(error_message)


#============================================
def try_bind(probe_socket: socket.socket, port: int) -> bool:
	"""
	Attempt to bind a probe socket to a port on the loopback interface.

	Args:
		probe_socket: An open TCP socket to test the bind on.
		port: The candidate port number.

	Returns:
		True when the bind succeeds, False when the port is already in use.
	"""
	# OSError is raised when the port is taken; treat that as "not free".
	try:
		probe_socket.bind(('127.0.0.1', port))
	except OSError:
		return False
	return True
