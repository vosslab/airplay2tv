"""Concurrent discovery aggregation across all registered backends.

Runs every backend's `discover()` coroutine concurrently and merges the results
into a single `DiscoveryResult`. A backend that times out or raises is recorded
as a `BackendFailure` and reported to the user, never silently swallowed: a
failed backend must be visible, not collapse into a blank "no devices" result.
An optional `on_backend_done` callback is invoked as each backend's task
completes so the caller can narrate live progress while the scan runs.
"""

# Standard Library
import asyncio
import collections.abc

# local repo modules
import airplay2tv.backends.base
import airplay2tv.discovery.discovery_result as discovery_result


# Type of the per-backend completion callback: (backend_key, devices, failure).
ProgressCallback = collections.abc.Callable[
	[
		str,
		list[airplay2tv.backends.base.Device],
		discovery_result.BackendFailure | None,
	],
	None,
]


#============================================
async def discover_all(
	backends: list[airplay2tv.backends.base.Backend],
	timeout: float,
	on_backend_done: ProgressCallback | None = None,
) -> discovery_result.DiscoveryResult:
	"""Run every backend's discover() concurrently and return the merged result.

	Each backend gets its own asyncio.wait_for timeout so a slow backend cannot
	cancel a fast one mid-gather. A backend that raises or times out contributes
	zero devices and one BackendFailure, so the failure reaches the user instead
	of vanishing. When `on_backend_done` is supplied it fires with each backend's
	outcome the moment that backend's task completes.

	Args:
		backends: The Backend instances to query. May be empty.
		timeout: Per-backend wall-clock seconds allowed for each discover() call.
		on_backend_done: Optional callback invoked as each backend finishes, with
			the backend key, its devices, and its failure (None on success).

	Returns:
		A DiscoveryResult holding the merged devices and any per-backend failures.
	"""
	if not backends:
		return discovery_result.DiscoveryResult(devices=[], failures=[])

	async def _run_one(
		backend: airplay2tv.backends.base.Backend,
	) -> tuple[list[airplay2tv.backends.base.Device], discovery_result.BackendFailure | None]:
		# A backend with no key still needs a stable label for its failure line.
		name = backend.backend_key or type(backend).__name__
		devices, failure = await _discover_one(backend, name, timeout)
		# Narrate this backend's outcome the moment its task finishes.
		if on_backend_done is not None:
			on_backend_done(name, devices, failure)
		return devices, failure

	# Gather all per-backend coroutines; each already guards its own timeout.
	results = await asyncio.gather(*[_run_one(b) for b in backends])

	# Merge devices in backend order and collect every surfaced failure.
	merged: list[airplay2tv.backends.base.Device] = []
	failures: list[discovery_result.BackendFailure] = []
	for devices, failure in results:
		merged.extend(devices)
		if failure is not None:
			failures.append(failure)
	return discovery_result.DiscoveryResult(devices=merged, failures=failures)


#============================================
async def _discover_one(
	backend: airplay2tv.backends.base.Backend,
	name: str,
	timeout: float,
) -> tuple[list[airplay2tv.backends.base.Device], discovery_result.BackendFailure | None]:
	"""Discover one backend, returning its devices or a typed failure.

	A timeout and any other exception are converted into a BackendFailure that
	the caller surfaces to the user. The broad catch here records and re-surfaces
	the error as a visible failure (it does not log-and-discard), so one backend's
	bug cannot abort the other backend's scan or hide behind a blank result.

	Args:
		backend: The backend to query.
		name: The backend's key, used as the failure's backend label.
		timeout: Wall-clock seconds allowed for this backend's discover() call.

	Returns:
		A (devices, failure) pair: devices is empty on failure; failure is None on
		success. An empty list from the backend is a valid "no devices" success;
		a None return is a contract violation surfaced as a failure.
	"""
	try:
		devices = await asyncio.wait_for(backend.discover(), timeout=timeout)
	except asyncio.TimeoutError:
		return [], discovery_result.BackendFailure(name, f"timed out after {timeout:.1f}s")
	except Exception as exc:
		# Surface the error as a visible failure, not a silent drop.
		return [], discovery_result.BackendFailure(name, f"{type(exc).__name__}: {exc}")
	if devices is None:
		# discover() must return a list; None is a backend bug, surfaced loudly
		# rather than silently treated as an empty result.
		return [], discovery_result.BackendFailure(name, "returned None instead of a device list")
	return list(devices), None
