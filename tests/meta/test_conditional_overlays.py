"""
Guardrail tying conditional-overlay folders to manifest entries both ways.

An underscore-prefixed folder under templates/<type>/ is a conditional overlay.
This guard keeps the on-disk overlay folders and the CONDITIONAL_OVERLAYS
manifest in sync in BOTH directions:

  (a) every `_`-prefixed folder under templates/<type>/ has a matching
      CONDITIONAL_OVERLAYS[type][folder] entry, and
  (b) every CONDITIONAL_OVERLAYS[type][folder] entry points at an existing
      templates/<type>/<folder>/ directory.

Discovery is read-only against the real templates/ tree. The test is data-driven
over what is on disk and what the manifest declares, so it stays stable as
overlays are added or removed.
"""

import os

import pytest

import repolib.model
import repolib.repo


#============================================
# Read-only discovery of overlay folders on disk
#============================================

def discover_underscore_overlays(templates_dir: str) -> list[tuple[str, str]]:
	"""
	Find every underscore-prefixed folder one level under templates/<type>/.

	Args:
		templates_dir (str): Absolute path to the templates/ directory.

	Returns:
		list[tuple[str, str]]: (repo_type, overlay_folder) pairs sorted ascending.
	"""
	pairs = []
	# Each immediate child of templates/ that is a directory is a repo_type root.
	for repo_type in sorted(os.listdir(templates_dir)):
		type_root = os.path.join(templates_dir, repo_type)
		if not os.path.isdir(type_root):
			continue
		# Underscore-prefixed subdirectories are conditional overlays.
		for entry in sorted(os.listdir(type_root)):
			if not entry.startswith('_'):
				continue
			if os.path.isdir(os.path.join(type_root, entry)):
				pairs.append((repo_type, entry))
	return pairs


def manifest_overlay_pairs() -> list[tuple[str, str]]:
	"""
	Flatten CONDITIONAL_OVERLAYS into (repo_type, overlay_folder) pairs.

	Returns:
		list[tuple[str, str]]: Declared overlay pairs sorted ascending.
	"""
	pairs = []
	for repo_type, overlays in repolib.model.CONDITIONAL_OVERLAYS.items():
		for overlay_name in overlays:
			pairs.append((repo_type, overlay_name))
	return sorted(pairs)


TEMPLATE_ROOT = repolib.repo.resolve_source_dir(None)
TEMPLATES_DIR = os.path.join(TEMPLATE_ROOT, 'templates')

DISK_OVERLAYS = discover_underscore_overlays(TEMPLATES_DIR)
MANIFEST_OVERLAYS = manifest_overlay_pairs()


#============================================
# (a) disk overlay -> manifest entry
#============================================

@pytest.mark.parametrize('repo_type, overlay', DISK_OVERLAYS, ids=lambda p: str(p))
def test_disk_overlay_has_manifest_entry(repo_type: str, overlay: str) -> None:
	"""Every underscore folder on disk has a CONDITIONAL_OVERLAYS entry."""
	overlays = repolib.model.CONDITIONAL_OVERLAYS.get(repo_type, {})
	assert overlay in overlays, (
		f"templates/{repo_type}/{overlay}/ has no CONDITIONAL_OVERLAYS"
		f"[{repo_type!r}][{overlay!r}] entry"
	)


#============================================
# (b) manifest entry -> existing directory
#============================================

@pytest.mark.parametrize('repo_type, overlay', MANIFEST_OVERLAYS, ids=lambda p: str(p))
def test_manifest_entry_points_at_existing_dir(repo_type: str, overlay: str) -> None:
	"""Every CONDITIONAL_OVERLAYS entry points at an existing overlay directory."""
	overlay_dir = os.path.join(TEMPLATES_DIR, repo_type, overlay)
	assert os.path.isdir(overlay_dir), (
		f"CONDITIONAL_OVERLAYS[{repo_type!r}][{overlay!r}] points at missing "
		f"directory templates/{repo_type}/{overlay}/"
	)
