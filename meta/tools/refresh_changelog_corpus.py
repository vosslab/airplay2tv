#!/usr/bin/env python3
"""Populate tests/fixtures/changelog_corpus/ from ~/nsh/*/docs/CHANGELOG*.md.

The corpus is the input for the read-only reader-tolerance survey at
tests/meta/test_changelog_corpus_compat.py. Corpus files are not shipped
with this template; each developer regenerates them locally from their
own sibling repos.

This script lives under tools/ so it is excluded from propagation to
consumer repos (tools/ is in META_DIRS per docs/REPO_STYLE.md).

Discovery: walks the search root (default ``~/nsh``) up to 4 levels
deep, collecting every ``CHANGELOG*.md`` file.

Naming: each source path under the search root is flattened with ``__``
separators. Example:

    ~/nsh/PROBLEMS/biology-problems/docs/CHANGELOG-2026-04a.md
      -> PROBLEMS__biology-problems__docs__CHANGELOG-2026-04a.md

Run:

    source source_me.sh && python3 tools/refresh_changelog_corpus.py

Outputs a one-line summary: ``copied: N, ..., dest: <path>``.
"""

# Standard Library
import os
import sys
import shutil
import argparse
import subprocess


#============================================
def get_repo_root() -> str:
	"""Return the repo root via ``git rev-parse --show-toplevel``."""
	result = subprocess.run(
		["git", "rev-parse", "--show-toplevel"],
		stdout=subprocess.PIPE,
		stderr=subprocess.PIPE,
		text=True,
	)
	if result.returncode != 0:
		raise RuntimeError("Not inside a git work tree.")
	root = result.stdout.strip()
	if not root:
		raise RuntimeError("Empty repo root.")
	return root


#============================================
def discover_changelogs(search_root: str, max_depth: int = 4) -> list:
	"""Walk ``search_root`` up to ``max_depth`` levels deep, collect CHANGELOG*.md."""
	results = []
	search_root = os.path.abspath(search_root)
	search_root_depth = search_root.count(os.sep)
	for dirpath, dirnames, filenames in os.walk(search_root):
		current_depth = dirpath.count(os.sep) - search_root_depth
		if current_depth >= max_depth:
			# prune deeper directories from further descent
			dirnames[:] = []
			continue
		for name in filenames:
			if name.startswith("CHANGELOG") and name.endswith(".md"):
				results.append(os.path.join(dirpath, name))
	results.sort()
	return results


#============================================
def flatten_name(src_path: str, anchor: str) -> str:
	"""Flatten the path relative to ``anchor`` into a single filename."""
	anchor = anchor.rstrip("/") + "/"
	if src_path.startswith(anchor):
		rel = src_path[len(anchor):]
	else:
		rel = src_path.lstrip("/")
	return rel.replace("/", "__")


#============================================
def parse_args() -> argparse.Namespace:
	"""Parse command-line arguments."""
	parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
	parser.add_argument(
		"-s", "--search-root", dest="search_root",
		default=os.path.expanduser("~/nsh"),
		help="Root directory to scan for CHANGELOG*.md files (default: ~/nsh).",
	)
	parser.add_argument(
		"-c", "--clean", dest="clean", action="store_true",
		help="Remove existing corpus files before refreshing.",
	)
	args = parser.parse_args()
	return args


#============================================
def main() -> int:
	"""Populate the corpus directory and print a one-line summary."""
	args = parse_args()
	repo_root = get_repo_root()
	dest_dir = os.path.join(repo_root, "tests", "fixtures", "changelog_corpus")
	os.makedirs(dest_dir, exist_ok=True)

	if args.clean:
		for name in os.listdir(dest_dir):
			full = os.path.join(dest_dir, name)
			if os.path.isfile(full):
				os.remove(full)

	search_root = os.path.abspath(args.search_root)
	if not os.path.isdir(search_root):
		print(f"search root not a directory: {search_root}", file=sys.stderr)
		return 1

	sources = discover_changelogs(search_root)
	copied = 0
	collisions = []
	seen = {}
	for path in sources:
		name = flatten_name(path, search_root)
		dest = os.path.join(dest_dir, name)
		if name in seen:
			collisions.append((name, seen[name], path))
		seen[name] = path
		shutil.copyfile(path, dest)
		copied += 1
	print(f"copied: {copied}, sources scanned: {len(sources)}, "
		f"collisions: {len(collisions)}, dest: {dest_dir}")
	for c in collisions:
		print(f"COLLISION: {c}")
	return 0


#============================================
if __name__ == "__main__":
	raise SystemExit(main())
