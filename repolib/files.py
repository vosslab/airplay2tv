"""File operations, I/O helpers, and merge logic."""

# Standard Library
import os
import shutil
import filecmp
import fnmatch
import collections.abc

# local repo modules
import repolib.console
import repolib.model


#============================================
# META leak guard
#============================================

def is_meta_file(file_rel: str) -> bool:
	"""Return True when a path is template-meta and must never ship.

	A path is meta when it matches META_FILES exactly (by full rel-path or bare
	basename) OR matches any META_FILE_PATTERNS glob (e.g. changelog archives).

	Args:
		file_rel (str): Repo-root-relative file path.

	Returns:
		bool: True when the path must never ship.
	"""
	basename = os.path.basename(file_rel)
	if file_rel in repolib.model.META_FILES or basename in repolib.model.META_FILES:
		return True
	for pattern in repolib.model.META_FILE_PATTERNS:
		if fnmatch.fnmatch(file_rel, pattern):
			return True
	return False


def assert_not_meta_file(file_rel: str) -> None:
	"""
	Fail loud if a path is template-meta and must never ship to a consumer.

	Delegates to is_meta_file, which checks both META_FILES (exact basename or
	full rel-path) AND META_FILE_PATTERNS globs (e.g. changelog archive
	patterns like docs/CHANGELOG-*.md). This is the consumer-path-safe guard:
	it protects per-consumer files the template must never clobber (README.md,
	VERSION, .gitignore, etc.) without rejecting paths that merely traverse a
	META_DIRS component. Legitimate consumer paths may live under a directory
	named like a META_DIRS entry -- for example templates/<type>/tools/ ships
	at the consumer's tools/ -- so the apply-time dispatcher uses this check,
	not the stricter directory-traversal check in assert_not_meta.

	Args:
		file_rel: Repo-root-relative file path about to be copied to a consumer.

	Raises:
		RuntimeError: file_rel matches META_FILES by basename or rel-path.
	"""
	if is_meta_file(file_rel):
		raise RuntimeError(
			f"META leak: {file_rel!r} is in META_FILES and must never ship. "
			"Fix the upstream walker or dispatcher branch that produced this entry."
		)


def assert_not_meta(file_rel: str) -> None:
	"""
	Fail loud if a template-relative path would land in any bucket despite being META.

	Called at every UNIVERSAL-walk plan-construction append site. Catches walker
	leaks where a universal-walk branch forgets to filter a META file or a path
	under a META_DIRS directory (e.g. the ROOT tools/ infrastructure).

	This is the strict guard: it rejects both META_FILES matches AND any path
	traversing a META_DIRS component. It must NOT be used on consumer paths from
	the typed overlay, where a consumer tools/ subpath is legitimate. Apply-time
	and typed-overlay code use assert_not_meta_file instead.

	Args:
		file_rel: Template-root-relative file path about to be added to a bucket.

	Raises:
		RuntimeError: file_rel matches META_FILES by basename or rel-path,
		              OR any path component matches META_DIRS.
	"""
	assert_not_meta_file(file_rel)
	parts = file_rel.split(os.sep)
	for part in parts:
		if part in repolib.model.META_DIRS:
			raise RuntimeError(
				f"META leak: {file_rel!r} traverses META_DIRS component {part!r} "
				"and must never ship. Fix the upstream walker or dispatcher branch."
			)


#============================================
# Routing overrides
#============================================

def should_ship_override(file_rel: str, repo_lang: str, repo_dir: str) -> bool | None:
	"""
	Apply routing overrides on top of the walker's default routing.

	Location is now the primary propagation determinant, so the only override this
	predicate evaluates is `exclude_repos`: it blocks a file when the destination
	repo basename is on that file's exclusion list. All other keys are unlisted and
	return None (the walker's location-based decision stands).

	The `repo_lang` parameter is retained for caller compatibility but is no longer
	consulted; language gating moved into the template folder layout.

	Args:
		file_rel (str): Repo-root-relative file path.
		repo_lang (str): Repository language type (kept for caller compatibility; unused).
		repo_dir (str): Repository directory path.

	Returns:
		bool or None: False if exclude_repos blocks the file for this destination repo,
		              None if no override applies (the common case).
	"""
	rule = repolib.model.ROUTING_OVERRIDES.get(file_rel)
	if rule is None:
		return None
	# Per-destination-repo exclusion: block when this dest repo is on the exclude list.
	exclude_repos = rule.get('exclude_repos')
	if exclude_repos is not None and os.path.basename(os.path.normpath(repo_dir)) in exclude_repos:
		return False
	return None


#============================================
# File and text mutation helpers
#============================================

def copy_file_safe(src: str, dst: str, dry_run: bool, action: str = 'copy', message: str | None = None) -> bool:
	"""
	Copy a file from src to dst, preserving mode bits (executable bit).

	Returns False on dry-run (logs dry-run line), True on actual copy.
	Raises exception on error (no try/except per code style).

	Args:
		src (str): Source file path.
		dst (str): Destination file path.
		dry_run (bool): If True, only log without copying.
		action (str): Action word for dry-run message (default 'copy').
		message (str): Optional pre-formatted message. If provided, overrides default formatting.

	Returns:
		bool: False on dry-run, True on actual copy.
	"""
	if dry_run:
		if message is None:
			message = f"{src} -> {dst}"
		repolib.console.log_action(action, message, dry_run=True)
		return False
	shutil.copy2(src, dst)
	return True


