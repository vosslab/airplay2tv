"""Pure unit tests for airplay2tv.media.decide (no ffmpeg involved).

decide() is exercised against an AirPlay profile (MP4 with H.264 and H.265,
since Apple TV decodes HEVC) and a Roku profile (H.264/AAC only, so H.265
sources must transcode down). Fixed MediaInfo values drive the logic directly,
so the tests stay fast and need no media files or ffmpeg.
"""

# Standard Library
import os
import shutil
import threading

import pytest

# local repo modules
import airplay2tv.media as media
import airplay2tv.errors as errors
import airplay2tv.backends.base as base


#============================================
def airplay_profile() -> base.MediaProfile:
	# Apple TV decodes HEVC, so H.265 stays a supported video codec here.
	profile = base.MediaProfile(
		containers={'mp4', 'mov', 'm4v'},
		video_codecs={'h264', 'hevc'},
		audio_codecs={'aac'},
	)
	return profile


#============================================
def roku_profile() -> base.MediaProfile:
	# Roku Media Player target is H.264/AAC; HEVC is not in the profile.
	profile = base.MediaProfile(
		containers={'mp4', 'mov', 'm4v'},
		video_codecs={'h264'},
		audio_codecs={'aac'},
	)
	return profile


#============================================
def make_info(container: str, video_codec: str, audio_codec: str) -> media.MediaInfo:
	info = media.MediaInfo(
		container=container,
		video_codec=video_codec,
		audio_codec=audio_codec,
		duration=10.0,
	)
	return info


#============================================
def test_mp4_h264_aac_passthrough_on_both_profiles() -> None:
	info = make_info('mp4', 'h264', 'aac')
	assert media.decide(info, airplay_profile()) == 'passthrough'
	assert media.decide(info, roku_profile()) == 'passthrough'


#============================================
def test_mkv_h264_aac_remux() -> None:
	# Codecs are fine but mkv is not an allowed container -> remux.
	info = make_info('matroska', 'h264', 'aac')
	assert media.decide(info, airplay_profile()) == 'remux'
	assert media.decide(info, roku_profile()) == 'remux'


#============================================
def test_h265_against_roku_profile_transcodes() -> None:
	# Roku cannot decode HEVC, so even an MP4-contained H.265 must transcode.
	info = make_info('mp4', 'hevc', 'aac')
	assert media.decide(info, roku_profile()) == 'transcode'


#============================================
def test_h265_against_airplay_profile_passes_through() -> None:
	# Apple TV decodes HEVC; an MP4 H.265 file streams as-is.
	info = make_info('mp4', 'hevc', 'aac')
	assert media.decide(info, airplay_profile()) == 'passthrough'


#============================================
def test_h265_mkv_against_airplay_profile_remuxes() -> None:
	# HEVC is supported by AirPlay, but mkv is not an allowed container.
	info = make_info('matroska', 'hevc', 'aac')
	assert media.decide(info, airplay_profile()) == 'remux'


#============================================
def test_override_passthrough_on_roku_h265_raises() -> None:
	info = make_info('mp4', 'hevc', 'aac')
	with pytest.raises(errors.UnsupportedMediaError):
		media.decide(info, roku_profile(), mode_override='passthrough')


#============================================
def test_override_passthrough_on_supported_file_returns_passthrough() -> None:
	info = make_info('mp4', 'h264', 'aac')
	decision = media.decide(info, roku_profile(), mode_override='passthrough')
	assert decision == 'passthrough'


#============================================
def test_override_transcode_always_transcodes() -> None:
	# Even a fully supported file transcodes when the user forces it.
	supported = make_info('mp4', 'h264', 'aac')
	assert media.decide(supported, airplay_profile(), mode_override='transcode') == 'transcode'
	# And an already-incompatible file too.
	incompatible = make_info('matroska', 'hevc', 'mp3')
	assert media.decide(incompatible, roku_profile(), mode_override='transcode') == 'transcode'


#============================================
def test_unsupported_audio_codec_transcodes() -> None:
	# mp3 audio is not in either profile, so the file must transcode.
	info = make_info('mp4', 'h264', 'mp3')
	assert media.decide(info, airplay_profile()) == 'transcode'
	assert media.decide(info, roku_profile()) == 'transcode'


#============================================
def test_empty_audio_codec_transcodes_not_passthrough() -> None:
	# A file whose audio codec is empty (missing or unreported) cannot be
	# served as-is: an empty token is not in the profile, so decide must
	# transcode rather than wrongly pass an unknown codec through.
	info = make_info('mp4', 'h264', '')
	assert media.decide(info, airplay_profile()) == 'transcode'
	assert media.decide(info, roku_profile()) == 'transcode'


#============================================
def test_empty_video_codec_transcodes_not_passthrough() -> None:
	# An empty video codec token is likewise unsupported, so an otherwise
	# in-profile container and audio codec still routes to transcode.
	info = make_info('mp4', '', 'aac')
	assert media.decide(info, airplay_profile()) == 'transcode'
	assert media.decide(info, roku_profile()) == 'transcode'


#============================================
def test_empty_codec_in_supported_container_still_transcodes() -> None:
	# Even with an allowed container, an empty required codec cannot be fixed by
	# a stream-copy remux, so the decision is transcode, not remux.
	info = make_info('mp4', '', '')
	assert media.decide(info, airplay_profile()) == 'transcode'


#============================================
def test_remux_disk_check_raises_when_space_short(
	tmp_path: object, monkeypatch: pytest.MonkeyPatch,
) -> None:
	# A remux writes a new file into tmpdir and must pass the same disk-space
	# guard as a transcode. With disk_usage forced below the required headroom,
	# prepare must raise PreparationError before any ffmpeg process starts.
	# Build a small real input file so os.path.getsize works.
	input_path = str(tmp_path / 'input.mkv')
	with open(input_path, 'wb') as handle:
		handle.write(b'0' * 1024)
	tmpdir = str(tmp_path / 'work')
	os.mkdir(tmpdir)

	# Force inspect to report an mkv with in-profile codecs so decide picks remux.
	def fake_inspect(path: str) -> media.MediaInfo:
		return make_info('matroska', 'h264', 'aac')
	monkeypatch.setattr(media, 'inspect', fake_inspect)

	# Report far too little free space so the headroom check fails.
	DiskUsage = type('DiskUsage', (), {})
	def fake_disk_usage(path: str) -> object:
		usage = DiskUsage()
		usage.total = 1
		usage.used = 1
		usage.free = 1
		return usage
	monkeypatch.setattr(shutil, 'disk_usage', fake_disk_usage)

	# ffmpeg must never run; fail loudly if the guard does not stop first.
	def fail_if_called(*call_args: object, **call_kwargs: object) -> None:
		raise AssertionError('ffmpeg should not run when disk space is short')
	monkeypatch.setattr(media, '_run_ffmpeg', fail_if_called)

	def noop_progress(fraction: float) -> None:
		return None

	with pytest.raises(errors.PreparationError):
		media.prepare(
			input_path,
			roku_profile(),
			tmpdir,
			noop_progress,
			threading.Event(),
		)
