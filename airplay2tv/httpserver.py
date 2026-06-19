"""Threaded range-capable HTTP server that serves one media file.

The server binds to a chosen interface (bind_host) but advertises a URL built
from a separate routable address (advertised_host), so a TV can reach the file
even when the server binds to all interfaces. The handler supports the requests
a seeking TV issues: HEAD, full GET, byte-range GET (single open or closed
range), and out-of-range requests answered with 416.
"""

# Standard Library
import os
import http.server
import threading
import mimetypes

# local repo modules
import airplay2tv.netutil


#============================================
def guess_content_type(path: str) -> str:
	"""
	Return a best-effort MIME type for a media path.

	Args:
		path: Filesystem path to the media file.

	Returns:
		The guessed MIME type, or a generic binary type when unknown.
	"""
	# mimetypes returns (type, encoding); a None type means "could not guess".
	guessed_type = mimetypes.guess_type(path)[0]
	if guessed_type is None:
		return 'application/octet-stream'
	return guessed_type


#============================================
def parse_range_header(range_value: str, file_size: int) -> tuple[int, int] | None:
	"""
	Parse a single HTTP byte-range header against a known file size.

	Supports a closed range (bytes=start-end), an open-ended range
	(bytes=start-), and a suffix range (bytes=-suffix_length). Returns the
	inclusive (start, end) byte offsets clamped to the file, or None when the
	header is malformed or the requested range cannot be satisfied.

	Args:
		range_value: The raw Range header value, for example "bytes=100-200".
		file_size: The total size of the file in bytes.

	Returns:
		An inclusive (start, end) byte pair, or None for an unsatisfiable or
		malformed range.
	"""
	# Only the "bytes=" unit is supported; anything else is malformed here.
	if not range_value.startswith('bytes='):
		return None
	spec = range_value[len('bytes='):]
	# A multi-range request contains commas.  This server intentionally returns
	# 416 (via a None result) rather than the whole entity; the plan scope covers
	# single-range only, and no real client has been observed sending multi-range.
	if ',' in spec:
		return None
	if '-' not in spec:
		return None
	start_text, end_text = spec.split('-', 1)
	# Suffix form bytes=-N: the last N bytes of the file.
	if start_text == '':
		if end_text == '':
			return None
		suffix_length = int(end_text)
		if suffix_length <= 0:
			return None
		start = max(0, file_size - suffix_length)
		end = file_size - 1
		return (start, end)
	start = int(start_text)
	# Open-ended form bytes=N-: from N to the end of the file.
	if end_text == '':
		end = file_size - 1
	else:
		end = int(end_text)
	# Clamp a closed end that runs past the final byte.
	if end > file_size - 1:
		end = file_size - 1
	# A start at or beyond EOF, or an inverted range, is unsatisfiable.
	if start > end or start >= file_size:
		return None
	return (start, end)


