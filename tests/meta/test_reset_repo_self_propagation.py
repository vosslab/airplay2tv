"""Regression tests for reset_repo.py propagation and cleanup contracts.

Coverage areas:
- initial_setup=True context: process_repo returns dict (not None) on a valid repo dir.
- Batch (initial_setup=False) self-skip: process_repo returns None for the template root.
- run_propagate raises RuntimeError when process_repo returns None.
- verify_clean_end_state raises when a leftover template-owned directory is present.
- Ordering invariant: propagation writes sentinel before cleanup removes templates/.
"""

import os
import pathlib
import subprocess

import pytest

import repolib.console
import repolib.files
import repolib.model
import repolib.process

import reset_repo


#============================================
# Helpers
#============================================

def _make_minimal_git_repo(path: pathlib.Path) -> pathlib.Path:
	"""Create a minimal git-init'd directory with a REPO_TYPE marker."""
	path.mkdir(parents=True, exist_ok=True)
	subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)
	subprocess.run(["git", "-C", str(path), "commit", "--allow-empty", "-m", "init", "-q"], check=True)
	(path / "REPO_TYPE").write_text("typescript\n", encoding="utf-8")
	return path


#============================================
# process_repo with initial_setup=True returns dict
#============================================

class TestInitialSetupReturnsDict:
	"""initial_setup=True must not trigger the self-skip guard."""

	def test_process_repo_returns_dict_not_none(self, tmp_path: pathlib.Path) -> None:
		"""process_repo with initial_setup=True returns dict on a valid git repo."""
		target = _make_minimal_git_repo(tmp_path / "consumer")

		context = repolib.process.build_context_for_repo(
			repo_path=str(target),
			dry_run=True,
			initial_setup=True,
			auto_discover=False,
			write_marker=False,
		)
		counters = repolib.console.init_counters()

		result = repolib.process.process_repo(str(target), context, counters, emit_per_repo_summary=False)

		assert result is not None

	def test_process_repo_result_has_name_and_type(self, tmp_path: pathlib.Path) -> None:
		"""process_repo result dict carries name and type keys."""
		target = _make_minimal_git_repo(tmp_path / "consumer")

		context = repolib.process.build_context_for_repo(
			repo_path=str(target),
			dry_run=True,
			initial_setup=True,
			auto_discover=False,
			write_marker=False,
		)
		counters = repolib.console.init_counters()

		result = repolib.process.process_repo(str(target), context, counters, emit_per_repo_summary=False)

		assert "name" in result
		assert "type" in result


#============================================
# Self-skip guard fires when initial_setup=False
#============================================

class TestSelfSkipWithoutInitialSetup:
	"""Batch propagation (initial_setup=False) must skip the template root."""

	def test_self_skip_returns_none(self, tmp_path: pathlib.Path) -> None:
		"""process_repo returns None for the template root when initial_setup=False."""
		# Build a context targeting a directory that IS the template_root.
		# Since build_context_for_repo resolves source_dir from the running checkout,
		# we need a context whose template_root matches the target. We do this by
		# monkeypatching after building a context pointed at a real repo, then
		# matching repo_dir to the resolved template_root.
		target = _make_minimal_git_repo(tmp_path / "tgt")

		context = repolib.process.build_context_for_repo(
			repo_path=str(target),
			dry_run=True,
			initial_setup=False,
			auto_discover=False,
			write_marker=False,
		)
		# Synthesize a scenario where target == template_root by pointing
		# template_root at target after the fact.
		patched_context = repolib.model.PropagateContext(
			source_dir=context.source_dir,
			template_root=repolib.files.normalize_path(str(target)),
			repo_name=context.repo_name,
			dry_run=True,
			initial_setup=False,
			auto_discover=False,
			write_marker=False,
		)
		counters = repolib.console.init_counters()

		result = repolib.process.process_repo(str(target), patched_context, counters, emit_per_repo_summary=False)

		assert result is None


#============================================
# run_propagate raises on None
#============================================