def make_dir_safe(path: str, dry_run: bool) -> bool:
	"""
	Create a directory if it does not exist.

	Returns False on dry-run, True on actual mkdir.
	"""
	if dry_run:
		repolib.console.log_action("create", path, dry_run=True)
		return False
	os.makedirs(path, exist_ok=True)
	return True


def copy_if_changed(source: str, dest: str, dry_run: bool, counters: dict, action_label: str = 'copy', format_path: collections.abc.Callable | None = None) -> str:
	"""
	Copy source to dest only if they differ; return indicator and suppress or log outcome.

	Args:
		source (str): Path to source file.
		dest (str): Path to destination file.
		dry_run (bool): If True, only log planned action without copying.
		counters (dict): Mutable counter dict to increment for SKIP and NO CHANGE (quiet tags).
			When counters is provided, these tags are counted but not printed.
		action_label (str): Label for dry-run output (default 'copy').
		format_path (callable | None): Optional function to format path pairs.
			Called as format_path(source, dest) and should return formatted path string.
			If None, uses default "{source} -> {dest}" format.

	Returns:
		str: One of 'skipped_source', 'no_change', 'copied', 'updated'.

	Behavior:
		- If source missing: logs SKIP to counters, returns 'skipped_source'.
		- If dest exists and files match: logs NO CHANGE to counters, returns 'no_change'.
		- Otherwise: copies/updates, logs COPIED or UPDATED (non-quiet, always printed),
		  returns 'copied' or 'updated'.

	Note:
		Message-prefix ('source:', 'self:', 'path:') drives counter dispatch via log_action().
		Callers that log non-standard prefixes must ensure log_action() handles them.

	Uses copy_file_safe() and make_dir_safe() underneath.
	"""
	def _default_format_path(s: str, d: str) -> str:
		"""Default path formatter when none provided."""
		return f"{s} -> {d}"

	if format_path is None:
		format_path = _default_format_path

	# Check if source exists
	if not os.path.isfile(source):
		repolib.console.log_action("skip", f"source: {source} (not found)", counters)
		return 'skipped_source'

	# Check if dest exists and compare
	dest_exists = os.path.isfile(dest)
	is_same = False
	if dest_exists:
		is_same = filecmp.cmp(source, dest, shallow=False)
	if is_same:
		repolib.console.log_action("no change", dest, counters)
		return 'no_change'

	# Ensure parent directory exists
	dest_parent = os.path.dirname(dest)
	if dest_parent and not os.path.isdir(dest_parent):
		make_dir_safe(dest_parent, dry_run)

	# Copy the file
	formatted_path = format_path(source, dest)
	action = 'update' if dest_exists else 'copy'
	copy_file_safe(source, dest, dry_run, action=action, message=formatted_path if dry_run else None)
	if not dry_run:
		if dest_exists:
			repolib.console.log_action("update", formatted_path)
			return 'updated'
		else:
			repolib.console.log_action("copy", formatted_path)
			return 'copied'
	else:
		# On dry-run, copy_file_safe() already printed; return the action we would take
		return 'updated' if dest_exists else 'copied'


def read_text(path: str) -> str:
	"""
	Read a UTF-8 text file.

	Returns the file contents as a string.
	"""
	with open(path, 'r', encoding='utf-8') as f:
		return f.read()


def write_text(path: str, content: str, dry_run: bool = False, action: str = 'update') -> bool:
	"""
	Write content to a UTF-8 text file.

	Returns False on dry-run (logs dry-run line), True on actual write.
	"""
	if dry_run:
		repolib.console.log_action(action, path, dry_run=True)
		return False
	with open(path, 'w', encoding='utf-8') as f:
		f.write(content)
	return True


#============================================
def safe_walk(root: str) -> collections.abc.Iterator[tuple[str, list[str], list[str]]]:
	"""
	Walk directory tree filtering out unwanted directories.

	Yields (dirpath, dirs, files) tuples like os.walk, with the following filters applied:
	- Skips directories in SKIP_WALK_DIRS
	- Skips directories starting with '.' (dotdirs)
	- Mutates dirs[:] internally so callers don't need to

	Args:
		root (str): Root directory to walk

	Yields:
		tuple: (dirpath, dirs, files) with dirs[:] already filtered
	"""
	for dirpath, dirs, files in os.walk(root, topdown=True, followlinks=False):
		dirs[:] = [d for d in dirs if d not in repolib.model.SKIP_WALK_DIRS and not d.startswith('.')]
		yield dirpath, dirs, files


#============================================
def load_gitignore_block(path: str) -> list[str]:
	"""
	Load gitignore block from file, filtering blanks and comments.

	Args:
		path (str): Path to gitignore source file.

	Returns:
		list[str]: List of non-blank, non-comment lines (stripped).
	"""
	if not os.path.isfile(path):
		return []
	content = read_text(path)
	lines = []
	for line in content.split('\n'):
		stripped = line.rstrip('\n').strip()
		if stripped and not stripped.startswith('#'):
			lines.append(stripped)
	return lines


