"""Non-secret settings for airplay2tv: saved device records and default device id."""

# Standard Library
import copy
import os
import tempfile

# PIP3 modules
import yaml

#============================================
# Schema version stored in every config file.
CONFIG_VERSION = 1

# Default (empty) config structure.
DEFAULT_CONFIG: dict = {
	"version": CONFIG_VERSION,
	"devices": [],
	"default_device_id": None,
}

#============================================

def _config_path() -> str:
	"""Return the path to the config file, honoring XDG_CONFIG_HOME when set.

	Args:
		None

	Returns:
		Absolute path string for ~/.config/airplay2tv/config.yaml (or
		$XDG_CONFIG_HOME/airplay2tv/config.yaml when XDG_CONFIG_HOME is set).
	"""
	# XDG_CONFIG_HOME is a standard OS/ecosystem variable; reading it is acceptable.
	xdg_config_home = os.environ.get("XDG_CONFIG_HOME", "")
	if xdg_config_home:
		config_dir = os.path.join(xdg_config_home, "airplay2tv")
	else:
		config_dir = os.path.join(os.path.expanduser("~"), ".config", "airplay2tv")
	return os.path.join(config_dir, "config.yaml")

#============================================

def load() -> dict:
	"""Load and return the config dict from disk.

	A missing config file yields an empty (default) config without raising an error.
	The returned dict always contains the keys: version, devices, default_device_id.

	Args:
		None

	Returns:
		Config dict with keys version (int), devices (list[dict]), and
		default_device_id (str | None).
	"""
	path = _config_path()
	if not os.path.exists(path):
		# Deep-copy so callers cannot mutate shared module-level list/dict objects.
		return copy.deepcopy(DEFAULT_CONFIG)
	with open(path, "r", encoding="ascii") as fh:
		raw = yaml.safe_load(fh)
	if raw is None:
		# Empty YAML file -- treat as missing.
		return copy.deepcopy(DEFAULT_CONFIG)
	# Ensure required top-level keys are present in older config versions.
	if "devices" not in raw:
		raw["devices"] = []
	if "default_device_id" not in raw:
		raw["default_device_id"] = None
	if "version" not in raw:
		raw["version"] = CONFIG_VERSION
	return raw

#============================================

def save(config: dict) -> None:
	"""Write the config dict to disk atomically.

	Writes to a temporary file in the same directory as the target, then calls
	os.replace() so readers never see a partial write.

	Args:
		config: dict produced by load() or assembled by the caller.

	Returns:
		None
	"""
	path = _config_path()
	config_dir = os.path.dirname(path)
	# Create the directory if it does not exist yet.
	os.makedirs(config_dir, exist_ok=True)
	yaml_text = yaml.dump(config, default_flow_style=False, allow_unicode=False)
	# Write to a temp file in the same directory so os.replace is atomic.
	fd, tmp_path = tempfile.mkstemp(dir=config_dir, suffix=".tmp")
	try:
		with os.fdopen(fd, "w", encoding="ascii") as fh:
			fh.write(yaml_text)
		os.replace(tmp_path, path)
	except Exception:
		# Clean up the temp file on any write failure, then re-raise.
		os.unlink(tmp_path)
		raise

#============================================

def add_device(config: dict, name: str, backend: str, identifier: str, address: str) -> None:
	"""Add or update a saved device record in the config dict (in place).

	If a record with the same identifier already exists, it is replaced.
	No credential payload is stored here.

	Args:
		config: config dict (mutated in place).
		name: human-readable device name.
		backend: backend token, e.g. "airplay" or "roku".
		identifier: unique device identifier string.
		address: last-seen IP or hostname.

	Returns:
		None
	"""
	record = {
		"name": name,
		"backend": backend,
		"identifier": identifier,
		"address": address,
	}
	devices: list = config["devices"]
	# Replace existing entry with the same identifier.
	for i, existing in enumerate(devices):
		if existing["identifier"] == identifier:
			devices[i] = record
			return
	devices.append(record)

#============================================

def get_device(config: dict, identifier: str) -> dict | None:
	"""Return the saved device record for the given identifier, or None if not found.

	Args:
		config: config dict returned by load().
		identifier: unique device identifier string.

	Returns:
		Device record dict (name, backend, identifier, address) or None.
	"""
	for record in config["devices"]:
		if record["identifier"] == identifier:
			return record
	return None

#============================================

def get_default_device_id(config: dict) -> str | None:
	"""Return the default device identifier, or None if none is set.

	Args:
		config: config dict returned by load().

	Returns:
		Identifier string or None.
	"""
	return config["default_device_id"]

#============================================

def set_default_device_id(config: dict, identifier: str | None) -> None:
	"""Set or clear the default device identifier in the config dict (in place).

	Args:
		config: config dict (mutated in place).
		identifier: device identifier string, or None to clear the default.

	Returns:
		None
	"""
	config["default_device_id"] = identifier
