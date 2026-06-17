"""Console output and counter management for propagation."""

from rich.console import Console

# highlight=False disables rich's auto-coloring of paths/numbers (renders as magenta in some terminals).
# width=200 hard-coded to prevent CI soft-wrap; keeps one line per action (determinism for snapshot tests).
CONSOLE = Console(width=200, highlight=False)

# Color philosophy: color signals importance/structure, not verb taxonomy.
# Action row verbs get meaningful color (changed files = yellow/blue, exceptions = red).
# Mode prefix "dry run" always dim. Counter rows + paths stay plain. Section headings use bold.
#
# Verb palette: update (yellow) = edit-in-place; copy/merge/create (blue) = file added/moved;
# removed (red) = destructive; skip/no change (dim) = no-op; warn (yellow) = caution; error (red) = failure.
ACTION_STYLES = {
	# mode prefix
	"dry run":   "dim",
	# changed-file verbs (color = "look here, file changed")
	"update":    "yellow",
	"copy":      "blue",
	"merge":     "blue",
	"create":    "blue",
	"removed":   "red",
	# non-change verbs (dim - usually suppressed)
	"skip":      "dim",
	"no change": "dim",
	# exceptions (warn/error)
	"warn":      "yellow",
	"error":     "red",
}

# Compute column width for verb alignment: widest verb name + 1 space.
# Exclude 'dry run': rendered as separate mode prefix token, not as a verb in the aligned column.
_VERB_WIDTH = max(len(v) for v in ACTION_STYLES if v != "dry run") + 1

# Verbs whose log lines are suppressed; counts roll into per-repo summary instead.
# Counter dispatch (skip message-prefix -> counter key) lives in log_action() body.
# When counters is None, quiet verbs still print (fallthrough behavior).
_QUIET_TAGS = {"no change", "skip"}


def log_action(verb: str, message: str, counters: dict | None = None, dry_run: bool = False) -> None:
	"""Log an action with separate mode and verb styling.

	For verbs in _QUIET_TAGS, suppress printing and increment counter instead.
	For other verbs, print with styled output: optional "dry run" prefix (dim) + verb (colored).

	Args:
		verb (str): Action verb in lowercase (must exist in ACTION_STYLES).
		message (str): Message body (separate from markup for safety).
		counters (dict | None): Optional counter dict to increment for quiet tags.
			When provided and verb is quiet, increments appropriate counter based on
			message prefix ('self:', 'source:', 'path:', or 'policy' default for SKIP;
			'unchanged' for NO CHANGE). When None or verb not quiet, behaves as before.
		dry_run (bool): If True, prepend "dry run" prefix (dim) before the verb.

	Raises:
		KeyError: If verb is not in ACTION_STYLES.
	"""
	style = ACTION_STYLES[verb]

	# Quiet tags: suppress printing and increment counter
	if verb in _QUIET_TAGS and counters is not None:
		if verb == "no change":
			counters['unchanged'] += 1
		elif verb == "skip":
			# Parse message prefix to attribute to correct counter
			if message.startswith("self:"):
				counters['skipped_self'] += 1
			elif message.startswith("source:"):
				counters['skipped_source'] += 1
			elif message.startswith("path:"):
				counters['skipped_path'] += 1
			else:
				counters['skipped_policy'] += 1
		return

	# Non-quiet tags: print with styled output
	padded_verb = verb.ljust(_VERB_WIDTH)
	if dry_run:
		CONSOLE.print(f"[dim]dry run[/] [{style}]{padded_verb}[/] {message}")
	else:
		CONSOLE.print(f"[{style}]{padded_verb}[/] {message}")


def init_counters() -> dict:
	"""
	Initialize mutable counter dictionary for global tracking.

	Returns a dict with all expected counter keys, each initialized to 0.

	Returns:
		dict: Counter dict with keys: copied_count, updated_count, merged_count,
			created_count, auto_discovered_count, errors,
			unchanged, skipped_source, skipped_self, skipped_path, skipped_policy.
	"""
	return {
		'copied_count': 0,
		'updated_count': 0,
		'merged_count': 0,
		'created_count': 0,
		'auto_discovered_count': 0,
		'errors': 0,
		'unchanged': 0,
		'skipped_source': 0,
		'skipped_self': 0,
		'skipped_path': 0,
		'skipped_policy': 0,
	}


