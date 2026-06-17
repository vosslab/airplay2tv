"""Behavioral tests for the shared report/assert harness in file_utils."""

# Standard Library
import ast
import pathlib

# PIP3 modules
import pytest

# local repo modules
import file_utils


#============================================
@pytest.fixture()
def fake_root(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
	"""
	Redirect get_repo_root to a tmp directory and reset the cleanup guard.

	Monkeypatches the file_utils.get_repo_root module attribute (not the lru_cache
	entry) so report writes and rel_to_root resolve against tmp_path instead of the
	real repo root. Also resets _STALE_REPORTS_CLEARED before and after so guard
	state never leaks between tests.

	Args:
		tmp_path: Pytest-provided temporary directory.
		monkeypatch: Pytest monkeypatch fixture.

	Returns:
		pathlib.Path: The tmp directory acting as the fake repo root.
	"""
	# Reset guard flag before the test so each test starts fresh.
	file_utils._STALE_REPORTS_CLEARED = False
	# Replace get_repo_root in the file_utils namespace with a tmp_path stub.
	monkeypatch.setattr(file_utils, "get_repo_root", lambda: str(tmp_path))
	yield tmp_path
	# Restore guard flag after the test to avoid leaking state to other tests.
	file_utils._STALE_REPORTS_CLEARED = False


#============================================
def _no_typing_check(rel: str, tree: ast.Module) -> list[str]:
	"""
	Minimal AST check: flag any `import typing` node.

	Args:
		rel: Repo-relative POSIX path for the violation message.
		tree: Parsed ast.Module.

	Returns:
		list[str]: One line per typing import (empty when clean).
	"""
	lines = []
	for node in ast.walk(tree):
		if isinstance(node, ast.Import):
			for alias in node.names:
				if alias.name == "typing":
					lines.append(f"{rel}:{node.lineno}: typing import")
	return lines


#============================================
class TestCollectPythonViolations:
	"""Behavioral tests for collect_python_violations."""

	def test_syntax_error_records_one_entry_and_skips_check(
		self, fake_root: pathlib.Path
	) -> None:
		"""A SyntaxError yields exactly one entry and the AST check is never run."""
		bad = fake_root / "broken.py"
		bad.write_text("def f(:\n", encoding="utf-8")

		# The check must never run on an unparsable file; trip a flag if it does.
		ran = []

		def check(rel: str, tree: ast.Module) -> list[str]:
			ran.append(rel)
			return []

		result = file_utils.collect_python_violations([str(bad)], check)
		rel = file_utils.rel_to_root(str(bad))
		assert list(result.keys()) == [rel]
		assert len(result[rel]) == 1
		assert result[rel][0].startswith(f"{rel}: SyntaxError: ")
		assert ran == []

	def test_clean_file_with_check_lines_is_included(self, fake_root: pathlib.Path) -> None:
		"""A parseable file whose check returns lines is included in the result."""
		src = fake_root / "uses_typing.py"
		src.write_text("import typing\n", encoding="utf-8")
		result = file_utils.collect_python_violations([str(src)], _no_typing_check)
		rel = file_utils.rel_to_root(str(src))
		assert rel in result
		assert result[rel] == [f"{rel}:1: typing import"]

	def test_clean_file_with_no_lines_is_omitted(self, fake_root: pathlib.Path) -> None:
		"""A parseable file whose check returns no lines is omitted from the result."""
		src = fake_root / "clean.py"
		src.write_text("import os\n", encoding="utf-8")
		result = file_utils.collect_python_violations([str(src)], _no_typing_check)
		assert result == {}


#============================================
class TestCollectFileViolations:
	"""Behavioral tests for collect_file_violations (no parsing)."""

	def test_check_receives_relative_path_and_lines_are_kept(
		self, fake_root: pathlib.Path
	) -> None:
		"""The check receives the repo-relative path; files with lines are kept."""
		target = fake_root / "data.txt"
		target.write_text("anything\n", encoding="utf-8")
		seen = []

		def check(rel: str) -> list[str]:
			seen.append(rel)
			return [f"{rel}: flagged"]

		result = file_utils.collect_file_violations([str(target)], check)
		rel = file_utils.rel_to_root(str(target))
		assert seen == [rel]
		assert result == {rel: [f"{rel}: flagged"]}

	def test_files_with_no_lines_are_omitted(self, fake_root: pathlib.Path) -> None:
		"""Files whose check returns no lines are omitted from the result."""
		target = fake_root / "ok.txt"
		target.write_text("fine\n", encoding="utf-8")

		def check(rel: str) -> list[str]:
			return []

		result = file_utils.collect_file_violations([str(target)], check)
		assert result == {}


#============================================
class TestFormatViolationReport:
	"""Behavioral tests for format_violation_report and its empty-dict invariant."""

	def test_empty_dict_returns_empty_list(self) -> None:
		"""INVARIANT: an empty dict returns [] -- never [header] alone."""
		result = file_utils.format_violation_report("hdr", {})
		assert result == []

	def test_non_empty_is_header_first_then_sorted_keys(self) -> None:
		"""Non-empty dict puts the header first, then each file's lines in sorted key order."""
		violations = {
			"zeta.py": ["zeta.py: z1"],
			"alpha.py": ["alpha.py: a1", "alpha.py: a2"],
		}
		result = file_utils.format_violation_report("the header", violations)
		assert result == [
			"the header",
			"alpha.py: a1",
			"alpha.py: a2",
			"zeta.py: z1",
		]


#============================================
class TestWriteReportLines:
	"""Behavioral tests for write_report_lines (pure write, no purge)."""

	def test_writes_one_trailing_newline_per_line(self, fake_root: pathlib.Path) -> None:
		"""Each line gets exactly one trailing newline and the file is truncate-written."""
		path = file_utils.write_report_lines("report_demo.txt", ["one", "two"])
		written = pathlib.Path(path).read_text(encoding="utf-8")
		assert written == "one\ntwo\n"

	def test_truncates_prior_content(self, fake_root: pathlib.Path) -> None:
		"""A second write replaces, not appends to, the prior body."""
		file_utils.write_report_lines("report_demo.txt", ["old", "stale", "lines"])
		path = file_utils.write_report_lines("report_demo.txt", ["fresh"])
		written = pathlib.Path(path).read_text(encoding="utf-8")
		assert written == "fresh\n"


#============================================
class TestFormatViolationAssertMessage:
	"""Behavioral tests for format_violation_assert_message."""

	def test_message_has_count_path_lines_and_report_pointer(
		self, fake_root: pathlib.Path
	) -> None:
		"""The message reports the count, the path, the joined lines, and the report pointer."""
		lines = ["foo.py:1: bad", "foo.py:2: worse"]
		message = file_utils.format_violation_assert_message(
			"foo.py", lines, "report_demo.txt"
		)
		report_rel = file_utils.rel_to_root(file_utils.report_path("report_demo.txt"))
		# Count and path appear in the message head.
		assert "2 violation(s) in foo.py" in message
		# The repo-relative report pointer appears in the message tail.
		assert report_rel in message


#============================================
class TestRelId:
	"""Behavioral tests for the rel_id parametrize-id callback."""

	def test_rel_id_returns_repo_relative_path(self, fake_root: pathlib.Path) -> None:
		"""rel_id returns the repo-relative POSIX path for an absolute path."""
		target = fake_root / "sub" / "thing.py"
		target.parent.mkdir(parents=True)
		target.write_text("import os\n", encoding="utf-8")
		assert file_utils.rel_id(str(target)) == "sub/thing.py"
