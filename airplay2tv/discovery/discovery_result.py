"""Typed result carriers for concurrent backend discovery.

`discover_all` returns a `DiscoveryResult` so a backend that fails at runtime
(timeout or scan error) is reported as a `BackendFailure` rather than collapsing
into a blank device list. Keeping these carriers in their own module lets the
aggregate layer and the app layer share one honest result shape without either
importing the other.
"""

# Standard Library
import dataclasses

# local repo modules
import airplay2tv.backends.base


#============================================
@dataclasses.dataclass(frozen=True)
class BackendFailure:
	"""One backend's runtime discovery failure, surfaced to the user.

	Attributes:
		backend: The backend key that failed (for example "airplay").
		reason: A short, human-readable reason (a timeout note or error text).
	"""
	backend: str
	reason: str


#============================================
@dataclasses.dataclass(frozen=True)
class DiscoveryResult:
	"""The merged outcome of running every backend's discovery.

	Attributes:
		devices: The flat list of devices found across all backends.
		failures: One BackendFailure per backend that errored or timed out, so a
			failed backend is visible to the user instead of silently dropped.
	"""
	devices: list[airplay2tv.backends.base.Device] = dataclasses.field(default_factory=list)
	failures: list[BackendFailure] = dataclasses.field(default_factory=list)