#============================================
def normalize_path(path: str) -> str:
	"""
	Normalize a path for stable filesystem comparisons.
	"""
	return os.path.normcase(os.path.realpath(os.path.abspath(path)))


#============================================
def remove_gitignore_entries(gitignore_path: str, entries: list[str], dry_run: bool) -> int:
	"""
	Remove deprecated entries from .gitignore file.

	Args:
		gitignore_path (str): Path to .gitignore file.
		entries (list[str]): List of gitignore patterns to remove.
		dry_run (bool): If True, do not write changes.

	Returns:
		int: Number of lines removed.
	"""
	if not os.path.isfile(gitignore_path):
		return 0

	content = read_text(gitignore_path)
	lines = [line.rstrip('\n') for line in content.split('\n')]

	entries_set = set(entry.strip() for entry in entries)
	filtered_lines = []
	removed_count = 0

	for line in lines:
		stripped = line.strip()
		if stripped in entries_set:
			removed_count += 1
			continue
		filtered_lines.append(line.rstrip())

	if removed_count == 0:
		return 0

	new_content = '\n'.join(filtered_lines) + '\n' if filtered_lines else ''
	write_text(gitignore_path, new_content, dry_run)

	return removed_count


#============================================
def deduplicate_gitignore(gitignore_path: str, dry_run: bool, counters: dict | None = None) -> None:
	"""
	Remove duplicate lines and trailing whitespace from .gitignore file.
	Preserves all empty lines and comments for visual grouping.

	Updates counters dict in-place if provided: increments 'merged_count' when changes
	are made (duplicates removed and/or whitespace cleaned).

	Args:
		gitignore_path (str): Path to .gitignore file.
		dry_run (bool): If True, do not write changes.
		counters (dict | None): Optional counter dict to update with merged_count.
	"""
	if not os.path.isfile(gitignore_path):
		return

	content = read_text(gitignore_path)
	original_lines = [line.rstrip('\n') for line in content.split('\n')]

	stripped_lines = [line.rstrip() for line in original_lines]

	seen = set()
	unique_lines = []
	for line in stripped_lines:
		if line == '':
			unique_lines.append(line)
		elif line not in seen:
			seen.add(line)
			unique_lines.append(line)

	duplicates_removed = len(stripped_lines) - len(unique_lines)
	whitespace_cleaned = any(orig != stripped for orig, stripped in zip(original_lines, stripped_lines))

	if duplicates_removed == 0 and not whitespace_cleaned:
		return

	new_content = '\n'.join(unique_lines) + '\n' if unique_lines else ''
	write_text(gitignore_path, new_content, dry_run)

	if not dry_run and counters is not None:
		counters['merged_count'] += 1


#============================================
def replace_managed_block(lines: list[str], header: str, block_lines: list[str]) -> list[str]:
	"""
	Replace or append a named managed block in a line list.

	Finds the named block (starting with header) and replaces it with the new content.
	If the block is absent, appends at end. Idempotent: works correctly on multiple calls.

	Args:
		lines (list[str]): Existing lines.
		header (str): Block header to search for (e.g., '# === UNIVERSAL ===').
		block_lines (list[str]): New block content (without header).

	Returns:
		list[str]: New line list with the block replaced or appended.
	"""
	start_idx = -1
	for i, line in enumerate(lines):
		if line.startswith(header):
			start_idx = i
			break

	if start_idx == -1:
		# Block not found: append
		result = list(lines)
		result.append(header)
		result.extend(block_lines)
		return result

	# Block found: replace
	end_idx = start_idx + 1
	for i in range(start_idx + 1, len(lines)):
		if lines[i].startswith('# ==='):
			end_idx = i
			break
	else:
		end_idx = len(lines)

	result = lines[:start_idx] + [header] + block_lines + lines[end_idx:]
	return result


# MERGE bucket: set-union merge for @-import list files. See meta/docs/MERGE_BUCKET_SPEC.md.

#============================================
def _load_claude_md_deprecated() -> list[str]:
	"""Load the maintainer-curated strip list for CLAUDE.md merges."""
	return load_deprecation_list('meta/propagation/deprecated_claude_md.txt', _get_template_root())