def validate_counters(counters: dict) -> None:
	"""
	Validate that all expected counter keys are present.

	Raises AssertionError if any expected key is missing from the counters dict.
	Called at end-of-run to ensure data integrity.

	Args:
		counters (dict): Counter dict to validate.

	Raises:
		AssertionError: If any expected key is missing.
	"""
	expected_keys = {
		'copied_count',
		'updated_count',
		'merged_count',
		'created_count',
		'auto_discovered_count',
		'errors',
		'unchanged',
		'skipped_source',
		'skipped_self',
		'skipped_path',
		'skipped_policy',
	}
	actual_keys = set(counters.keys())
	missing = expected_keys - actual_keys
	if missing:
		raise RuntimeError(f"counters missing keys: {missing}")


def print_summary(counters: dict, repo_results: list = None, dry_run: bool = False) -> None:
	"""
	Print the summary block at end of run.

	For single-repo mode (len(repo_results) == 1), emits one SUMMARY block with
	repo and type rows plus counters.

	For multi-repo mode (len(repo_results) > 1), emits a final SUMMARY block with
	repos count plus aggregated counters.

	When dry_run is True, counter labels switch from past-tense to "would X" form:
	  updated -> would update
	  copied -> would copy
	  merged -> would merge
	  created -> would create
	  unchanged, skipped, errors stay as-is

	Suppresses zero-valued routine counters (only show nonzero action/state counters
	plus errors, which always displays even at 0). Order preserved: action counters
	first, then state counters, then errors.

	Args:
		counters (dict): Counter dict with all keys present (should be validated).
		repo_results (list): List of dicts with 'name' and 'type' keys (single-repo mode
			expects one element; multi-repo mode expects >1). When None or empty,
			defaults to multi-repo display with repos count.
		dry_run (bool): If True, use "would X" labels instead of past-tense.
	"""
	if repo_results is None:
		repo_results = []

	CONSOLE.print("")
	CONSOLE.print("[bold white]SUMMARY[/]")

	# Define counter label mapping based on dry_run flag
	if dry_run:
		action_labels = {
			'updated_count': 'would update',
			'copied_count': 'would copy',
			'merged_count': 'would merge',
			'created_count': 'would create',
		}
	else:
		action_labels = {
			'updated_count': 'updated',
			'copied_count': 'copied',
			'merged_count': 'merged',
			'created_count': 'created',
		}

	# Build counter rows based on single vs. multi-repo mode
	if len(repo_results) == 1:
		# Single-repo mode: include repo and type rows at top
		repo_info = repo_results[0]
		counter_rows = [
			('repo', repo_info['name']),
			('type', repo_info['type']),
			(action_labels['updated_count'], counters['updated_count']),
			(action_labels['copied_count'], counters['copied_count']),
			(action_labels['merged_count'], counters['merged_count']),
			(action_labels['created_count'], counters['created_count']),
			('unchanged', counters['unchanged']),
			('skipped', counters['skipped_source'] + counters['skipped_self'] + counters['skipped_path'] + counters['skipped_policy']),
			('errors', counters['errors']),
		]
	else:
		# Multi-repo mode: repos count instead of repo/type rows
		counter_rows = [
			('repos', len(repo_results)),
			(action_labels['updated_count'], counters['updated_count']),
			(action_labels['copied_count'], counters['copied_count']),
			(action_labels['merged_count'], counters['merged_count']),
			(action_labels['created_count'], counters['created_count']),
			('unchanged', counters['unchanged']),
			('skipped', counters['skipped_source'] + counters['skipped_self'] + counters['skipped_path'] + counters['skipped_policy']),
			('errors', counters['errors']),
		]

	# Suppress zero-valued routine counters (except errors, which always shows)
	# Routine counters: action counters and state counters (skip repo/repos/type rows)
	visible_rows = []
	for name, value in counter_rows:
		# Identity rows (repo/repos/type) always visible
		if name in ('repo', 'repos', 'type'):
			visible_rows.append((name, value))
		# Errors always visible
		elif name == 'errors':
			visible_rows.append((name, value))
		# Routine counters: show only if nonzero
		elif value != 0:
			visible_rows.append((name, value))

	# Compute column width based on visible counter names
	col_width = max(len(name) for name, _ in visible_rows) + 1

	# Print each visible row
	for name, value in visible_rows:
		if name == 'errors' and value > 0:
			CONSOLE.print(f"  {name.ljust(col_width)}[bold red]{value}[/]")
		else:
			CONSOLE.print(f"  {name.ljust(col_width)}{value}")