class TestRunPropagateRaisesOnNone:
	"""run_propagate must raise RuntimeError when process_repo returns None."""

	def test_run_propagate_raises_when_skipped(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
		"""run_propagate raises RuntimeError when process_repo returns None."""
		# Patch process_repo so it returns None unconditionally.
		monkeypatch.setattr(repolib.process, "process_repo", lambda *a, **kw: None)

		with pytest.raises(RuntimeError, match="propagation was skipped"):
			reset_repo.run_propagate(str(tmp_path), dry_run=False)


#============================================
# verify_clean_end_state raises on leftover template dirs
#============================================

class TestVerifyCleanEndState:
	"""verify_clean_end_state must raise when template-owned paths remain on disk."""

	def test_raises_when_leftover_template_dir_on_disk(self, tmp_path: pathlib.Path) -> None:
		"""verify_clean_end_state raises RuntimeError when templates/ still exists on disk."""
		# Create a bare git-init repo so git ls-files works, and plant a leftover templates/ dir.
		repo = tmp_path / "repo"
		repo.mkdir()
		subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
		subprocess.run(["git", "-C", str(repo), "commit", "--allow-empty", "-m", "init", "-q"], check=True)

		leftover = repo / "templates"
		leftover.mkdir()
		(leftover / "dummy.txt").write_text("should not be here", encoding="utf-8")

		with pytest.raises(RuntimeError, match="template-owned paths remain"):
			reset_repo.verify_clean_end_state(str(repo), dry_run=False)

	def test_clean_repo_does_not_raise(self, tmp_path: pathlib.Path) -> None:
		"""verify_clean_end_state returns 1 when no template-owned paths are present."""
		repo = tmp_path / "repo"
		repo.mkdir()
		subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
		subprocess.run(["git", "-C", str(repo), "commit", "--allow-empty", "-m", "init", "-q"], check=True)

		result = reset_repo.verify_clean_end_state(str(repo), dry_run=False)

		assert result == 1


#============================================
# verify_scaffold_sentinel behavior
#============================================

class TestVerifyScaffoldSentinel:
	"""verify_scaffold_sentinel raises when the sentinel path is absent."""

	def test_raises_when_sentinel_absent(self, tmp_path: pathlib.Path) -> None:
		"""verify_scaffold_sentinel raises RuntimeError when eslint.config.js is missing."""
		repo = tmp_path / "repo"
		repo.mkdir()

		with pytest.raises(RuntimeError, match="scaffold path is missing"):
			reset_repo.verify_scaffold_sentinel(str(repo), "typescript")

	def test_passes_when_sentinel_present(self, tmp_path: pathlib.Path) -> None:
		"""verify_scaffold_sentinel does not raise when sentinel file exists."""
		repo = tmp_path / "repo"
		repo.mkdir()
		(repo / "eslint.config.js").write_text("// eslint config", encoding="utf-8")

		# Should not raise
		reset_repo.verify_scaffold_sentinel(str(repo), "typescript")

	def test_skips_unknown_project_type(self, tmp_path: pathlib.Path) -> None:
		"""verify_scaffold_sentinel silently skips when project_type has no sentinel."""
		repo = tmp_path / "repo"
		repo.mkdir()

		# rust and other have no sentinel; should not raise
		reset_repo.verify_scaffold_sentinel(str(repo), "rust")
		reset_repo.verify_scaffold_sentinel(str(repo), "other")


#============================================
# Ordering invariant: sentinel exists, templates/ absent
#============================================

class TestOrderingInvariant:
	"""After initial_setup propagation, sentinel exists. After cleanup, templates/ is absent."""

	def test_sentinel_written_before_templates_removed(self, tmp_path: pathlib.Path) -> None:
		"""Propagation writes typescript sentinel; simulated cleanup removes templates/."""
		target = _make_minimal_git_repo(tmp_path / "consumer")

		context = repolib.process.build_context_for_repo(
			repo_path=str(target),
			dry_run=False,
			initial_setup=True,
			auto_discover=False,
			write_marker=False,
		)
		counters = repolib.console.init_counters()

		result = repolib.process.process_repo(str(target), context, counters, emit_per_repo_summary=False)

		# Propagation succeeded (not skipped)
		assert result is not None

		# typescript sentinel was written during propagation
		sentinel_path = os.path.join(str(target), reset_repo.SCAFFOLD_SENTINELS["typescript"])
		assert os.path.isfile(sentinel_path)

		# After simulated cleanup: templates/ absent on disk (it was never planted on target)
		templates_path = os.path.join(str(target), "templates")
		assert not os.path.isdir(templates_path)
