"""
Behavior tests for repolib.manifests.load_manifests over synthetic YAML.

The loader reads meta/propagation/manifests.yaml under a template root and
converts each section to the Python type repolib.model exposes (frozenset for
set manifests, frozenset for exclude_repos, nested dict for conditional_overlays,
ordered tuple for meta_test_prefixes and known_repo_types). These tests write
their OWN small manifests.yaml
in tmp_path so value assertions never depend on the live config. Type and
key-presence assertions follow whatever the loader and model agree on, so they
stay stable as live values change.
"""

import pathlib

import pytest

import repolib.manifests
import repolib.model


#============================================
# Synthetic manifest construction
#============================================

# A minimal manifests.yaml that exercises every section the loader reads.
# Values are synthetic; only their types and structure are asserted below.
SYNTHETIC_MANIFEST_YAML = """\
routing_overrides:
  "docs/SYNTH.md":
    exclude_repos:
      - synth-repo
conditional_overlays:
  python:
    _synth:
      when: has_file
      path: pyproject.toml
      description: synthetic overlay
root_propagate_allowlist:
  - SYNTH_ROOT.md
universal_noexist:
  - SYNTH_NOEXIST.md
merge_files:
  - SYNTH_MERGE.md
meta_files:
  - SYNTH_META.md
meta_file_patterns:
  - docs/SYNTH-*.md
meta_dirs:
  - synth_dir
skip_walk_dirs:
  - synth_skip
auto_discover_docs_exclude:
  - SYNTH_EXCLUDE.md
default_repo_skip_names:
  - synth-skip-repo
meta_test_prefixes:
  - test_synth_
known_repo_types:
  - python
  - synthlang
  - other
"""


def write_manifest(template_root: pathlib.Path, body: str) -> str:
	"""
	Write a manifests.yaml under template_root/meta/propagation/.

	Args:
		template_root (pathlib.Path): Synthetic template root directory.
		body (str): Raw YAML text to write.

	Returns:
		str: The template root as a string for passing to load_manifests.
	"""
	manifest_path = template_root / repolib.manifests.MANIFESTS_REL_PATH
	manifest_path.parent.mkdir(parents=True, exist_ok=True)
	manifest_path.write_text(body, encoding='utf-8')
	return str(template_root)


#============================================
# Set-manifest typing
#============================================

def test_set_manifests_load_as_frozensets(tmp_path: pathlib.Path) -> None:
	"""Each declared set manifest loads as a frozenset."""
	root = write_manifest(tmp_path, SYNTHETIC_MANIFEST_YAML)
	manifests = repolib.manifests.load_manifests(root)
	for key in repolib.manifests.SET_MANIFEST_KEYS:
		assert isinstance(manifests[key], frozenset), f"{key} is not a frozenset"


def test_set_manifest_preserves_members(tmp_path: pathlib.Path) -> None:
	"""A set manifest contains the member written in the synthetic YAML."""
	root = write_manifest(tmp_path, SYNTHETIC_MANIFEST_YAML)
	manifests = repolib.manifests.load_manifests(root)
	assert 'SYNTH_MERGE.md' in manifests['merge_files']


#============================================
# routing_overrides typing
#============================================

def test_routing_overrides_exclude_repos_is_frozenset(tmp_path: pathlib.Path) -> None:
	"""routing_overrides loads as a dict whose exclude_repos is a frozenset."""
	root = write_manifest(tmp_path, SYNTHETIC_MANIFEST_YAML)
	manifests = repolib.manifests.load_manifests(root)
	overrides = manifests['routing_overrides']
	assert isinstance(overrides, dict)
	rule = overrides['docs/SYNTH.md']
	assert isinstance(rule['exclude_repos'], frozenset)
	assert 'synth-repo' in rule['exclude_repos']


#============================================
# conditional_overlays parsing
#============================================

def test_conditional_overlays_parse_to_nested_shape(tmp_path: pathlib.Path) -> None:
	"""conditional_overlays parses to repo_type -> overlay -> condition dict."""
	root = write_manifest(tmp_path, SYNTHETIC_MANIFEST_YAML)
	manifests = repolib.manifests.load_manifests(root)
	overlay = manifests['conditional_overlays']['python']['_synth']
	assert overlay['when'] == 'has_file'
	assert overlay['path'] == 'pyproject.toml'


#============================================
# meta_test_prefixes typing
#============================================

def test_meta_test_prefixes_is_tuple(tmp_path: pathlib.Path) -> None:
	"""meta_test_prefixes loads as a tuple."""
	root = write_manifest(tmp_path, SYNTHETIC_MANIFEST_YAML)
	manifests = repolib.manifests.load_manifests(root)
	assert isinstance(manifests['meta_test_prefixes'], tuple)


#============================================
# Error handling
#============================================

def test_missing_file_raises(tmp_path: pathlib.Path) -> None:
	"""A template root with no manifests.yaml raises FileNotFoundError."""
	# tmp_path has no meta/propagation/manifests.yaml.
	with pytest.raises(FileNotFoundError):
		repolib.manifests.load_manifests(str(tmp_path))


def test_malformed_yaml_raises(tmp_path: pathlib.Path) -> None:
	"""A manifests.yaml that is not a mapping raises ValueError."""
	# A bare scalar is valid YAML but not the required top-level mapping.
	root = write_manifest(tmp_path, "just a scalar string\n")
	with pytest.raises(ValueError):
		repolib.manifests.load_manifests(root)


#============================================
# Loader output exposes every model manifest name
#============================================

# Loader keys whose model attribute name is NOT the plain uppercase of the key.
# known_repo_types is the ordered-tuple loader key; repolib.model binds that
# tuple to REPO_TYPE_ORDER (same type) and derives the KNOWN_REPO_TYPES frozenset
# from it, so the same-type model attribute for this key is REPO_TYPE_ORDER.
MODEL_ATTR_OVERRIDES = {
	'known_repo_types': 'REPO_TYPE_ORDER',
}


def model_manifest_attr_for(loader_key: str) -> str:
	"""
	Map a loader key to the module-level name repolib.model exposes for it.

	repolib.model binds most loaded manifests to their uppercase name
	(routing_overrides -> ROUTING_OVERRIDES, etc.). A few keys use a different
	export name (see MODEL_ATTR_OVERRIDES); known_repo_types binds to the ordered
	REPO_TYPE_ORDER tuple, with KNOWN_REPO_TYPES derived as a separate frozenset.

	Returns:
		str: The model attribute name for this loader key.
	"""
	return MODEL_ATTR_OVERRIDES.get(loader_key, loader_key.upper())


def test_loader_keys_match_model_attribute_types(tmp_path: pathlib.Path) -> None:
	"""Every loader key maps to a model attribute of the same Python type."""
	root = write_manifest(tmp_path, SYNTHETIC_MANIFEST_YAML)
	manifests = repolib.manifests.load_manifests(root)
	# Iterate the keys the loader returns; assert presence + type parity with the
	# live model attribute. Live VALUES are never compared, only types.
	for loader_key, loaded_value in manifests.items():
		attr_name = model_manifest_attr_for(loader_key)
		assert hasattr(repolib.model, attr_name), (
			f"repolib.model is missing attribute {attr_name!r} for "
			f"loader key {loader_key!r}"
		)
		model_value = getattr(repolib.model, attr_name)
		assert type(loaded_value) is type(model_value), (
			f"loader key {loader_key!r} type {type(loaded_value)} does not match "
			f"model.{attr_name} type {type(model_value)}"
		)
