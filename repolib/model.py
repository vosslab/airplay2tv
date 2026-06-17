"""Data models and propagation spec/plan logic."""

# Standard Library
import os
from dataclasses import dataclass

#============================================
# Orchestration context dataclass
#============================================

@dataclass
class PropagateContext:
	"""
	Context object passed to orchestration helpers.
	Mirrors all args fields that downstream helpers need. Treat as read-only after construction.
	"""
	source_dir: str
	template_root: str
	repo_name: str | None
	dry_run: bool
	initial_setup: bool
	# auto_discover: source-template test discovery for ONE repo. When True, the
	# source template's tests/ is scanned for test_*.py/test_*.mjs files absent
	# from the static spec, and those are added to the files copied INTO the
	# target repo. It never walks other repos; the meaning is single-repo only.
	auto_discover: bool
	write_marker: bool

# Language type constants
LANG_PYTHON = 'python'
LANG_TYPESCRIPT = 'typescript'
LANG_RUST = 'rust'
LANG_SWIFT = 'swift'
LANG_OTHER = 'other'
LANG_UNKNOWN = 'unknown'

#============================================
# Propagation manifests: loaded from meta/propagation/manifests.yaml
#============================================

# All propagation manifests live in meta/propagation/manifests.yaml, the single
# source of propagation config. They are loaded once at import and assigned to the
# module-level names below so importers (from repolib.model import ROUTING_OVERRIDES)
# and dir() keep working. The loaded values carry the same Python types the literals
# previously had: frozenset for set manifests, tuple for META_TEST_PREFIXES, and dict
# for ROUTING_OVERRIDES and CONDITIONAL_OVERLAYS (with frozenset exclude_repos).
#
# Manifest meanings:
#   ROUTING_OVERRIDES: per-file exceptions (only exclude_repos remains).
#   CONDITIONAL_OVERLAYS: repo_type -> overlay_name -> {when, path, description}.
#   ROOT_PROPAGATE_ALLOWLIST: root files that MAY ship; UNIVERSAL_NOEXIST refines how.
#   UNIVERSAL_NOEXIST: files that ship only when absent at the consumer.
#   MERGE_FILES: files routed to the set-union @-import merge bucket.
#   META_FILES / META_DIRS: files and dirs that NEVER ship (template-meta).
#   META_FILE_PATTERNS: glob patterns that never ship, e.g. changelog archives.
#   SKIP_WALK_DIRS: dirs skipped during os.walk of the source template.
#   AUTO_DISCOVER_DOCS_EXCLUDE: docs excluded from auto-discovery.
#   META_TEST_PREFIXES: template-meta test filename prefixes.
#   DEFAULT_REPO_SKIP_NAMES: default skip list for repo discovery.
#   KNOWN_REPO_TYPES: recognized consumer marker tokens (from the ordered
#     known_repo_types manifest); REPO_TYPE_ORDER keeps display order, the
#     KNOWN_REPO_TYPES frozenset is for membership only.

#============================================
# Manifest loading
#============================================

def _load_propagation_manifests() -> dict:
	"""
	Resolve the template root and load all propagation manifests once at import.

	repolib.repo is imported lazily here to avoid an import cycle: repolib.repo
	imports repolib.model at its module top, so importing repolib.repo at the top
	of this module would cycle. resolve_source_dir only walks the filesystem and
	does not need repolib.model state, so a deferred import is safe.

	Returns:
		dict: Typed propagation manifests from meta/propagation/manifests.yaml.
	"""
	# Lazy imports break the repolib.repo <-> repolib.model import cycle; both
	# modules are only needed once at load time, not at module scope.
	import repolib.repo
	import repolib.manifests
	# Anchor the template root on the running source checkout (repolib package).
	template_root = repolib.repo.resolve_source_dir(None)
	return repolib.manifests.load_manifests(template_root)


