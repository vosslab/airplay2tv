#!/usr/bin/env python3
"""Single-repo interactive tool for propagating canonical docs and styles."""

import argparse

import repolib.console
import repolib.process


#============================================
def parse_args() -> argparse.Namespace:
	"""Parse CLI flags and return the argparse Namespace."""
	parser = argparse.ArgumentParser(
		description=(
			"Propagate shared style guides and docs into a single target repo."
		)
	)
	parser.add_argument(
		'-n', '--dry-run', dest='dry_run',
		help='Only display planned changes', action='store_true'
	)
	parser.add_argument(
		'-R', '--repo', dest='repo_path',
		required=True,
		help='Path to the target repo (relative or absolute, e.g. ../vosslab-skills or .)'
	)
	parser.set_defaults(dry_run=False)
	args = parser.parse_args()
	return args


#============================================
def main() -> int:
	"""Build context for a single repo and run propagation."""
	args = parse_args()
	context = repolib.process.build_context_for_repo(
		repo_path=args.repo_path, dry_run=args.dry_run,
		initial_setup=False, auto_discover=True, write_marker=True)
	counters = repolib.console.init_counters()
	result = repolib.process.process_repo(args.repo_path, context, counters, emit_per_repo_summary=False)
	repo_results = []
	if result is not None:
		repo_results.append(result)
	repolib.console.validate_counters(counters)
	repolib.console.print_summary(counters, repo_results=repo_results, dry_run=context.dry_run)

	# Final completion line: success (green) or failure (bold red)
	if counters['errors'] == 0:
		repolib.console.CONSOLE.print("[green]done[/]")
	else:
		repolib.console.CONSOLE.print(f"[bold red]failed ({counters['errors']} errors)[/]")

	exit_code = repolib.process.exit_code_for(counters)
	return exit_code


if __name__ == '__main__':
	raise SystemExit(main())
