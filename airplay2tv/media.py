"""Media inspection and ffmpeg-based preparation for the selected backend.

Three responsibilities live here:

- `inspect(path)` runs ffprobe and parses its JSON into a `MediaInfo`.
- `decide(info, profile, mode_override)` is a pure function that chooses
  'passthrough', 'remux', or 'transcode' against a backend `MediaProfile`.
- `prepare(...)` runs the decided ffmpeg path into a temp dir, reports
  progress, honors a cancel event, checks disk space, and cleans up partial
  output on every failure path.

The portable transcode baseline is an MP4 container with H.264 video via
libx264 and AAC audio, so the same ffmpeg command produces identical output on
macOS and Debian with no hardware encoders involved.
"""

# Standard Library
import os
import json
import shutil
import mimetypes
import dataclasses
import threading
import subprocess
import urllib.parse
import collections.abc

# local repo modules
import airplay2tv.errors as errors
import airplay2tv.backends.base as base


# The portable transcode target. Identical on macOS and Debian: software H.264
# (libx264) in MP4 with AAC audio, no hardware encoders.
TRANSCODE_CONTAINER = 'mp4'
TRANSCODE_VIDEO_CODEC = 'h264'
TRANSCODE_AUDIO_CODEC = 'aac'
TRANSCODE_CONTENT_TYPE = 'video/mp4'

# Container content types served over HTTP, keyed by lowercase container token.
# ffprobe reports the whole ISO BMFF family (mp4, mov, m4v) under one demuxer and
# lists "mov" first even for an .mp4 file, so the mov/mp4/m4v family all map to
# video/mp4, the content type devices reliably accept for that family.
CONTAINER_CONTENT_TYPES = {
	'mp4': 'video/mp4',
	'mov': 'video/mp4',
	'm4v': 'video/mp4',
	'mkv': 'video/x-matroska',
	'webm': 'video/webm',
}

# Headroom multiplier for the disk-space check before a remux or transcode. The
# output size is unknown up front, so require free space at least this fraction
# of the input size to fail loudly before a long ffmpeg run rather than mid-run.
DISK_SPACE_HEADROOM = 1.5

# Content type for an HLS playlist. mimetypes does not know ".m3u8", so a
# remote .m3u8 URL is matched explicitly before falling back to mimetypes.
HLS_PLAYLIST_CONTENT_TYPE = 'application/vnd.apple.mpegurl'

# Source-type contract: no scheme means a local path, http/https means a
# remote URL the device fetches directly, and any other scheme (rtsp://,
# file://, ...) is not something this tool can stream.
REMOTE_URL_SCHEMES = {'http', 'https'}


#============================================
@dataclasses.dataclass
class MediaInfo:
	"""Inspected facts about a local media file.

	Attributes:
		container: Lowercase container token (for example "mp4"). ffprobe may
			report several comma-joined format names; the first is used.
		video_codec: Lowercase video codec token (for example "h264", "hevc").
		audio_codec: Lowercase audio codec token (for example "aac").
		duration: Total duration in seconds.
	"""
	container: str
	video_codec: str
	audio_codec: str
	duration: float


#============================================
@dataclasses.dataclass
class PreparedMedia:
	"""The result of preparing media for streaming.

	Attributes:
		path: The backend-visible source locator. This name is intentionally
			general: it may be an absolute local filesystem path the HTTP
			server should serve (passthrough serves the original input,
			remux/transcode serve the produced file inside the temp dir), or a
			remote http(s) URL the device fetches directly.
		content_type: The HTTP Content-Type the server advertises for the file.
	"""
	path: str
	content_type: str


#============================================
def is_remote_url(value: str) -> bool:
	"""
	Report whether value is an http or https URL.

	Args:
		value: The -i input string, either a local path or a URL.

	Returns:
		True when value parses to an http or https scheme, False otherwise
		(including a bare path like "movie.mp4" or "/abs/path.mkv").
	"""
	parsed = urllib.parse.urlparse(value)
	is_remote = parsed.scheme in REMOTE_URL_SCHEMES
	return is_remote


