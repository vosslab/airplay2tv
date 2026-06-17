"""Unit tests for propagate_style_guides.py helper functions (Phase A)."""

import os
import stat
import pathlib

import pytest

import repolib.console
import repolib.files
import repolib.model
import repolib.repo
import repolib.process


class TestCopyFileSafe:
	"""Test copy_file_safe helper."""

	def test_copy_file_safe_real_run(self, tmp_path: pathlib.Path) -> None:
		"""Test actual file copy."""
		src = tmp_path / "source.txt"
		dst = tmp_path / "dest.txt"
		src.write_text("hello", encoding='utf-8')

		result = repolib.files.copy_file_safe(str(src), str(dst), dry_run=False)

		assert result is True
		assert dst.read_text(encoding='utf-8') == "hello"

	def test_copy_file_safe_dry_run(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
		"""Test dry-run mode."""
		src = tmp_path / "source.txt"
		dst = tmp_path / "dest.txt"
		src.write_text("hello", encoding='utf-8')

		result = repolib.files.copy_file_safe(str(src), str(dst), dry_run=True)

		assert result is False
		assert not dst.exists()
		captured = capsys.readouterr()
		assert "dry run" in captured.out
		assert "copy" in captured.out

	def test_copy_file_safe_preserves_executable_bit(self, tmp_path: pathlib.Path) -> None:
		"""Test that executable bit is preserved."""
		src = tmp_path / "script.sh"
		dst = tmp_path / "script_copy.sh"
		src.write_text("#!/bin/bash\necho hello", encoding='utf-8')

		# Make source executable
		os.chmod(src, os.stat(src).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

		repolib.files.copy_file_safe(str(src), str(dst), dry_run=False)

		dst_mode = os.stat(dst).st_mode
		assert dst_mode & stat.S_IXUSR == stat.S_IXUSR
		assert dst_mode & stat.S_IXGRP == stat.S_IXGRP
		assert dst_mode & stat.S_IXOTH == stat.S_IXOTH

	def test_copy_file_safe_custom_action(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
		"""Test custom action parameter in dry-run."""
		src = tmp_path / "source.txt"
		dst = tmp_path / "dest.txt"
		src.write_text("hello", encoding='utf-8')

		repolib.files.copy_file_safe(str(src), str(dst), dry_run=True, action='update')

		captured = capsys.readouterr()
		assert "update" in captured.out


class TestMakeDirSafe:
	"""Test make_dir_safe helper."""

	def test_make_dir_safe_real_run(self, tmp_path: pathlib.Path) -> None:
		"""Test actual directory creation."""
		new_dir = tmp_path / "newdir"
		assert not new_dir.exists()

		result = repolib.files.make_dir_safe(str(new_dir), dry_run=False)

		assert result is True
		assert new_dir.is_dir()

	def test_make_dir_safe_dry_run(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
		"""Test dry-run mode."""
		new_dir = tmp_path / "newdir"
		assert not new_dir.exists()

		result = repolib.files.make_dir_safe(str(new_dir), dry_run=True)

		assert result is False
		assert not new_dir.exists()
		captured = capsys.readouterr()
		assert "dry run" in captured.out
		assert "create" in captured.out

	def test_make_dir_safe_idempotent(self, tmp_path: pathlib.Path) -> None:
		"""Test that creating an existing dir succeeds (exist_ok=True)."""
		new_dir = tmp_path / "newdir"
		new_dir.mkdir()

		# Should not raise even though dir exists
		result = repolib.files.make_dir_safe(str(new_dir), dry_run=False)

		assert result is True
		assert new_dir.is_dir()


class TestLoadGitignoreBlock:
	"""Test load_gitignore_block helper."""

	def test_load_gitignore_block_filters_blanks_and_comments(self, tmp_path: pathlib.Path) -> None:
		"""Test that blanks and comments are filtered."""
		file_path = tmp_path / "gitignore.txt"
		content = """
# Comment line
*.pyc

# Another comment
__pycache__/
.env

# Final comment
"""
		file_path.write_text(content, encoding='utf-8')

		result = repolib.files.load_gitignore_block(str(file_path))

		assert result == ['*.pyc', '__pycache__/', '.env']

	def test_load_gitignore_block_empty_file(self, tmp_path: pathlib.Path) -> None:
		"""Test loading empty file."""
		file_path = tmp_path / "gitignore.txt"
		file_path.write_text("", encoding='utf-8')

		result = repolib.files.load_gitignore_block(str(file_path))

		assert result == []

	def test_load_gitignore_block_only_comments(self, tmp_path: pathlib.Path) -> None:
		"""Test file with only comments and blanks."""
		file_path = tmp_path / "gitignore.txt"
		content = """# Comment 1
# Comment 2

# Comment 3"""
		file_path.write_text(content, encoding='utf-8')

		result = repolib.files.load_gitignore_block(str(file_path))

		assert result == []

	def test_load_gitignore_block_missing_file(self) -> None:
		"""Test loading non-existent file returns empty list."""
		result = repolib.files.load_gitignore_block('/nonexistent/path.txt')

		assert result == []


class TestWriteRepoTypeMarker:
	"""Test write_repo_type_marker helper."""

	def test_write_repo_type_marker_real_run(self, tmp_path: pathlib.Path) -> None:
		"""Test actual marker write."""
		file_path = tmp_path / "REPO_TYPE"

		result = repolib.repo.write_repo_type_marker(str(file_path), 'typescript', dry_run=False)

		assert result is True
		assert file_path.read_text(encoding='utf-8') == 'typescript\n'

	def test_write_repo_type_marker_dry_run(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
		"""Test dry-run mode."""
		file_path = tmp_path / "REPO_TYPE"

		result = repolib.repo.write_repo_type_marker(str(file_path), 'rust', dry_run=True)

		assert result is False
		assert not file_path.exists()
		captured = capsys.readouterr()
		assert "dry run" in captured.out


class TestParseRepoTypeChoice:
	"""Test parse_repo_type_choice helper."""

	def test_parse_repo_type_choice_single_letters(self) -> None:
		"""Test single-letter choices."""
		assert repolib.repo.parse_repo_type_choice('p') == 'python'
		assert repolib.repo.parse_repo_type_choice('t') == 'typescript'
		assert repolib.repo.parse_repo_type_choice('r') == 'rust'
		assert repolib.repo.parse_repo_type_choice('o') == 'other'

	def test_parse_repo_type_choice_swift(self) -> None:
		"""Test swift single-letter and full-word choices resolve to swift."""
		assert repolib.repo.parse_repo_type_choice('s') == 'swift'
		assert repolib.repo.parse_repo_type_choice('swift') == 'swift'

	def test_parse_repo_type_choice_full_words(self) -> None:
		"""Test full-word choices."""
		assert repolib.repo.parse_repo_type_choice('python') == 'python'
		assert repolib.repo.parse_repo_type_choice('typescript') == 'typescript'
		assert repolib.repo.parse_repo_type_choice('rust') == 'rust'
		assert repolib.repo.parse_repo_type_choice('other') == 'other'

	def test_parse_repo_type_choice_case_insensitive(self) -> None:
		"""Test case insensitivity."""
		assert repolib.repo.parse_repo_type_choice('P') == 'python'
		assert repolib.repo.parse_repo_type_choice('PYTHON') == 'python'
		assert repolib.repo.parse_repo_type_choice('TypeScript') == 'typescript'

	def test_parse_repo_type_choice_unknown_returns_default(self) -> None:
		"""Test unknown input returns default."""
		assert repolib.repo.parse_repo_type_choice('invalid', 'python') == 'python'
		assert repolib.repo.parse_repo_type_choice('xyz', 'rust') == 'rust'
		assert repolib.repo.parse_repo_type_choice('invalid', None) is None

	def test_parse_repo_type_choice_empty_returns_default(self) -> None:
		"""Test empty string returns default."""
		assert repolib.repo.parse_repo_type_choice('', 'python') == 'python'
		assert repolib.repo.parse_repo_type_choice('', None) is None

	def test_parse_repo_type_choice_whitespace(self) -> None:
		"""Test whitespace handling."""
		assert repolib.repo.parse_repo_type_choice('  p  ') == 'python'
		assert repolib.repo.parse_repo_type_choice('  python  ') == 'python'


class TestReadRepoType:
	"""Test read_repo_type marker reading: unknown-token fallback and precedence."""

	def test_unknown_repo_type_token_falls_back_to_other(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
		"""Unknown REPO_TYPE token warns (naming token + REPO_TYPE) and returns other, no raise."""
		marker = tmp_path / "REPO_TYPE"
		marker.write_text("pyton\n", encoding='utf-8')

		result = repolib.repo.read_repo_type(str(tmp_path))

		assert result == repolib.model.LANG_OTHER
		warn_text = capsys.readouterr().out
		assert "pyton" in warn_text
		assert "REPO_TYPE" in warn_text

	def test_unknown_legacy_token_falls_back_to_other(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
		"""Unknown STARTER_REPO_TYPE token (no REPO_TYPE) warns and returns other, no raise."""
		legacy = tmp_path / "STARTER_REPO_TYPE"
		legacy.write_text("pyton\n", encoding='utf-8')

		result = repolib.repo.read_repo_type(str(tmp_path))

		assert result == repolib.model.LANG_OTHER
		warn_text = capsys.readouterr().out
		assert "pyton" in warn_text
		assert "STARTER_REPO_TYPE" in warn_text

	def test_repo_type_takes_precedence_over_legacy(self, tmp_path: pathlib.Path) -> None:
		"""When both markers exist, REPO_TYPE wins and the legacy marker is ignored."""
		(tmp_path / "REPO_TYPE").write_text("swift\n", encoding='utf-8')
		(tmp_path / "STARTER_REPO_TYPE").write_text("python\n", encoding='utf-8')

		result = repolib.repo.read_repo_type(str(tmp_path))

		assert result == repolib.model.LANG_SWIFT


class TestReplaceManagedBlock:
	"""Test replace_managed_block helper."""

	def test_replace_managed_block_present(self) -> None:
		"""Test replacing an existing block with content after."""
		lines = [
			'user content',
			'# === UNIVERSAL ===',
			'old pattern 1',
			'old pattern 2',
			'# === PYTHON ===',
			'python content',
		]
		new_block = ['new pattern 1', 'new pattern 2', 'new pattern 3']
		header = '# === UNIVERSAL ==='

		result = repolib.files.replace_managed_block(lines, header, new_block)

		assert result == [
			'user content',
			'# === UNIVERSAL ===',
			'new pattern 1',
			'new pattern 2',
			'new pattern 3',
			'# === PYTHON ===',
			'python content',
		]

	def test_replace_managed_block_absent(self) -> None:
		"""Test appending when block is absent."""
		lines = ['user content 1', 'user content 2']
		new_block = ['pattern 1', 'pattern 2']
		header = '# === UNIVERSAL ==='

		result = repolib.files.replace_managed_block(lines, header, new_block)

		assert result == [
			'user content 1',
			'user content 2',
			'# === UNIVERSAL ===',
			'pattern 1',
			'pattern 2',
		]

	def test_replace_managed_block_empty_list(self) -> None:
		"""Test with empty line list."""
		lines = []
		new_block = ['pattern 1']
		header = '# === UNIVERSAL ==='

		result = repolib.files.replace_managed_block(lines, header, new_block)

		assert result == ['# === UNIVERSAL ===', 'pattern 1']

	def test_replace_managed_block_multiple_blocks(self) -> None:
		"""Test that only the named block is replaced."""
		lines = [
			'# === UNIVERSAL ===',
			'universal content',
			'# === PYTHON ===',
			'python content',
			'more python content',
		]
		new_block = ['new python pattern']
		header = '# === PYTHON ==='

		result = repolib.files.replace_managed_block(lines, header, new_block)

		assert result == [
			'# === UNIVERSAL ===',
			'universal content',
			'# === PYTHON ===',
			'new python pattern',
		]

	def test_replace_managed_block_idempotent(self) -> None:
		"""Test idempotency: result is same if called twice."""
		lines = [
			'# === UNIVERSAL ===',
			'old pattern',
			'user content',
		]
		new_block = ['new pattern 1', 'new pattern 2']
		header = '# === UNIVERSAL ==='

		result1 = repolib.files.replace_managed_block(lines, header, new_block)
		result2 = repolib.files.replace_managed_block(result1, header, new_block)

		assert result1 == result2


class TestCopyIfChanged:
	"""Test copy_if_changed helper."""

	def test_copy_if_changed_source_missing(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
		"""Test returns skipped_source and suppresses output when source missing + counters passed."""
		source = tmp_path / "missing.txt"
		dest = tmp_path / "dest.txt"
		counters = repolib.console.init_counters()

		result = repolib.files.copy_if_changed(str(source), str(dest), dry_run=False, counters=counters)

		assert result == 'skipped_source'
		assert not dest.exists()
		assert counters['skipped_source'] == 1
		captured = capsys.readouterr()
		# Quiet tag suppressed when counters passed
		assert "skip" not in captured.out

	def test_copy_if_changed_source_missing_no_counters(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
		"""Test source missing prints skip line when counters=None."""
		source = tmp_path / "missing.txt"
		dest = tmp_path / "dest.txt"

		result = repolib.files.copy_if_changed(str(source), str(dest), dry_run=False, counters=None)

		assert result == 'skipped_source'
		captured = capsys.readouterr()
		assert "skip" in captured.out
		assert "source:" in captured.out
		assert "(not found)" in captured.out

	def test_copy_if_changed_dest_missing_copied(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
		"""Test returns copied and prints COPIED line when dest missing."""
		source = tmp_path / "source.txt"
		dest = tmp_path / "dest.txt"
		source.write_text("hello", encoding='utf-8')
		counters = None

		result = repolib.files.copy_if_changed(str(source), str(dest), dry_run=False, counters=counters)

		assert result == 'copied'
		assert dest.read_text(encoding='utf-8') == "hello"
		captured = capsys.readouterr()
		assert "copy" in captured.out
		assert "->" in captured.out

	def test_copy_if_changed_dest_exists_same_no_change(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
		"""Test returns no_change and suppresses output when files identical + counters passed."""
		source = tmp_path / "source.txt"
		dest = tmp_path / "dest.txt"
		content = "identical content"
		source.write_text(content, encoding='utf-8')
		dest.write_text(content, encoding='utf-8')
		counters = repolib.console.init_counters()

		result = repolib.files.copy_if_changed(str(source), str(dest), dry_run=False, counters=counters)

		assert result == 'no_change'
		assert counters['unchanged'] == 1
		captured = capsys.readouterr()
		# Quiet tag suppressed when counters passed
		assert "no change" not in captured.out

	def test_copy_if_changed_dest_exists_same_no_change_no_counters(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
		"""Test no_change prints NO CHANGE line when counters=None."""
		source = tmp_path / "source.txt"
		dest = tmp_path / "dest.txt"
		content = "identical content"
		source.write_text(content, encoding='utf-8')
		dest.write_text(content, encoding='utf-8')

		result = repolib.files.copy_if_changed(str(source), str(dest), dry_run=False, counters=None)

		assert result == 'no_change'
		captured = capsys.readouterr()
		assert "no change" in captured.out

	def test_copy_if_changed_dest_exists_differs_updated(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
		"""Test returns updated and prints UPDATED line when files differ."""
		source = tmp_path / "source.txt"
		dest = tmp_path / "dest.txt"
		source.write_text("new content", encoding='utf-8')
		dest.write_text("old content", encoding='utf-8')
		counters = None

		result = repolib.files.copy_if_changed(str(source), str(dest), dry_run=False, counters=counters)

		assert result == 'updated'
		assert dest.read_text(encoding='utf-8') == "new content"
		captured = capsys.readouterr()
		assert "update" in captured.out
		assert "->" in captured.out

	def test_copy_if_changed_dry_run_no_copy(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
		"""Test dry-run mode does not write but prints dry-run line and returns indicator."""
		source = tmp_path / "source.txt"
		dest = tmp_path / "dest.txt"
		source.write_text("hello", encoding='utf-8')
		counters = None

		result = repolib.files.copy_if_changed(str(source), str(dest), dry_run=True, counters=counters)

		# dry-run should still return 'copied' (the action it would take)
		assert result == 'copied'
		# but file should not be written
		assert not dest.exists()
		captured = capsys.readouterr()
		assert "dry run" in captured.out

	def test_copy_if_changed_creates_parent_directory(self, tmp_path: pathlib.Path) -> None:
		"""Test that parent directory is created if needed."""
		source = tmp_path / "source.txt"
		dest = tmp_path / "subdir" / "nested" / "dest.txt"
		source.write_text("hello", encoding='utf-8')
		counters = None

		result = repolib.files.copy_if_changed(str(source), str(dest), dry_run=False, counters=counters)

		assert result == 'copied'
		assert dest.exists()
		assert dest.read_text(encoding='utf-8') == "hello"

	def test_copy_if_changed_preserves_executable_bit(self, tmp_path: pathlib.Path) -> None:
		"""Test that executable bit is preserved on copy."""
		source = tmp_path / "script.sh"
		dest = tmp_path / "script_copy.sh"
		source.write_text("#!/bin/bash\necho hello", encoding='utf-8')

		# Make source executable
		os.chmod(source, os.stat(source).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

		counters = None
		repolib.files.copy_if_changed(str(source), str(dest), dry_run=False, counters=counters)

		dest_mode = os.stat(dest).st_mode
		assert dest_mode & stat.S_IXUSR == stat.S_IXUSR
		assert dest_mode & stat.S_IXGRP == stat.S_IXGRP
		assert dest_mode & stat.S_IXOTH == stat.S_IXOTH


class TestApplyFileBucket:
	"""Test apply_file_bucket helper covering per-bucket special cases."""

	def test_noexist_bucket_skip_policy(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
		"""Test noexist bucket: skip when dest exists and --initial_setup not set."""
		# Setup
		repo_dir = tmp_path / "repo"
		repo_dir.mkdir()
		source_dir = tmp_path / "source"
		source_dir.mkdir()

		# Create source file
		source_file = source_dir / "source_me.sh"
		source_file.write_text("#!/bin/bash", encoding='utf-8')

		# Create existing dest file
		dest_file = repo_dir / "source_me.sh"
		dest_file.write_text("existing content", encoding='utf-8')

		# Create spec
		spec = {
			'overwrite_files': [],
			'noexist_files': ['source_me.sh'],
			'devel_files': [],
			'test_files': [],
		}

		# Context with initial_setup=False
		context = repolib.model.PropagateContext(
			source_dir=str(source_dir),
			template_root=str(source_dir),
			repo_name=None,
			dry_run=False,
			initial_setup=False,
			auto_discover=False,
			write_marker=False,
		)
		counters = repolib.console.init_counters()

		# Mock find_source_for_bucket (None-returning variant used by apply_file_bucket)
		def mock_source_path(source_dir: str, bucket: str, file_rel: str, repo_type: str) -> str | None:
			if file_rel == 'source_me.sh':
				return str(source_file)
			return None

		monkeypatch.setattr(repolib.model, 'find_source_for_bucket', mock_source_path)

		# Mock repo_is_on_path to return False
		monkeypatch.setattr(repolib.repo, 'repo_is_on_path', lambda x: False)

		# Call apply_file_bucket
		updates, copies, skips = repolib.process.apply_file_bucket(
			'noexist_files', spec, str(repo_dir), 'python', context, counters
		)

		# Verify: should skip due to policy
		assert updates == 0
		assert copies == 0
		assert skips == 1
		assert counters['skipped_policy'] == 1

	def test_noexist_bucket_source_me_sh_path_skip(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
		"""Test noexist bucket: skip source_me.sh when repo is on PATH."""
		# Setup
		repo_dir = tmp_path / "repo"
		repo_dir.mkdir()
		source_dir = tmp_path / "source"
		source_dir.mkdir()

		# Create source file
		source_file = source_dir / "source_me.sh"
		source_file.write_text("#!/bin/bash", encoding='utf-8')

		# Create spec
		spec = {
			'overwrite_files': [],
			'noexist_files': ['source_me.sh'],
			'devel_files': [],
			'test_files': [],
		}

		# Context
		context = repolib.model.PropagateContext(
			source_dir=str(source_dir),
			template_root=str(source_dir),
			repo_name=None,
			dry_run=False,
			initial_setup=False,
			auto_discover=False,
			write_marker=False,
		)
		counters = repolib.console.init_counters()

		# Mock find_source_for_bucket (None-returning variant used by apply_file_bucket)
		def mock_source_path(source_dir: str, bucket: str, file_rel: str, repo_type: str) -> str | None:
			if file_rel == 'source_me.sh':
				return str(source_file)
			return None

		monkeypatch.setattr(repolib.model, 'find_source_for_bucket', mock_source_path)

		# Mock repo_is_on_path to return True (repo is on PATH)
		monkeypatch.setattr(repolib.repo, 'repo_is_on_path', lambda x: True)

		# Call apply_file_bucket
		updates, copies, skips = repolib.process.apply_file_bucket(
			'noexist_files', spec, str(repo_dir), 'python', context, counters
		)

		# Verify: should skip due to PATH
		assert updates == 0
		assert copies == 0
		assert skips == 0
		assert counters['skipped_path'] == 1

	def test_devel_bucket_no_change_check(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
		"""Test devel bucket: filecmp no-change check when files identical."""
		# Setup
		repo_dir = tmp_path / "repo"
		repo_dir.mkdir()
		devel_dir = repo_dir / "devel"
		devel_dir.mkdir()
		source_dir = tmp_path / "source"
		source_dir.mkdir()

		content = "identical content"

		# Create source file
		source_file = source_dir / "helper.py"
		source_file.write_text(content, encoding='utf-8')

		# Create identical dest file
		dest_file = devel_dir / "helper.py"
		dest_file.write_text(content, encoding='utf-8')

		# Create spec
		spec = {
			'overwrite_files': [],
			'noexist_files': [],
			'devel_files': ['helper.py'],
			'test_files': [],
		}

		# Context
		context = repolib.model.PropagateContext(
			source_dir=str(source_dir),
			template_root=str(source_dir),
			repo_name=None,
			dry_run=False,
			initial_setup=False,
			auto_discover=False,
			write_marker=False,
		)
		counters = repolib.console.init_counters()

		# find_source_for_bucket is the variant used by apply_file_bucket; return None on miss.
		def mock_source_path(source_dir: str, bucket: str, file_rel: str, repo_type: str) -> str | None:
			if file_rel == 'helper.py':
				return str(source_file)
			return None

		monkeypatch.setattr(repolib.model, 'find_source_for_bucket', mock_source_path)

		# Mock target_path_for_bucket
		def mock_target_path(repo_dir: str, bucket: str, file_rel: str) -> str:
			if bucket == 'devel_files':
				return str(devel_dir / file_rel)
			raise ValueError()

		monkeypatch.setattr(repolib.model, 'target_path_for_bucket', mock_target_path)

		# Call apply_file_bucket
		updates, copies, skips = repolib.process.apply_file_bucket(
			'devel_files', spec, str(repo_dir), 'python', context, counters
		)

		# Verify: files should match, no changes needed
		assert updates == 0
		assert skips == 0

	def test_test_bucket_auto_discovered_files_handled(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
		"""Test test_files bucket: auto-discovered files are handled correctly."""
		# Setup
		repo_dir = tmp_path / "repo"
		repo_dir.mkdir()
		tests_dir = repo_dir / "tests"
		tests_dir.mkdir()
		source_dir = tmp_path / "source"
		source_dir.mkdir()

		# Create source file
		source_file = source_dir / "test_auto.py"
		source_file.write_text("test code", encoding='utf-8')

		# Create spec with auto-discovered test file
		spec = {
			'overwrite_files': [],
			'noexist_files': [],
			'devel_files': [],
			'test_files': ['test_auto.py'],  # This would be auto-discovered
		}

		# Context
		context = repolib.model.PropagateContext(
			source_dir=str(source_dir),
			template_root=str(source_dir),
			repo_name=None,
			dry_run=False,
			initial_setup=False,
			auto_discover=False,
			write_marker=False,
		)
		counters = repolib.console.init_counters()

		# find_source_for_bucket is the variant used by apply_file_bucket; return None on miss.
		def mock_source_path(source_dir: str, bucket: str, file_rel: str, repo_type: str) -> str | None:
			if file_rel == 'test_auto.py':
				return str(source_file)
			return None

		monkeypatch.setattr(repolib.model, 'find_source_for_bucket', mock_source_path)

		# Mock target_path_for_bucket
		def mock_target_path(repo_dir: str, bucket: str, file_rel: str) -> str:
			if bucket == 'test_files':
				return str(tests_dir / file_rel)
			raise ValueError()

		monkeypatch.setattr(repolib.model, 'target_path_for_bucket', mock_target_path)

		# Call apply_file_bucket
		updates, copies, skips = repolib.process.apply_file_bucket(
			'test_files', spec, str(repo_dir), 'python', context, counters
		)

		# Verify: file should be copied
		assert skips == 0
		assert counters['copied_count'] == 1



