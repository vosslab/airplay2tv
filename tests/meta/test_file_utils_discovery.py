import os
import pathlib

import pytest

import file_utils


#============================================
def write_files(root: str, rel_paths: list[str]) -> None:
	"""
	Create empty files at the given repo-relative paths under root.
	"""
	for rel in rel_paths:
		abs_path = os.path.join(root, rel)
		os.makedirs(os.path.dirname(abs_path), exist_ok=True)
		with open(abs_path, "w", encoding="utf-8") as handle:
			handle.write("")


#============================================
def stub_git_listers(monkeypatch: pytest.MonkeyPatch, tracked: list[str]) -> None:
	"""
	Replace the git lister discover_files relies on with a deterministic stub.

	The stub returns repo-relative paths, matching the real list function,
	so discover_files joins them to repo_root the same way it would in
	production. This keeps the test offline and deterministic.
	"""
	def fake_tracked(repo_root: str, patterns: list | None = None, error_message: str | None = None) -> list[str]:
		return list(tracked)

	monkeypatch.setattr(file_utils, "list_tracked_files", fake_tracked)


#============================================
def stub_registry(monkeypatch: pytest.MonkeyPatch, registry: dict) -> None:
	"""
	Replace the repo-local hygiene-filter registry loader with a stub.

	discover_files reads Layer 2 patterns through _load_repo_hygiene_filters,
	which normally imports tests/conftest.py REPO_HYGIENE_FILTERS. Patching the
	loader keeps the test deterministic and independent of the real conftest.
	"""
	monkeypatch.setattr(
		file_utils, "_load_repo_hygiene_filters", lambda: registry,
	)


#============================================
def test_path_has_skip_dir_full_segment_match() -> None:
	"""
	path_has_skip_dir matches a full segment, never a substring.
	"""
	assert file_utils.path_has_skip_dir("legacy/foo.py") is True
	assert file_utils.path_has_skip_dir("notlegacy/foo.py") is False


#============================================
def test_path_has_skip_dir_separator_normalization() -> None:
	"""
	path_has_skip_dir normalizes backslash separators before splitting.
	"""
	assert file_utils.path_has_skip_dir("legacy\\foo.py") is True