# Load once at import and bind each manifest to its module-level public name.
_MANIFESTS = _load_propagation_manifests()
ROUTING_OVERRIDES = _MANIFESTS['routing_overrides']
CONDITIONAL_OVERLAYS = _MANIFESTS['conditional_overlays']
ROOT_PROPAGATE_ALLOWLIST = _MANIFESTS['root_propagate_allowlist']
UNIVERSAL_NOEXIST = _MANIFESTS['universal_noexist']
MERGE_FILES = _MANIFESTS['merge_files']
META_FILES = _MANIFESTS['meta_files']
# Glob patterns (template-root-relative) that never ship, e.g. changelog archives.
META_FILE_PATTERNS = _MANIFESTS['meta_file_patterns']
META_DIRS = _MANIFESTS['meta_dirs']
SKIP_WALK_DIRS = _MANIFESTS['skip_walk_dirs']
AUTO_DISCOVER_DOCS_EXCLUDE = _MANIFESTS['auto_discover_docs_exclude']
META_TEST_PREFIXES = _MANIFESTS['meta_test_prefixes']
DEFAULT_REPO_SKIP_NAMES = _MANIFESTS['default_repo_skip_names']
# Recognized consumer marker tokens. REPO_TYPE_ORDER is the ordered tuple
# (canonical display order for prompts and docs); KNOWN_REPO_TYPES is the derived
# frozenset used only for membership checks. Internal routing pseudo-types
# (universal, unknown) are NOT included here; they are added at their own guard
# in repolib.files so they never leak into UI, docs, or marker validation.
REPO_TYPE_ORDER = _MANIFESTS['known_repo_types']
KNOWN_REPO_TYPES = frozenset(REPO_TYPE_ORDER)


#============================================
# Conditional-overlay selection
#============================================

def select_overlay_dirs(repo_type: str, repo_dir: str) -> list[str]:
	"""
	Select the ordered template overlay folders that apply to a consumer repo.

	The base repo_type folder always applies. Each conditional overlay configured
	in CONDITIONAL_OVERLAYS for that repo_type is appended when its condition holds
	at the consumer (currently only the 'has_file' verb is supported).

	Args:
		repo_type (str): Consumer repository type (python, typescript, rust, swift, other).
		repo_dir (str): Consumer repository directory to test marker files against.

	Returns:
		list[str]: Ordered overlay path segments under templates/, e.g.
			['python', 'python/_pypi'] when pyproject.toml exists at repo_dir.
			The base type is always first; conditional overlays follow in config order.
	"""
	# Base repo_type overlay always applies and comes first.
	overlay_dirs = [repo_type]
	# Conditional overlays for this repo_type, if any are configured.
	overlay_config = CONDITIONAL_OVERLAYS.get(repo_type, {})
	for overlay_name, condition in overlay_config.items():
		when_verb = condition['when']
		# Only the has_file verb is understood; anything else is a config error.
		if when_verb != 'has_file':
			raise ValueError(
				f"unknown conditional-overlay 'when' verb {when_verb!r} for "
				f"overlay {overlay_name!r} (repo_type {repo_type!r}); "
				"only 'has_file' is supported"
			)
		# Marker file path is relative to the consumer repo root.
		marker_path = os.path.join(repo_dir, condition['path'])
		if os.path.isfile(marker_path):
			# Overlay segment is the underscore folder under templates/<repo_type>/.
			overlay_dirs.append(f"{repo_type}/{overlay_name}")
	return overlay_dirs


def overlay_roots_for_type(template_root: str, repo_type: str) -> list[str]:
	"""
	Yield the candidate overlay root directories for a repo_type.

	Returns the base templates/<repo_type>/ root plus every configured conditional
	overlay root (templates/<repo_type>/_<name>/). These are the typed roots that
	source resolvers must search; the universal template root is handled separately
	by each resolver. Roots are returned in config order with the base type first.

	Args:
		template_root (str): Template root directory.
		repo_type (str): Repository type (python, typescript, rust, swift, other).

	Returns:
		list[str]: Absolute candidate overlay root directories under templates/.
	"""
	# Base typed root always comes first.
	roots = [os.path.join(template_root, 'templates', repo_type)]
	# Append each configured conditional overlay root for this repo_type.
	overlay_config = CONDITIONAL_OVERLAYS.get(repo_type, {})
	for overlay_name in overlay_config:
		roots.append(os.path.join(template_root, 'templates', repo_type, overlay_name))
	return roots


