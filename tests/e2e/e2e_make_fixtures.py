#!/usr/bin/env python3
"""Generate tiny deterministic media fixtures for the test suite.

Creates three files under tests/fixtures/ (gitignored) using ffmpeg's lavfi
test source so no human-provided media is required:

  sample_h264.mp4  -- H.264/AAC in MP4  (drives passthrough)
  sample_h264.mkv  -- H.264/AAC in MKV  (drives remux)
  sample_hevc.mp4  -- H.265/HEVC in MP4 (drives transcode)

All three are < 1 MB (4-second 160x120 @ 15fps test pattern).

Run with:  source source_me.sh && python3 tests/e2e/e2e_make_fixtures.py
"""

# Standard Library
import os
import sys
import shutil
import subprocess


#============================================
def repo_root() -> str:
	# Use git to locate the repo root so the script is cwd-independent.
	result = subprocess.run(
		['git', 'rev-parse', '--show-toplevel'],
		capture_output=True, text=True, check=True,
	)
	return result.stdout.strip()


#============================================
def fixtures_dir() -> str:
	# Always write into <repo-root>/tests/fixtures/ regardless of cwd.
	root = repo_root()
	target = os.path.join(root, 'tests', 'fixtures')
	return target


#============================================
def have_ffmpeg() -> bool:
	# Both ffmpeg (encode) and ffprobe (verify codec) must be on PATH.
	return shutil.which('ffmpeg') is not None and shutil.which('ffprobe') is not None


#============================================
def run_ffmpeg(args: list[str]) -> None:
	# Run ffmpeg; raise immediately with stderr visible on a non-zero exit code.
	result = subprocess.run(args, capture_output=True, text=True)
	if result.returncode != 0:
		raise RuntimeError(f'ffmpeg exited {result.returncode}:\n{result.stderr.strip()}')


#============================================
def make_h264_mp4(path: str) -> None:
	# 4 seconds of color bars (H.264) + 440 Hz sine (AAC) in an MP4 container.
	# Short duration and low resolution keep the file well under 1 MB.
	command = [
		'ffmpeg', '-nostdin', '-y',
		'-f', 'lavfi', '-i', 'testsrc=duration=4:size=160x120:rate=15',
		'-f', 'lavfi', '-i', 'sine=frequency=440:duration=4',
		'-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '35',
		'-c:a', 'aac', '-b:a', '32k',
		'-shortest',
		path,
	]
	run_ffmpeg(command)


#============================================
def make_h264_mkv(path: str) -> None:
	# Same H.264/AAC content wrapped in a Matroska (MKV) container.
	# The differing container is what drives the remux decision in decide().
	command = [
		'ffmpeg', '-nostdin', '-y',
		'-f', 'lavfi', '-i', 'testsrc=duration=4:size=160x120:rate=15',
		'-f', 'lavfi', '-i', 'sine=frequency=440:duration=4',
		'-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '35',
		'-c:a', 'aac', '-b:a', '32k',
		'-shortest',
		path,
	]
	run_ffmpeg(command)


#============================================
def make_hevc_mp4(path: str) -> None:
	# H.265/HEVC video + AAC audio in MP4.
	# Against a Roku profile (H.264 only) decide() returns 'transcode'.
	command = [
		'ffmpeg', '-nostdin', '-y',
		'-f', 'lavfi', '-i', 'testsrc=duration=4:size=160x120:rate=15',
		'-f', 'lavfi', '-i', 'sine=frequency=440:duration=4',
		'-c:v', 'libx265', '-preset', 'ultrafast', '-crf', '35',
		'-c:a', 'aac', '-b:a', '32k',
		'-shortest',
		path,
	]
	run_ffmpeg(command)


#============================================
def probe_codec(path: str) -> str:
	# Return the codec_name of the first video stream reported by ffprobe.
	result = subprocess.run(
		[
			'ffprobe', '-v', 'quiet',
			'-select_streams', 'v:0',
			'-show_entries', 'stream=codec_name',
			'-of', 'default=noprint_wrappers=1:nokey=1',
			path,
		],
		capture_output=True, text=True, check=True,
	)
	return result.stdout.strip()


#============================================
def print_summary(fixtures: list[tuple[str, str]]) -> None:
	# Print path, size in bytes, and confirmed video codec for each fixture.
	print('Fixtures created:')
	for path, expected_codec in fixtures:
		size = os.path.getsize(path)
		actual_codec = probe_codec(path)
		# Confirm the codec matches what was requested.
		assert actual_codec == expected_codec, (
			f'codec mismatch for {path}: expected {expected_codec}, got {actual_codec}'
		)
		print(f'  {path}  ({size} bytes, codec={actual_codec})')


#============================================
def main() -> None:
	if not have_ffmpeg():
		print('ERROR: ffmpeg and/or ffprobe not found on PATH; cannot generate fixtures.')
		print('Install with: brew install ffmpeg')
		sys.exit(1)

	outdir = fixtures_dir()
	# Create the output directory if it does not already exist.
	os.makedirs(outdir, exist_ok=True)

	h264_mp4 = os.path.join(outdir, 'sample_h264.mp4')
	h264_mkv = os.path.join(outdir, 'sample_h264.mkv')
	hevc_mp4 = os.path.join(outdir, 'sample_hevc.mp4')

	print(f'Generating fixtures in: {outdir}')

	print('  Generating sample_h264.mp4 (H.264/AAC, MP4)...')
	make_h264_mp4(h264_mp4)

	print('  Generating sample_h264.mkv (H.264/AAC, MKV)...')
	make_h264_mkv(h264_mkv)

	print('  Generating sample_hevc.mp4 (H.265/HEVC, MP4)...')
	make_hevc_mp4(hevc_mp4)

	# Print paths, sizes, and codec confirmation.
	print_summary([
		(h264_mp4, 'h264'),
		(h264_mkv, 'h264'),
		(hevc_mp4, 'hevc'),
	])
	print('Done.')


#============================================
if __name__ == '__main__':
	main()