#============================================
def test_discover_files_all_scope_extensions(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
	"""
	Discovery applies the case-insensitive extension filter over all tracked files.
	"""
	root = str(tmp_path)
	rel_paths = ["a.py", "b.PY", "c.txt", "legacy/d.py"]
	write_files(root, rel_paths)
	stub_git_listers(monkeypatch, tracked=rel_paths)

	result = file_utils.discover_files(extensions=(".py",), repo_root=root)

	rel_result = [os.path.relpath(p, root).replace("\\", "/") for p in result]
	# b.PY is kept via case-insensitive match; legacy/d.py is skipped.
	assert rel_result == ["a.py", "b.PY"]


#============================================
def test_discover_files_extra_filter_receives_relative_posix(
	tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
	"""
	extra_filter receives exactly the repo-relative POSIX path form.
	"""
	root = str(tmp_path)
	rel_paths = ["tests/foo.py"]
	write_files(root, rel_paths)
	stub_git_listers(monkeypatch, tracked=rel_paths)

	captured = []

	def capture_keep(rel: str) -> bool:
		captured.append(rel)
		return True

	file_utils.discover_files(extra_filter=capture_keep, repo_root=root)

	# The predicate sees the repo-relative POSIX form, not an absolute path.
	assert captured == ["tests/foo.py"]


#============================================
def test_discover_files_returns_absolute_paths(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
	"""
	discover_files returns absolute paths even though extra_filter is relative.
	"""
	root = str(tmp_path)
	rel_paths = ["only.py"]
	write_files(root, rel_paths)
	stub_git_listers(monkeypatch, tracked=rel_paths)

	result = file_utils.discover_files(extensions=(".py",), repo_root=root)

	assert os.path.isabs(result[0])
	assert result[0] == os.path.normpath(os.path.join(root, "only.py"))


#============================================
def test_discover_files_optional_repo_root(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
	"""
	When repo_root is omitted, discover_files calls get_repo_root internally.

	Monkeypatches get_repo_root to return a controlled tmp directory and stubs
	the git lister so the test is offline and deterministic.
	"""
	root = str(tmp_path)
	rel_paths = ["src/hello.py"]
	write_files(root, rel_paths)
	stub_git_listers(monkeypatch, tracked=rel_paths)
	# Redirect get_repo_root so discover_files uses tmp_path as the root.
	monkeypatch.setattr(file_utils, "get_repo_root", lambda: root)

	# Call with NO repo_root argument to exercise the optional-root path.
	result = file_utils.discover_files(extensions=(".py",))

	# The file was discovered under the monkeypatched root, not the real repo.
	assert result[0] == os.path.normpath(os.path.join(root, "src/hello.py"))


#============================================
def test_repo_hygiene_all_excludes_for_any_test_key(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
	"""
	An "all" pattern excludes a matching file regardless of test_key.
	"""
	root = str(tmp_path)
	rel_paths = ["TEMPLATE.py", "keep.py"]
	write_files(root, rel_paths)
	stub_git_listers(monkeypatch, tracked=rel_paths)
	stub_registry(monkeypatch, {"all": ["TEMPLATE.py"]})

	# A test_key unrelated to the "all" key still gets the "all" exclusion.
	result = file_utils.discover_files(
		extensions=(".py",), test_key="ascii_compliance", repo_root=root,
	)

	rel_result = [os.path.relpath(p, root).replace("\\", "/") for p in result]
	assert rel_result == ["keep.py"]


#============================================
def test_repo_hygiene_per_key_excludes_only_with_that_key(
	tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
	"""
	A per-test-key pattern excludes only when that test_key is passed.
	"""
	root = str(tmp_path)
	rel_paths = ["scratch.py", "keep.py"]
	write_files(root, rel_paths)
	stub_git_listers(monkeypatch, tracked=rel_paths)
	stub_registry(monkeypatch, {"pyflakes_code_lint": ["scratch.py"]})

	# With the matching test_key, scratch.py is excluded.
	matched = file_utils.discover_files(
		extensions=(".py",), test_key="pyflakes_code_lint", repo_root=root,
	)
	matched_rel = [os.path.relpath(p, root).replace("\\", "/") for p in matched]
	assert matched_rel == ["keep.py"]


#============================================
def test_repo_hygiene_non_matching_key_keeps_file(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
	"""
	A non-matching test_key leaves a per-test-key file in place.
	"""
	root = str(tmp_path)
	rel_paths = ["scratch.py", "keep.py"]
	write_files(root, rel_paths)
	stub_git_listers(monkeypatch, tracked=rel_paths)
	stub_registry(monkeypatch, {"pyflakes_code_lint": ["scratch.py"]})

	# A different test_key does not see the pyflakes_code_lint exclusion.
	result = file_utils.discover_files(
		extensions=(".py",), test_key="ascii_compliance", repo_root=root,
	)
	rel_result = [os.path.relpath(p, root).replace("\\", "/") for p in result]
	assert rel_result == ["keep.py", "scratch.py"]


#============================================
def test_repo_hygiene_recursive_glob_excludes_subtree(
	tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
	"""
	A "dir/**" pattern excludes a whole subtree via fnmatch.fnmatchcase.
	"""
	root = str(tmp_path)
	rel_paths = ["temp_scripts/a.py", "temp_scripts/sub/b.py", "keep.py"]
	write_files(root, rel_paths)
	stub_git_listers(monkeypatch, tracked=rel_paths)
	stub_registry(monkeypatch, {"all": ["temp_scripts/**"]})

	result = file_utils.discover_files(extensions=(".py",), repo_root=root)

	rel_result = [os.path.relpath(p, root).replace("\\", "/") for p in result]
	assert rel_result == ["keep.py"]
