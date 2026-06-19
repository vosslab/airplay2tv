"""Command-line entry point for airplay2tv.

This module owns only the argparse surface and dispatch. The orchestration
(`app.py`) and the pair/doctor/devices command handlers are imported lazily
inside `main()` so `airplay2tv --help` and `<subcommand> --help` work today,
before those modules exist.
"""

# Standard Library
import sys
import traceback
import argparse
import importlib

# local repo modules
import airplay2tv.errors
import airplay2tv.logging_setup


#============================================
def add_logging_arguments(parser: argparse.ArgumentParser) -> None:
	"""Add the verbose and debug flags shared by every action.

	`main()` reads `verbose` and `debug` from the namespace for every command,
	so every parser (top level and each subparser) must define them. Defining
	them here keeps the two flags on every namespace the parser produces.

	Args:
		parser: The argparse parser to extend.

	Returns:
		None
	"""
	parser.add_argument(
		"-v", "--verbose", dest="verbose", action="store_true",
		help="raise the log level to informational messages",
	)
	parser.add_argument(
		"--debug", dest="debug", action="store_true",
		help="raise the log level to debug and show full tracebacks",
	)


#============================================
def add_stream_arguments(parser: argparse.ArgumentParser) -> None:
	"""Add the default stream-action flags to a parser.

	These are the flags a user changes between runs of the default action
	(serve a file and play it on a chosen device).

	Args:
		parser: The argparse parser to extend.

	Returns:
		None
	"""
	parser.add_argument(
		"-i", "--input", dest="input_file",
		help="path to the media file to stream",
	)
	parser.add_argument(
		"-d", "--device", dest="device",
		help="name or identifier of the target receiver",
	)
	parser.add_argument(
		"--bind", dest="bind_host",
		help="local host or IP the file server binds to",
	)
	parser.add_argument(
		"--save-device", dest="save_device", action="store_true",
		help="save the selected device to the config for next time",
	)
	parser.add_argument(
		"--default-device", dest="default_device",
		help="set this device identifier as the default and use it",
	)
	add_logging_arguments(parser)
	# Mutually exclusive media-mode group. Leaving both off (the default of
	# None) lets the pipeline choose automatically based on the device profile.
	media_group = parser.add_mutually_exclusive_group()
	media_group.add_argument(
		"--passthrough", dest="media_mode",
		action="store_const", const="passthrough",
		help="stream the original file when the selected device supports it",
	)
	media_group.add_argument(
		"--transcode", dest="media_mode",
		action="store_const", const="transcode",
		help="prepare a compatible MP4 with H.264 video and AAC audio",
	)
	parser.set_defaults(media_mode=None)


#============================================
def parse_args() -> argparse.Namespace:
	"""Parse command-line arguments for airplay2tv.

	The default action (no subcommand) serves a file and plays it on a device.
	Three subcommands run helper flows: pair, doctor, and devices.

	Args:
		None

	Returns:
		The parsed argparse.Namespace.
	"""
	parser = argparse.ArgumentParser(
		prog="airplay2tv",
		description="Stream a local media file to an AirPlay or Roku receiver.",
	)
	# Top-level stream-action flags (used when no subcommand is given).
	add_stream_arguments(parser)
	# Subcommands. The command attribute is None for the default stream action.
	# Each subparser carries the logging flags so `main()` can always read
	# `verbose` and `debug`, plus the flags its own handler reads in `app.run`.
	subparsers = parser.add_subparsers(dest="command")
	pair_parser = subparsers.add_parser(
		"pair", help="pair with a device that requires a PIN",
	)
	pair_parser.add_argument(
		"-d", "--device", dest="device",
		help="name or identifier of the device to pair with",
	)
	add_logging_arguments(pair_parser)
	doctor_parser = subparsers.add_parser(
		"doctor", help="check the environment and report any problems",
	)
	doctor_parser.add_argument(
		"-d", "--device", dest="device",
		help="name or identifier of a device to check reachability for",
	)
	doctor_parser.add_argument(
		"-i", "--input", dest="input_file",
		help="path to a media file to probe during the checks",
	)
	add_logging_arguments(doctor_parser)
	devices_parser = subparsers.add_parser(
		"devices", help="discover and list reachable receivers",
	)
	add_logging_arguments(devices_parser)
	args = parser.parse_args()
	return args


#============================================
def main() -> None:
	"""Configure logging and dispatch to the requested action.

	The stream action and every subcommand are handled by `airplay2tv.app`,
	which inspects `args.command`. The app module is imported lazily here so
	this module (and `--help`) work before `app.py` exists.

	Args:
		None

	Returns:
		None
	"""
	args = parse_args()
	# Configure logging before any work so handlers honor the chosen level.
	airplay2tv.logging_setup.configure(args.verbose, args.debug)
	# Import the orchestration layer lazily so --help never needs app.py.
	app = importlib.import_module("airplay2tv.app")
	exit_code = dispatch(app, args)
	raise SystemExit(exit_code)


#============================================
def dispatch(app: object, args: argparse.Namespace) -> int:
	"""Run the requested action and map expected failures to a clean exit.

	`app.run` is a synchronous dispatcher: it drives the async stream/devices
	actions through asyncio.run itself and runs the sync doctor/pair handlers
	directly, so the CLI never nests event loops.

	Any `Airplay2tvError` (the base for every failure this tool raises on
	purpose) is rendered as a single readable line on stderr and mapped to exit
	code 1. The full traceback is shown only under `--debug`, so a normal user
	sees a short message while a developer can still see the stack. Unexpected
	exceptions are not caught here; they propagate so real bugs surface loudly.

	Args:
		app: The imported orchestration module exposing `run(args) -> int`.
		args: The parsed CLI namespace; `debug` controls traceback printing.

	Returns:
		The integer exit code for the process.
	"""
	# Only a deliberate, typed failure is rendered as one line; anything else is
	# an unexpected bug and is allowed to propagate with its full traceback.
	try:
		exit_code = app.run(args)
	except airplay2tv.errors.Airplay2tvError as exc:
		# Show the full stack only under --debug; otherwise one readable line.
		if getattr(args, "debug", False):
			traceback.print_exc()
		print(f"error: {exc}", file=sys.stderr)
		return 1
	return exit_code
