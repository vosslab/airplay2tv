"""Tests for folder-convention propagation routing.

Routing is LOCATION-PRIMARY: where a file lives in the template tree decides its
bucket and which repo types receive it. Universal-root files (docs/, allowlisted
root files, tests/ helpers) ship to every type; language-specific content lives
under templates/<type>/ and conditional overlays templates/<type>/_<name>/.

Each test builds a synthetic template root under tmp_path and asserts on the
buckets returned by compute_propagation_plan.
"""

import pathlib

import repolib.files
import repolib.model


def test_universal_doc_routes_overwrite(tmp_path: pathlib.Path) -> None:
	"""Docs/ file routes to overwrite_files for all repo types."""
	docs_dir = tmp_path / 'docs'
	docs_dir.mkdir()
	(docs_dir / 'FOO.md').write_text('test')
	plan = repolib.files.compute_propagation_plan(str(tmp_path), 'python')
	assert 'docs/FOO.md' in plan['overwrite_files']


def test_universal_doc_reaches_every_type(tmp_path: pathlib.Path) -> None:
	"""A universal docs/ file reaches python, typescript, and other alike.

	Under the location model, universal-root placement means universal delivery;
	there is no per-type gating for a file that lives at the universal root.
	"""
	docs_dir = tmp_path / 'docs'
	docs_dir.mkdir()
	(docs_dir / 'SHARED.md').write_text('test')
	for repo_type in repolib.model.REPO_TYPE_ORDER:
		plan = repolib.files.compute_propagation_plan(str(tmp_path), repo_type)
		assert 'docs/SHARED.md' in plan['overwrite_files']


def test_meta_file_excluded_basename_form(tmp_path: pathlib.Path) -> None:
	"""META_FILES entry by basename (e.g. README.md) excludes the file."""
	(tmp_path / 'README.md').write_text('test')
	plan = repolib.files.compute_propagation_plan(str(tmp_path), 'python')
	assert 'README.md' not in plan['overwrite_files']


def test_meta_dir_excludes_nested_files(tmp_path: pathlib.Path) -> None:
	"""Files under meta/ (META_DIRS entry) never ship, regardless of depth."""
	meta_docs = tmp_path / 'meta' / 'docs'
	meta_docs.mkdir(parents=True)
	(meta_docs / 'PROPAGATION_RULES.md').write_text('test')
	plan = repolib.files.compute_propagation_plan(str(tmp_path), 'python')
	assert 'meta/docs/PROPAGATION_RULES.md' not in plan['overwrite_files']


def test_meta_dir_excludes_root_tools_nested(tmp_path: pathlib.Path) -> None:
	"""ROOT tools/ (META_DIRS entry) never ships, regardless of file name.

	This guards the template's own root infrastructure (e.g.
	tools/detect_repo_type.py). The separate templates/<type>/tools/ overlay
	path DOES ship -- see test_typescript_overlay_tools_ships.
	"""
	tools_dir = tmp_path / 'tools'
	tools_dir.mkdir()
	(tools_dir / 'detect_repo_type.py').write_text('test')
	plan = repolib.files.compute_propagation_plan(str(tmp_path), 'python')
	assert 'tools/detect_repo_type.py' not in plan['overwrite_files']


def test_typescript_overlay_tools_ships(tmp_path: pathlib.Path) -> None:
	"""templates/typescript/tools/<file> ships at consumer tools/<file>.

	Standard: every file under templates/<type>/ ships at its relative path,
	including tools/ subpaths. This is the typed-overlay counterpart to the
	ROOT tools/ exclusion above.
	"""
	tools_dir = tmp_path / 'templates' / 'typescript' / 'tools'
	tools_dir.mkdir(parents=True)
	(tools_dir / 'sync_typescript_package_pins.py').write_text('test')
	plan_ts = repolib.files.compute_propagation_plan(str(tmp_path), 'typescript')
	plan_py = repolib.files.compute_propagation_plan(str(tmp_path), 'python')
	assert 'tools/sync_typescript_package_pins.py' in plan_ts['overwrite_files']
	# Other repo types do not get the typescript overlay file.
	assert 'tools/sync_typescript_package_pins.py' not in plan_py['overwrite_files']


