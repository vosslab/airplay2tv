"""Per-repo propagation orchestration shared by entry scripts.

Holds the context builder and the per-repo apply logic so both
propagate_style_guides.py and reset_repo.py can drive propagation without
importing each other. All clients build a context via build_context_for_repo()
and process one repo via process_repo().
"""

import os

import repolib.console
import repolib.files
import repolib.model
import repolib.repo


#============================================
def build_context_for_repo(repo_path: str, dry_run: bool, initial_setup: bool,
		auto_discover: bool, write_marker: bool) -> repolib.model.PropagateContext:
	"""
	Build a PropagateContext for a single target repo.

	Single shared contract for both entry scripts. Resolves repo_path to an
	absolute path and resolves the source template root from the running source
	checkout -- the one that contains propagate_style_guides.py and repolib/ --
	NOT from the target -R repo. propagate_style_guides.py calls this with
	initial_setup=False, auto_discover=True, write_marker=True; reset_repo.py
	calls it with initial_setup=True, auto_discover=False, write_marker=False.

	Args:
		repo_path (str): Direct path to the target repo directory.
		dry_run (bool): If True, only display planned changes.
		initial_setup (bool): If True, this run intentionally applies the selected
			project template to the current checkout. Skips the self-skip guard so
			the template repo can propagate files onto itself. Also force-copies
			noexist files even when already present. Batch propagation keeps
			initial_setup=False.
		auto_discover (bool): If True, scan the SOURCE template tests/ for
			test_*.py/test_*.mjs files absent from the static spec and add them
			to what gets copied INTO the target repo. Single-repo meaning only;
			it never walks other repos.
		write_marker (bool): If True, predict and write REPO_TYPE when missing.

	Returns:
		PropagateContext: Immutable context for all orchestration helpers.
	"""
	repo_name = os.path.basename(os.path.normpath(os.path.abspath(os.path.expanduser(repo_path))))
	source_dir = repolib.repo.resolve_source_dir(None)
	template_root = repolib.files.normalize_path(source_dir)

	context = repolib.model.PropagateContext(
		source_dir=source_dir,
		template_root=template_root,
		repo_name=repo_name,
		dry_run=dry_run,
		initial_setup=initial_setup,
		auto_discover=auto_discover,
		write_marker=write_marker,
	)
	return context


#============================================
def remove_deprecated_tests(tests_dir: str, dry_run: bool) -> int:
	"""
	Remove deprecated tests scripts from one repo's tests directory.
	"""
	deprecated_tests = repolib.files.load_deprecation_list(
		'meta/propagation/deprecated_tests.txt',
		os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
	)

	removed = 0
	for deprecated_test_file in deprecated_tests:
		deprecated_test_path = os.path.join(tests_dir, deprecated_test_file)
		if not os.path.isfile(deprecated_test_path):
			continue
		if dry_run:
			repolib.console.log_action("removed", deprecated_test_path, dry_run=True)
		else:
			os.remove(deprecated_test_path)
			repolib.console.log_action("removed", deprecated_test_path)
		removed += 1
	return removed


