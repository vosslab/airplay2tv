"""Tests for the propagate_style_guides.py CLI surface and source-vs-target safety.

Coverage areas:
- Source-vs-target: build_context_for_repo target_dir is never the same as source_dir.
"""

import pathlib

import repolib.process


#============================================
# Source-vs-target safety
#============================================

def test_build_context_target_is_not_source(tmp_path: pathlib.Path) -> None:
	"""The target repo path passed to process_repo is distinct from source_dir."""
	target_repo = tmp_path / "consumer_repo"
	target_repo.mkdir()

	context = repolib.process.build_context_for_repo(
		repo_path=str(target_repo),
		dry_run=True,
		initial_setup=False,
		auto_discover=False,
		write_marker=False,
	)

	# source and target must never be the same directory
	assert context.source_dir != str(target_repo.resolve())
