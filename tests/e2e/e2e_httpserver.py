#!/usr/bin/env python3
"""E2E checks for airplay2tv.httpserver: real server bind + real HTTP round-trips.

Runs a ThreadingHTTPServer on loopback, issues actual HTTP GET/HEAD/Range
requests, and verifies status codes, headers, and body slices.  Exits 0 when
all checks pass and non-zero when any check fails.
"""

# Standard Library
import collections.abc
import http.client
import shutil
import subprocess
import sys
import tempfile
import traceback

# Locate the repo root and put it on sys.path so the airplay2tv package
# imports cleanly when invoked directly as python3 tests/e2e/e2e_httpserver.py.
REPO_ROOT = subprocess.run(
	['git', 'rev-parse', '--show-toplevel'],
	capture_output=True, text=True, check=True,
).stdout.strip()
if REPO_ROOT not in sys.path:
	sys.path.insert(0, REPO_ROOT)

# local repo modules
import airplay2tv.httpserver

# Fixed body so range offsets and lengths are exact and deterministic.
BODY = bytes(range(256)) * 8
FILE_NAME = 'sample.bin'


#============================================
def parse_url_host_port(url: str) -> tuple[str, int]:
	"""Extract (host, port) from an http://host:port/... URL."""
	without_scheme = url.split('://', 1)[1]
	authority = without_scheme.split('/', 1)[0]
	host, port_text = authority.split(':', 1)
	return (host, int(port_text))


#============================================
def setup_server() -> tuple[dict, str]:
	"""Start a server on loopback serving BODY; return connection details and tmpdir path.

	Returns:
		A tuple of (details dict, tmpdir path string). Call teardown_server(details, tmpdir)
		when done.
	"""
	# Create a real temp directory independent of pytest's tmp_path fixture.
	tmpdir = tempfile.mkdtemp()
	media_path = tmpdir + '/' + FILE_NAME
	with open(media_path, 'wb') as media_file:
		media_file.write(BODY)
	url, server, thread = airplay2tv.httpserver.serve(media_path, '127.0.0.1', '127.0.0.1')
	host, port = parse_url_host_port(url)
	details = {'url': url, 'host': host, 'port': port, 'server': server, 'thread': thread}
	return (details, tmpdir)


#============================================
def teardown_server(details: dict, tmpdir: str) -> None:
	"""Shut down the server and remove the temp directory.

	Args:
		details: The dict returned by setup_server().
		tmpdir: The temp directory path returned by setup_server().
	"""
	airplay2tv.httpserver.shutdown(details['server'], details['thread'])
	shutil.rmtree(tmpdir)


#============================================
def request(host: str, port: int, method: str, headers: dict | None = None
		) -> http.client.HTTPResponse:
	"""Issue one HTTP request to the served file and return the response.

	Args:
		host: The server hostname.
		port: The server port.
		method: HTTP method string such as 'GET' or 'HEAD'.
		headers: Optional dict of request headers.

	Returns:
		The HTTPResponse with a `_body` attribute holding the already-read body bytes.
	"""
	connection = http.client.HTTPConnection(host, port, timeout=5)
	connection.request(method, '/' + FILE_NAME, headers=headers or {})
	response = connection.getresponse()
	# Read the body now so the connection is fully drained before close.
	response._body = response.read()
	connection.close()
	return response


#============================================
def check_head_reports_full_length(details: dict) -> None:
	"""HEAD must return 200 with Content-Length equal to the full body size."""
	response = request(details['host'], details['port'], 'HEAD')
	assert response.status == 200
	assert int(response.getheader('Content-Length')) == len(BODY)


#============================================
def check_full_get_returns_whole_body(details: dict) -> None:
	"""Full GET must return 200 with the complete body."""
	response = request(details['host'], details['port'], 'GET')
	assert response.status == 200
	assert response._body == BODY


#============================================
def check_full_get_sets_accept_ranges(details: dict) -> None:
	"""Full GET must advertise byte-range support via Accept-Ranges header."""
	response = request(details['host'], details['port'], 'GET')
	assert response.getheader('Accept-Ranges') == 'bytes'


#============================================
def check_valid_range_returns_206_with_content_range(details: dict) -> None:
	"""Range GET must return 206, the correct slice, and a Content-Range header."""
	headers = {'Range': 'bytes=100-199'}
	response = request(details['host'], details['port'], 'GET', headers)
	assert response.status == 206
	assert response._body == BODY[100:200]
	expected_range = f'bytes 100-199/{len(BODY)}'
	assert response.getheader('Content-Range') == expected_range


