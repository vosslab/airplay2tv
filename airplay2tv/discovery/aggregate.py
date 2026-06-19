"""Concurrent discovery aggregation across all registered backends.

Runs every backend's `discover()` coroutine concurrently and merges the
returned Device lists into a single flat list.  A backend that returns an
empty list, raises an exception, or times out contributes zero devices to
the result; the rest of the backends are not affected.
"""

# Standard Library
import asyncio
import logging

# local repo modules
import airplay2tv.backends.base


logger = logging.getLogger(__name__)


#============================================
async def discover_all(
	backends: list[airplay2tv.backends.base.Backend],
	timeout: float,
) -> list[airplay2tv.backends.base.Device]:
	"""Run every backend's discover() concurrently and return the merged result.

	Each backend gets its own asyncio.wait_for timeout so a slow backend
	cannot cancel a fast one mid-gather.  A backend that raises an exception,
	times out, or returns no devices contributes zero devices to the merged
	result; all other backends proceed normally.

	Args:
		backends: The list of Backend instances to query.  May be empty.
		timeout: Per-backend wall-clock seconds allowed for each discover() call.

	Returns:
		A flat list of Device objects from every backend that responded within
		its timeout, in the order backends were supplied.  Empty when no devices
		are found.
	"""
	if not backends:
		return []

	async def _safe_discover(
		backend: airplay2tv.backends.base.Backend,
	) -> list[airplay2tv.backends.base.Device]:
		# Each backend gets its own timeout so a slow backend cannot cancel others.
		try:
			devices = await asyncio.wait_for(backend.discover(), timeout=timeout)
			# Treat None or a non-list return as an empty result
			if not devices:
				return []
			return list(devices)
		except asyncio.TimeoutError:
			logger.debug("Backend %r discover() timed out after %.1f s", backend, timeout)
			return []
		except Exception as exc:
			logger.debug("Backend %r discover() raised: %s", backend, exc)
			return []

	# Gather all per-backend coroutines; each already guards its own timeout.
	results = await asyncio.gather(*[_safe_discover(b) for b in backends])

	# Flatten the per-backend lists into one merged list
	merged: list[airplay2tv.backends.base.Device] = []
	for device_list in results:
		merged.extend(device_list)
	return merged
