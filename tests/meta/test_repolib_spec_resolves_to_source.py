"""Test that every propagation plan entry has a corresponding source file."""
import os

import file_utils
import repolib.model
import repolib.files


def test_repolib_spec_all_entries_resolve_to_source() -> None:
	"""Every propagation plan entry across all buckets resolves to an existing source file."""
	repo_root = file_utils.get_repo_root()

	for repo_type in repolib.model.REPO_TYPE_ORDER:
		plan = repolib.files.compute_propagation_plan(repo_root, repo_type)
		for bucket, entries in plan.items():
			if bucket == 'gitignore_block':
				continue
			for entry in entries:
				source_path = repolib.model.source_path_for_bucket(repo_root, bucket, entry, repo_type=repo_type)
				assert os.path.isfile(source_path), f"[{repo_type}] {bucket} {entry!r}: {source_path}"
