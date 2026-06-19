"""Tests for airplay2tv/config.py non-secret settings management."""

import os
import pathlib

import pytest
import yaml

import airplay2tv.config as config_mod

#============================================

def _make_config_dir(tmp_path: pathlib.Path) -> str:
	"""Return a fresh per-test XDG_CONFIG_HOME path under tmp_path."""
	xdg = str(tmp_path / "xdg")
	os.makedirs(xdg, exist_ok=True)
	return xdg

#============================================

def test_load_missing_file_returns_empty_config(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
	"""A missing config file yields a default config without error."""
	xdg = _make_config_dir(tmp_path)
	monkeypatch.setenv("XDG_CONFIG_HOME", xdg)
	result = config_mod.load()
	assert result["devices"] == []
	assert result["default_device_id"] is None

#============================================

def test_save_and_load_round_trip(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
	"""Save then load produces an equivalent config."""
	xdg = _make_config_dir(tmp_path)
	monkeypatch.setenv("XDG_CONFIG_HOME", xdg)
	cfg = config_mod.load()
	config_mod.add_device(cfg, "Living Room TV", "airplay", "aabbccdd", "192.168.1.10")
	config_mod.set_default_device_id(cfg, "aabbccdd")
	config_mod.save(cfg)
	loaded = config_mod.load()
	assert loaded["default_device_id"] == "aabbccdd"
	device = config_mod.get_device(loaded, "aabbccdd")
	assert device["name"] == "Living Room TV"
	assert device["backend"] == "airplay"
	assert device["address"] == "192.168.1.10"

#============================================

def test_atomic_save_writes_to_target_path(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
	"""After save(), config.yaml exists at the XDG path; no leftover .tmp files."""
	xdg = _make_config_dir(tmp_path)
	monkeypatch.setenv("XDG_CONFIG_HOME", xdg)
	cfg = config_mod.load()
	config_mod.save(cfg)
	expected_path = os.path.join(xdg, "airplay2tv", "config.yaml")
	assert os.path.isfile(expected_path)
	# No stale temp files should remain.
	config_dir = os.path.join(xdg, "airplay2tv")
	tmp_files = [f for f in os.listdir(config_dir) if f.endswith(".tmp")]
	assert tmp_files == []

#============================================

def test_default_device_get_set(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
	"""get_default_device_id and set_default_device_id round-trip correctly."""
	xdg = _make_config_dir(tmp_path)
	monkeypatch.setenv("XDG_CONFIG_HOME", xdg)
	cfg = config_mod.load()
	assert config_mod.get_default_device_id(cfg) is None
	config_mod.set_default_device_id(cfg, "roku-serial-001")
	assert config_mod.get_default_device_id(cfg) == "roku-serial-001"
	config_mod.set_default_device_id(cfg, None)
	assert config_mod.get_default_device_id(cfg) is None

#============================================

def test_two_independent_loads_do_not_share_devices_list(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
	"""Two load() calls on a missing file return independent devices lists."""
	xdg = _make_config_dir(tmp_path)
	monkeypatch.setenv("XDG_CONFIG_HOME", xdg)
	# Both calls see no config file, so both get the deep-copy default.
	cfg_a = config_mod.load()
	cfg_b = config_mod.load()
	# Mutate cfg_a -- cfg_b must remain unaffected.
	config_mod.add_device(cfg_a, "Living Room TV", "airplay", "aa:bb", "192.168.1.10")
	assert cfg_b["devices"] == []

#============================================

def test_saved_file_contains_no_credential_field(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
	"""The YAML on disk holds no field that could store a credential payload."""
	xdg = _make_config_dir(tmp_path)
	monkeypatch.setenv("XDG_CONFIG_HOME", xdg)
	cfg = config_mod.load()
	config_mod.add_device(cfg, "Bedroom Roku", "roku", "X1234", "10.0.0.5")
	config_mod.save(cfg)
	config_path = os.path.join(xdg, "airplay2tv", "config.yaml")
	with open(config_path, "r", encoding="ascii") as fh:
		raw = yaml.safe_load(fh)
	# None of these credential-like keys should appear anywhere in the stored file.
	credential_keys = {"credentials", "pairing", "pin", "token", "secret", "password", "key"}
	all_keys: set = set()
	# Check top-level keys.
	all_keys.update(raw.keys())
	# Check per-device record keys.
	for device in raw.get("devices", []):
		all_keys.update(device.keys())
	overlap = credential_keys & all_keys
	assert not overlap
