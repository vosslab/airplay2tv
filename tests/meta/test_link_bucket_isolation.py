"""Enforce bucket-isolation rule for markdown links across the starter-repo template.

The design rule:

	A file may only link to targets that propagate with it.

Allowed transitions:
	universal      -> universal only
	overlay-<type> -> universal or overlay-<type> (same type)
	meta           -> any bucket in the template

This test walks every tracked ``*.md`` file, classifies each file's bucket
from its path (using ``repolib.model.META_FILES`` and
``repolib.model.META_DIRS``), resolves each local ``[..](..)`` link to a
repo-relative path, classifies the target's bucket, and hard-fails on any
disallowed transition.

Targets that do not exist on disk are not checked here -- ``tests/test_markdown_links.py``
owns link-existence. This test only covers bucket isolation.
"""

import os
import re
import subprocess

import file_utils
import repolib.model

REPO_ROOT = file_utils.get_repo_root()


LINK_RE = re.compile(r'\[[^\]]*\]\(([^)#?]+)(?:[#?][^)]*)?\)')

EXTERNAL_PREFIXES = ('http://', 'https://', 'mailto:', 'ftp://', '#')


#============================================
def classify_bucket(file_rel: str) -> str:
	"""Classify a repo-relative file path into one of three buckets.

	Args:
		file_rel: Path relative to the repo root, forward-slash separated.

	Returns:
		'universal', 'overlay-<type>', or 'meta'.
	"""
	# Typed overlay takes precedence over meta (templates/ is in META_DIRS
	# only because untyped contents at templates/ never ship; the typed
	# subtree templates/<type>/ ships to that type).
	if file_rel.startswith('templates/'):
		parts = file_rel.split('/')
		if len(parts) >= 2 and parts[1]:
			return f'overlay-{parts[1]}'
		return 'meta'
	# Root-level meta files (README.md, VERSION, etc.).
	if file_rel in repolib.model.META_FILES:
		return 'meta'
	# Any path under a META_DIRS directory is meta.
	parts = file_rel.split('/')
	for meta_dir in repolib.model.META_DIRS:
		# META_DIRS entries may be 'tools' or 'docs/active_plans'.
		meta_parts = meta_dir.split('/')
		if parts[:len(meta_parts)] == meta_parts:
			return 'meta'
	return 'universal'


#============================================
def transition_allowed(source_bucket: str, target_bucket: str) -> bool:
	"""Return True if a link from source_bucket to target_bucket is allowed.

	Args:
		source_bucket: Bucket of the file containing the link.
		target_bucket: Bucket of the link target.

	Returns:
		True if the transition is allowed by the bucket-isolation rule.
	"""
	# meta -> anywhere: meta files do not ship, so they may link anywhere.
	if source_bucket == 'meta':
		return True
	# universal -> universal only.
	if source_bucket == 'universal':
		return target_bucket == 'universal'
	# overlay-X -> universal or overlay-X (same X).
	if source_bucket.startswith('overlay-'):
		return target_bucket == 'universal' or target_bucket == source_bucket
	return False


#============================================
def list_tracked_markdown(repo_root: str) -> list[str]:
	"""Return repo-relative paths of every tracked ``*.md`` file."""
	result = subprocess.run(
		["git", "-C", repo_root, "ls-files", "*.md"],
		capture_output=True, text=True, check=True,
	)
	return [line for line in result.stdout.splitlines() if line.strip()]


#============================================
def extract_links(content: str) -> list[tuple[int, str]]:
	"""Yield (line_number, link_target) tuples for every markdown link in content."""
	links = []
	for lineno, line in enumerate(content.splitlines(), start=1):
		for match in LINK_RE.finditer(line):
			target = match.group(1).strip()
			if not target:
				continue
			if target.startswith(EXTERNAL_PREFIXES):
				continue
			links.append((lineno, target))
	return links


#============================================
def resolve_target(source_rel: str, target: str) -> str:
	"""Resolve a markdown link target to a repo-relative path.

	Args:
		source_rel: Repo-relative path of the file containing the link.
		target: Raw link URL from the markdown source.

	Returns:
		Normalized repo-relative path to the target.
	"""
	source_dir = os.path.dirname(source_rel)
	combined = os.path.normpath(os.path.join(source_dir, target))
	return combined.replace(os.sep, '/')


#============================================
def test_link_bucket_isolation() -> None:
	"""Hard-fail on any markdown link that crosses bucket-isolation boundaries."""
	md_files = list_tracked_markdown(REPO_ROOT)
	violations = []
	for md_file in md_files:
		source_bucket = classify_bucket(md_file)
		file_abs = os.path.join(REPO_ROOT, md_file)
		with open(file_abs, 'r', encoding='utf-8') as f:
			content = f.read()
		for lineno, target in extract_links(content):
			target_rel = resolve_target(md_file, target)
			# Targets resolved outside the repo (e.g. '..' that escape) are
			# out of scope; link existence is checked elsewhere.
			if target_rel.startswith('..'):
				continue
			target_bucket = classify_bucket(target_rel)
			if not transition_allowed(source_bucket, target_bucket):
				violations.append(
					f'{md_file}:{lineno}: {target} '
					f'({source_bucket} -> {target_bucket})'
				)
	assert not violations, (
		'Markdown link bucket-isolation violations:\n  ' + '\n  '.join(violations)
	)
