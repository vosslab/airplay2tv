"""Behavioral tests for file_utils.clear_stale_reports and its once-per-process guard."""

# Standard Library
import pathlib

# PIP3 modules
import pytest

# local repo modules
import file_utils


#============================================
@pytest.fixture()
def fake_root(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
	"""
	Redirect get_repo_root to a tmp directory and reset the guard before each test.

	Monkeypatches file_utils.get_repo_root (the module attribute, not the lru_cache
	entry) so clear_stale_reports globs the tmp directory instead of the real repo
	root. The lru_cache on the real get_repo_root is bypassed because we replace the
	name in the file_utils namespace, not the cached function itself.

	Also resets _STALE_REPORTS_CLEARED to False so every test starts with a clean
	guard state regardless of execution order.
	"""
	# Reset guard flag before the test so each test starts fresh.
	file_utils._STALE_REPORTS_CLEARED = False
	# Replace get_repo_root in the file_utils namespace with a stub returning tmp_path.
	monkeypatch.setattr(file_utils, "get_repo_root", lambda: str(tmp_path))
	yield tmp_path
	# Restore guard flag after the test to avoid leaking state to other tests.
	file_utils._STALE_REPORTS_CLEARED = False


#============================================
class TestClearStaleReports:
	"""Behavioral tests pinning the contract of clear_stale_reports."""

	def test_removes_report_txt_files(self, fake_root: pathlib.Path) -> None:
		"""First call removes all report_*.txt files in the repo root."""
		# Plant two stale report files.
		report_a = fake_root / "report_alpha.txt"
		report_b = fake_root / "report_beta.txt"
		report_a.write_text("stale\n", encoding="utf-8")
		report_b.write_text("stale\n", encoding="utf-8")
		# Call should unlink both.
		file_utils.clear_stale_reports()
		assert not report_a.exists()
		assert not report_b.exists()

	def test_guard_makes_second_call_noop(self, fake_root: pathlib.Path) -> None:
		"""After the first call the guard blocks re-cleaning; a newly planted file survives."""
		# First call runs cleanup and sets the guard.
		file_utils.clear_stale_reports()
		# Plant a new report AFTER the first call.
		new_report = fake_root / "report_newone.txt"
		new_report.write_text("should survive\n", encoding="utf-8")
		# Second call must be a no-op because the guard is set.
		file_utils.clear_stale_reports()
		assert new_report.exists()

	def test_zero_matches_is_harmless(self, fake_root: pathlib.Path) -> None:
		"""Calling with no report_*.txt files in the root does not raise."""
		# tmp_path is empty; should complete without error.
		file_utils.clear_stale_reports()
		# Guard should be set after a successful no-match call.
		assert file_utils._STALE_REPORTS_CLEARED is True

	def test_directory_named_like_report_is_not_unlinked(self, fake_root: pathlib.Path) -> None:
		"""A directory whose name matches report_*.txt is skipped, not unlinked."""
		# Create a directory that matches the glob pattern.
		fake_dir = fake_root / "report_dir.txt"
		fake_dir.mkdir()
		# Should not raise and should leave the directory intact.
		file_utils.clear_stale_reports()
		assert fake_dir.exists()
		assert fake_dir.is_dir()
