"""
Tests for routing-override behavior (location-primary routing).

Location is now the primary propagation determinant. The only routing override
that survives is the per-destination `exclude_repos` gate. These tests are
data-driven over the LIVE ROUTING_OVERRIDES table so they cannot drift when the
table shrinks or grows, plus a synthetic anchor that keeps gate coverage alive
even if the live table ever empties. They also exercise the
override_key_source() resolver against synthetic template trees.
"""

import os
import pathlib

import pytest

import repolib.files
import repolib.model
import repolib.repo


#============================================
# Helpers (keep test bodies free of logic)
#============================================

def excluded_name_for(rule: dict) -> str | None:
	"""
	Return one repo name from a rule's exclude_repos set, or None.

	Returns:
		str | None: An arbitrary member of exclude_repos, or None when the rule
		            declares no exclude_repos gate.
	"""
	exclude_repos = rule.get('exclude_repos')
	if not exclude_repos:
		return None
	# frozenset has no ordering; any single member proves the gate fires.
	return next(iter(exclude_repos))


def repo_dir_named(parent: pathlib.Path, basename: str) -> str:
	"""
	Create a child directory whose basename drives the exclude_repos match.

	Returns:
		str: Absolute path to the created directory.
	"""
	dest = parent / basename
	dest.mkdir()
	return str(dest)


#============================================
# Data-driven coverage of the live ROUTING_OVERRIDES table
#============================================

# Parametrize over the live table so no key names, counts, or expected-value
# lists are hardcoded here. Each case asserts the predicate honors whatever the
# entry declares, not a specific entry.
LIVE_OVERRIDE_ITEMS = list(repolib.model.ROUTING_OVERRIDES.items())


@pytest.mark.parametrize('file_rel, rule', LIVE_OVERRIDE_ITEMS, ids=lambda item: str(item))
def test_exclude_repos_blocks_listed_destination(
	file_rel: str, rule: dict, tmp_path: pathlib.Path
) -> None:
	"""An exclude_repos entry blocks a destination whose basename is listed."""
	excluded = excluded_name_for(rule)
	if excluded is None:
		pytest.skip("entry declares no exclude_repos gate")
	dest = repo_dir_named(tmp_path, excluded)
	result = repolib.files.should_ship_override(file_rel, repolib.model.LANG_PYTHON, dest)
	assert result is False


@pytest.mark.parametrize('file_rel, rule', LIVE_OVERRIDE_ITEMS, ids=lambda item: str(item))
def test_exclude_repos_allows_unlisted_destination(
	file_rel: str, rule: dict, tmp_path: pathlib.Path
) -> None:
	"""An exclude_repos entry returns None for a destination not on the list."""
	if excluded_name_for(rule) is None:
		pytest.skip("entry declares no exclude_repos gate")
	dest = repo_dir_named(tmp_path, 'some-unlisted-consumer-repo')
	result = repolib.files.should_ship_override(file_rel, repolib.model.LANG_PYTHON, dest)
	assert result is None


def test_no_override_for_unregistered_file(tmp_path: pathlib.Path) -> None:
	"""A file absent from ROUTING_OVERRIDES yields None (location decides)."""
	result = repolib.files.should_ship_override(
		'docs/A_FILE_WITH_NO_OVERRIDE.md', repolib.model.LANG_PYTHON, str(tmp_path)
	)
	assert result is None


#============================================
# Synthetic anchor: exclude_repos gate survives a shrinking live table
#============================================