#============================================
def make_handler(path: str) -> type:
	"""
	Build a request handler class bound to a single media file path.

	The returned class serves only that one file for any request path, with
	full range support and a quiet access log routed to nowhere by default.

	Args:
		path: Filesystem path to the media file the server exposes.

	Returns:
		A BaseHTTPRequestHandler subclass serving the given file.
	"""
	# Chunk size for streamed body writes; keeps memory flat for large files.
	chunk_size = 64 * 1024

	#--------------------------------------------
	class SingleFileHandler(http.server.BaseHTTPRequestHandler):
		"""Serves one fixed media file with HEAD/GET and byte-range support."""

		# HTTP/1.1 so clients may keep the connection alive between ranges.
		protocol_version = 'HTTP/1.1'

		#--------------------------------------------
		def log_message(self, format_string: str, *args: object) -> None:
			"""Silence the default stderr access log."""
			return

		#--------------------------------------------
		def send_common_headers(self, content_type: str) -> None:
			"""Send headers shared by HEAD and GET responses."""
			self.send_header('Content-Type', content_type)
			# Advertise range support so seeking clients issue Range requests.
			self.send_header('Accept-Ranges', 'bytes')

		#--------------------------------------------
		def do_HEAD(self) -> None:
			"""Answer a HEAD request with metadata and no body."""
			file_size = os.path.getsize(path)
			content_type = guess_content_type(path)
			self.send_response(200)
			self.send_common_headers(content_type)
			self.send_header('Content-Length', str(file_size))
			self.end_headers()

		#--------------------------------------------
		def do_GET(self) -> None:
			"""Answer a GET request, honoring an optional Range header."""
			file_size = os.path.getsize(path)
			content_type = guess_content_type(path)
			range_value = self.headers.get('Range')
			if range_value is None:
				self.send_full(file_size, content_type)
				return
			byte_range = parse_range_header(range_value, file_size)
			# A None parse means the range cannot be satisfied: answer 416.
			if byte_range is None:
				self.send_unsatisfiable(file_size)
				return
			self.send_partial(byte_range, file_size, content_type)

		#--------------------------------------------
		def send_full(self, file_size: int, content_type: str) -> None:
			"""Send the whole file with a 200 status."""
			self.send_response(200)
			self.send_common_headers(content_type)
			self.send_header('Content-Length', str(file_size))
			self.end_headers()
			self.stream_file(0, file_size - 1)

		#--------------------------------------------
		def send_partial(self, byte_range: tuple[int, int], file_size: int,
				content_type: str) -> None:
			"""Send a byte range with a 206 status and Content-Range."""
			start, end = byte_range
			length = end - start + 1
			self.send_response(206)
			self.send_common_headers(content_type)
			self.send_header('Content-Length', str(length))
			content_range = f'bytes {start}-{end}/{file_size}'
			self.send_header('Content-Range', content_range)
			self.end_headers()
			self.stream_file(start, end)

		#--------------------------------------------
		def send_unsatisfiable(self, file_size: int) -> None:
			"""Send a 416 with the valid Content-Range size hint."""
			self.send_response(416)
			self.send_header('Content-Range', f'bytes */{file_size}')
			self.send_header('Content-Length', '0')
			self.end_headers()

		#--------------------------------------------
		def stream_file(self, start: int, end: int) -> None:
			"""Write the inclusive [start, end] byte span to the client."""
			# rb so we read raw bytes; seek to the first requested offset.
			with open(path, 'rb') as media_file:
				media_file.seek(start)
				remaining = end - start + 1
				while remaining > 0:
					read_size = min(chunk_size, remaining)
					data = media_file.read(read_size)
					# A short read means EOF; stop rather than spin.
					if not data:
						break
					self.wfile.write(data)
					remaining -= len(data)

	return SingleFileHandler


#============================================
def serve(path: str, bind_host: str, advertised_host: str
		) -> tuple[str, http.server.ThreadingHTTPServer, threading.Thread]:
	"""
	Start a threaded HTTP server that serves a single media file.

	The server binds to bind_host on an auto-selected free port and serves the
	file with full range support on its own daemon thread. The returned URL is
	built from advertised_host (the routable address a TV can reach) and the
	chosen port, independent of the bind host.

	Args:
		path: Filesystem path to the media file to serve.
		bind_host: The interface address to bind to (for example "0.0.0.0").
		advertised_host: The routable address used to build the returned URL.

	Returns:
		A tuple of (url, server, thread). Call shutdown(server, thread) to stop
		the server cleanly and join its thread.
	"""
	port = airplay2tv.netutil.pick_free_port()
	handler_class = make_handler(path)
	server = http.server.ThreadingHTTPServer((bind_host, port), handler_class)
	# The OS may assign a different port if 0 was bound; read the real one back.
	bound_port = server.server_address[1]
	# Name the served file in the URL path so logs and clients show it.
	file_name = os.path.basename(path)
	url = f'http://{advertised_host}:{bound_port}/{file_name}'
	# Daemon thread so an unjoined server never blocks interpreter exit.
	thread = threading.Thread(target=server.serve_forever, daemon=True)
	thread.start()
	return (url, server, thread)


#============================================
def shutdown(server: http.server.ThreadingHTTPServer,
		thread: threading.Thread) -> None:
	"""
	Stop a running server and join its serving thread.

	Args:
		server: The server returned by serve().
		thread: The serving thread returned by serve().
	"""
	# shutdown() tells serve_forever to return; close releases the socket.
	server.shutdown()
	server.server_close()
	thread.join()
