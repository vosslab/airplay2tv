"""Load propagation manifests from the single YAML data file.

meta/propagation/manifests.yaml is the single source of propagation config.
load_manifests() reads it and returns a dict whose values carry the SAME
Python types repolib.model exposes (frozenset for set manifests, ordered tuple
for meta_test_prefixes and known_repo_types, dict for routing_overrides and
conditional_overlays).
A missing file or malformed YAML raises loudly; there is no empty fallback.
"""

# Standard Library
import os

# PIP3 modules
import yaml


# Relative path from the template root to the manifests data file.
MANIFESTS_REL_PATH = os.path.join('meta', 'propagation', 'manifests.yaml')

# Set manifests: top-level YAML sequences loaded as frozensets.
SET_MANIFEST_KEYS = (
	'root_propagate_allowlist',
	'universal_noexist',
	'merge_files',
	'meta_files',
	'meta_file_patterns',
	'meta_dirs',
	'skip_walk_dirs',
	'auto_discover_docs_exclude',
	'default_repo_skip_names',
)


#============================================
def load_manifests(template_root: str) -> dict:
	"""
	Load propagation manifests from meta/propagation/manifests.yaml.

	Reads the YAML data file under template_root and converts each section to the
	Python type repolib.model exposes. Set manifests become frozensets, the
	routing_overrides exclude_repos value becomes a frozenset, conditional_overlays
	keeps its nested-dict structure, and meta_test_prefixes and known_repo_types
	become ordered tuples.

	A missing file or malformed YAML raises loudly so propagation never runs on a
	silently empty config.

	Args:
		template_root (str): Template root directory containing meta/propagation/.

	Returns:
		dict: Manifest names mapped to their typed values.
	"""
	# Resolve the data file path under the template root.
	manifests_path = os.path.join(template_root, MANIFESTS_REL_PATH)
	# A missing manifests file is a hard error; do not fall back to empty config.
	if not os.path.isfile(manifests_path):
		raise FileNotFoundError(f"propagation manifests file missing: {manifests_path}")
	with open(manifests_path, 'r', encoding='utf-8') as handle:
		raw = yaml.safe_load(handle)
	# safe_load returns None for an empty file; that is a malformed config here.
	if not isinstance(raw, dict):
		raise ValueError(f"propagation manifests must be a mapping: {manifests_path}")
	# Build the typed manifest dict. Direct key access fails loud on a missing section.
	manifests = {}
	# Set manifests: each top-level sequence becomes a frozenset.
	for key in SET_MANIFEST_KEYS:
		manifests[key] = frozenset(raw[key])
	# routing_overrides: dict of file_rel -> rule; exclude_repos becomes a frozenset.
	manifests['routing_overrides'] = build_routing_overrides(raw['routing_overrides'])
	# conditional_overlays: nested dict kept as-is (repo_type -> overlay -> condition).
	manifests['conditional_overlays'] = raw['conditional_overlays']
	# meta_test_prefixes: ordered tuple to match the model.py type.
	manifests['meta_test_prefixes'] = tuple(raw['meta_test_prefixes'])
	# known_repo_types: ORDERED tuple of consumer marker tokens. Order is
	# preserved (NOT a frozenset, NOT in SET_MANIFEST_KEYS) because prompts and
	# docs need stable display order; repolib.model derives KNOWN_REPO_TYPES
	# (a frozenset) from it for membership. Direct key access fails loud here.
	manifests['known_repo_types'] = tuple(raw['known_repo_types'])
	return manifests


#============================================
def build_routing_overrides(raw_overrides: dict) -> dict:
	"""
	Convert raw routing_overrides into the typed model.py structure.

	Each rule's exclude_repos sequence becomes a frozenset, matching the type
	repolib.model previously exposed. Every rule must carry an exclude_repos
	field; the key is accessed explicitly so a missing field fails loudly.

	Args:
		raw_overrides (dict): file_rel mapped to a rule dict from YAML.

	Returns:
		dict: file_rel mapped to a rule dict with frozenset exclude_repos.

	Raises:
		KeyError: If a rule is missing the required exclude_repos field.
	"""
	overrides = {}
	for file_rel, rule in raw_overrides.items():
		# Copy the rule so the loaded YAML structure is not mutated in place.
		typed_rule = dict(rule)
		# exclude_repos is the only rule field; convert its sequence to a frozenset.
		typed_rule['exclude_repos'] = frozenset(rule['exclude_repos'])
		overrides[file_rel] = typed_rule
	return overrides