#============================================
def remote_media(url: str) -> PreparedMedia:
	"""
	Build a PreparedMedia for a remote http(s) URL, unchanged and unfetched.

	The URL is streamed directly to the backend, bypassing local ffmpeg and
	the local HTTP server, so path is the URL itself.

	Args:
		url: The remote http(s) URL to stream.

	Returns:
		A PreparedMedia whose path is the URL unchanged and whose content_type
		is the HLS playlist type for a ".m3u8" path, or a mimetypes guess
		falling back to "application/octet-stream".
	"""
	parsed = urllib.parse.urlparse(url)
	if parsed.path.lower().endswith('.m3u8'):
		content_type = HLS_PLAYLIST_CONTENT_TYPE
	else:
		guessed_type, _encoding = mimetypes.guess_type(url)
		content_type = guessed_type if guessed_type is not None else 'application/octet-stream'
	prepared = PreparedMedia(path=url, content_type=content_type)
	return prepared


#============================================
def classify_source(value: str) -> str:
	"""
	Classify a -i input as a local path or a remote URL.

	The source-type contract: no scheme means a local path, http/https means
	a remote URL, and any other non-empty scheme (rtsp://, file://, ...) is
	not something this tool can stream.

	Args:
		value: The -i input string, either a local path or a URL.

	Returns:
		"local" or "remote".

	Raises:
		UnsupportedInputError: When value has a URL scheme other than http or
			https.
	"""
	if is_remote_url(value):
		return 'remote'
	parsed = urllib.parse.urlparse(value)
	if parsed.scheme:
		message = ''
		message += f'cannot stream input with scheme "{parsed.scheme}://": {value}; '
		message += 'only local paths and http/https URLs are supported'
		raise errors.UnsupportedInputError(message)
	return 'local'


#============================================
def inspect(path: str) -> MediaInfo:
	"""
	Probe a media file with ffprobe and parse it into a MediaInfo.

	Runs `ffprobe -v quiet -print_format json -show_format -show_streams` and
	reads the first video stream codec, the first audio stream codec, the
	container format name, and the duration. Required JSON fields are accessed
	directly with dict[key] so missing data fails loudly.

	Args:
		path: Path to the local media file to inspect.

	Returns:
		A MediaInfo with the container, video codec, audio codec, and duration.

	Raises:
		PreparationError: When ffprobe exits non-zero or returns no usable
			video or audio stream.
	"""
	# Build the ffprobe command; -v quiet keeps stderr clean for parsing.
	command = [
		'ffprobe', '-v', 'quiet',
		'-print_format', 'json',
		'-show_format', '-show_streams',
		path,
	]
	completed = subprocess.run(command, capture_output=True, text=True)
	if completed.returncode != 0:
		message = ''
		message += f'ffprobe failed for {path}: {completed.stderr.strip()}'
		raise errors.PreparationError(message)
	probe = json.loads(completed.stdout)
	container = _first_container(probe['format']['format_name'])
	video_codec = _first_stream_codec(probe['streams'], 'video')
	audio_codec = _first_stream_codec(probe['streams'], 'audio')
	duration = float(probe['format']['duration'])
	info = MediaInfo(
		container=container,
		video_codec=video_codec,
		audio_codec=audio_codec,
		duration=duration,
	)
	return info


#============================================
def _first_container(format_name: str) -> str:
	"""
	Return the first container token from ffprobe's comma-joined format_name.

	ffprobe reports container families like "mov,mp4,m4a,3gp,3g2,mj2"; the
	first token is the canonical container used for the decision logic.

	Args:
		format_name: The raw format_name string from ffprobe.

	Returns:
		The first comma-separated token, lowercased and stripped.
	"""
	first = format_name.split(',')[0]
	return first.strip().lower()


#============================================
def _first_stream_codec(streams: list[dict], codec_type: str) -> str:
	"""
	Return the codec_name of the first stream of the requested type.

	Args:
		streams: The ffprobe "streams" list of stream dicts.
		codec_type: The stream type to match ("video" or "audio").

	Returns:
		The lowercase codec_name of the first matching stream, or an empty
		string when the file has no stream of that type.
	"""
	# Walk streams in order; the first matching type wins.
	for stream in streams:
		if stream['codec_type'] == codec_type:
			return stream['codec_name'].lower()
	return ''