def test_typescript_overlay_tools_meta_file_basename_excluded(tmp_path: pathlib.Path) -> None:
	"""A META_FILES basename inside templates/<type>/tools/ still does not ship.

	The META_FILES basename guard is retained in the typed overlay so a stray
	README.md (or any META name) under the overlay -- even in a shipping subdir
	like tools/ -- cannot clobber the consumer's file.
	"""
	tools_dir = tmp_path / 'templates' / 'typescript' / 'tools'
	tools_dir.mkdir(parents=True)
	(tools_dir / 'README.md').write_text('test')
	plan = repolib.files.compute_propagation_plan(str(tmp_path), 'typescript')
	assert 'tools/README.md' not in plan['overwrite_files']
	assert 'README.md' not in plan['overwrite_files']


def test_meta_test_prefix_excluded(tmp_path: pathlib.Path) -> None:
	"""A META_TEST_PREFIXES file at tests/ root never ships under the denylist."""
	tests_dir = tmp_path / 'tests'
	tests_dir.mkdir()
	(tests_dir / 'test_repolib_x.py').write_text('test')
	plan = repolib.files.compute_propagation_plan(str(tmp_path), 'python')
	assert 'tests/test_repolib_x.py' not in plan['test_files']


def test_tests_denylist_ships_non_test_helper(tmp_path: pathlib.Path) -> None:
	"""Denylist routing ships a non-test_-prefixed tests/ helper by location.

	The old enumerated allowlist only shipped test_*/check_*/fix_*/file_utils.py;
	the denylist ships all non-meta tests/ files, so a plain helper now ships.
	"""
	tests_dir = tmp_path / 'tests'
	tests_dir.mkdir()
	(tests_dir / 'test_foo.py').write_text('test')
	(tests_dir / 'helper_thing.py').write_text('test')
	plan = repolib.files.compute_propagation_plan(str(tmp_path), 'python')
	assert 'tests/test_foo.py' in plan['test_files']
	assert 'tests/helper_thing.py' in plan['test_files']


def test_tests_denylist_skips_scratch(tmp_path: pathlib.Path) -> None:
	"""An underscore-prefixed scratch file under tests/ is never shipped."""
	tests_dir = tmp_path / 'tests'
	tests_dir.mkdir()
	(tests_dir / '_scratch.py').write_text('test')
	plan = repolib.files.compute_propagation_plan(str(tmp_path), 'python')
	all_entries = (
		plan['overwrite_files']
		+ plan['noexist_files']
		+ plan['devel_files']
		+ plan['test_files']
	)
	assert not any(entry.endswith('_scratch.py') for entry in all_entries)


def test_tests_denylist_skips_conftest(tmp_path: pathlib.Path) -> None:
	"""tests/conftest.py is merge-owned and never appears in any bucket.

	conftest.py is handled by merge_conftest in process.py (additive merge of
	collect_ignore/REPO_HYGIENE_FILTERS), not by bucket routing.
	"""
	tests_dir = tmp_path / 'tests'
	tests_dir.mkdir()
	(tests_dir / 'conftest.py').write_text('test')
	plan = repolib.files.compute_propagation_plan(str(tmp_path), 'python')
	all_entries = (
		plan['overwrite_files']
		+ plan['noexist_files']
		+ plan['merge_files']
		+ plan['devel_files']
		+ plan['test_files']
	)
	assert 'tests/conftest.py' not in all_entries
	assert 'conftest.py' not in all_entries


def test_typescript_overlay_routes_to_overwrite(tmp_path: pathlib.Path) -> None:
	"""templates/typescript/foo.ts routes to overwrite_files for typescript type."""
	type_dir = tmp_path / 'templates' / 'typescript'
	type_dir.mkdir(parents=True)
	(type_dir / 'foo.ts').write_text('test')
	plan = repolib.files.compute_propagation_plan(str(tmp_path), 'typescript')
	assert 'foo.ts' in plan['overwrite_files']


def test_typescript_noexist_routes_to_noexist(tmp_path: pathlib.Path) -> None:
	"""templates/typescript/noexist/package.json routes to noexist_files."""
	noexist_dir = tmp_path / 'templates' / 'typescript' / 'noexist'
	noexist_dir.mkdir(parents=True)
	(noexist_dir / 'package.json').write_text('test')
	plan = repolib.files.compute_propagation_plan(str(tmp_path), 'typescript')
	assert 'package.json' in plan['noexist_files']


