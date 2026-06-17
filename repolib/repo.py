"""Repository discovery and type detection."""

import os
import sys

import repolib.console
# repolib.model is imported lazily inside read_repo_type (not at module top) to
# break an import cycle: repolib.model loads propagation manifests at import time
# and resolves the template root via repolib.repo.resolve_source_dir. A top-level
# import here would leave resolve_source_dir undefined when model imports repo first.


#============================================
def is_repo_dir(repo_dir: str) -> bool:
	"""Return True if directory contains a .git entry, False otherwise."""
	return os.path.exists(os.path.join(repo_dir, '.git'))


#============================================
def read_repo_type(repo_path: str, single_repo_mode: bool = False, write_marker: bool = False, skip_confirm: bool = False, non_interactive: bool = False, counters: dict | None = None) -> str:
	"""Read REPO_TYPE marker file and return repository language type token.

	In single-repo mode with write_marker, predicts type and writes marker.
	In batch mode with missing marker, attempts detection; falls back to LANG_UNKNOWN.
	LANG_UNKNOWN means no ROUTING_OVERRIDES exclude_repos rule applies;
	universal walker-routed files still ship.

	Returns token (python, typescript, rust, swift, other, unknown).
	An unrecognized marker token logs a warning and falls back to other
	instead of raising, so a single bad marker never aborts a batch run.

	Fallback to legacy STARTER_REPO_TYPE for backward compatibility.
	"""
	# repolib.model is imported here, at the top of the function body, not at
	# module level. Two reasons: (1) it breaks the import cycle described in the
	# module-top note (model loads manifests at import time and calls
	# resolve_source_dir from this module); a function-scoped import runs only at
	# call time, after both modules have finished loading. (2) `import
	# repolib.model` binds the package name `repolib` as a function-local for the
	# whole scope, so it MUST run before any `repolib.console.*` reference below,
	# or those references raise UnboundLocalError on the predict-and-write path.
	import repolib.model

	# Optional import: tools/detect_repo_type is present in template, removed at consumer bootstrap.
	detect_repo_type = None
	template_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
	tools_dir = os.path.join(template_root, 'tools')
	if os.path.isdir(tools_dir) and os.path.isfile(os.path.join(tools_dir, 'detect_repo_type.py')):
		sys.path.insert(0, tools_dir)
		import detect_repo_type

	marker_path = os.path.join(repo_path, 'REPO_TYPE')
	legacy_marker_path = os.path.join(repo_path, 'STARTER_REPO_TYPE')

	# Check for legacy marker first if new marker doesn't exist
	if not os.path.isfile(marker_path) and os.path.isfile(legacy_marker_path):
		repolib.console.log_action("warn", f"{repo_path}: legacy STARTER_REPO_TYPE marker found; rename to REPO_TYPE")
		with open(legacy_marker_path, 'r', encoding='utf-8') as f:
			token = f.read().strip()
		# Unknown legacy token: warn (naming token + STARTER_REPO_TYPE marker) and
		# fall back to other instead of raising, so a bad marker does not abort a batch.
		if token not in repolib.model.KNOWN_REPO_TYPES:
			repolib.console.log_action("warn", f"repo={os.path.basename(repo_path)} STARTER_REPO_TYPE token {token!r} not recognized; treating as other")
			return repolib.model.LANG_OTHER
		return token

	if not os.path.isfile(marker_path):
		# Missing marker: predict if conditions met, else default to python
		if single_repo_mode and write_marker and detect_repo_type:
			token, confidence, reasoning = detect_repo_type.detect_repo_type(repo_path)

			if confidence == 'high' and token in repolib.model.KNOWN_REPO_TYPES:
				# High confidence: write silently
				write_repo_type_marker(marker_path, token, dry_run=False)
				repolib.console.log_action("skip", f"repo={os.path.basename(repo_path)} type={token} confidence=high (auto-wrote marker, predicted)", counters)
				return token

			if confidence == 'medium':
				# Medium confidence: print and ask
				repolib.console.log_action("warn", f"repo={os.path.basename(repo_path)} type={token} (predicted, medium confidence)")
				repolib.console.CONSOLE.print("  reasoning:")
				for bullet in reasoning:
					repolib.console.CONSOLE.print(f"    - {bullet}")

				if skip_confirm or non_interactive:
					# Accept silently
					write_repo_type_marker(marker_path, token, dry_run=False)
					repolib.console.log_action("skip", "wrote marker (medium confidence accepted)", counters)
					return token

				if not non_interactive:
					# Prompt user
					user_input = input(f"Accept predicted type '{token}'? [Y/n]: ").strip()
					if user_input == '' or user_input.lower() == 'y':
						write_repo_type_marker(marker_path, token, dry_run=False)
						return token
					else:
						# User rejected; re-prompt for explicit type
						while True:
							user_type = input(
								"Project type? [p]ython / [t]ypescript / [r]ust / [s]wift / [o]ther [p]: "
							).strip()
							chosen_type = parse_repo_type_choice(user_type, 'python')
							write_repo_type_marker(marker_path, chosen_type, dry_run=False)
							return chosen_type

			# Low confidence or ambiguous: abort if non-interactive, else prompt
			repolib.console.log_action("error", f"repo={os.path.basename(repo_path)} (ambiguous, could not predict)")
			repolib.console.CONSOLE.print("  reasoning:")
			for bullet in reasoning:
				repolib.console.CONSOLE.print(f"    - {bullet}")

			if non_interactive:
				raise ValueError("ambiguous repo type; specify REPO_TYPE manually or use reset_repo.py")

			# Interactive prompt for ambiguous
			while True:
				user_type = input(
					"Project type? [p]ython / [t]ypescript / [r]ust / [s]wift / [o]ther: "
				).strip()
				chosen_type = parse_repo_type_choice(user_type, None)
				if chosen_type is None:
					print("Invalid choice. Try again.")
					continue
				write_repo_type_marker(marker_path, chosen_type, dry_run=False)
				return chosen_type

		# Batch mode with missing marker: try detection, fall back to LANG_UNKNOWN.
		# LANG_UNKNOWN means no ROUTING_OVERRIDES exclude_repos rule applies;
		# universal walker-routed files still ship. repolib.model was imported at
		# the top of this function (see note there).
		if detect_repo_type:
			token, confidence, _reasoning = detect_repo_type.detect_repo_type(repo_path)
			if confidence == 'high' and token in repolib.model.KNOWN_REPO_TYPES:
				return token
		return repolib.model.LANG_UNKNOWN

	with open(marker_path, 'r', encoding='utf-8') as f:
		token = f.read().strip()
	# Unknown token: warn (naming token + REPO_TYPE marker) and fall back to other
	# instead of raising, so a single bad marker never aborts a batch propagation.
	if token not in repolib.model.KNOWN_REPO_TYPES:
		repolib.console.log_action("warn", f"repo={os.path.basename(repo_path)} REPO_TYPE token {token!r} not recognized; treating as other")
		return repolib.model.LANG_OTHER
	return token


