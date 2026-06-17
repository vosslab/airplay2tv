"""Tests for precedence and routing rules in compute_propagation_plan.

Routing is now LOCATION-PRIMARY: a file's bucket and which repo types receive
it are decided by where the file lives in the template tree, not by per-file
override gating.

  - A docs/<f>.md at the UNIVERSAL template root ships to every repo type.
  - Language-specific content lives under templates/<type>/ (and conditional
    overlays templates/<type>/_<name>/), so placement is what makes a file
    language-specific.
  - ROUTING_OVERRIDES now carries only the exclude_repos gate.

The synthetic-template pattern below builds a fake template root under tmp_path
(templates/..., docs/..., etc.), then calls compute_propagation_plan and asserts
on the resulting buckets. Monkeypatched manifest globals are restored by pytest.
"""

import pathlib

import pytest

import repolib.model
import repolib.files


#============================================
# META precedence (unchanged by the location model)
#============================================

def test_meta_file_never_ships_even_if_in_docs(tmp_path: pathlib.Path) -> None:
	"""META_FILES entries have highest precedence and are excluded from plan."""
	docs_dir = tmp_path / 'docs'
	docs_dir.mkdir()
	(docs_dir / 'README.md').write_text('test')
	plan = repolib.files.compute_propagation_plan(str(tmp_path), 'python')
	assert 'docs/README.md' not in plan['overwrite_files']
	assert 'docs/README.md' not in plan['noexist_files']


#============================================
# Universal-root routing under the location model
#============================================

def test_universal_doc_ships_to_all_types(tmp_path: pathlib.Path) -> None:
	"""A docs/*.md at the universal root ships to every repo type.

	MODEL CHANGE: the old test_python_lang_file_excluded_from_typescript placed
	docs/PYTHON_STYLE.md at the universal root and asserted typescript/other were
	excluded by override gating. Under the location model, a universal-root doc is
	universal by definition and reaches all types; language-specificity now comes
	from templates/<type>/ placement (covered in the folder-convention tests).
	"""
	docs_dir = tmp_path / 'docs'
	docs_dir.mkdir()
	(docs_dir / 'PYTHON_STYLE.md').write_text('test')
	plan_py = repolib.files.compute_propagation_plan(str(tmp_path), 'python')
	plan_ts = repolib.files.compute_propagation_plan(str(tmp_path), 'typescript')
	plan_other = repolib.files.compute_propagation_plan(str(tmp_path), 'other')
	assert 'docs/PYTHON_STYLE.md' in plan_py['overwrite_files']
	assert 'docs/PYTHON_STYLE.md' in plan_ts['overwrite_files']
	assert 'docs/PYTHON_STYLE.md' in plan_other['overwrite_files']


def test_root_file_not_in_allowlist_stays_out_of_every_plan(tmp_path: pathlib.Path) -> None:
	"""A universal-root file absent from ROOT_PROPAGATE_ALLOWLIST never ships.

	MODEL CHANGE: the old test_pip_requirements_not_in_typescript_plan asserted
	pip_requirements.txt was excluded specifically from the typescript plan via
	override gating. Under the location model the real invariant is the
	root-manifest one: a root file not on ROOT_PROPAGATE_ALLOWLIST is dropped for
	ALL types (not a typescript-only exclusion). pip_requirements.txt is not on
	the allowlist, so it stays out of python, typescript, and other plans.
	"""
	(tmp_path / 'pip_requirements.txt').write_text('test')
	for repo_type in ('python', 'typescript', 'other'):
		plan = repolib.files.compute_propagation_plan(str(tmp_path), repo_type)
		assert 'pip_requirements.txt' not in plan['overwrite_files']
		assert 'pip_requirements.txt' not in plan['noexist_files']


def test_universal_noexist_overrides_overwrite(tmp_path: pathlib.Path) -> None:
	"""Universal NOEXIST entries override universal OVERWRITE."""
	(tmp_path / 'AGENTS.md').write_text('test')
	plan = repolib.files.compute_propagation_plan(str(tmp_path), 'python')
	assert 'AGENTS.md' not in plan['overwrite_files']
	assert 'AGENTS.md' in plan['noexist_files']


def test_typed_noexist_overrides_typed_overwrite(tmp_path: pathlib.Path) -> None:
	"""Type-specific NOEXIST entries override type-specific OVERWRITE."""
	type_dir = tmp_path / 'templates' / 'typescript'
	noexist_dir = type_dir / 'noexist'
	noexist_dir.mkdir(parents=True)
	(type_dir / 'foo.ts').write_text('test')
	(noexist_dir / 'foo.ts').write_text('test')
	plan = repolib.files.compute_propagation_plan(str(tmp_path), 'typescript')
	assert 'foo.ts' not in plan['overwrite_files']
	assert 'foo.ts' in plan['noexist_files']


def test_typed_overlay_shadows_universal_same_destination(tmp_path: pathlib.Path) -> None:
	"""Type-specific files shadow universal files when destination paths collide."""
	(tmp_path / 'docs').mkdir()
	type_docs_dir = tmp_path / 'templates' / 'typescript' / 'docs'
	type_docs_dir.mkdir(parents=True)
	(tmp_path / 'docs' / 'FOO.md').write_text('universal content')
	(type_docs_dir / 'FOO.md').write_text('typed content')
	plan_ts = repolib.files.compute_propagation_plan(str(tmp_path), 'typescript')
	plan_py = repolib.files.compute_propagation_plan(str(tmp_path), 'python')
	source_ts = repolib.model.source_path_for_bucket(str(tmp_path), 'overwrite_files', 'docs/FOO.md', 'typescript')
	source_py = repolib.model.source_path_for_bucket(str(tmp_path), 'overwrite_files', 'docs/FOO.md', 'python')
	assert 'docs/FOO.md' in plan_ts['overwrite_files']
	assert 'docs/FOO.md' in plan_py['overwrite_files']
	assert 'templates/typescript' in source_ts
	assert 'templates' not in source_py


