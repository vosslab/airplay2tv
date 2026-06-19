#!/usr/bin/env python3
"""Whole-pipeline E2E for airplay2tv.media.prepare (invokes real ffmpeg).

This runner generates tiny media fixtures with ffmpeg's lavfi test source, then
exercises the real ffmpeg-backed prepare() paths end to end:

- remux: an MKV (H.264/AAC) into the Roku profile -> remuxed MP4 produced.
- transcode: an H.265 (HEVC) MP4 into the Roku profile (H.264/AAC) -> a portable
  MP4 H.264/AAC produced.
- passthrough: an MP4 (H.264/AAC) into the Roku profile -> original served, no
  temp output written.
- simulated failure (pre-set cancel_event): prepare() raises PreparationError
  and leaves no partial output in the temp dir.

It lives under tests/e2e/ (not pytest) because it runs ffmpeg and touches the
real filesystem. It exits non-zero on any failure and prints a clear status log.
This is an E2E test file, so asserts are allowed here per the repo rules.
"""

# Standard Library
import os
import sys
import shutil
import tempfile
import threading
import subprocess

# This runner executes outside pytest, so the pyproject pythonpath does not
# apply. Locate the repo root and put it on sys.path so the airplay2tv package
# imports cleanly when invoked directly as python3 tests/e2e/e2e_media_prepare.py.
REPO_ROOT = subprocess.run(
	['git', 'rev-parse', '--show-toplevel'],
	capture_output=True, text=True, check=True,
).stdout.strip()
if REPO_ROOT not in sys.path:
	sys.path.insert(0, REPO_ROOT)

# local repo modules
import airplay2tv.media as media
import airplay2tv.errors as errors
import airplay2tv.backends.base as base


#============================================
def have_ffmpeg() -> bool:
	# Both binaries are required: ffprobe for inspect(), ffmpeg for prepare().
	return shutil.which('ffmpeg') is not None and shutil.which('ffprobe') is not None


#============================================
def roku_profile() -> base.MediaProfile:
	# H.264/AAC only: an HEVC source must transcode down for Roku.
	profile = base.MediaProfile(
		containers={'mp4', 'mov', 'm4v'},
		video_codecs={'h264'},
		audio_codecs={'aac'},
	)
	return profile


#============================================
def run_ffmpeg_gen(command: list[str]) -> None:
	# Generate a fixture; fail loudly with ffmpeg's stderr on a non-zero exit.
	completed = subprocess.run(command, capture_output=True, text=True)
	assert completed.returncode == 0, f'fixture ffmpeg failed: {completed.stderr.strip()}'


#============================================
def make_mp4_h264(path: str) -> None:
	# 1 second of color bars (H.264) plus a sine tone (AAC) in MP4.
	command = [
		'ffmpeg', '-nostdin', '-y',
		'-f', 'lavfi', '-i', 'testsrc=duration=1:size=160x120:rate=15',
		'-f', 'lavfi', '-i', 'sine=frequency=440:duration=1',
		'-c:v', 'libx264', '-c:a', 'aac', '-shortest',
		path,
	]
	run_ffmpeg_gen(command)


#============================================
def make_mkv_h264(path: str) -> None:
	# Same H.264/AAC content, but in an MKV container -> drives the remux path.
	command = [
		'ffmpeg', '-nostdin', '-y',
		'-f', 'lavfi', '-i', 'testsrc=duration=1:size=160x120:rate=15',
		'-f', 'lavfi', '-i', 'sine=frequency=440:duration=1',
		'-c:v', 'libx264', '-c:a', 'aac', '-shortest',
		path,
	]
	run_ffmpeg_gen(command)


#============================================
def make_mp4_h265(path: str) -> None:
	# H.265/HEVC video in MP4 -> drives the transcode path for the Roku profile.
	command = [
		'ffmpeg', '-nostdin', '-y',
		'-f', 'lavfi', '-i', 'testsrc=duration=1:size=160x120:rate=15',
		'-f', 'lavfi', '-i', 'sine=frequency=440:duration=1',
		'-c:v', 'libx265', '-c:a', 'aac', '-shortest',
		path,
	]
	run_ffmpeg_gen(command)


#============================================
def collect_progress() -> tuple[list, object]:
	# A small recorder so the test can assert progress was reported.
	fractions: list[float] = []

	def on_progress(fraction: float) -> None:
		fractions.append(fraction)

	return fractions, on_progress