#============================================
def write_repo_type_marker(path: str, token: str, dry_run: bool = False) -> bool:
	"""
	Write REPO_TYPE marker file.

	Args:
		path (str): Path to REPO_TYPE marker file.
		token (str): Canonical type token (python, typescript, rust, swift, other).
		dry_run (bool): If True, do not write changes.

	Returns:
		bool: True if written, False on dry-run.
	"""
	content = token + '\n'
	if dry_run:
		repolib.console.log_action('create', path, dry_run=True)
		return False
	with open(path, 'w', encoding='utf-8') as f:
		f.write(content)
	return True


#============================================
def parse_repo_type_choice(text: str, default: str | None = None) -> str | None:
	"""
	Parse user input for repo type choice.

	Maps single-letter aliases and full words to canonical tokens.
	Unknown input returns default.

	Args:
		text (str): User input or single-letter choice.
		default (str): Default token if input is unrecognized.

	Returns:
		str: Canonical token (python, typescript, rust, swift, other) or default.
	"""
	if not text:
		return default
	choice = text.strip().lower()
	if choice in ('p', 'python'):
		return 'python'
	if choice in ('t', 'typescript'):
		return 'typescript'
	if choice in ('r', 'rust'):
		return 'rust'
	if choice in ('s', 'swift'):
		return 'swift'
	if choice in ('o', 'other'):
		return 'other'
	return default


#============================================
def repo_is_on_path(repo_dir: str) -> bool:
	"""
	Check whether the repository directory is present in PATH.
	"""
	# Normalize repo_dir for comparison
	target = os.path.normcase(os.path.realpath(os.path.abspath(repo_dir)))
	path_env = os.environ.get('PATH', '')
	for path_entry in path_env.split(os.pathsep):
		if not path_entry:
			continue
		# Normalize path entry for comparison
		normalized_entry = os.path.normcase(os.path.realpath(os.path.abspath(path_entry)))
		if normalized_entry == target:
			return True
	return False


#============================================
def find_repo_root(start_dir: str) -> str | None:
	"""
	Find the nearest ancestor that contains the expected style guides or templates.

	Args:
		start_dir (str): Starting directory.

	Returns:
		str | None: Repo root path when found, otherwise None.
	"""
	current = os.path.abspath(start_dir)
	while True:
		# Check for canonical template overlay (typed templates/ layout)
		if os.path.isdir(os.path.join(current, 'templates', 'typescript')):
			return current
		if os.path.isfile(os.path.join(current, 'docs', 'PYTHON_STYLE.md')):
			return current
		parent = os.path.dirname(current)
		if parent == current:
			return None
		current = parent


#============================================
def resolve_source_dir(source_dir_arg: str | None) -> str:
	"""
	Resolve the source template root used for propagation.

	When no override is provided, the source is the repo root of the running
	source checkout -- the one that contains propagate_style_guides.py and
	repolib/. This is anchored on repolib/__file__ (stable regardless of which
	entry script runs) via the find_repo_root() walk, so it never resolves to a
	target -R repo.

	Args:
		source_dir_arg (str | None): Optional user-provided source dir.

	Returns:
		str: Absolute source directory path.
	"""
	source_dir = source_dir_arg
	if source_dir is None:
		# Anchor on this package's location, not the cwd or any target repo.
		package_dir = os.path.dirname(os.path.abspath(__file__))
		detected_repo_root = find_repo_root(package_dir)
		if detected_repo_root is None:
			raise FileNotFoundError(
				"Default source dir not found: repolib package is not inside a recognizable repo root."
			)
		source_dir = detected_repo_root
	return os.path.abspath(os.path.expanduser(source_dir))


#============================================


