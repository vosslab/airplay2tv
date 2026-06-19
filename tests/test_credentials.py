"""Tests for airplay2tv/credentials.py pairing record storage."""

# Standard Library
import os
import stat
import pathlib
import logging
import threading

# PIP3 modules
import pytest

# local repo modules
import airplay2tv.credentials as creds_mod
import airplay2tv.backends.base as base
import airplay2tv.errors as errors

#============================================

def _make_xdg(tmp_path: pathlib.Path) -> str:
	"""Return a fresh per-test XDG_CONFIG_HOME path under tmp_path."""
	xdg = str(tmp_path / "xdg")
	os.makedirs(xdg, exist_ok=True)
	return xdg

#============================================

def test_load_missing_file_returns_empty(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
	"""A missing credentials file yields an empty dict without error."""
	xdg = _make_xdg(tmp_path)
	monkeypatch.setenv("XDG_CONFIG_HOME", xdg)
	result = creds_mod.load()
	assert result == {}

#============================================

def test_save_and_load_round_trip(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
	"""save_record then load recovers the same PairingRecord."""
	xdg = _make_xdg(tmp_path)
	monkeypatch.setenv("XDG_CONFIG_HOME", xdg)
	record = base.PairingRecord(
		identifier="device-abc",
		backend="airplay",
		credential="pyatv-cred-string",
	)
	creds_mod.save_record(record)
	loaded = creds_mod.load()
	recovered = loaded[("device-abc", "airplay")]
	assert recovered.identifier == "device-abc"
	assert recovered.credential == "pyatv-cred-string"

#============================================

def test_file_mode_is_0600_after_save(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
	"""The credentials file has mode 0600 after save_record."""
	xdg = _make_xdg(tmp_path)
	monkeypatch.setenv("XDG_CONFIG_HOME", xdg)
	record = base.PairingRecord(
		identifier="device-xyz",
		backend="roku",
		credential={"key": "val"},
	)
	creds_mod.save_record(record)
	creds_path = os.path.join(xdg, "airplay2tv", "credentials.yaml")
	file_stat = os.stat(creds_path)
	mode_bits = stat.S_IMODE(file_stat.st_mode)
	assert mode_bits == 0o600

#============================================

def test_loose_permissions_triggers_warning(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
	"""A pre-existing file with permissions 0644 triggers a warning but still loads."""
	xdg = _make_xdg(tmp_path)
	monkeypatch.setenv("XDG_CONFIG_HOME", xdg)
	# Save a record first so the file exists.
	record = base.PairingRecord(
		identifier="dev-warn",
		backend="airplay",
		credential="some-cred",
	)
	creds_mod.save_record(record)
	creds_path = os.path.join(xdg, "airplay2tv", "credentials.yaml")
	# Loosen permissions to 0644 to simulate an insecure state.
	os.chmod(creds_path, 0o644)
	with caplog.at_level(logging.WARNING, logger="airplay2tv.credentials"):
		loaded = creds_mod.load()
	# The record should still load correctly.
	assert ("dev-warn", "airplay") in loaded
	# A warning must have been logged about the loose permissions.
	assert any("0644" in msg or "644" in msg for msg in caplog.messages)

#============================================

def test_credentials_file_separate_from_config_file(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
	"""The credentials file path ends with credentials.yaml, not config.yaml."""
	xdg = _make_xdg(tmp_path)
	monkeypatch.setenv("XDG_CONFIG_HOME", xdg)
	record = base.PairingRecord(
		identifier="dev-sep",
		backend="roku",
		credential="cred-data",
	)
	creds_mod.save_record(record)
	creds_path = os.path.join(xdg, "airplay2tv", "credentials.yaml")
	config_path = os.path.join(xdg, "airplay2tv", "config.yaml")
	assert os.path.isfile(creds_path)
	# config.yaml must NOT have been created by the credentials module.
	assert not os.path.isfile(config_path)

#============================================

def test_get_record_returns_none_when_absent(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
	"""get_record returns None for a device that has not been paired."""
	xdg = _make_xdg(tmp_path)
	monkeypatch.setenv("XDG_CONFIG_HOME", xdg)
	result = creds_mod.get_record("no-such-device", "airplay")
	assert result is None

#============================================

def test_get_record_returns_saved_record(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
	"""get_record returns the PairingRecord that was previously saved."""
	xdg = _make_xdg(tmp_path)
	monkeypatch.setenv("XDG_CONFIG_HOME", xdg)
	record = base.PairingRecord(
		identifier="roku-001",
		backend="roku",
		credential={"pin": "1234"},
	)
	creds_mod.save_record(record)
	found = creds_mod.get_record("roku-001", "roku")
	assert found is not None
	assert found.backend == "roku"

#============================================

def test_concurrent_save_both_records_survive(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
	"""Two threads calling save_record concurrently both persist their records.

	Finding 2 (HIGH): without a file lock, the second writer's load-merge-write
	races the first and silently discards the first record.  With fcntl.flock,
	both records must survive.
	"""
	xdg = _make_xdg(tmp_path)
	monkeypatch.setenv("XDG_CONFIG_HOME", xdg)
	record_a = base.PairingRecord(
		identifier="device-alpha",
		backend="airplay",
		credential="cred-alpha",
	)
	record_b = base.PairingRecord(
		identifier="device-beta",
		backend="roku",
		credential="cred-beta",
	)
	# Run both saves concurrently in threads.
	errors_list: list[Exception] = []
	def _save(rec: base.PairingRecord) -> None:
		try:
			creds_mod.save_record(rec)
		except Exception as exc:
			errors_list.append(exc)
	thread_a = threading.Thread(target=_save, args=(record_a,))
	thread_b = threading.Thread(target=_save, args=(record_b,))
	thread_a.start()
	thread_b.start()
	thread_a.join(timeout=5)
	thread_b.join(timeout=5)
	# Both threads must have finished without exceptions.
	assert errors_list == []
	# Both records must be present after both writes complete.
	loaded = creds_mod.load()
	assert ("device-alpha", "airplay") in loaded
	assert ("device-beta", "roku") in loaded

#============================================

def test_load_non_list_yaml_raises_credentials_error(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
	"""load() raises CredentialsError when the YAML file contains a dict, not a list.

	Finding 11 (LOW): hand-editing credentials.yaml to a dict causes a bare
	KeyError on entry["identifier"] without a clear message.  The fix must raise
	CredentialsError with the filename included.
	"""
	xdg = _make_xdg(tmp_path)
	monkeypatch.setenv("XDG_CONFIG_HOME", xdg)
	# Write a valid YAML file whose top-level value is a dict, not a list.
	creds_dir = os.path.join(xdg, "airplay2tv")
	os.makedirs(creds_dir, exist_ok=True)
	creds_path = os.path.join(creds_dir, "credentials.yaml")
	with open(creds_path, "w", encoding="ascii") as fh:
		fh.write("identifier: bad-device\nbackend: airplay\ncredential: oops\n")
	os.chmod(creds_path, 0o600)
	with pytest.raises(errors.CredentialsError):
		creds_mod.load()
