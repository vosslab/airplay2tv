"""Logging configuration for the airplay2tv CLI: level and traceback policy."""

# Standard Library
import logging


#============================================
# Module-level flag recording whether debug mode is active. The CLI top-level
# error handler reads this to decide whether to print a full traceback (debug)
# or a single concise error line (normal). Treated as read-only after configure.
DEBUG_ENABLED = False


#============================================
def configure(verbose: bool, debug: bool) -> None:
	"""Configure root logging level and the debug traceback flag.

	The normal level is WARNING. The verbose flag raises it to INFO, and the
	debug flag raises it further to DEBUG. Debug also sets the module-level
	DEBUG_ENABLED flag so the CLI shows full tracebacks only under debug.

	Args:
		verbose: When True, raise the log level to INFO.
		debug: When True, raise the log level to DEBUG and enable tracebacks.

	Returns:
		None
	"""
	global DEBUG_ENABLED
	# Debug takes precedence over verbose; otherwise verbose lifts WARNING to INFO.
	if debug:
		level = logging.DEBUG
	elif verbose:
		level = logging.INFO
	else:
		level = logging.WARNING
	# basicConfig is a no-op if handlers already exist, so set the level directly
	# on the root logger as well to stay correct on repeated calls within a process.
	logging.basicConfig(level=level, format="%(levelname)s: %(message)s")
	logging.getLogger().setLevel(level)
	# Record debug state for the CLI traceback policy.
	DEBUG_ENABLED = debug


#============================================
def show_tracebacks() -> bool:
	"""Report whether full tracebacks should be shown on error.

	Args:
		None

	Returns:
		True when debug mode is active, otherwise False.
	"""
	return DEBUG_ENABLED
