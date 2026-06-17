"""Tests for load_deprecation_list() and the meta/propagation/ files.

Covers loader round-trip, real-file loads, entry-shape sanity, and
propagation-plan exclusion (meta/propagation/ must never ship to consumers).
"""

import os
import pathlib

import repolib.files
import repolib.model


# ============================================
# Loader behavior
# ============================================
def test_load_deprecation_list_round_trip(tmp_path: pathlib.Path) -> None:
	"""Loader strips blanks and comment lines, returns the remaining entries."""
	fixture = tmp_path / 'sample.txt'
	fixture.write_text('# comment\n\nfoo\nbar\n# trailing\n')

	# Use absolute path with the helper.
	result = repolib.files.load_deprecation_list(str(fixture), os.path.dirname(str(fixture)))
	assert result == ['foo', 'bar']


def test_load_deprecation_list_skips_indented_comments(tmp_path: pathlib.Path) -> None:
	"""Lines with leading whitespace before # are still treated as comments."""
	fixture = tmp_path / 'indented.txt'
	fixture.write_text('foo\n   # indented comment\nbar\n')

	result = repolib.files.load_deprecation_list(str(fixture), os.path.dirname(str(fixture)))
	assert result == ['foo', 'bar']


# ============================================
# Real-file loads
# ============================================
def test_deprecated_test_scripts_loaded() -> None:
	"""Real file loads as a non-empty list."""
	assert len(repolib.files.DEPRECATED_TEST_SCRIPTS) > 0


def test_deprecated_gitignore_entries_loaded() -> None:
	"""Real file loads as a non-empty list."""
	assert len(repolib.files.DEPRECATED_GITIGNORE_ENTRIES) > 0


# ============================================
# Entry-shape sanity (catches silent typos)
# ============================================
def test_deprecated_test_scripts_entries_are_bare_filenames() -> None:
	"""Test-script entries must be bare filenames: no path separators, no whitespace."""
	for entry in repolib.files.DEPRECATED_TEST_SCRIPTS:
		assert entry, 'Empty entry in DEPRECATED_TEST_SCRIPTS'
		assert '/' not in entry, f'Path separator in test entry: {entry!r}'
		assert '\\' not in entry, f'Backslash in test entry: {entry!r}'
		assert entry == entry.strip(), f'Leading/trailing whitespace: {entry!r}'


def test_deprecated_gitignore_entries_have_no_whitespace() -> None:
	"""Gitignore entries must have no leading/trailing whitespace."""
	for entry in repolib.files.DEPRECATED_GITIGNORE_ENTRIES:
		assert entry, 'Empty entry in DEPRECATED_GITIGNORE_ENTRIES'
		assert entry == entry.strip(), f'Leading/trailing whitespace: {entry!r}'


# ============================================
# Propagation-plan exclusion (meta/propagation/ must never ship)
# ============================================
def _flatten_plan(plan: dict[str, list[str]]) -> list[str]:
	"""Flatten every bucket into one list of strings for membership checks."""
	flat = []
	for bucket in ('overwrite_files', 'noexist_files', 'devel_files', 'test_files'):
		flat.extend(plan.get(bucket, []))
	flat.extend(plan.get('gitignore_block', []))
	return flat


def test_meta_propagation_excluded_from_plan() -> None:
	"""compute_propagation_plan() must not include any meta/propagation/ entry."""
	template_root = repolib.files.TEMPLATE_ROOT
	for repo_type in repolib.model.REPO_TYPE_ORDER:
		plan = repolib.files.compute_propagation_plan(template_root, repo_type)
		flat = _flatten_plan(plan)
		# No entry should contain 'meta/propagation' or just 'propagation' (devel-bucket bare name).
		for entry in flat:
			assert 'propagation' not in entry, (
				f'meta/propagation/ leaked into plan for {repo_type!r}: {entry!r}'
			)
		# Also confirm the deprecation filenames do not appear as bare devel-bucket names.
		assert 'deprecated_tests.txt' not in plan.get('devel_files', [])
		assert 'deprecated_gitignore.txt' not in plan.get('devel_files', [])


def test_load_deprecation_lists_test_file_not_in_plan() -> None:
	"""This test file itself lives under tests/meta/ and must not repolib."""
	template_root = repolib.files.TEMPLATE_ROOT
	plan = repolib.files.compute_propagation_plan(template_root, 'python')
	for entry in plan.get('test_files', []):
		assert 'test_load_deprecation_lists' not in entry, (
			f'tests/meta/test_load_deprecation_lists.py leaked into plan: {entry!r}'
		)
