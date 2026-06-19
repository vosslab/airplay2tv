# Standard Library
import http.client
import pathlib
import collections.abc

# Third-party
import pytest

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
@pytest.fixture
def served_file(tmp_path: pathlib.Path) -> collections.abc.Generator:
	"""Serve a fixed-content file on loopback; yield connection details."""
	media_path = tmp_path / FILE_NAME
	media_path.write_bytes(BODY)
	url, server, thread = airplay2tv.httpserver.serve(
		str(media_path), '127.0.0.1', '127.0.0.1')
	host, port = parse_url_host_port(url)
	yield {'url': url, 'host': host, 'port': port, 'server': server, 'thread': thread}
	airplay2tv.httpserver.shutdown(server, thread)


#============================================
def request(host: str, port: int, method: str, headers: dict | None = None
		) -> http.client.HTTPResponse:
	"""Issue one HTTP request to the served file and return the response."""
	connection = http.client.HTTPConnection(host, port, timeout=5)
	connection.request(method, '/' + FILE_NAME, headers=headers or {})
	response = connection.getresponse()
	# Read the body now so the connection is fully drained before close.
	response._body = response.read()
	connection.close()
	return response


#============================================
def test_head_reports_full_length(served_file: dict) -> None:
	response = request(served_file['host'], served_file['port'], 'HEAD')
	assert response.status == 200
	assert int(response.getheader('Content-Length')) == len(BODY)


#============================================
def test_full_get_returns_whole_body(served_file: dict) -> None:
	response = request(served_file['host'], served_file['port'], 'GET')
	assert response.status == 200
	assert response._body == BODY


#============================================
def test_full_get_sets_accept_ranges(served_file: dict) -> None:
	response = request(served_file['host'], served_file['port'], 'GET')
	assert response.getheader('Accept-Ranges') == 'bytes'


#============================================
def test_valid_range_returns_206_with_content_range(served_file: dict) -> None:
	headers = {'Range': 'bytes=100-199'}
	response = request(served_file['host'], served_file['port'], 'GET', headers)
	assert response.status == 206
	assert response._body == BODY[100:200]
	expected_range = f'bytes 100-199/{len(BODY)}'
	assert response.getheader('Content-Range') == expected_range


#============================================
def test_open_ended_range_returns_tail(served_file: dict) -> None:
	start = len(BODY) - 50
	headers = {'Range': f'bytes={start}-'}
	response = request(served_file['host'], served_file['port'], 'GET', headers)
	assert response.status == 206
	assert response._body == BODY[start:]


#============================================
def test_out_of_range_returns_416(served_file: dict) -> None:
	start = len(BODY) + 10
	headers = {'Range': f'bytes={start}-{start + 5}'}
	response = request(served_file['host'], served_file['port'], 'GET', headers)
	assert response.status == 416
	assert response.getheader('Content-Range') == f'bytes */{len(BODY)}'


#============================================
def test_advertised_host_in_url(tmp_path: pathlib.Path) -> None:
	media_path = tmp_path / FILE_NAME
	media_path.write_bytes(BODY)
	# Bind to all interfaces but advertise a distinct routable host.
	url, server, thread = airplay2tv.httpserver.serve(
		str(media_path), '0.0.0.0', '10.1.2.3')  # nosec B104 - test deliberately checks bind-all behavior
	airplay2tv.httpserver.shutdown(server, thread)
	# The URL must carry the advertised host, not the bind host.
	assert url.startswith('http://10.1.2.3:')


#============================================
def test_shutdown_joins_serving_thread(tmp_path: pathlib.Path) -> None:
	media_path = tmp_path / FILE_NAME
	media_path.write_bytes(BODY)
	url, server, thread = airplay2tv.httpserver.serve(
		str(media_path), '127.0.0.1', '127.0.0.1')
	assert thread.is_alive() is True
	airplay2tv.httpserver.shutdown(server, thread)
	# After shutdown the serving thread must have ended (no leak).
	assert thread.is_alive() is False
