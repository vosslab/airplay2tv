"""META leak detector across every bucket of every repo type plan."""

import os

import pytest

import file_utils
import repolib.files
import repolib.model

TEMPLATE_ROOT = file_utils.get_repo_root()

# Every consumer type (from the shared ordered set) plus the 'unknown' pseudo-type,
# so a future type is covered here without editing this list.
REPO_TYPES = repolib.model.REPO_TYPE_ORDER + ('unknown',)

# Buckets that store repo-relative paths verbatim.
PATH_BUCKETS = ('overwrite_files', 'noexist_files', 'merge_files', 'test_files')
# devel_files stores flat basenames (devel/ prefix dropped).
BASENAME_BUCKETS = ('devel_files',)


# 'tools' is in META_DIRS to keep the ROOT tools/ (template infrastructure)
# from shipping via the universal walk. But the typed-overlay standard is that
# every file under templates/<type>/ ships at its relative path, including
# tools/ subpaths (e.g. tools/sync_typescript_package_pins.py for typescript).
# Those legitimately land in overwrite_files at a consumer tools/ path, so the
# META_DIRS-traversal leak check excludes 'tools'. META_FILES protection (which
# guards consumer README.md, VERSION, etc.) still applies to every entry.
TYPED_OVERLAY_ALLOWED_META_DIRS = frozenset({'tools'})


def _assert_entry_not_meta(entry: str, bucket_name: str, repo_type: str) -> None:
	"""Per-entry check. Fails the test with a useful message on META leak."""
	basename = os.path.basename(entry)
	assert entry not in repolib.model.META_FILES, (
		f"META leak: {entry!r} (full rel-path) in plan[{bucket_name!r}] for repo_type={repo_type!r}"
	)
	assert basename not in repolib.model.META_FILES, (
		f"META leak: {entry!r} (basename={basename!r}) in plan[{bucket_name!r}] for repo_type={repo_type!r}"
	)
	for part in entry.split(os.sep):
		if part in TYPED_OVERLAY_ALLOWED_META_DIRS:
			continue
		assert part not in repolib.model.META_DIRS, (
			f"META_DIRS leak: {entry!r} traverses {part!r} in plan[{bucket_name!r}] for repo_type={repo_type!r}"
		)


@pytest.mark.parametrize('repo_type', REPO_TYPES)
def test_no_meta_leak_any_bucket(repo_type: str) -> None:
	"""No plan entry across any bucket may match META_FILES or traverse META_DIRS."""
	plan = repolib.files.compute_propagation_plan(TEMPLATE_ROOT, repo_type)
	for bucket in PATH_BUCKETS + BASENAME_BUCKETS:
		for entry in plan.get(bucket, []):
			_assert_entry_not_meta(entry, bucket, repo_type)


def test_assert_not_meta_helper_raises_on_readme() -> None:
	"""The helper that powers in-code dispatcher checks must fail loud on a known META file."""
	with pytest.raises(RuntimeError):
		repolib.files.assert_not_meta('README.md')


def test_assert_not_meta_helper_raises_on_meta_dir() -> None:
	"""The helper must fail when a path traverses any META_DIRS component."""
	with pytest.raises(RuntimeError):
		repolib.files.assert_not_meta(os.path.join('meta', 'something.py'))


def test_assert_not_meta_helper_accepts_legit_path() -> None:
	"""The helper must not raise on a path the propagator legitimately ships."""
	repolib.files.assert_not_meta('docs/REPO_STYLE.md')
	repolib.files.assert_not_meta('CLAUDE.md')