def test_typed_overlay_doc_is_language_specific(tmp_path: pathlib.Path) -> None:
	"""A doc placed under templates/<type>/docs/ ships only to that type.

	MODEL CHANGE: the old test_python_lang_files_only_for_python relied on a
	docs/PYTHON_STYLE.md at the universal root being gated to python by override.
	Under the location model, language-specificity comes from typed-overlay
	PLACEMENT: a doc under templates/python/docs/ reaches python only, and a doc
	under templates/typescript/docs/ reaches typescript only.
	"""
	py_docs = tmp_path / 'templates' / 'python' / 'docs'
	py_docs.mkdir(parents=True)
	(py_docs / 'PY_ONLY.md').write_text('test')
	plan_py = repolib.files.compute_propagation_plan(str(tmp_path), 'python')
	plan_ts = repolib.files.compute_propagation_plan(str(tmp_path), 'typescript')
	plan_other = repolib.files.compute_propagation_plan(str(tmp_path), 'other')
	assert 'docs/PY_ONLY.md' in plan_py['overwrite_files']
	assert 'docs/PY_ONLY.md' not in plan_ts['overwrite_files']
	assert 'docs/PY_ONLY.md' not in plan_other['overwrite_files']


def test_typed_overlay_devel_is_language_specific(tmp_path: pathlib.Path) -> None:
	"""A devel tool under templates/python/devel/ ships only to python repos.

	MODEL CHANGE: the old test_other_gets_python_style_only placed
	devel/submit_to_pypi.py at the UNIVERSAL devel root and asserted 'other' did
	not get it via override gating. A universal devel/ file now ships to every
	type by location; language-specific devel content must live in the typed
	overlay, where placement -- not an override -- restricts delivery.
	"""
	py_devel = tmp_path / 'templates' / 'python' / 'devel'
	py_devel.mkdir(parents=True)
	(py_devel / 'py_tool.py').write_text('test')
	plan_py = repolib.files.compute_propagation_plan(str(tmp_path), 'python')
	plan_ts = repolib.files.compute_propagation_plan(str(tmp_path), 'typescript')
	plan_other = repolib.files.compute_propagation_plan(str(tmp_path), 'other')
	assert 'py_tool.py' in plan_py['devel_files']
	assert 'py_tool.py' not in plan_ts['devel_files']
	assert 'py_tool.py' not in plan_other['devel_files']


def test_universal_noexist_overrides_overwrite(tmp_path: pathlib.Path) -> None:
	"""AGENTS.md in UNIVERSAL_NOEXIST moves to noexist_files, not overwrite."""
	(tmp_path / 'AGENTS.md').write_text('test')
	plan = repolib.files.compute_propagation_plan(str(tmp_path), 'python')
	assert 'AGENTS.md' not in plan['overwrite_files']
	assert 'AGENTS.md' in plan['noexist_files']


def test_universal_noexist_root_file_reaches_every_type(tmp_path: pathlib.Path) -> None:
	"""An allowlisted UNIVERSAL_NOEXIST root file lands in noexist for all types.

	source_me.sh is on ROOT_PROPAGATE_ALLOWLIST and in UNIVERSAL_NOEXIST, so it
	ships only-when-absent to python, typescript, and other alike -- universal
	delivery driven by location, not per-type override.
	"""
	(tmp_path / 'source_me.sh').write_text('test')
	for repo_type in ('python', 'typescript', 'other'):
		plan = repolib.files.compute_propagation_plan(str(tmp_path), repo_type)
		assert 'source_me.sh' in plan['noexist_files']
		assert 'source_me.sh' not in plan['overwrite_files']


def test_root_file_not_in_allowlist_excluded(tmp_path: pathlib.Path) -> None:
	"""Root file outside allowlist not in plan."""
	(tmp_path / 'random_root.md').write_text('test')
	plan = repolib.files.compute_propagation_plan(str(tmp_path), 'python')
	assert 'random_root.md' not in plan['overwrite_files']
	assert 'random_root.md' not in plan['noexist_files']


def test_gitignore_blocks_loaded_from_files(tmp_path: pathlib.Path) -> None:
	"""Gitignore blocks loaded from gitignore.universal and templates/<type>/gitignore.<type>."""
	# Universal lives under templates/, not at template root.
	templates_dir = tmp_path / 'templates'
	templates_dir.mkdir()
	(templates_dir / 'gitignore.universal').write_text('report_*.txt\n.DS_Store\n')
	ts_dir = tmp_path / 'templates' / 'typescript'
	ts_dir.mkdir()
	(ts_dir / 'gitignore.typescript').write_text('node_modules/\ndist/\n')
	plan = repolib.files.compute_propagation_plan(str(tmp_path), 'typescript')
	assert 'report_*.txt' in plan['gitignore_block']
	assert '.DS_Store' in plan['gitignore_block']
	assert 'node_modules/' in plan['gitignore_block']
	assert 'dist/' in plan['gitignore_block']