def test_exclude_repos_gate_with_synthetic_table(
	tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	"""A synthetic exclude_repos rule blocks its named repo and allows others."""
	# Build a tiny synthetic table independent of the live one so gate coverage
	# survives even if the live ROUTING_OVERRIDES shrinks further.
	synthetic = {
		'docs/SYNTHETIC.md': {'exclude_repos': frozenset({'forbidden-repo'})},
	}
	monkeypatch.setattr(repolib.model, 'ROUTING_OVERRIDES', synthetic)

	blocked_dest = repo_dir_named(tmp_path, 'forbidden-repo')
	allowed_dest = repo_dir_named(tmp_path, 'allowed-repo')

	blocked = repolib.files.should_ship_override(
		'docs/SYNTHETIC.md', repolib.model.LANG_PYTHON, blocked_dest
	)
	allowed = repolib.files.should_ship_override(
		'docs/SYNTHETIC.md', repolib.model.LANG_PYTHON, allowed_dest
	)

	assert blocked is False
	assert allowed is None


def test_exclude_repos_gate_ignores_trailing_slash(
	tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	"""A trailing slash on repo_dir does not defeat the exclude_repos match."""
	synthetic = {
		'docs/SYNTHETIC.md': {'exclude_repos': frozenset({'forbidden-repo'})},
	}
	monkeypatch.setattr(repolib.model, 'ROUTING_OVERRIDES', synthetic)
	dest = repo_dir_named(tmp_path, 'forbidden-repo')

	result = repolib.files.should_ship_override(
		'docs/SYNTHETIC.md', repolib.model.LANG_PYTHON, dest + os.sep
	)
	assert result is False


#============================================
# override_key_source() resolver over synthetic template trees
#============================================

def write_file(path: pathlib.Path, text: str = 'x') -> pathlib.Path:
	"""
	Create parent dirs and write a small file.

	Returns:
		pathlib.Path: The written file path.
	"""
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(text, encoding='utf-8')
	return path


def test_override_key_source_resolves_universal_root(tmp_path: pathlib.Path) -> None:
	"""A source under the universal template root resolves to that file."""
	source = write_file(tmp_path / 'docs' / 'X.md')
	result = repolib.model.override_key_source(str(tmp_path), 'docs/X.md')
	assert result == str(source)


def test_override_key_source_resolves_typed_overlay(tmp_path: pathlib.Path) -> None:
	"""A source under templates/python/ resolves to the typed overlay file."""
	source = write_file(tmp_path / 'templates' / 'python' / 'docs' / 'Y.md')
	result = repolib.model.override_key_source(str(tmp_path), 'docs/Y.md')
	assert result == str(source)


def test_override_key_source_resolves_conditional_overlay(tmp_path: pathlib.Path) -> None:
	"""A devel source under a configured conditional overlay resolves."""
	# Discover the overlay folder name from live config rather than hardcoding it,
	# because override_key_source consults the live CONDITIONAL_OVERLAYS table.
	overlays = repolib.model.CONDITIONAL_OVERLAYS[repolib.model.LANG_PYTHON]
	overlay_name = next(iter(overlays))
	source = write_file(
		tmp_path / 'templates' / 'python' / overlay_name / 'devel' / 'z.py'
	)
	result = repolib.model.override_key_source(str(tmp_path), 'devel/z.py')
	assert result == str(source)


def test_override_key_source_returns_none_when_unresolved(tmp_path: pathlib.Path) -> None:
	"""A key with no matching source anywhere resolves to None."""
	result = repolib.model.override_key_source(str(tmp_path), 'docs/DOES_NOT_EXIST.md')
	assert result is None


#============================================
# Guardrails over the live table (trivial bodies)
#============================================

@pytest.mark.parametrize('file_rel', list(repolib.model.ROUTING_OVERRIDES.keys()))
def test_all_override_keys_resolve_to_a_source(file_rel: str) -> None:
	"""Every live override key resolves to an existing template source."""
	template_root = repolib.repo.resolve_source_dir(None)
	assert repolib.model.override_key_source(template_root, file_rel) is not None


@pytest.mark.parametrize(
	'file_rel, rule', LIVE_OVERRIDE_ITEMS, ids=lambda item: str(item)
)
def test_all_override_values_have_valid_schema(file_rel: str, rule: dict) -> None:
	"""Every live override rule uses only the supported exclude_repos schema."""
	# Location-primary routing dropped bucket/language/requires_repo_file; only
	# exclude_repos remains a valid rule field.
	valid_fields = {'exclude_repos'}
	assert isinstance(rule, dict)
	assert set(rule).issubset(valid_fields)
	if 'exclude_repos' in rule:
		exclude_repos = rule['exclude_repos']
		assert isinstance(exclude_repos, frozenset)
		assert exclude_repos
