"""Construct the active receiver backend instances for the CLI and app layer.

This module is construction-only: it imports the concrete backends and returns
fresh instances. Both concrete backends depend on a third-party client (`pyatv`
for AirPlay, `rokuecp` for Roku ECP), and both are REQUIRED runtime
dependencies. When one is missing, `active_backends` raises a typed
`Airplay2tvError` naming the missing package and the install command, instead of
silently dropping the backend and letting discovery report a blank result -- a
missing driver must look like a missing driver, not an empty network.

`backend_availability` is the non-raising counterpart that `doctor` uses to
report each backend's state (and reuse the constructed instance) without
aborting when a dependency is absent.
"""

# Standard Library
import importlib
import dataclasses

# local repo modules
import airplay2tv.errors
import airplay2tv.backends.base


#============================================
# Dotted module path, class name, and required pip package for each backend the
# registry constructs. The package name is what a user installs to make the
# backend available and is the single source for the install hint. This tuple is
# the one place to add or remove a backend.
BACKEND_SPECS = (
	("airplay2tv.backends.airplay", "AirPlayBackend", "pyatv"),
	("airplay2tv.backends.roku_ecp", "RokuBackend", "rokuecp"),
)


#============================================
@dataclasses.dataclass(frozen=True)
class BackendAvailability:
	"""Whether one backend could be constructed, and how to fix it if not.

	Attributes:
		package: The pip package the backend depends on (for example "pyatv").
		available: True when the backend module imported and constructed.
		install_command: The exact command that installs the missing package.
		backend: The constructed Backend instance when available, else None.
	"""
	package: str
	available: bool
	install_command: str
	backend: airplay2tv.backends.base.Backend | None


#============================================
def backend_availability() -> list[BackendAvailability]:
	"""Probe every backend without raising, for doctor-style reporting.

	Each backend module is imported and constructed; a missing third-party
	dependency marks that backend unavailable with an install command rather than
	aborting, so the caller can report the full picture even when a dependency is
	absent. The constructed instance is returned so the caller can reuse it
	without importing twice.

	Returns:
		One BackendAvailability per entry in BACKEND_SPECS, in declared order.
	"""
	results: list[BackendAvailability] = []
	for module_path, class_name, package in BACKEND_SPECS:
		backend = _try_construct(module_path, class_name)
		# A per-package install hint reads clearly in doctor output.
		install_command = f"pip install {package}"
		results.append(
			BackendAvailability(package, backend is not None, install_command, backend)
		)
	return results


#============================================
def _try_construct(
	module_path: str,
	class_name: str,
) -> airplay2tv.backends.base.Backend | None:
	"""Import and construct one backend, or return None when its dep is missing.

	Only a missing third-party module returns None; any other import-time error
	carries a real bug and is allowed to propagate.

	Args:
		module_path: Dotted path of the backend module.
		class_name: Backend class to construct inside that module.

	Returns:
		The constructed Backend, or None when the backend's dependency is absent.
	"""
	# Only the backend's own missing dependency yields None; other errors raise.
	try:
		module = importlib.import_module(module_path)
	except ModuleNotFoundError:
		return None
	# A present module is expected to expose its backend class.
	backend_class = getattr(module, class_name)
	return backend_class()


#============================================
def active_backends() -> list[airplay2tv.backends.base.Backend]:
	"""Construct the active backends, raising loudly when a dependency is missing.

	Both declared backends are required. When any backend's dependency is not
	installed, this raises a typed Airplay2tvError naming the missing package(s)
	and the install command, so a missing dependency surfaces as a clear,
	actionable error instead of a blank "no devices" result.

	Returns:
		The constructed Backend instances, one per BACKEND_SPECS entry.

	Raises:
		Airplay2tvError: When one or more required backend dependencies is missing.
	"""
	probed = backend_availability()
	missing = [item.package for item in probed if not item.available]
	if missing:
		raise airplay2tv.errors.Airplay2tvError(_missing_dependency_message(missing))
	# Every backend is available here, so each carries a constructed instance.
	return [item.backend for item in probed if item.backend is not None]


#============================================
def _missing_dependency_message(packages: list[str]) -> str:
	"""Build the loud, actionable message for missing backend dependencies.

	Args:
		packages: The pip package names that are not installed.

	Returns:
		A one-line message naming the packages and the exact install command.
	"""
	package_list = ", ".join(packages)
	message = ""
	message += f"required backend dependencies not installed: {package_list}. "
	message += "install them with: pip install -r pip_requirements.txt"
	return message