#============================================
def check_passthrough(input_path: str) -> None:
	print('CASE passthrough: MP4 H.264/AAC into Roku profile')
	with tempfile.TemporaryDirectory() as tmpdir:
		fractions, on_progress = collect_progress()
		cancel_event = threading.Event()
		prepared = media.prepare(
			input_path, roku_profile(), tmpdir, on_progress, cancel_event,
		)
		# Passthrough serves the original file and writes nothing into tmpdir.
		assert prepared.path == os.path.abspath(input_path)
		assert prepared.content_type == 'video/mp4'
		assert os.listdir(tmpdir) == [], 'passthrough must not write temp output'
		assert fractions[-1] == 1.0
	print('  OK passthrough served original, no temp output')


#============================================
def check_remux(input_path: str) -> None:
	print('CASE remux: MKV H.264/AAC into Roku profile')
	with tempfile.TemporaryDirectory() as tmpdir:
		fractions, on_progress = collect_progress()
		cancel_event = threading.Event()
		prepared = media.prepare(
			input_path, roku_profile(), tmpdir, on_progress, cancel_event,
		)
		assert os.path.exists(prepared.path), 'remux output must exist'
		assert prepared.path.endswith('remuxed.mp4')
		assert os.path.getsize(prepared.path) > 0
		assert fractions[-1] == 1.0
	print('  OK remux produced an MP4 output')


#============================================
def check_transcode(input_path: str) -> None:
	print('CASE transcode: MP4 H.265 into Roku H.264/AAC profile')
	with tempfile.TemporaryDirectory() as tmpdir:
		fractions, on_progress = collect_progress()
		cancel_event = threading.Event()
		prepared = media.prepare(
			input_path, roku_profile(), tmpdir, on_progress, cancel_event,
		)
		assert os.path.exists(prepared.path), 'transcode output must exist'
		assert prepared.path.endswith('transcoded.mp4')
		# Confirm the output is the portable H.264/AAC baseline.
		result = media.inspect(prepared.path)
		assert result.video_codec == 'h264', f'video codec was {result.video_codec}'
		assert result.audio_codec == 'aac', f'audio codec was {result.audio_codec}'
		assert fractions[-1] == 1.0
	print('  OK transcode produced a portable H.264/AAC MP4')


#============================================
def check_failure_cleanup(input_path: str) -> None:
	print('CASE simulated failure: pre-set cancel_event leaves no partial output')
	tmpdir = tempfile.mkdtemp()
	raised = False
	try:
		fractions, on_progress = collect_progress()
		# Set the cancel event before the run so prepare() aborts immediately.
		cancel_event = threading.Event()
		cancel_event.set()
		try:
			media.prepare(
				input_path, roku_profile(), tmpdir, on_progress, cancel_event,
				mode_override='transcode',
			)
		except errors.PreparationError:
			raised = True
		assert raised, 'cancelled prepare must raise PreparationError'
		# The temp dir must hold no partial output after the failed run.
		leftovers = os.listdir(tmpdir)
		assert leftovers == [], f'temp dir not cleaned: {leftovers}'
	finally:
		shutil.rmtree(tmpdir, ignore_errors=True)
	print('  OK failure raised PreparationError and removed partial output')


#============================================
def main() -> None:
	if not have_ffmpeg():
		print('SKIP: ffmpeg and/or ffprobe not on PATH; cannot run media prepare E2E')
		sys.exit(1)
	with tempfile.TemporaryDirectory() as fixture_dir:
		mp4_path = os.path.join(fixture_dir, 'sample_h264.mp4')
		mkv_path = os.path.join(fixture_dir, 'sample_h264.mkv')
		hevc_path = os.path.join(fixture_dir, 'sample_h265.mp4')
		print('Generating fixtures with ffmpeg lavfi test source...')
		make_mp4_h264(mp4_path)
		make_mkv_h264(mkv_path)
		make_mp4_h265(hevc_path)
		print('Fixtures ready.')
		check_passthrough(mp4_path)
		check_remux(mkv_path)
		check_transcode(hevc_path)
		check_failure_cleanup(hevc_path)
	print('ALL MEDIA PREPARE E2E CASES PASSED')


#============================================
if __name__ == '__main__':
	main()
