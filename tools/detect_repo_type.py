#!/usr/bin/env python3
"""Detect repository type from contents."""

import os
import json
import argparse


SKIP_WALK_DIRS = {
	'node_modules',
	'.git',
	'dist',
	'build',
	'venv',
	'.venv',
	'__pycache__',
	# propagator-shipped dirs: not project signal
	'tests',
	'devel',
}

# .ts/.tsx clearly TypeScript. .js/.mjs are TS-adjacent: many user repos
# host pre-TypeScript HTML/JS that will migrate. Count both as "ts-family".
TS_FAMILY_EXT = ('.ts', '.tsx', '.js', '.mjs')

MAX_FILES_SCANNED = 2000


#============================================
def detect_repo_type(repo_dir: str) -> tuple[str, str, list[str]]:
	"""Predict repo type from contents. Returns (token, confidence, reasoning_bullets)."""
	reasoning = []

	# Priority 1: Strong markers at repo root
	has_cargo = os.path.isfile(os.path.join(repo_dir, 'Cargo.toml'))
	has_tsconfig = os.path.isfile(os.path.join(repo_dir, 'tsconfig.json'))
	has_pyproject = os.path.isfile(os.path.join(repo_dir, 'pyproject.toml'))
	has_setup_py = os.path.isfile(os.path.join(repo_dir, 'setup.py'))
	has_swift_pkg = os.path.isfile(os.path.join(repo_dir, 'Package.swift'))

	# Count multiple strong signals; a Swift+Rust or Swift+Python repo is ambiguous
	# like any other mixed pair (e.g. Cargo.toml + tsconfig.json)
	strong_signals = sum([has_cargo, has_tsconfig, has_pyproject or has_setup_py, has_swift_pkg])

	if strong_signals >= 2:
		signals_found = []
		if has_cargo:
			signals_found.append('Cargo.toml')
		if has_tsconfig:
			signals_found.append('tsconfig.json')
		if has_pyproject or has_setup_py:
			signals_found.append('pyproject.toml/setup.py')
		if has_swift_pkg:
			signals_found.append('Package.swift')
		reasoning.append(f"mixed strong signals: {', '.join(signals_found)}")
		return ('ambiguous', 'low', reasoning)

	if has_cargo:
		reasoning.append('Found Cargo.toml at root')
		return ('rust', 'high', reasoning)

	if has_tsconfig:
		reasoning.append('Found tsconfig.json at root')
		return ('typescript', 'high', reasoning)

	if has_pyproject or has_setup_py:
		if has_pyproject:
			reasoning.append('Found pyproject.toml at root')
		else:
			reasoning.append('Found setup.py at root')
		return ('python', 'high', reasoning)

	if has_swift_pkg:
		reasoning.append('Found Package.swift at root')
		return ('swift', 'high', reasoning)

	# Priority 2: package.json with TypeScript dependency
	has_package_json = os.path.isfile(os.path.join(repo_dir, 'package.json'))
	if has_package_json:
		package_json_path = os.path.join(repo_dir, 'package.json')
		try:
			with open(package_json_path, 'r', encoding='utf-8') as f:
				pkg_data = json.load(f)
		except (json.JSONDecodeError, FileNotFoundError, PermissionError):
			pkg_data = {}

		# Check for typescript in dependencies or devDependencies
		has_ts_dep = False
		if isinstance(pkg_data.get('dependencies'), dict):
			if 'typescript' in pkg_data['dependencies']:
				has_ts_dep = True
		if isinstance(pkg_data.get('devDependencies'), dict):
			if 'typescript' in pkg_data['devDependencies']:
				has_ts_dep = True

		if has_ts_dep:
			reasoning.append('Found package.json with typescript dependency')
			return ('typescript', 'high', reasoning)

		# package.json without typescript is medium confidence for TS (could be JS)
		reasoning.append('Found package.json without typescript dependency (could be plain JS)')
		return ('typescript', 'medium', reasoning)

	# NOTE: pip_requirements.txt is NOT a python signal because the universal
	# pytest hygiene suite ships to every repo (including TS/rust/perl) and
	# requires pip_requirements.txt for its own dev install. Using it as a
	# python signal would misclassify nearly every repo.

	# Priority 3: File-count tiebreaker
	py_count = 0
	ts_count = 0
	rs_count = 0
	swift_count = 0
	other_count = 0
	file_count = 0
	has_pg_files = False

	for root, dirs, files in os.walk(repo_dir, topdown=True, followlinks=False):
		# Prune skip dirs
		dirs[:] = [d for d in dirs if d not in SKIP_WALK_DIRS and not d.startswith('.')]

		for name in files:
			file_count += 1
			if file_count >= MAX_FILES_SCANNED:
				break

			if name.endswith('.py'):
				py_count += 1
			elif name.endswith(TS_FAMILY_EXT):
				ts_count += 1
			elif name.endswith('.rs'):
				rs_count += 1
			elif name.endswith('.swift'):
				swift_count += 1
			elif name.endswith(('.pl', '.pm', '.pg')):
				other_count += 1
				if name.endswith('.pg'):
					has_pg_files = True

		if file_count >= MAX_FILES_SCANNED:
			break

	# Cap reached note
	if file_count >= MAX_FILES_SCANNED:
		reasoning.append(f"Scanned first {MAX_FILES_SCANNED} files")

	# Find highest count
	counts = {
		'python': py_count,
		'typescript': ts_count,
		'rust': rs_count,
		'swift': swift_count,
		'other': other_count,
	}

	max_count = max(counts.values())

	if max_count >= 5:
		# Check 3x threshold
		second_max = sorted(counts.values(), reverse=True)[1] if len(counts) > 1 else 0
		if second_max == 0 or max_count >= second_max * 3:
			winner = [k for k, v in counts.items() if v == max_count][0]
			reasoning.append(f"File count: {winner}={max_count}, others < threshold")
			return (winner, 'medium', reasoning)

	# Priority 5: Perl/WebWork detection
	has_webwork_in_name = 'webwork' in repo_dir.lower() or 'perl' in repo_dir.lower()

	if has_pg_files or has_webwork_in_name:
		if has_pg_files:
			reasoning.append('Found .pg files')
		if has_webwork_in_name:
			reasoning.append('Repo name contains webwork/perl')
		return ('other', 'medium', reasoning)

	# No strong signals
	reasoning.append('No definitive type markers found')
	return ('ambiguous', 'low', reasoning)


