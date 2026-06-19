"""Typed error hierarchy for readable, user-facing failure messages.

Every airplay2tv error derives from `Airplay2tvError`, so the CLI can catch one
base type and print a one-line message (and a traceback only under --debug).
The media pipeline raises `UnsupportedMediaError` when a forced mode cannot be
honored and `PreparationError` when an ffmpeg conversion cannot complete.
"""


#============================================
class Airplay2tvError(Exception):
	"""Base class for every error this tool raises on purpose.

	Catching this one type lets the CLI render a readable message for any
	expected failure while letting unexpected exceptions propagate.
	"""


#============================================
class UnsupportedMediaError(Airplay2tvError):
	"""The selected device cannot play the media and no conversion was allowed.

	Raised when the user forces passthrough (mode_override='passthrough') but
	the backend profile does not accept the file's container and codecs, so
	streaming the original would fail on the device.
	"""


#============================================
class PreparationError(Airplay2tvError):
	"""Preparing the media for streaming failed.

	Raised when the ffmpeg remux or transcode step cannot complete, for example
	when ffmpeg exits non-zero or when free disk space is too low for the
	transcode output.
	"""


#============================================
class DeviceUnreachableError(Airplay2tvError):
	"""A backend could not reach or control the selected device.

	Raised when a control call fails because the device refused it. The Roku
	backend raises this on an HTTP 403 from the External Control Protocol, which
	means the TV setting "Control by mobile apps" is disabled; the message tells
	the user exactly which setting to enable.
	"""


#============================================
class PairingRequiredError(Airplay2tvError):
	"""The selected device needs pairing but pairing cannot run here.

	Raised when a device requires a PIN pairing handshake yet the process has no
	controlling TTY to read the on-screen code. The message points the user at
	`airplay2tv pair` so they can complete pairing in an interactive terminal.
	"""


#============================================
class CredentialsError(Airplay2tvError):
	"""The credentials file is malformed or unreadable.

	Raised when the credentials file exists but cannot be parsed into the
	expected list-of-records format, for example when a hand-edited file
	contains a dict instead of a list.
	"""