#============================================
def decide(
	info: MediaInfo,
	profile: base.MediaProfile,
	mode_override: str | None = None,
) -> str:
	"""
	Choose how to prepare the media for a backend, as a pure function.

	The automatic decision is:
	- 'passthrough' when the container and both codecs are in the profile,
	- 'remux' when both codecs are in the profile but the container is not,
	- 'transcode' otherwise (codecs the device cannot decode).

	A codec token that is empty (a missing stream, or a present stream whose
	codec ffprobe did not report) is not in any profile, so it counts as
	unsupported. Because an unknown codec cannot be served as-is or fixed by a
	stream-copy remux, an empty required codec routes to 'transcode'.

	With mode_override='transcode' the function always returns 'transcode'.
	With mode_override='passthrough' it returns 'passthrough' when the profile
	accepts the file and raises UnsupportedMediaError otherwise, so forcing
	passthrough of incompatible media fails clearly instead of silently
	converting.

	Args:
		info: The inspected MediaInfo for the file.
		profile: The selected backend's MediaProfile.
		mode_override: Optional forced mode, 'transcode' or 'passthrough'.

	Returns:
		One of 'passthrough', 'remux', or 'transcode'.

	Raises:
		UnsupportedMediaError: When mode_override='passthrough' but the profile
			does not accept the file's container and codecs.
	"""
	# Forcing transcode always wins, regardless of what the device supports.
	if mode_override == 'transcode':
		return 'transcode'
	codecs_ok = _codecs_supported(info, profile)
	container_ok = info.container in profile.containers
	# Forcing passthrough only succeeds when the device can play the file as-is.
	if mode_override == 'passthrough':
		if codecs_ok and container_ok:
			return 'passthrough'
		message = ''
		message += 'cannot passthrough this file to the selected device: '
		message += f'container={info.container}, video={info.video_codec}, '
		message += f'audio={info.audio_codec} is not in the device profile'
		raise errors.UnsupportedMediaError(message)
	# Automatic decision.
	if codecs_ok and container_ok:
		return 'passthrough'
	if codecs_ok:
		return 'remux'
	return 'transcode'


#============================================
def _codecs_supported(info: MediaInfo, profile: base.MediaProfile) -> bool:
	"""
	Report whether both the video and audio codecs are in the profile.

	Rule for empty codec tokens: an empty token means inspect() could not
	determine that stream's codec (a missing stream, or a present stream whose
	codec_name ffprobe did not report). An empty token is NOT in the profile, so
	it is treated as unsupported. A codec the device cannot identify cannot be
	served by passthrough or fixed by a stream-copy remux, so the caller's
	decision logic routes an empty required codec to transcode (the only path
	that re-encodes into a known, in-profile codec). This avoids serving a
	video-only or codec-missing file as passthrough on the false assumption that
	an empty codec is acceptable.

	Args:
		info: The inspected MediaInfo.
		profile: The backend MediaProfile to check against.

	Returns:
		True only when both codec tokens are non-empty and in the profile.
	"""
	# An empty token is never in the profile, so it counts as unsupported.
	video_ok = info.video_codec in profile.video_codecs
	audio_ok = info.audio_codec in profile.audio_codecs
	return video_ok and audio_ok


