"""
Unit tests for file_utils.run_fixer_script wrapper contract.

These tests monkeypatch subprocess.run; no real subprocess is invoked.
They verify the wrapper contract: returns a (returncode, stderr) tuple for
every subprocess completion, raises RuntimeError only for environment
preconditions (missing script file, missing interpreter).

run_fixer_script constructs the script path as:
  os.path.join(get_repo_root(), "tests", script_name)
So dummy scripts must be placed at tmp_path/tests/<name>.
"""

# Standard Library
import pathlib
import subprocess
import unittest.mock

# PIP3 modules
import pytest

# local repo modules
import file_utils


#============================================
def _make_script(tmp_path: pathlib.Path, name: str) -> None:
	"""Create a dummy script under tmp_path/tests/<name>."""
	tests_dir = tmp_path / "tests"
	tests_dir.mkdir(exist_ok=True)
	script = tests_dir / name
	script.write_text("# dummy")


#============================================
def test_run_fixer_script_returns_two(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
	"""Return code 2 (fixed by script) -> (2, stderr) with no exception.

	Regression guard for the original cascade bug: exit 2 (successful fix)
	was treated as failure and raised inside a module-scoped fixture.
	"""
	_make_script(tmp_path, "fix_dummy.py")

	fake_result = unittest.mock.MagicMock()
	fake_result.returncode = 2
	fake_result.stderr = "auto-fixed"

	monkeypatch.setattr(subprocess, "run", unittest.mock.MagicMock(return_value=fake_result))
	monkeypatch.setattr(file_utils, "get_repo_root", lambda: str(tmp_path))

	returncode, stderr = file_utils.run_fixer_script("fix_dummy.py", "some_file.py")
	assert returncode == 2
	assert stderr == "auto-fixed"


#============================================
def test_run_fixer_script_returns_unexpected_code(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
	"""Unexpected return code 7 -> (7, stderr) unchanged, no exception."""
	_make_script(tmp_path, "fix_dummy.py")

	fake_result = unittest.mock.MagicMock()
	fake_result.returncode = 7
	fake_result.stderr = "unexpected error"

	monkeypatch.setattr(subprocess, "run", unittest.mock.MagicMock(return_value=fake_result))
	monkeypatch.setattr(file_utils, "get_repo_root", lambda: str(tmp_path))

	returncode, stderr = file_utils.run_fixer_script("fix_dummy.py", "some_file.py")
	assert returncode == 7
	assert stderr == "unexpected error"


#============================================
def test_run_fixer_script_nonexistent_script_raises_runtime_error(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
	"""Nonexistent script path raises RuntimeError; subprocess.run never called."""
	# Point repo root at tmp_path; no tests/no_such_script.py exists there.
	monkeypatch.setattr(file_utils, "get_repo_root", lambda: str(tmp_path))

	spy = unittest.mock.MagicMock()
	monkeypatch.setattr(subprocess, "run", spy)

	with pytest.raises(RuntimeError):
		file_utils.run_fixer_script("no_such_script.py", "some_file.py")

	# subprocess.run must never have been called.
	spy.assert_not_called()


#============================================
def test_run_fixer_script_missing_interpreter_raises_runtime_error(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
	"""subprocess.run raising FileNotFoundError (missing interpreter) is re-raised as RuntimeError."""
	_make_script(tmp_path, "fix_dummy.py")

	monkeypatch.setattr(file_utils, "get_repo_root", lambda: str(tmp_path))
	monkeypatch.setattr(
		subprocess,
		"run",
		unittest.mock.MagicMock(side_effect=FileNotFoundError("python3 not found")),
	)

	with pytest.raises(RuntimeError):
		file_utils.run_fixer_script("fix_dummy.py", "some_file.py")