#============================================
def check_open_ended_range_returns_tail(details: dict) -> None:
	"""An open-ended Range (bytes=N-) must return the tail of the file with 206."""
	start = len(BODY) - 50
	headers = {'Range': f'bytes={start}-'}
	response = request(details['host'], details['port'], 'GET', headers)
	assert response.status == 206
	assert response._body == BODY[start:]


#============================================
def check_out_of_range_returns_416(details: dict) -> None:
	"""A range starting beyond EOF must return 416 with a Content-Range size hint."""
	start = len(BODY) + 10
	headers = {'Range': f'bytes={start}-{start + 5}'}
	response = request(details['host'], details['port'], 'GET', headers)
	assert response.status == 416
	assert response.getheader('Content-Range') == f'bytes */{len(BODY)}'


#============================================
def check_advertised_host_in_url() -> None:
	"""The returned URL must carry the advertised host, not the bind host."""
	tmpdir = tempfile.mkdtemp()
	media_path = tmpdir + '/' + FILE_NAME
	with open(media_path, 'wb') as media_file:
		media_file.write(BODY)
	# Bind to all interfaces but advertise a distinct routable host.
	url, server, thread = airplay2tv.httpserver.serve(
		media_path, '0.0.0.0', '10.1.2.3')  # nosec B104 - test deliberately checks bind-all behavior
	airplay2tv.httpserver.shutdown(server, thread)
	shutil.rmtree(tmpdir)
	# The URL must carry the advertised host, not the bind host.
	assert url.startswith('http://10.1.2.3:')


#============================================
def check_shutdown_joins_serving_thread() -> None:
	"""After shutdown(), the serving thread must no longer be alive."""
	tmpdir = tempfile.mkdtemp()
	media_path = tmpdir + '/' + FILE_NAME
	with open(media_path, 'wb') as media_file:
		media_file.write(BODY)
	url, server, thread = airplay2tv.httpserver.serve(media_path, '127.0.0.1', '127.0.0.1')
	assert thread.is_alive() is True
	airplay2tv.httpserver.shutdown(server, thread)
	shutil.rmtree(tmpdir)
	# After shutdown the serving thread must have ended (no leak).
	assert thread.is_alive() is False


#============================================
def run_check(label: str, check_fn: collections.abc.Callable[[], None]) -> bool:
	"""Run one check function, print pass/fail, and return True on pass.

	Args:
		label: Human-readable name for the check.
		check_fn: Zero-argument callable that raises AssertionError on failure.

	Returns:
		True if the check passed, False if it raised any exception.
	"""
	try:
		check_fn()
		print(f'PASS  {label}')
		return True
	except Exception:
		print(f'FAIL  {label}')
		traceback.print_exc()
		return False


#============================================
def main() -> int:
	"""Run all HTTP server E2E checks and return exit code.

	Returns:
		0 when every check passes, 1 when any check fails.
	"""
	failures = 0

	# Checks that need a running server: set up once, run all, tear down.
	details, tmpdir = setup_server()
	server_checks: list[tuple[str, collections.abc.Callable[[], None]]] = [
		('head_reports_full_length', lambda: check_head_reports_full_length(details)),
		('full_get_returns_whole_body', lambda: check_full_get_returns_whole_body(details)),
		('full_get_sets_accept_ranges', lambda: check_full_get_sets_accept_ranges(details)),
		('valid_range_returns_206_with_content_range',
			lambda: check_valid_range_returns_206_with_content_range(details)),
		('open_ended_range_returns_tail',
			lambda: check_open_ended_range_returns_tail(details)),
		('out_of_range_returns_416', lambda: check_out_of_range_returns_416(details)),
	]
	for label, fn in server_checks:
		if not run_check(label, fn):
			failures += 1
	teardown_server(details, tmpdir)

	# Standalone checks that spin up their own server internally.
	standalone_checks: list[tuple[str, collections.abc.Callable[[], None]]] = [
		('advertised_host_in_url', check_advertised_host_in_url),
		('shutdown_joins_serving_thread', check_shutdown_joins_serving_thread),
	]
	for label, fn in standalone_checks:
		if not run_check(label, fn):
			failures += 1

	# Print a summary line.
	total = len(server_checks) + len(standalone_checks)
	passed = total - failures
	print(f'\n{passed}/{total} checks passed')
	if failures:
		return 1
	return 0


if __name__ == '__main__':
	raise SystemExit(main())