#============================================
def prepare(
	path: str,
	profile: base.MediaProfile,
	tmpdir: str,
	on_progress: collections.abc.Callable[[float], None],
	cancel_event: threading.Event,
	mode_override: str | None = None,
) -> PreparedMedia:
	"""
	Prepare a file for streaming to a backend, choosing the ffmpeg path.

	Inspects the file, decides passthrough/remux/transcode, and runs the
	matching ffmpeg command into tmpdir. Passthrough serves the original file
	untouched. Remux copies streams into an MP4 with `-c copy`. Transcode
	produces the portable MP4 H.264 (libx264) / AAC baseline. Progress is
	reported through on_progress as a fraction in [0.0, 1.0]. The cancel_event
	is honored: when it is set the ffmpeg process is terminated and the partial
	output is removed. Any failure also removes the partial output before
	raising.

	Args:
		path: Path to the input media file.
		profile: The selected backend's MediaProfile.
		tmpdir: Directory the produced file is written into (caller-owned).
		on_progress: Callback receiving a fraction in [0.0, 1.0] as ffmpeg runs.
		cancel_event: Set by the caller to request cancellation.
		mode_override: Optional forced mode, 'transcode' or 'passthrough'.

	Returns:
		A PreparedMedia naming the file to serve and its HTTP content type.

	Raises:
		UnsupportedMediaError: When passthrough is forced on incompatible media.
		PreparationError: When the conversion is cancelled, ffmpeg fails, or
			free disk space is too low for a transcode.
	"""
	info = inspect(path)
	mode = decide(info, profile, mode_override)
	# Passthrough streams the original file; no temp output is produced.
	if mode == 'passthrough':
		content_type = _content_type_for(info.container)
		prepared = PreparedMedia(path=os.path.abspath(path), content_type=content_type)
		on_progress(1.0)
		return prepared
	# Both remux and transcode write a new file into tmpdir, so both need
	# headroom; fail loudly before a long ffmpeg run when disk space is short.
	if mode == 'remux':
		_check_disk_space(path, tmpdir)
		output_path = os.path.join(tmpdir, 'remuxed.mp4')
		command = _remux_command(path, output_path)
		content_type = TRANSCODE_CONTENT_TYPE
	else:
		_check_disk_space(path, tmpdir)
		output_path = os.path.join(tmpdir, 'transcoded.mp4')
		command = _transcode_command(path, output_path)
		content_type = TRANSCODE_CONTENT_TYPE
	_run_ffmpeg(command, output_path, info.duration, on_progress, cancel_event)
	prepared = PreparedMedia(path=output_path, content_type=content_type)
	return prepared


#============================================
def _content_type_for(container: str) -> str:
	"""
	Return the HTTP Content-Type for a container token.

	Args:
		container: The lowercase container token (for example "mp4").

	Returns:
		The matching Content-Type, defaulting to a generic video type for an
		unlisted but still streamable container.
	"""
	# A container we do not list is still video; default to a generic type.
	return CONTAINER_CONTENT_TYPES.get(container, 'video/mp4')


#============================================
def _remux_command(input_path: str, output_path: str) -> list[str]:
	"""
	Build the ffmpeg remux command (stream copy into MP4).

	Args:
		input_path: Path to the input file.
		output_path: Path to the produced MP4.

	Returns:
		The ffmpeg argument list for a stream-copy remux with progress on stdout.
	"""
	command = [
		'ffmpeg', '-nostdin', '-y',
		'-i', input_path,
		'-c', 'copy',
		'-movflags', '+faststart',
		'-progress', 'pipe:1', '-loglevel', 'error',
		output_path,
	]
	return command


#============================================
def _transcode_command(input_path: str, output_path: str) -> list[str]:
	"""
	Build the portable MP4 H.264 (libx264) / AAC transcode command.

	Args:
		input_path: Path to the input file.
		output_path: Path to the produced MP4.

	Returns:
		The ffmpeg argument list for the portable transcode with progress on
		stdout.
	"""
	command = [
		'ffmpeg', '-nostdin', '-y',
		'-i', input_path,
		'-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
		'-c:a', 'aac', '-b:a', '160k',
		'-movflags', '+faststart',
		'-progress', 'pipe:1', '-loglevel', 'error',
		output_path,
	]
	return command


#============================================
def _check_disk_space(input_path: str, tmpdir: str) -> None:
	"""
	Raise when free space in tmpdir is too low for a remux or transcode.

	Both remux and transcode write a new file into tmpdir, so both need
	headroom. The output size is unknown up front, so require free space at
	least DISK_SPACE_HEADROOM times the input size as a conservative guard.

	Args:
		input_path: Path to the input file (used to size the requirement).
		tmpdir: Directory the output is written into.

	Raises:
		PreparationError: When free disk space is below the required headroom.
	"""
	input_size = os.path.getsize(input_path)
	required = int(input_size * DISK_SPACE_HEADROOM)
	free = shutil.disk_usage(tmpdir).free
	if free < required:
		message = ''
		message += f'not enough free disk space in {tmpdir} for transcode: '
		message += f'need about {required} bytes, have {free} bytes'
		raise errors.PreparationError(message)