#============================================
def parse_args() -> argparse.Namespace:
	"""Parse command-line arguments."""
	parser = argparse.ArgumentParser(
		description='Detect repository type from contents'
	)
	parser.add_argument(
		'--repo', dest='repo_name',
		default=None,
		help='Repo name under base-dir (or ~/nsh by default)'
	)
	parser.add_argument(
		'--base-dir', dest='base_dir',
		default=None,
		help='Base directory containing repos (default: ~/nsh)'
	)
	parser.add_argument(
		'--repo-path', dest='repo_path',
		default=None,
		help='Absolute path to repo (overrides --repo)'
	)
	args = parser.parse_args()
	return args


#============================================
def main() -> None:
	"""CLI interface for repo type detection."""
	args = parse_args()

	# Resolve repo path
	if args.repo_path:
		repo_dir = os.path.abspath(os.path.expanduser(args.repo_path))
	elif args.repo_name:
		if args.base_dir:
			base_dir = os.path.abspath(os.path.expanduser(args.base_dir))
		else:
			base_dir = os.path.abspath(os.path.expanduser('~/nsh'))
		repo_dir = os.path.join(base_dir, args.repo_name)
	else:
		repo_dir = os.getcwd()

	if not os.path.isdir(repo_dir):
		print("repo=unknown type=error confidence=error")
		print("reasoning:")
		print(f"  - Directory not found: {repo_dir}")
		return

	repo_basename = os.path.basename(repo_dir)
	token, confidence, reasoning = detect_repo_type(repo_dir)

	print(f"repo={repo_basename} type={token} confidence={confidence}")
	print("reasoning:")
	for bullet in reasoning:
		print(f"  - {bullet}")


if __name__ == '__main__':
	main()
