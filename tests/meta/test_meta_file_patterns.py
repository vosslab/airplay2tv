"""Tests for META_FILE_PATTERNS: changelog archives are template-meta and never ship.

Covers:
  - Direct is_meta_file behavior for pattern-matched archives vs normal docs.
  - Propagation exclusion via a synthetic tmp_path template tree: a
    docs/CHANGELOG-*.md archive must appear in no bucket; a normal docs file
    must still ship.
"""

# Standard Library
import pathlib

# local repo modules
import repolib.files
import repolib.model


#============================================
# Direct is_meta_file behavior
#============================================

def test_changelog_archive_is_meta() -> None:
	"""A CHANGELOG rotation archive path matches META_FILE_PATTERNS and is meta."""
	# Pattern is docs/CHANGELOG-*.md; this path matches it.
	result = repolib.files.is_meta_file('docs/CHANGELOG-2099-01a.md')
	assert result is True


def test_changelog_archive_different_date_is_meta() -> None:
	"""Any dated archive basename matches the glob pattern and is meta."""
	result = repolib.files.is_meta_file('docs/CHANGELOG-2025-12b.md')
	assert result is True


def test_active_changelog_is_meta() -> None:
	"""The active docs/CHANGELOG.md is in META_FILES and is therefore meta."""
	# docs/CHANGELOG.md lives in META_FILES (exact match), not META_FILE_PATTERNS.
	result = repolib.files.is_meta_file('docs/CHANGELOG.md')
	assert result is True


def test_normal_doc_is_not_meta() -> None:
	"""A normal doc like docs/USAGE.md is not meta."""
	result = repolib.files.is_meta_file('docs/USAGE.md')
	assert result is False


def test_repo_style_doc_is_not_meta() -> None:
	"""A known-propagated doc is not flagged as meta."""
	result = repolib.files.is_meta_file('docs/REPO_STYLE.md')
	assert result is False


#============================================
# Propagation exclusion via synthetic template tree
#============================================

#============================================
def _build_synthetic_template(tmp_path: pathlib.Path) -> None:
	"""Create a minimal synthetic template tree with a normal doc and a changelog archive.

	docs/USAGE.md             -- a normal propagatable doc (should ship)
	docs/CHANGELOG-2099-01a.md -- a changelog archive (must NOT ship)
	docs/CHANGELOG.md         -- the active changelog (must NOT ship; it is in META_FILES)
	"""
	docs_dir = tmp_path / 'docs'
	docs_dir.mkdir(parents=True)
	(docs_dir / 'USAGE.md').write_text('usage content')
	(docs_dir / 'CHANGELOG-2099-01a.md').write_text('archive content')
	(docs_dir / 'CHANGELOG.md').write_text('active changelog')


#============================================
def _all_plan_entries(plan: dict) -> list[str]:
	"""Flatten every file-path bucket in a plan into one list for presence checks."""
	# devel_files holds bare names; all others hold repo-relative paths.
	entries = []
	for bucket in ('overwrite_files', 'noexist_files', 'merge_files', 'test_files'):
		entries.extend(plan[bucket])
	for name in plan['devel_files']:
		entries.append('devel/' + name)
	return entries


def test_changelog_archive_in_no_bucket(tmp_path: pathlib.Path) -> None:
	"""A docs/CHANGELOG-*.md archive appears in no propagation bucket."""
	_build_synthetic_template(tmp_path)
	plan = repolib.files.compute_propagation_plan(str(tmp_path), 'python')
	entries = _all_plan_entries(plan)
	# The archive must not appear in any bucket regardless of bucket or name form.
	assert 'docs/CHANGELOG-2099-01a.md' not in entries


def test_normal_doc_ships_in_plan(tmp_path: pathlib.Path) -> None:
	"""A normal docs/*.md file appears in the propagation plan's overwrite bucket."""
	_build_synthetic_template(tmp_path)
	plan = repolib.files.compute_propagation_plan(str(tmp_path), 'python')
	# docs/USAGE.md is not meta and should be routed to overwrite_files.
	assert 'docs/USAGE.md' in plan['overwrite_files']


def test_active_changelog_in_no_bucket(tmp_path: pathlib.Path) -> None:
	"""docs/CHANGELOG.md (active, in META_FILES) appears in no propagation bucket."""
	_build_synthetic_template(tmp_path)
	plan = repolib.files.compute_propagation_plan(str(tmp_path), 'python')
	entries = _all_plan_entries(plan)
	assert 'docs/CHANGELOG.md' not in entries


def test_archive_exclusion_holds_for_typescript(tmp_path: pathlib.Path) -> None:
	"""The archive exclusion applies regardless of repo_type."""
	_build_synthetic_template(tmp_path)
	plan = repolib.files.compute_propagation_plan(str(tmp_path), 'typescript')
	entries = _all_plan_entries(plan)
	assert 'docs/CHANGELOG-2099-01a.md' not in entries
	# Normal doc still ships to typescript consumers.
	assert 'docs/USAGE.md' in plan['overwrite_files']
