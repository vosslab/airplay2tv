"""Credential storage for airplay2tv: pairing records keyed by (identifier, backend).

Secrets live here; non-secret device preferences live in config.py.
The credentials file is stored at ~/.config/airplay2tv/credentials.yaml
(or $XDG_CONFIG_HOME/airplay2tv/credentials.yaml when XDG_CONFIG_HOME is set),
mode 0600, and written atomically via a temp file + os.replace.

Concurrent writers are serialized by an exclusive fcntl.flock on a companion
lock file (credentials.yaml.lock) that is held across the entire
load-merge-write window.  The lock is always released via a finally block.
"""

# Standard Library
import os
import stat
import fcntl
import logging
import tempfile

# PIP3 modules
import yaml

# local repo modules
import airplay2tv.backends.base as base
import airplay2tv.errors as errors

#============================================
# Logger for permission warnings shown to the user.
_log = logging.getLogger(__name__)

#============================================

def _credentials_path() -> str:
	"""Return the path to the credentials file, honoring XDG_CONFIG_HOME when set.

	Args:
		None

	Returns:
		Absolute path string for ~/.config/airplay2tv/credentials.yaml (or
		$XDG_CONFIG_HOME/airplay2tv/credentials.yaml when XDG_CONFIG_HOME is set).
	"""
	# XDG_CONFIG_HOME is a standard OS/ecosystem variable; reading it is acceptable.
	xdg_config_home = os.environ.get("XDG_CONFIG_HOME", "")
	if xdg_config_home:
		config_dir = os.path.join(xdg_config_home, "airplay2tv")
	else:
		config_dir = os.path.join(os.path.expanduser("~"), ".config", "airplay2tv")
	return os.path.join(config_dir, "credentials.yaml")

#============================================

def _lock_path(credentials_file_path: str) -> str:
	"""Return the companion lock file path for the given credentials file.

	Args:
		credentials_file_path: Absolute path to the credentials YAML file.

	Returns:
		Path string with a .lock suffix appended to credentials_file_path.
	"""
	return credentials_file_path + ".lock"

#============================================

def _check_permissions(path: str) -> None:
	"""Warn if the credentials file has permissions looser than 0600.

	Args:
		path: Absolute path to the credentials file on disk.

	Returns:
		None
	"""
	file_stat = os.stat(path)
	# Extract the low 9 permission bits (owner/group/other rwx).
	mode_bits = stat.S_IMODE(file_stat.st_mode)
	if mode_bits != 0o600:
		_log.warning(
			"Credentials file %s has permissions %04o (expected 0600). "
			"Run: chmod 600 %s",
			path, mode_bits, path,
		)

#============================================

def _load_unlocked() -> dict[tuple[str, str], base.PairingRecord]:
	"""Load all pairing records from disk without acquiring a lock.

	Called from save_record while the exclusive lock is already held, and
	also from the public load() which acquires no lock (load is read-only and
	idempotent; only the write side needs serialization).

	Args:
		None

	Returns:
		Dict mapping (identifier, backend) tuples to PairingRecord instances.

	Raises:
		errors.CredentialsError: The file exists and contains valid YAML but the
			top-level value is not a list (for example a hand-edited dict).
	"""
	path = _credentials_path()
	if not os.path.exists(path):
		# Missing file is not an error; caller gets an empty record store.
		return {}
	_check_permissions(path)
	with open(path, "r", encoding="ascii") as fh:
		raw = yaml.safe_load(fh)
	if raw is None:
		# Empty YAML file -- treat as missing.
		return {}
	# Guard against hand-edited files that contain a dict instead of a list.
	if not isinstance(raw, list):
		raise errors.CredentialsError(
			f"Credentials file {path} must contain a YAML list of records "
			f"but found {type(raw).__name__}. "
			"Fix or remove the file and re-pair your devices."
		)
	records: dict[tuple[str, str], base.PairingRecord] = {}
	# Each entry in the YAML list is a flat dict with identifier, backend, credential.
	for entry in raw:
		identifier = entry["identifier"]
		backend = entry["backend"]
		credential = entry["credential"]
		record = base.PairingRecord(
			identifier=identifier,
			backend=backend,
			credential=credential,
		)
		records[(identifier, backend)] = record
	return records

#============================================

def load() -> dict[tuple[str, str], base.PairingRecord]:
	"""Load all pairing records from disk and return them keyed by (identifier, backend).

	A missing credentials file yields an empty dict without raising an error.
	When the file exists with permissions looser than 0600, the file is still
	loaded but a warning is emitted via logging.

	Args:
		None

	Returns:
		Dict mapping (identifier, backend) tuples to PairingRecord instances.

	Raises:
		errors.CredentialsError: The credentials file contains valid YAML that is
			not a list (for example a hand-edited dict).
	"""
	return _load_unlocked()

#============================================

def save_record(record: base.PairingRecord) -> None:
	"""Persist or replace a pairing record on disk.

	The load-merge-write window is protected by an exclusive fcntl.flock on a
	companion lock file (credentials.yaml.lock) so concurrent callers cannot
	silently discard each other's records.  The credentials file itself is
	written atomically (temp file in same dir + os.replace) and its mode is
	set to 0600 on every save.  The directory is created if absent.

	Args:
		record: PairingRecord to persist.

	Returns:
		None
	"""
	path = _credentials_path()
	config_dir = os.path.dirname(path)
	os.makedirs(config_dir, exist_ok=True)
	lock_file_path = _lock_path(path)
	# Open (or create) the lock file; we never write to it, just lock it.
	lock_fh = open(lock_file_path, "w", encoding="ascii")
	try:
		# LOCK_EX blocks until any other writer releases the lock.
		fcntl.flock(lock_fh, fcntl.LOCK_EX)
		# Load existing records to merge or replace (lock is now held).
		existing = _load_unlocked()
		existing[(record.identifier, record.backend)] = record
		# Serialize to a flat list of dicts for YAML storage.
		entries = []
		for rec in existing.values():
			entry: dict = {
				"identifier": rec.identifier,
				"backend": rec.backend,
				"credential": rec.credential,
			}
			entries.append(entry)
		yaml_text = yaml.dump(entries, default_flow_style=False, allow_unicode=False)
		# Write to a temp file in the same directory, then atomically replace.
		fd, tmp_path = tempfile.mkstemp(dir=config_dir, suffix=".tmp")
		try:
			with os.fdopen(fd, "w", encoding="ascii") as fh:
				fh.write(yaml_text)
			# Set 0600 on the temp file before it replaces the target.
			os.chmod(tmp_path, 0o600)
			os.replace(tmp_path, path)
		except Exception:
			# Clean up the temp file on any write failure, then re-raise.
			os.unlink(tmp_path)
			raise
		# Reassert 0600 on the final file (os.replace carries the temp mode, but be explicit).
		os.chmod(path, 0o600)
	finally:
		# Always release the lock and close the lock file descriptor.
		fcntl.flock(lock_fh, fcntl.LOCK_UN)
		lock_fh.close()

#============================================

def get_record(identifier: str, backend: str) -> base.PairingRecord | None:
	"""Return the pairing record for (identifier, backend), or None if not found.

	Args:
		identifier: Device identifier string.
		backend: Backend key string (for example "airplay" or "roku").

	Returns:
		PairingRecord if one exists, otherwise None.
	"""
	records = load()
	return records.get((identifier, backend))
