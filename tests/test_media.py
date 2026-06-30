"""Unit tests for airplay2tv.media's remote-URL classification helpers.

is_remote_url, remote_media, and classify_source are pure functions over
inline string inputs, so these tests need no media files or ffmpeg.
"""

# PIP3 modules
import pytest

# local repo modules
import airplay2tv.media as media
import airplay2tv.errors as errors


#============================================
def test_is_remote_url_true_for_https_m3u8() -> None:
	assert media.is_remote_url('https://h/x.m3u8') is True


#============================================
def test_is_remote_url_false_for_bare_filename() -> None:
	assert media.is_remote_url('movie.mp4') is False


#============================================
def test_is_remote_url_false_for_absolute_path() -> None:
	assert media.is_remote_url('/abs/path.mkv') is False


#============================================
def test_remote_media_content_type_for_m3u8() -> None:
	prepared = media.remote_media('https://h/x.m3u8')
	assert prepared.content_type == 'application/vnd.apple.mpegurl'


#============================================
def test_classify_source_local_for_bare_filename() -> None:
	assert media.classify_source('movie.mp4') == 'local'


#============================================
def test_classify_source_remote_for_https_m3u8() -> None:
	assert media.classify_source('https://h/x.m3u8') == 'remote'


#============================================
def test_classify_source_raises_for_unsupported_scheme() -> None:
	with pytest.raises(errors.UnsupportedInputError):
		media.classify_source('rtsp://h/s')