#============================================
# Conditional overlay routing (the _pypi/pyproject.toml rule)
#============================================

def _build_pypi_overlay(template_root: pathlib.Path) -> None:
	"""Create a synthetic templates/python/_pypi overlay with devel + noexist files.

	Mirrors the real _pypi overlay shape so the existing CONDITIONAL_OVERLAYS
	rule (python -> _pypi when pyproject.toml exists) selects it without any
	monkeypatching.
	"""
	pypi = template_root / 'templates' / 'python' / '_pypi'
	(pypi / 'devel').mkdir(parents=True)
	(pypi / 'noexist').mkdir(parents=True)
	(pypi / 'devel' / 'submit_to_pypi.py').write_text('test')
	(pypi / 'noexist' / 'pyproject.toml').write_text('test')


def test_conditional_overlay_ships_when_marker_present(tmp_path: pathlib.Path) -> None:
	"""python/_pypi devel content ships when the consumer has pyproject.toml."""
	_build_pypi_overlay(tmp_path)
	repo_dir = tmp_path / 'consumer'
	repo_dir.mkdir()
	(repo_dir / 'pyproject.toml').write_text('test')
	plan = repolib.files.compute_propagation_plan(str(tmp_path), 'python', repo_dir=str(repo_dir))
	assert 'submit_to_pypi.py' in plan['devel_files']


def test_conditional_overlay_noexist_routes_to_noexist(tmp_path: pathlib.Path) -> None:
	"""A noexist file inside the conditional overlay lands in noexist, not overwrite."""
	_build_pypi_overlay(tmp_path)
	repo_dir = tmp_path / 'consumer'
	repo_dir.mkdir()
	(repo_dir / 'pyproject.toml').write_text('test')
	plan = repolib.files.compute_propagation_plan(str(tmp_path), 'python', repo_dir=str(repo_dir))
	assert 'pyproject.toml' in plan['noexist_files']
	assert 'pyproject.toml' not in plan['overwrite_files']


def test_conditional_overlay_absent_without_marker(tmp_path: pathlib.Path) -> None:
	"""python/_pypi content is absent when the consumer lacks pyproject.toml."""
	_build_pypi_overlay(tmp_path)
	repo_dir = tmp_path / 'consumer'
	repo_dir.mkdir()
	plan = repolib.files.compute_propagation_plan(str(tmp_path), 'python', repo_dir=str(repo_dir))
	assert 'submit_to_pypi.py' not in plan['devel_files']
	assert 'pyproject.toml' not in plan['noexist_files']


def test_conditional_overlay_absent_for_other_types(tmp_path: pathlib.Path) -> None:
	"""python/_pypi content never ships to typescript or other, marker or not."""
	_build_pypi_overlay(tmp_path)
	repo_dir = tmp_path / 'consumer'
	repo_dir.mkdir()
	(repo_dir / 'pyproject.toml').write_text('test')
	for repo_type in ('typescript', 'other'):
		plan = repolib.files.compute_propagation_plan(str(tmp_path), repo_type, repo_dir=str(repo_dir))
		assert 'submit_to_pypi.py' not in plan['devel_files']
		assert 'pyproject.toml' not in plan['noexist_files']


def test_underscore_dir_without_overlay_rule_never_ships(tmp_path: pathlib.Path) -> None:
	"""A templates/<type>/_foo with no CONDITIONAL_OVERLAYS entry is never shipped.

	The base overlay walk skips underscore-prefixed subdirectories, and without a
	matching conditional-overlay rule the folder is never selected, so its content
	appears in no bucket.
	"""
	foo = tmp_path / 'templates' / 'python' / '_foo'
	foo.mkdir(parents=True)
	(foo / 'x.py').write_text('test')
	plan = repolib.files.compute_propagation_plan(str(tmp_path), 'python')
	all_entries = (
		plan['overwrite_files']
		+ plan['noexist_files']
		+ plan['devel_files']
		+ plan['test_files']
	)
	assert 'x.py' not in all_entries
	assert not any(entry.endswith('x.py') for entry in all_entries)


#============================================
# exclude_repos override gate (the only surviving ROUTING_OVERRIDES key)
#============================================

def test_exclude_repos_blocks_named_consumer(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
	"""A universal doc with an exclude_repos override is dropped for the named repo.

	Monkeypatch ROUTING_OVERRIDES so the synthetic doc has an exact-basename
	exclusion; pytest restores the dict after the test.
	"""
	docs_dir = tmp_path / 'docs'
	docs_dir.mkdir()
	(docs_dir / 'GUIDE.md').write_text('test')
	monkeypatch.setitem(
		repolib.model.ROUTING_OVERRIDES,
		'docs/GUIDE.md',
		{'exclude_repos': frozenset({'excluded_repo'})},
	)
	normal_repo = tmp_path / 'normal_repo'
	excluded_repo = tmp_path / 'excluded_repo'
	normal_repo.mkdir()
	excluded_repo.mkdir()
	plan_normal = repolib.files.compute_propagation_plan(str(tmp_path), 'python', repo_dir=str(normal_repo))
	plan_excluded = repolib.files.compute_propagation_plan(str(tmp_path), 'python', repo_dir=str(excluded_repo))
	assert 'docs/GUIDE.md' in plan_normal['overwrite_files']
	assert 'docs/GUIDE.md' not in plan_excluded['overwrite_files']