#============================================
# Source/target path resolution
#============================================

def source_path_for_bucket(template_root: str, bucket: str, file_rel: str, repo_type: str = 'universal') -> str:
	"""
	Resolve canonical source path for a file in a bucket.
	Handles universal files at template root and typed files under templates/<repo_type>/.
	Typed lookups also search the repo_type's conditional overlays
	(templates/<repo_type>/_<name>/), so an overlay file such as
	templates/python/_pypi/devel/submit_to_pypi.py resolves for python repos.
	For noexist_files, looks under templates/<repo_type>[/_overlay]/noexist/ as well as root.
	"""
	# Reuse the non-raising resolver, then fail loud if nothing matched.
	source = find_source_for_bucket(template_root, bucket, file_rel, repo_type)
	if source is None:
		raise FileNotFoundError(f"canonical source missing for {bucket} entry {file_rel!r}")
	return source


def find_source_for_bucket(template_root: str, bucket: str, file_rel: str, repo_type: str = 'universal') -> str | None:
	"""
	Resolve canonical source path for a file in a bucket, or return None if not found.

	Non-raising variant of source_path_for_bucket() for cleaner predicate-based control flow.

	Args:
		template_root (str): Template root directory.
		bucket (str): Bucket name (overwrite_files, noexist_files, devel_files, test_files).
		file_rel (str): Relative path of the file.
		repo_type (str): Repository type (python, typescript, rust, swift, other). Defaults to 'universal'.

	Returns:
		str | None: Canonical source path if found, None otherwise.

	Typed lookups search the repo_type's base root (templates/<repo_type>/) AND each
	of its conditional overlay roots (templates/<repo_type>/_<name>/) via
	overlay_roots_for_type(), so overlay-only source files resolve correctly.
	"""
	# Normalize repo_type alias
	if repo_type == 'universal':
		repo_type = 'python'

	# Typed candidate roots: base templates/<repo_type>/ plus conditional overlays.
	typed_roots = overlay_roots_for_type(template_root, repo_type)

	# Determine candidate paths based on bucket.
	if bucket == 'devel_files':
		# Typed/overlay roots shadow the universal root, mirroring overwrite_files.
		# This ordering matters during single-repo reset: there template_root IS the
		# consumer repo, so a consumer-owned devel/<name> (e.g. a stale, tracked
		# devel/submit_to_pypi.py) sits at the universal devel/ location. Checking
		# the universal root first would resolve the propagation SOURCE to that
		# consumer file, making the copy a self no-op and leaving stale content in
		# place. An overlay-only file like _pypi/devel/submit_to_pypi.py must resolve
		# to its overlay source so the refresh/overwrite actually happens.
		# Typed/overlay roots: templates/<repo_type>[/_overlay]/devel/<name>
		for typed_root in typed_roots:
			candidate = os.path.join(typed_root, 'devel', file_rel)
			if os.path.isfile(candidate):
				return candidate
		# Universal devel files: template_root/devel/<name>
		candidate = os.path.join(template_root, 'devel', file_rel)
		if os.path.isfile(candidate):
			return candidate

	elif bucket == 'test_files':
		# test files: file_rel already includes tests/ prefix, so just join directly
		candidate = os.path.join(template_root, file_rel)
		if os.path.isfile(candidate):
			return candidate
		# Typed/overlay roots: templates/<repo_type>[/_overlay]/tests/<name>
		for typed_root in typed_roots:
			candidate = os.path.join(typed_root, file_rel)
			if os.path.isfile(candidate):
				return candidate

	elif bucket == 'noexist_files':
		# noexist files: could be at template root (universal) or under typed noexist dirs
		candidate = os.path.join(template_root, file_rel)
		if os.path.isfile(candidate):
			return candidate
		# Typed/overlay noexist: templates/<repo_type>[/_overlay]/noexist/<path>
		for typed_root in typed_roots:
			candidate = os.path.join(typed_root, 'noexist', file_rel)
			if os.path.isfile(candidate):
				return candidate

	else:
		# overwrite_files (or default): typed under templates/<type>[/_overlay]/ shadows root
		for typed_root in typed_roots:
			candidate = os.path.join(typed_root, file_rel)
			if os.path.isfile(candidate):
				return candidate
		candidate = os.path.join(template_root, file_rel)
		if os.path.isfile(candidate):
			return candidate

	return None