def merge_at_imports_safe(source: str, dest: str, dry_run: bool, counters: dict) -> str:
	"""
	Merge a flat @-import list file by set-union additions + deprecation strips.

	Designed for CLAUDE.md and other files that are nothing more than a list of
	@filename imports plus optional non-@ commentary. No fences required: the
	template content set is added on top of consumer content, and any line
	matching the meta/propagation/deprecated_claude_md.txt list is removed.

	Outcomes:
		'created'   -- dest missing; wrote template verbatim.
		'merged'    -- consumer file updated (additions, removals, or both).
		'unchanged' -- no additions, no removals; consumer already in sync.
		'error'     -- source file missing.
	"""
	if not os.path.isfile(source):
		counters['errors'] += 1
		repolib.console.log_action("error", f"merge source missing: {source}")
		return 'error'

	src_text = read_text(source)

	if not os.path.isfile(dest):
		dest_parent = os.path.dirname(dest)
		if dest_parent and not os.path.isdir(dest_parent):
			make_dir_safe(dest_parent, dry_run)
		write_text(dest, src_text, dry_run, action='create')
		if not dry_run:
			repolib.console.log_action("create", dest)
			counters['created_count'] += 1
		return 'created'

	dest_text = read_text(dest)
	deprecated = set(_load_claude_md_deprecated())

	# split('\n') (not splitlines) preserves trailing-newline state on round-trip.
	src_lines = src_text.split('\n')
	dest_lines = dest_text.split('\n')

	consumer_at_imports = {ln.strip() for ln in dest_lines if ln.strip().startswith('@')}
	pruned_lines = [ln for ln in dest_lines if ln.strip() not in deprecated]

	additions: list[str] = []
	additions_seen: set[str] = set()
	for ln in src_lines:
		stripped = ln.strip()
		if not stripped.startswith('@'):
			continue
		if stripped in consumer_at_imports or stripped in deprecated or stripped in additions_seen:
			continue
		additions.append(stripped)
		additions_seen.add(stripped)

	# Splice additions after the last @-line in the pruned consumer so the
	# new entries cluster with the existing import block.
	if additions:
		insertion_idx = None
		for idx in range(len(pruned_lines) - 1, -1, -1):
			if pruned_lines[idx].strip().startswith('@'):
				insertion_idx = idx + 1
				break
		if insertion_idx is None:
			# No existing @-lines; prepend at top (after any leading blanks).
			insertion_idx = 0
			while insertion_idx < len(pruned_lines) and not pruned_lines[insertion_idx].strip():
				insertion_idx += 1
		new_lines = pruned_lines[:insertion_idx] + additions + pruned_lines[insertion_idx:]
	else:
		new_lines = pruned_lines

	merged = '\n'.join(new_lines)

	# Preserve dest's trailing-newline state.
	if dest_text.endswith('\n') and not merged.endswith('\n'):
		merged += '\n'
	elif not dest_text.endswith('\n') and merged.endswith('\n'):
		merged = merged.rstrip('\n')

	if merged == dest_text:
		repolib.console.log_action("no change", dest, counters)
		return 'unchanged'

	write_text(dest, merged, dry_run, action='merge')
	if not dry_run:
		repolib.console.log_action("merge", dest)
		counters['merged_count'] += 1
	return 'merged'


#============================================
def merge_conftest(source_file: str, dest_file: str) -> str | None:
	"""
	Inject the canonical managed blocks into a destination conftest.py.

	The canonical source tests/conftest.py carries two managed blocks:
	  1. the collect_ignore block (everything before the REPO_HYGIENE_FILTERS
	     marker), which excludes the e2e and playwright tiers from pytest.
	  2. the REPO_HYGIENE_FILTERS block (the documented comment block ending in
	     REPO_HYGIENE_FILTERS = {}), the repo-local hygiene-exclusion registry.

	Both blocks ship additively. Any other consumer content (imports, fixtures,
	a consumer-set collect_ignore value, a consumer-set REPO_HYGIENE_FILTERS
	value) is preserved verbatim. A missing block is appended; an existing block
	is never overwritten.

	Args:
		source_file (str): Path to the canonical tests/conftest.py.
		dest_file (str): Path to the consumer repo's tests/conftest.py.

	Returns:
		str | None: Merged content when an update is needed, None when the
		consumer already carries both managed blocks.
	"""
	source_text = read_text(source_file)
	if not os.path.isfile(dest_file):
		return source_text

	# Split the canonical source into its two managed blocks at the first line
	# that starts the REPO_HYGIENE_FILTERS comment block.
	source_lines = source_text.split('\n')
	marker_idx = None
	for idx, line in enumerate(source_lines):
		if line.startswith('# REPO_HYGIENE_FILTERS'):
			marker_idx = idx
			break
	if marker_idx is None:
		# Canonical source lacks the registry marker; treat the whole source as
		# the collect_ignore block and ship no filters block.
		collect_ignore_block = source_text.rstrip()
		filters_block = ''
	else:
		collect_ignore_block = '\n'.join(source_lines[:marker_idx]).rstrip()
		filters_block = '\n'.join(source_lines[marker_idx:]).rstrip()

	dest_text = read_text(dest_file)
	if dest_text.strip() == '':
		return source_text
	need_collect = 'collect_ignore' not in dest_text
	need_filters = 'REPO_HYGIENE_FILTERS' not in dest_text
	if not need_collect and not need_filters:
		return None

	# Preserve all existing consumer content; append only the missing block(s).
	merged = dest_text.rstrip()
	if need_collect:
		merged += '\n\n' + collect_ignore_block
	if need_filters and filters_block:
		merged += '\n\n' + filters_block
	merged += '\n'
	return merged


