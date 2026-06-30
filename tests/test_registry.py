"""Behavior tests for the backend registry's loud missing-dependency handling.

These cover the design fix: a missing required backend dependency must surface
as a named, actionable error from `active_backends`, and as a non-raising
availability report from `backend_availability`, never as a silent drop.
"""

# PIP3 modules
import pytest

# local repo modules
import airplay2tv.errors as errors
import airplay2tv.backends.registry as registry


# A spec pointing at a module that does not exist stands in for a backend whose
# required dependency is not installed: importing it raises ModuleNotFoundError.
_MISSING_SPECS = (("airplay2tv.backends.does_not_exist", "Missing", "ghostpkg"),)


#============================================
def test_active_backends_missing_dep_raises_named_error(
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	"""A missing required backend dependency raises a named, actionable error."""
	monkeypatch.setattr(registry, "BACKEND_SPECS", _MISSING_SPECS)
	with pytest.raises(errors.Airplay2tvError) as caught:
		registry.active_backends()
	message = str(caught.value)
	# The message must name the package and the install command, not be blank.
	assert "ghostpkg" in message
	assert "pip install" in message


#============================================
def test_backend_availability_reports_missing_without_raising(
	monkeypatch: pytest.MonkeyPatch,
) -> None:
	"""backend_availability marks a missing backend unavailable and never raises."""
	monkeypatch.setattr(registry, "BACKEND_SPECS", _MISSING_SPECS)
	report = registry.backend_availability()
	missing = report[0]
	assert missing.available is False
	assert missing.backend is None
	assert "ghostpkg" in missing.install_command