def override_key_source(template_root: str, file_rel: str) -> str | None:
	"""
	Resolve a ROUTING_OVERRIDES key to its existing template source path.

	An override key is a repo-root-relative path (e.g. 'docs/CLAUDE_HOOK_USAGE_GUIDE.md').
	Its source may live in any bucket layout, so this probes find_source_for_bucket()
	across the relevant buckets (overwrite, noexist, devel, test) and returns the first
	existing source path. The probe uses the python repo_type so that typed and
	conditional-overlay roots are searched in addition to the universal root.

	Args:
		template_root (str): Template root directory.
		file_rel (str): ROUTING_OVERRIDES key (repo-root-relative path).

	Returns:
		str | None: Existing template source path, or None if it resolves nowhere.
	"""
	# devel keys carry a 'devel/' prefix at the override layer, but find_source_for_bucket
	# expects the bare name under devel_files; strip the prefix for that probe.
	devel_rel = file_rel
	if devel_rel.startswith('devel' + os.sep):
		devel_rel = devel_rel[len('devel' + os.sep):]
	# Probe each plausible bucket; first hit wins. python repo_type pulls in typed
	# and conditional-overlay roots via overlay_roots_for_type().
	for bucket, probe_rel in (
		('overwrite_files', file_rel),
		('noexist_files', file_rel),
		('devel_files', devel_rel),
		('test_files', file_rel),
	):
		source = find_source_for_bucket(template_root, bucket, probe_rel, LANG_PYTHON)
		if source is not None:
			return source
	return None


def target_path_for_bucket(repo_dir: str, bucket: str, file_rel: str) -> str:
	"""
	Resolve target path at consumer repo.
	Note: for test_files, file_rel includes 'tests/' prefix (e.g., 'tests/test_foo.py').
	For devel_files, file_rel is a bare name (e.g., 'submit_to_pypi.py').
	"""
	if bucket == 'devel_files':
		return os.path.join(repo_dir, 'devel', file_rel)
	# test_files: file_rel already includes 'tests/' prefix; other buckets are repo-root-relative.
	return os.path.join(repo_dir, file_rel)


def format_path_pair(source_file: str, dest_file: str, repo_dir: str, context: 'PropagateContext') -> str:
	"""
	Format a source-dest file pair for logging using repo-relative paths.

	  - If src relative path == dst relative path, show only the dst relative path
	  - Otherwise, show both as "src_rel -> dst_rel"

	Args:
		source_file (str): Absolute source file path.
		dest_file (str): Absolute destination file path.
		repo_dir (str): Repository directory path.
		context (PropagateContext): Context with source_dir.

	Returns:
		str: Formatted path string for logging.
	"""
	# Compute relative paths
	src_relative = os.path.relpath(source_file, context.source_dir)
	dst_relative = os.path.relpath(dest_file, repo_dir)

	# If relative paths are the same, show only one
	if src_relative == dst_relative:
		return dst_relative

	# Otherwise show both
	return f"{src_relative} -> {dst_relative}"