#============================================
def merge_gitignore_blocks(repo_dir: str, repo_type: str, template_root: str, context: 'repolib.model.PropagateContext', counters: dict | None = None) -> None:
	"""
	Manage .gitignore as a sequence of named blocks delimited by '# === <NAME> ==='.
	Blocks: UNIVERSAL (always), and <REPO_TYPE_UPPERCASE> (when non-empty).
	If block header exists, replace just that block. If not, append at end.
	User-added lines OUTSIDE any managed block stay untouched.

	Updates counters dict in-place if provided: increments 'created_count' or 'merged_count'
	depending on whether .gitignore was newly created or updated.

	Args:
		repo_dir (str): Repository directory path.
		repo_type (str): Type of repository (python, typescript, rust, swift, other).
		template_root (str): Template root directory for gitignore sources.
		context (PropagateContext): Context with dry_run and path formatting info.
		counters (dict | None): Optional counter dict to update with created/merged counts.
	"""
	gitignore_path = os.path.join(repo_dir, '.gitignore')

	file_exists = os.path.isfile(gitignore_path)
	existing_lines = []
	if file_exists:
		content = read_text(gitignore_path)
		existing_lines = [line.rstrip('\n') for line in content.split('\n')]

	# Load universal and type-specific gitignore blocks from files.
	# Universal source lives under templates/ (not a canonical consumer-root filename).
	gitignore_universal_path = os.path.join(template_root, 'templates', 'gitignore.universal')
	universal_lines = load_gitignore_block(gitignore_universal_path)

	gitignore_typed_path = os.path.join(template_root, 'templates', repo_type, f'gitignore.{repo_type}')
	type_lines = load_gitignore_block(gitignore_typed_path)

	universal_header = '# === UNIVERSAL ==='
	type_header = f"# === {repo_type.upper()} ==="

	# Build new content
	new_lines = list(existing_lines)
	new_lines = replace_managed_block(new_lines, universal_header, universal_lines)

	# Handle type-specific block (if any)
	if type_lines:
		new_lines = replace_managed_block(new_lines, type_header, type_lines)

	# Build content with proper trailing newline
	content = '\n'.join(new_lines)
	if content and not content.endswith('\n'):
		content += '\n'

	existing_content = '\n'.join(existing_lines)
	if existing_lines and not existing_content.endswith('\n'):
		existing_content += '\n'

	# Write if needed
	if not file_exists:
		display_path = repolib.model.format_path_pair(gitignore_path, gitignore_path, repo_dir, context)
		if context.dry_run:
			repolib.console.log_action("create", display_path, dry_run=True)
		else:
			with open(gitignore_path, 'w', encoding='utf-8') as f:
				f.write(content)
			repolib.console.log_action("create", display_path)
			if counters is not None:
				counters['created_count'] += 1
	elif content != existing_content:
		display_path = repolib.model.format_path_pair(gitignore_path, gitignore_path, repo_dir, context)
		if context.dry_run:
			repolib.console.log_action("update", display_path, dry_run=True)
		else:
			with open(gitignore_path, 'w', encoding='utf-8') as f:
				f.write(content)
			repolib.console.log_action("update", display_path)
			if counters is not None:
				counters['merged_count'] += 1



#============================================
def ensure_changelog_file(changelog_path: str, dry_run: bool) -> bool:
	"""
	Create docs/CHANGELOG.md if missing.

	Args:
		changelog_path (str): Path to docs/CHANGELOG.md.
		dry_run (bool): If True, do not write changes.

	Returns:
		bool: True if file was created, False otherwise.
	"""
	if os.path.exists(changelog_path):
		return False

	write_text(changelog_path, '', dry_run, action='create')
	return True


#============================================
def ensure_tests_dir(tests_dir: str, dry_run: bool) -> bool:
	"""
	Create the tests directory if missing.

	Args:
		tests_dir (str): Path to tests directory.
		dry_run (bool): If True, do not write changes.

	Returns:
		bool: True if directory was created, False otherwise.
	"""
	if os.path.isdir(tests_dir):
		return False
	if dry_run:
		return True
	os.makedirs(tests_dir, exist_ok=True)
	return True


#============================================
def load_deprecation_list(rel_path: str, template_root: str) -> list[str]:
	"""Read newline-delimited deprecation entries from meta/propagation/.

	Skips blank lines and comment lines (those starting with '#').
	Raises FileNotFoundError if the file is missing; loud failure beats
	silent missing-deprecation scrub.
	"""
	full_path = os.path.join(template_root, rel_path)
	with open(full_path) as f:
		return [ln.strip() for ln in f if ln.strip() and not ln.lstrip().startswith('#')]


#============================================
# Module-level constants for testing
#============================================
def _get_template_root() -> str:
	"""Compute template root directory lazily."""
	return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _get_deprecated_test_scripts() -> list[str]:
	"""Load deprecated test scripts list lazily."""
	return load_deprecation_list('meta/propagation/deprecated_tests.txt', _get_template_root())


def _get_deprecated_gitignore_entries() -> list[str]:
	"""Load deprecated gitignore entries list lazily."""
	return load_deprecation_list('meta/propagation/deprecated_gitignore.txt', _get_template_root())


# Lazy-loaded module-level exports for test access
TEMPLATE_ROOT = None
DEPRECATED_TEST_SCRIPTS = None
DEPRECATED_GITIGNORE_ENTRIES = None


def _init_module_constants() -> None:
	"""Initialize module-level constants once on first access."""
	global TEMPLATE_ROOT, DEPRECATED_TEST_SCRIPTS, DEPRECATED_GITIGNORE_ENTRIES
	if TEMPLATE_ROOT is not None:
		return  # Already initialized
	TEMPLATE_ROOT = _get_template_root()
	DEPRECATED_TEST_SCRIPTS = _get_deprecated_test_scripts()
	DEPRECATED_GITIGNORE_ENTRIES = _get_deprecated_gitignore_entries()


# Initialize on first import
_init_module_constants()


