"""Construct the active receiver backend instances for the CLI and app layer.

This module is construction-only: it imports the concrete backends and returns
fresh instances. It holds no business logic, no discovery, and no control flow.
The concrete backends are imported lazily inside the function so importing this
module (and running `airplay2tv --help`) never fails while the backends are
still being built.
"""

# Standard Library
import importlib
import logging

# local repo modules
import airplay2tv.backends.base


#============================================
# Dotted module path and class name for each backend that the registry constructs.
# Both concrete backends (AirPlayBackend and RokuEcpBackend) are present; this
# tuple is the single place to add or remove importable backends.
BACKEND_SPECS = (
	("airplay2tv.backends.airplay", "AirPlayBackend"),
	("airplay2tv.backends.roku_ecp", "RokuBackend"),
)


#============================================
def active_backends() -> list[airplay2tv.backends.base.Backend]:
	"""Construct and return the active backend instances.

	Each entry in BACKEND_SPECS is imported lazily. A backend whose module or
	class does not exist yet is skipped with a debug log line rather than raising,
	so the CLI keeps working while the concrete backends are still being built.

	Args:
		None

	Returns:
		A list of constructed Backend instances; possibly empty while the
		concrete backends are not yet implemented.
	"""
	logger = logging.getLogger(__name__)
	backends: list[airplay2tv.backends.base.Backend] = []
	for module_path, class_name in BACKEND_SPECS:
		# Import the backend module lazily; a missing module is expected for now.
		try:
			module = importlib.import_module(module_path)
		except ModuleNotFoundError:
			logger.debug("backend module not available yet: %s", module_path)
			continue
		# A present module is expected to expose its backend class.
		backend_class = getattr(module, class_name)
		backends.append(backend_class())
	return backends