#============================================
def apply_file_bucket(bucket_name: str, spec: dict, repo_dir: str, repo_type: str, context: repolib.model.PropagateContext, counters: dict) -> tuple[int, int, int]:
	"""
	Process one file bucket (overwrite_files, noexist_files, devel_files, test_files).

	Returns a tuple of (updates, copies, skips) for the per-repo summary line.
	Updates counters in-place.

	Args:
		bucket_name: One of 'overwrite_files', 'noexist_files', 'devel_files', 'test_files'.
		spec: The spec dict containing all four bucket lists.
		repo_dir: The repo directory path.
		repo_type: The detected repo type.
		context: The PropagateContext object.
		counters: The global counters dict (modified in-place).

	Returns:
		Tuple of (bucket_updates, bucket_copies, bucket_skips) for per-repo summary.
	"""
	bucket_updates = 0
	bucket_copies = 0
	bucket_skips = 0

	# Defense in depth: assert no dispatcher entry is a META FILE even if the
	# walker was bypassed (plan read from disk, user-supplied paths, etc.).
	# Uses the META_FILES-only guard, not the strict directory-traversal guard:
	# consumer paths may legitimately live under a META_DIRS-named directory
	# (e.g. typed-overlay tools/ ships at the consumer's tools/), and rejecting
	# those here would block the new "every templates/<type>/ file ships" standard.
	for entry in spec.get(bucket_name, []):
		repolib.files.assert_not_meta_file(entry)

	if bucket_name == 'overwrite_files':
		# ============ OVERWRITE BUCKET ============
		# Overwrite: copy to repo at exact path.
		for file_rel in spec['overwrite_files']:
			source_file = repolib.model.find_source_for_bucket(context.source_dir, 'overwrite_files', file_rel, repo_type)
			if source_file is None:
				counters['errors'] += 1
				repolib.console.log_action("error", f"source missing for {file_rel}")
				continue

			dest_file = os.path.join(repo_dir, file_rel)

			if os.path.abspath(dest_file) == os.path.abspath(source_file):
				repolib.console.log_action("skip", f"self: {dest_file}", counters)
				continue

			# Regular overwrite: use copy_if_changed
			def _format_overwrite_path(s: str, d: str) -> str:
				"""Format path for overwrite bucket with context."""
				return repolib.model.format_path_pair(s, d, repo_dir, context)
			result = repolib.files.copy_if_changed(source_file, dest_file, context.dry_run, counters, action_label='update', format_path=_format_overwrite_path)
			if not context.dry_run:
				if result == 'copied':
					counters['copied_count'] += 1
				elif result == 'updated':
					counters['updated_count'] += 1
					bucket_updates += 1
			else:
				# On dry-run, result is still the action we would take
				if result == 'updated':
					bucket_updates += 1

	elif bucket_name == 'noexist_files':
		# ============ NOEXIST BUCKET ============
		# Noexist: copy only if destination does not exist; initial_setup mode overrides.
		for file_rel in spec['noexist_files']:
			source_file = repolib.model.find_source_for_bucket(context.source_dir, 'noexist_files', file_rel, repo_type)
			if source_file is None:
				counters['errors'] += 1
				repolib.console.log_action("error", f"source missing for {file_rel}")
				continue

			dest_file = os.path.join(repo_dir, file_rel)

			if os.path.abspath(dest_file) == os.path.abspath(source_file):
				repolib.console.log_action("skip", f"self: {dest_file}", counters)
				continue

			if file_rel == 'source_me.sh' and repolib.repo.repo_is_on_path(repo_dir):
				repolib.console.log_action("skip", f"path: {dest_file} (repo is already on PATH)", counters)
				continue

			if os.path.exists(dest_file) and not context.initial_setup:
				repolib.console.log_action("skip", f"{dest_file} (exists; initial_setup mode overrides)", counters)
				bucket_skips += 1
				continue

			dest_parent = os.path.dirname(dest_file)
			if dest_parent and not os.path.isdir(dest_parent):
				repolib.files.make_dir_safe(dest_parent, context.dry_run)

			formatted_path = repolib.model.format_path_pair(source_file, dest_file, repo_dir, context)
			repolib.files.copy_file_safe(source_file, dest_file, context.dry_run, action='copy', message=formatted_path if context.dry_run else None)
			if not context.dry_run:
				repolib.console.log_action("copy", formatted_path)
				counters['copied_count'] += 1
			bucket_copies += 1

	elif bucket_name == 'devel_files':
		# ============ DEVEL BUCKET ============
		# Devel: copy to repo/devel/<basename>; flat namespace, not subdirectory-preserved.
		for file_rel in spec['devel_files']:
			source_file = repolib.model.find_source_for_bucket(context.source_dir, 'devel_files', file_rel, repo_type)
			if source_file is None:
				counters['errors'] += 1
				repolib.console.log_action("error", f"source missing for devel_files:{file_rel}")
				continue

			dest_file = repolib.model.target_path_for_bucket(repo_dir, 'devel_files', file_rel)

			if os.path.abspath(dest_file) == os.path.abspath(source_file):
				repolib.console.log_action("skip", f"self: {dest_file}", counters)
				continue

			# Use copy_if_changed for standard overwrite semantics
			def _format_devel_path(s: str, d: str) -> str:
				"""Format path for devel bucket with context."""
				return repolib.model.format_path_pair(s, d, repo_dir, context)
			result = repolib.files.copy_if_changed(source_file, dest_file, context.dry_run, counters, action_label='update', format_path=_format_devel_path)
			if not context.dry_run:
				if result == 'copied':
					counters['copied_count'] += 1
				elif result == 'updated':
					counters['updated_count'] += 1
					bucket_updates += 1
			else:
				# On dry-run, result is still the action we would take
				if result == 'updated':
					bucket_updates += 1

	elif bucket_name == 'merge_files':
		# ============ MERGE BUCKET ============
		# Merge: replace template-managed fenced region in consumer file; preserve consumer
		# additions outside the fences. See meta/docs/MERGE_BUCKET_SPEC.md.
		for file_rel in spec['merge_files']:
			# Merge sources live at template_root paths (same lookup shape as overwrite_files).
			source_file = repolib.model.find_source_for_bucket(context.source_dir, 'overwrite_files', file_rel, repo_type)
			if source_file is None:
				counters['errors'] += 1
				repolib.console.log_action("error", f"source missing for merge_files:{file_rel}")
				continue

			dest_file = os.path.join(repo_dir, file_rel)

			if os.path.abspath(dest_file) == os.path.abspath(source_file):
				repolib.console.log_action("skip", f"self: {dest_file}", counters)
				continue

			outcome = repolib.files.merge_at_imports_safe(source_file, dest_file, context.dry_run, counters)
			if outcome == 'merged':
				bucket_updates += 1
			elif outcome == 'created':
				bucket_copies += 1

	elif bucket_name == 'test_files':
		# ============ TEST BUCKET ============
		# Test: copy to tests/<file_rel> preserving tests/ prefix; auto-discovered files merge here.
		for file_rel in spec['test_files']:
			source_file = repolib.model.find_source_for_bucket(context.source_dir, 'test_files', file_rel, repo_type)
			if source_file is None:
				counters['errors'] += 1
				repolib.console.log_action("error", f"source missing for test_files:{file_rel}")
				continue

			dest_file = repolib.model.target_path_for_bucket(repo_dir, 'test_files', file_rel)

			if os.path.abspath(dest_file) == os.path.abspath(source_file):
				repolib.console.log_action("skip", f"self: {dest_file}", counters)
				continue

			# Use copy_if_changed for standard overwrite semantics
			def _format_test_path(s: str, d: str) -> str:
				"""Format path for test bucket with context."""
				return repolib.model.format_path_pair(s, d, repo_dir, context)
			result = repolib.files.copy_if_changed(source_file, dest_file, context.dry_run, counters, action_label='update', format_path=_format_test_path)
			if not context.dry_run:
				if result == 'copied':
					counters['copied_count'] += 1
				elif result == 'updated':
					counters['updated_count'] += 1
					bucket_updates += 1
			else:
				# On dry-run, result is still the action we would take
				if result == 'updated':
					bucket_updates += 1

	return (bucket_updates, bucket_copies, bucket_skips)