#============================================
def resolve_spec_for_type(repo_type: str, template_root: str | None = None, counters: dict | None = None, repo_dir: str | None = None) -> dict:
	"""
	Return the six-bucket propagation spec for the given repo_type.
	Uses compute_propagation_plan with template_root (defaults to script directory).
	"""
	# Accept consumer tokens from the shared set plus the internal pseudo-types.
	# Pseudo-types (universal, unknown) are added here explicitly so they never
	# leak into KNOWN_REPO_TYPES and the consumer-facing token set stays clean.
	if repo_type not in repolib.model.KNOWN_REPO_TYPES | {'universal', 'unknown'}:
		raise ValueError(f"unknown repo type {repo_type!r}")
	if template_root is None:
		template_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
	if repo_type == 'universal':
		repo_type = 'python'  # 'universal' is an alias for python in the fold scheme
	return compute_propagation_plan(template_root, repo_type, counters=counters, repo_dir=repo_dir)


#============================================
def auto_discover_test_files(template_root: str, repo_type: str) -> list[str]:
	"""
	Scan template tests/ for files matching test_*.py or test_*.mjs not already
	in the spec's test_files list. Return their relative paths under tests/.

	For universal, python, other, and swift types: scan template_root/tests/ directly.
	For typed overlays (typescript, rust): scan templates/<repo_type>/tests/.
	"""
	spec = resolve_spec_for_type(repo_type, template_root)
	spec_test_files = set(spec['test_files'])

	discovered = []

	if repo_type in ('universal', 'python', 'other', 'swift'):
		# Scan template root tests/ for universal, python, other, and swift (no overlay).
		test_dir = os.path.join(template_root, 'tests')
	else:
		# Scan templates/<repo_type>/tests/ for typed overlays (typescript, rust).
		test_dir = os.path.join(template_root, 'templates', repo_type, 'tests')

	if not os.path.isdir(test_dir):
		return discovered

	for root, dirs, files in os.walk(test_dir, topdown=True, followlinks=False):
		# Filter walk dirs in-place to skip unwanted directories
		dirs[:] = [d for d in dirs if d not in repolib.model.SKIP_WALK_DIRS and not d.startswith('.')]

		for name in files:
			if not (name.startswith('test_') and (name.endswith('.py') or name.endswith('.mjs'))):
				continue
			# Exclude template-meta tests (propagate/reset_repo/detect_repo_type self-tests)
			if any(name.startswith(p) for p in repolib.model.META_TEST_PREFIXES):
				continue
			rel_path = os.path.relpath(os.path.join(root, name), test_dir)
			# Prepend 'tests/' to make it an absolute path from template_root
			full_rel_path = os.path.join('tests', rel_path)
			if full_rel_path not in spec_test_files and full_rel_path not in discovered:
				discovered.append(full_rel_path)

	return discovered