#============================================
def _run_ffmpeg(
	command: list[str],
	output_path: str,
	duration: float,
	on_progress: collections.abc.Callable[[float], None],
	cancel_event: threading.Event,
) -> None:
	"""
	Run an ffmpeg command, stream progress, and honor cancellation.

	ffmpeg writes `-progress pipe:1` key=value lines to stdout; the out_time_ms
	key is divided by the known duration to produce a [0.0, 1.0] fraction
	passed to on_progress. When cancel_event is set the process is terminated
	and the partial output is removed. Any non-zero exit or cancellation
	removes the partial output and raises PreparationError.

	Args:
		command: The full ffmpeg argument list (must include -progress pipe:1).
		output_path: Path ffmpeg writes; removed on cancel or failure.
		duration: Total media duration in seconds, for the progress fraction.
		on_progress: Callback receiving a fraction in [0.0, 1.0].
		cancel_event: Set by the caller to request cancellation.

	Raises:
		PreparationError: On cancellation or a non-zero ffmpeg exit.
	"""
	process = subprocess.Popen(
		command,
		stdout=subprocess.PIPE,
		stderr=subprocess.PIPE,
		text=True,
	)
	# Read progress lines until ffmpeg closes stdout or the caller cancels.
	cancelled = _consume_progress(process, duration, on_progress, cancel_event)
	if cancelled:
		process.wait()
		_remove_partial(output_path)
		raise errors.PreparationError('media preparation cancelled')
	process.wait()
	if process.returncode != 0:
		stderr_text = process.stderr.read().strip()
		_remove_partial(output_path)
		message = ''
		message += f'ffmpeg failed with exit code {process.returncode}: {stderr_text}'
		raise errors.PreparationError(message)
	# Final 100% tick so callers always see completion.
	on_progress(1.0)


#============================================
def _consume_progress(
	process: subprocess.Popen,
	duration: float,
	on_progress: collections.abc.Callable[[float], None],
	cancel_event: threading.Event,
) -> bool:
	"""
	Read ffmpeg progress lines and report the completion fraction.

	Cancellation latency: cancel_event is checked once per progress line at the
	top of the loop, so the worst-case delay between cancel_event being set and
	the process being terminated is one ffmpeg progress-update interval (roughly
	0.5-1 s with the default -progress cadence). The bound is one interval, not
	unbounded, because each new line wakes the loop and re-checks the event.

	Args:
		process: The running ffmpeg Popen with stdout=PIPE.
		duration: Total media duration in seconds.
		on_progress: Callback receiving a [0.0, 1.0] fraction.
		cancel_event: Set by the caller to request cancellation.

	Returns:
		True when cancellation terminated the process, False on normal end.
	"""
	# Iterate stdout line by line; ffmpeg flushes progress key=value pairs.
	for line in process.stdout:
		if cancel_event.is_set():
			process.terminate()
			return True
		stripped = line.strip()
		# out_time_ms is microseconds of media processed so far.
		if stripped.startswith('out_time_ms=') and duration > 0:
			value = stripped.split('=', 1)[1]
			fraction = _progress_fraction(value, duration)
			on_progress(fraction)
	return False


#============================================
def _progress_fraction(out_time_ms: str, duration: float) -> float:
	"""
	Convert ffmpeg's out_time_ms value to a clamped [0.0, 1.0] fraction.

	The key is named out_time_ms but ffmpeg reports microseconds, so the value
	is divided by one million to get seconds before dividing by duration.

	Args:
		out_time_ms: The raw out_time_ms value string from ffmpeg.
		duration: Total media duration in seconds.

	Returns:
		The completion fraction clamped to [0.0, 1.0]; 0.0 for "N/A".
	"""
	# ffmpeg emits "N/A" before the first real timestamp.
	if out_time_ms == 'N/A':
		return 0.0
	seconds_done = int(out_time_ms) / 1_000_000.0
	fraction = seconds_done / duration
	# Clamp so a slightly-over reading never reports past 100%.
	if fraction < 0.0:
		return 0.0
	if fraction > 1.0:
		return 1.0
	return fraction


#============================================
def _remove_partial(output_path: str) -> None:
	"""
	Remove a partial ffmpeg output file if it exists.

	Args:
		output_path: Path to the partial output to delete.
	"""
	# A cancelled or failed run may leave a partial file; remove it quietly.
	if os.path.exists(output_path):
		os.remove(output_path)