#============================================
def process_repo(repo_dir: str, context: repolib.model.PropagateContext, counters: dict, emit_per_repo_summary: bool = True) -> dict | None:
	"""
	Process a single repository: read type, discover files, and perform propagation.

	Handles all per-repo logic: type detection, directory creation, file propagation
	across four buckets (overwrite, noexist, devel, test), gitignore management,
	and optionally per-repo summary output. Updates counters in-place.

	Return contract (single source of truth):
	  - None   = intentionally skipped (not a git repo, or self-skip guard fired)
	  - dict   = propagation applied; keys 'name' and 'type' identify the repo
	  - raises = failure; caller is responsible for catching and counting

	Args:
		repo_dir (str): Path to the repository directory.
		context (PropagateContext): Immutable context with template and flag info.
		counters (dict): Mutable counter dict (copied_count, updated_count, etc.).
		emit_per_repo_summary (bool): If False, suppress per-repo summary output
			(used in single-repo mode where summary is printed at end).

	Returns:
		dict | None: {'name': repo_basename, 'type': repo_type} or None if skipped.
	"""
	if not repolib.repo.is_repo_dir(repo_dir):
		return None

	# Self-skip guard: when the target IS the template repo, skip unless this is
	# an initial_setup run (reset_repo.py bootstrapping the template itself).
	repo_normalized = repolib.files.normalize_path(repo_dir)
	if repo_normalized == context.template_root and not context.initial_setup:
		repolib.console.log_action("skip", f"self: {repo_dir}", counters)
		return None

	single_repo_mode = context.repo_name is not None
	# skip_confirm field removed from context; always False in single-repo interactive mode
	repo_type = repolib.repo.read_repo_type(
		repo_dir,
		single_repo_mode=single_repo_mode,
		write_marker=context.write_marker,
		skip_confirm=False,
		non_interactive=False,
		counters=counters
	)

	# Capture baseline counters to calculate per-repo deltas for quiet counts
	baseline_unchanged = counters['unchanged']
	baseline_skipped_source = counters['skipped_source']
	baseline_skipped_self = counters['skipped_self']
	baseline_skipped_path = counters['skipped_path']
	baseline_skipped_policy = counters['skipped_policy']
	baseline_merged_count = counters['merged_count']
	baseline_created_count = counters['created_count']

	# Per-repo counters for summary line
	repo_updates = 0
	repo_copies = 0
	repo_skips = 0

	spec = repolib.files.resolve_spec_for_type(repo_type, context.source_dir, counters=counters, repo_dir=repo_dir)

	auto_discovered = []
	if context.auto_discover:
		auto_discovered = repolib.files.auto_discover_test_files(context.source_dir, repo_type)
		if auto_discovered:
			counters['auto_discovered_count'] += len(auto_discovered)
			spec['test_files'].extend(auto_discovered)
			# Informational summary, not an action - bypasses log_action so no counter increments.
			repolib.console.CONSOLE.print(f"auto-discovered {len(auto_discovered)} test files: {', '.join(auto_discovered)}")

	docs_dir = os.path.join(repo_dir, 'docs')
	if not os.path.isdir(docs_dir):
		repolib.files.make_dir_safe(docs_dir, context.dry_run)

	tests_dir = os.path.join(repo_dir, 'tests')
	if repolib.files.ensure_tests_dir(tests_dir, context.dry_run):
		if context.dry_run:
			repolib.console.log_action("create", tests_dir, counters=counters, dry_run=True)

	conftest_path = os.path.join(tests_dir, 'conftest.py')
	source_conftest = os.path.join(context.source_dir, 'tests', 'conftest.py')
	if os.path.abspath(conftest_path) != os.path.abspath(source_conftest):
		merged_conftest = repolib.files.merge_conftest(source_conftest, conftest_path)
		if merged_conftest is not None:
			dest_existed = os.path.isfile(conftest_path)
			action = 'merge' if dest_existed else 'create'
			repolib.files.write_text(conftest_path, merged_conftest, context.dry_run, action=action)
			if not context.dry_run:
				if dest_existed:
					repolib.console.log_action("merge", f"injected collect_ignore into {conftest_path}", counters=counters)
					counters['merged_count'] += 1
				else:
					repolib.console.log_action("create", conftest_path, counters=counters)
					counters['created_count'] += 1

	remove_deprecated_tests(tests_dir, context.dry_run)

	devel_dir = os.path.join(repo_dir, 'devel')
	if not os.path.isdir(devel_dir):
		repolib.files.make_dir_safe(devel_dir, context.dry_run)

	changelog_path = os.path.join(docs_dir, 'CHANGELOG.md')
	if repolib.files.ensure_changelog_file(changelog_path, context.dry_run):
		if not context.dry_run:
			counters['created_count'] += 1

	# Apply file buckets
	updates, copies, skips = apply_file_bucket('overwrite_files', spec, repo_dir, repo_type, context, counters)
	repo_updates += updates
	repo_copies += copies
	repo_skips += skips

	updates, copies, skips = apply_file_bucket('noexist_files', spec, repo_dir, repo_type, context, counters)
	repo_updates += updates
	repo_copies += copies
	repo_skips += skips

	updates, copies, skips = apply_file_bucket('merge_files', spec, repo_dir, repo_type, context, counters)
	repo_updates += updates
	repo_copies += copies
	repo_skips += skips

	updates, copies, skips = apply_file_bucket('devel_files', spec, repo_dir, repo_type, context, counters)
	repo_updates += updates
	repo_copies += copies
	repo_skips += skips

	updates, copies, skips = apply_file_bucket('test_files', spec, repo_dir, repo_type, context, counters)
	repo_updates += updates
	repo_copies += copies
	repo_skips += skips

	# Process gitignore blocks, then dedupe across blocks (e.g., dist/ in
	# both python and typescript would otherwise duplicate).
	repolib.files.merge_gitignore_blocks(repo_dir, repo_type, context.source_dir, context, counters=counters)
	gitignore_path = os.path.join(repo_dir, '.gitignore')
	repolib.files.deduplicate_gitignore(gitignore_path, context.dry_run, counters=counters)
	deprecated_tests = repolib.files.load_deprecation_list(
		'meta/propagation/deprecated_gitignore.txt',
		context.source_dir
	)
	removed_deprecated = repolib.files.remove_gitignore_entries(gitignore_path, deprecated_tests, context.dry_run)
	if not context.dry_run and removed_deprecated > 0:
		counters['merged_count'] += 1

	# Per-repo summary block with quiet counter deltas (only if emit_per_repo_summary is True)
	repo_unchanged = counters['unchanged'] - baseline_unchanged
	repo_skipped_source = counters['skipped_source'] - baseline_skipped_source
	repo_skipped_self = counters['skipped_self'] - baseline_skipped_self
	repo_skipped_path = counters['skipped_path'] - baseline_skipped_path
	repo_skipped_policy = counters['skipped_policy'] - baseline_skipped_policy
	repo_merged = counters['merged_count'] - baseline_merged_count
	repo_created = counters['created_count'] - baseline_created_count

	repo_basename = os.path.basename(repo_dir)
	repo_type_display = repo_type

	if emit_per_repo_summary:
		# Header line: repo=name  type=python
		header = f"repo={repo_basename}  type={repo_type_display}"
		repolib.console.CONSOLE.print(f"[bold]{header}[/]")

		# Counter rows: indented, right-aligned counters
		# Build list of (name, value) tuples in display order
		counter_rows = [
			('updated', repo_updates),
			('copied', repo_copies),
			('merged', repo_merged),
			('created', repo_created),
			('unchanged', repo_unchanged),
			('skipped', repo_skipped_source + repo_skipped_self + repo_skipped_path + repo_skipped_policy),
			('errors', counters['errors']),
		]

		# Compute column width for counter names
		col_width = max(len(name) for name, _ in counter_rows) + 1

		# Print each counter row
		for name, value in counter_rows:
			if name == 'errors' and value > 0:
				repolib.console.CONSOLE.print(f"  {name.ljust(col_width)}[bold red]{value}[/]")
			else:
				repolib.console.CONSOLE.print(f"  {name.ljust(col_width)}{value}")

	# Return repo info for summary aggregation
	return {'name': repo_basename, 'type': repo_type}


#============================================
def exit_code_for(counters: dict) -> int:
	"""
	Compute exit code based on error count.

	Returns 1 if counters['errors'] > 0, else returns 0.

	Args:
		counters (dict): Counter dict with 'errors' key.

	Returns:
		int: 0 if no errors, 1 if any errors occurred.
	"""
	if counters['errors'] > 0:
		return 1
	return 0