#============================================
def compute_propagation_plan(template_root: str, repo_type: str, counters: dict | None = None, repo_dir: str | None = None) -> dict:
	"""
	Compute the six-bucket propagation plan by walking the filesystem.

	Walks template_root and returns a dict with:
	- 'overwrite_files': repo-root-relative paths that overwrite at consumer
	- 'noexist_files': repo-root-relative paths that ship only when missing
	- 'merge_files': paths routed to the set-union @-import merge bucket
	- 'devel_files': bare filenames under devel/ at consumer
	- 'test_files': paths under tests/ at consumer
	- 'gitignore_block': pattern lines for .gitignore

	Args:
		template_root (str): Root directory of template files to scan.
		repo_type (str): Repository type (python, typescript, rust, swift, other, unknown).
		counters (dict | None): Optional counter dict for progress tracking.
		repo_dir (str | None): Optional repository directory for requirement checks.
			Falls back to template_root for requirement predicate evaluation.

	Precedence (apply in this order; earlier rules win on conflict):
	  1. META_FILES / META_DIRS              -> never ship (drop from all buckets)
	  2. ROUTING_OVERRIDES (via should_ship_override) -> exclude_repos gate only
	  3. UNIVERSAL_NOEXIST                   -> override universal overwrite -> noexist
	  4. templates/<type>/noexist/<path>     -> override typed overlay overwrite -> noexist
	  5. Type overlay wins over universal     -> when both target the same consumer destination,
	                                            the typed overlay version ships; log the override
	                                            so silent shadowing is visible.

	Routing rules:
	- Universal docs/ (not in META_FILES/META_DIRS) -> overwrite_files
	- Universal tests/ (denylist): ship all non-meta tests/ files by location;
	  skip dotfiles, `_`-scratch, conftest.py (merge-owned), and META_TEST_PREFIXES
	- Universal devel/ -> devel_files
	- Root files in ROOT_PROPAGATE_ALLOWLIST -> overwrite_files
	- ROUTING_OVERRIDES (via should_ship_override) applies to routing decisions
	- Paths in UNIVERSAL_NOEXIST override overwrite_files -> noexist_files
	- templates/<repo_type>/<path> (not noexist) -> overwrite_files
	- templates/<repo_type>/devel/<X> -> devel_files
	- templates/<repo_type>/tests/<X> -> test_files
	- templates/<repo_type>/noexist/<path> -> noexist_files
	- templates/gitignore.universal -> universal gitignore_block
	- templates/<repo_type>/gitignore.<repo_type> -> typed gitignore_block
	"""
	plan = {
		'overwrite_files': [],
		'noexist_files': [],
		'merge_files': [],
		'devel_files': [],
		'test_files': [],
		'gitignore_block': [],
	}

	# Default repo_dir to template_root if not provided (for requirement checks)
	if repo_dir is None:
		repo_dir = template_root

	# Helper: check if a path is under a meta directory
	def is_in_meta_dir(rel_path: str) -> bool:
		parts = rel_path.split(os.sep)
		for part in parts:
			if part in repolib.model.META_DIRS:
				return True
		return False

	# 1. Walk universal files at template root. Every known consumer type plus the
	# 'unknown' pseudo-type receives the universal walk; derive from the shared set
	# so a future type is covered without editing this condition.
	if repo_type in repolib.model.KNOWN_REPO_TYPES | {'unknown'}:
		for root, dirs, files in os.walk(template_root, topdown=True, followlinks=False):
			# Skip directories: meta, templates (we walk it separately)
			dirs[:] = [d for d in dirs if d not in repolib.model.META_DIRS]

			rel_root = os.path.relpath(root, template_root)
			if rel_root == '.':
				rel_root = ''

			# Process files in this directory
			for name in files:
				if name.startswith('.'):
					continue

				file_rel = os.path.join(rel_root, name) if rel_root else name

				# Skip META_FILES (matches by full rel-path OR bare basename for
				# entries that may appear at any depth). docs/active_plans and
				# docs/archive are caught by is_in_meta_dir().
				if is_meta_file(file_rel):
					continue

				# Skip if under a meta directory
				if is_in_meta_dir(file_rel):
					continue

				# Apply routing overrides (exclude_repos gate only)
				override = should_ship_override(file_rel, repo_type, repo_dir)
				if override is False:
					continue

				# Route by prefix/location
				if file_rel.startswith('docs/'):
					assert_not_meta(file_rel)
					plan['overwrite_files'].append(file_rel)
				elif file_rel.startswith('devel/'):
					bare_name = os.path.basename(file_rel)
					if bare_name not in plan['devel_files']:
						assert_not_meta(bare_name)
						plan['devel_files'].append(bare_name)
				elif file_rel.startswith('tests/'):
					bare_name = os.path.basename(file_rel)
					# Denylist routing: ship all non-meta tests/ files by location.
					# Skip underscore-prefixed scratch files (repo convention: _temp
					# = scratch, safe to delete).
					if bare_name.startswith('_'):
						continue
					# conftest.py is owned by merge_conftest (process.py), which
					# additively merges collect_ignore/REPO_HYGIENE_FILTERS; it is
					# not bucket-routed.
					if bare_name == 'conftest.py':
						continue
					# Skip template-meta test prefixes (defensive: template-meta
					# tests must never ship even if one appears at tests/ root).
					if any(bare_name.startswith(p) for p in repolib.model.META_TEST_PREFIXES):
						continue
					# Ship everything else by location.
					if file_rel not in plan['test_files']:
						assert_not_meta(file_rel)
						plan['test_files'].append(file_rel)
				elif file_rel in repolib.model.ROOT_PROPAGATE_ALLOWLIST:
					assert_not_meta(file_rel)
					plan['overwrite_files'].append(file_rel)



	# 2. Walk the SELECTED SET of typed overlays under templates/.
	#
	# select_overlay_dirs() returns ordered overlay path segments: the base
	# repo_type folder first (e.g. 'python'), then each conditional overlay
	# 'python/_<name>' (e.g. 'python/_pypi') whose marker file exists at repo_dir.
	# Overlay SELECTION is what gates conditional content -- a _<name> folder ships
	# only when its marker is present, so the typed-overlay walk does NOT call
	# should_ship_override (the universal walk in block 1 still applies the
	# exclude_repos gate).
	#
	# Standard: EVERY file under a selected overlay ships at its relative path to
	# consumers of that type. The typed overlay deliberately does NOT skip the
	# META_DIRS-style 'tools' directory the way the universal walk does: the ROOT
	# tools/ is template infrastructure (never ships), but templates/<type>/tools/
	# is consumer-bound content (e.g. tools/sync_typescript_package_pins.py).
	# The genuine walk-efficiency skips (node_modules, build, dist, caches, .git)
	# still apply; only 'tools' and 'meta' are removed from the trim so typed
	# overlay subpaths under them ship verbatim.
	#
	# In the BASE overlay walk (segment == repo_type, no '/'), underscore-prefixed
	# subdirectories are conditional overlays. They are skipped here so the base
	# walk never ships their content wholesale; instead they ride in as their own
	# selected overlay segment when their marker is present.
	typed_overlay_skip_dirs = repolib.model.SKIP_WALK_DIRS - {'tools', 'meta'}

	# Typed-overlay append guard: enforce META_FILES only, not META_DIRS. The
	# strict assert_not_meta rejects any path traversing a META_DIRS component
	# (including 'tools'), which would wrongly block legitimate typed-overlay
	# subpaths like tools/sync_typescript_package_pins.py. Typed-overlay files
	# ship under any subdirectory, so only the META_FILES guard applies.
	typed_overlay_assert_not_meta = assert_not_meta_file

	overlay_segments = repolib.model.select_overlay_dirs(repo_type, repo_dir)
	for segment in overlay_segments:
		# The base overlay segment is the bare repo_type with no path separator;
		# a conditional overlay segment contains '/', e.g. 'python/_pypi'.
		is_base_overlay = '/' not in segment
		overlay_root = os.path.join(template_root, 'templates', segment)
		if not os.path.isdir(overlay_root):
			continue
		for root, dirs, files in os.walk(overlay_root, topdown=True, followlinks=False):
			# Standard walk-efficiency skips plus dotdirs. In the BASE overlay,
			# also skip underscore-prefixed conditional-overlay folders so they are
			# never shipped wholesale by the base walk.
			dirs[:] = [
				d for d in dirs
				if d not in typed_overlay_skip_dirs and not d.startswith('.')
				and not (is_base_overlay and d.startswith('_'))
			]

			rel_root = os.path.relpath(root, overlay_root)
			if rel_root == '.':
				rel_root = ''

			for name in files:
				# Ship every file under the selected overlay; META filter below
				# handles exclusions. No .gitkeep filter needed -- the repo
				# deliberately holds zero .gitkeep files (verified via
				# `find templates -name '.gitkeep'`); add one back here only if
				# .gitkeep placeholders are reintroduced.
				file_rel = os.path.join(rel_root, name) if rel_root else name

				# META guard: typed overlays must filter template-internal files so a stray
				# templates/<type>/README.md (or any META name) cannot ship to consumers.
				# Standard: every file under the overlay ships at its relative path.
				# Only the META_FILES basename/path guard applies here; subdirectories such
				# as tools/ ship verbatim (no META_DIRS directory-segment filtering).
				if is_meta_file(file_rel):
					continue

				# Route by subdirectory. Conditional overlays route identically to
				# the base overlay: file_rel is relative to the overlay root, so a
				# _pypi/devel/submit_to_pypi.py source has file_rel 'devel/...'.
				if file_rel.startswith('noexist/'):
					# Strip 'noexist/' prefix for the consumer path
					consumer_path = file_rel[8:]  # len('noexist/') = 8
					# META filter on consumer_path so a typed-noexist entry whose
					# stripped path collides with a META name cannot ship.
					if not consumer_path:
						continue
					if is_meta_file(consumer_path):
						continue
					if consumer_path not in plan['noexist_files']:
						typed_overlay_assert_not_meta(consumer_path)
						plan['noexist_files'].append(consumer_path)
				elif file_rel.startswith('devel/'):
					bare_name = os.path.basename(file_rel)
					if bare_name not in plan['devel_files']:
						typed_overlay_assert_not_meta(bare_name)
						plan['devel_files'].append(bare_name)
				elif file_rel.startswith('tests/'):
					if file_rel not in plan['test_files']:
						typed_overlay_assert_not_meta(file_rel)
						plan['test_files'].append(file_rel)
				elif name.startswith('gitignore.'):
					# Skip; will be loaded separately
					pass
				else:
					# Any non-special-prefix file under the overlay, at any depth
					# (top-level files, and subdirs like tools/), routes to the overwrite
					# bucket at its relative path. rule 5: typed overlay shadows universal.
					if file_rel in plan['overwrite_files']:
						plan['overwrite_files'].remove(file_rel)
					typed_overlay_assert_not_meta(file_rel)
					plan['overwrite_files'].append(file_rel)

	# 3. Load gitignore blocks from files
	gitignore_block = []

	# Load universal gitignore block
	universal_gitignore_path = os.path.join(template_root, 'templates', 'gitignore.universal')
	gitignore_block.extend(load_gitignore_block(universal_gitignore_path))

	# Load typed gitignore block
	typed_gitignore_path = os.path.join(template_root, 'templates', repo_type, f'gitignore.{repo_type}')
	gitignore_block.extend(load_gitignore_block(typed_gitignore_path))

	# Deduplicate gitignore block
	plan['gitignore_block'] = list(dict.fromkeys(gitignore_block))

	# 4. Apply UNIVERSAL_NOEXIST overrides
	# Any path in UNIVERSAL_NOEXIST must move from overwrite/test buckets to noexist.
	# Covers tests/TESTS_README.md, which the tests-walker routes to test_files by default.
	for path in repolib.model.UNIVERSAL_NOEXIST:
		if path in plan['overwrite_files']:
			plan['overwrite_files'].remove(path)
		if path in plan['test_files']:
			plan['test_files'].remove(path)
		if path not in plan['noexist_files']:
			plan['noexist_files'].append(path)

	# 5. Apply typed noexist overrides (rule 4: typed noexist shadows typed overwrite)
	# Any path in plan['noexist_files'] that is also in plan['overwrite_files'] must be removed from overwrite
	for path in list(plan['noexist_files']):
		if path in plan['overwrite_files']:
			plan['overwrite_files'].remove(path)

	# 6. Apply MERGE_FILES routing. MERGE wins over OVERWRITE and NOEXIST for the same path.
	# META still wins over MERGE: assert_not_meta() fails loud if a MERGE-tagged file is META.
	for path in repolib.model.MERGE_FILES:
		if path in plan['overwrite_files']:
			plan['overwrite_files'].remove(path)
		if path in plan['noexist_files']:
			plan['noexist_files'].remove(path)
		if path not in plan['merge_files']:
			assert_not_meta(path)
			plan['merge_files'].append(path)

	return plan
