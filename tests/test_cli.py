"""Test the fail-fast guard in run_stream.

run_stream must raise Airplay2tvError before any device discovery when
-i/--input is missing, so a user who forgot the file does not wait through a
full discovery scan only to be told the file was never supplied. This is the
one subtle behavioral invariant the entry-point change introduced; it is fast,
offline, and deterministic, so it belongs in pytest rather than an E2E run.
"""

# Standard Library
import asyncio
import argparse

# PIP3 modules
import pytest

# local repo modules
import airplay2tv.app
import airplay2tv.errors


#============================================
def test_run_stream_raises_before_discovery_when_input_missing(
	monkeypatch: object,
) -> None:
	# The missing-input guard is the first statement in run_stream, so a
	# namespace carrying only input_file=None reaches it without any backend
	# setup. The spy records any discover_all call; the test proves none happens
	# because the guard raises first.
	discover_calls: list[int] = []

	async def spy_discover_all(backends: list, timeout: float) -> list:
		discover_calls.append(1)
		return []

	monkeypatch.setattr(airplay2tv.app.aggregate, "discover_all", spy_discover_all)
	args = argparse.Namespace(input_file=None)
	with pytest.raises(airplay2tv.errors.Airplay2tvError):
		asyncio.run(airplay2tv.app.run_stream(args))
	# Discovery must not have run when the input file was missing.
	assert len(discover_calls) == 0
