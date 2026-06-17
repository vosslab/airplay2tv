#!/usr/bin/env python3
"""Analyze the local changelog corpus and emit a structured markdown report.

Reads every ``CHANGELOG*.md`` under ``tests/fixtures/changelog_corpus/``,
parses each with ``devel.changelog_lib.parse_file(strict=False)``, and
writes ``report_changelog_corpus.md`` at the repo root with:

- Headline verdict paragraph (parser robust / no crashes / dominant
  warning shapes summarized)
- aggregate counts (files, blocks, entries, warnings)
- warning bucket breakdown using the parser's new warning shapes:
  ``legacy_flat_summary`` (one summary line per file with bare-flat
  blocks), ``bullets_before_first_category`` (per-block orphan-bullet
  shape, near-zero in observed corpus), ``lead_text_under_heading``
  (per-block author/attribution lines captured as `DayBlock.lead_text`),
  plus the existing ``bad_date``, ``duplicate_date``, and (strict-only)
  ``non_canonical_category`` shapes.
- lead-text frequency table sourced from ``block.lead_text`` (no
  warning-text re-parsing required).
- duplicate-date per-file counts
- per-file worst-offender tables
- list of files with no date headings

This script lives under ``meta/tools/`` so it does not propagate to
consumer repos. The corpus directory itself is also not committed;
populate it first with ``meta/tools/refresh_changelog_corpus.py``.

Usage:
	source source_me.sh && python meta/tools/analyze_corpus.py

The output report path can be overridden with ``-o/--output``.
"""

# Standard Library
import os
import sys
import glob
import types
import argparse
import datetime
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
# Warning bucket markers (substring match against warning text)
WARNING_BUCKETS = [
	("bad_date", "invalid date"),
	("duplicate_date", "duplicate date"),
	("non_canonical_category", "non-canonical category"),
	("legacy_flat_summary", "legacy flat changelog"),
	("bullets_before_first_category", "orphan bullets before first category"),
	("lead_text_under_heading", "lead text under day heading"),
]


#============================================
def bucket_for_warning(warning_text: str) -> str:
	"""Return the bucket name for a warning, or 'other' if unmatched."""
	for name, marker in WARNING_BUCKETS:
		if marker in warning_text:
			return name
	return "other"


#============================================
def short_name(path: str) -> str:
	"""Convert flattened fixture filename back to a sibling-repo path."""
	base = os.path.basename(path)
	return base.replace("__docs__", "/docs/").replace("__", "/")


#============================================
def parse_legacy_flat_block_count(warning_text: str) -> int:
	"""Extract the day-block count from a legacy_flat_summary warning."""
	# warning shape: "{path}: legacy flat changelog: N day blocks have ..."
	import re
	match = re.search(r"legacy flat changelog: (\d+) day blocks", warning_text)
	if not match:
		return 0
	return int(match.group(1))


#============================================
def parse_args() -> argparse.Namespace:
	"""Parse command-line arguments."""
	parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
	parser.add_argument(
		"-o", "--output", dest="output_path",
		default=None,
		help="Output report path (default: <repo>/report_changelog_corpus.md).",
	)
	parser.add_argument(
		"-d", "--corpus-dir", dest="corpus_dir",
		default=None,
		help="Corpus directory (default: <repo>/tests/fixtures/changelog_corpus).",
	)
	args = parser.parse_args()
	return args


#============================================
def analyze_corpus(corpus_dir: str, lib: types.ModuleType) -> dict:
	"""Parse every corpus file and collect aggregate + per-file data."""
	paths = sorted(glob.glob(os.path.join(corpus_dir, "*CHANGELOG*.md")))
	totals = {
		"files": 0,
		"with_headings": 0,
		"blocks": 0,
		"entries": 0,
		"warnings": 0,
		"legacy_flat_block_total": 0,
		"buckets": {name: 0 for name, _ in WARNING_BUCKETS},
	}
	totals["buckets"]["other"] = 0
	totals["buckets"]["no_headings_in_file"] = 0

	per_file = []
	lead_text_frequency = {}

	for path in paths:
		blocks, entries, warnings = lib.parse_file(path, strict=False)
		text = lib.read_changelog(path)
		has_headings = any(lib.DATE_RE.match(line) for line in text.splitlines())

		file_buckets = {name: 0 for name, _ in WARNING_BUCKETS}
		file_buckets["other"] = 0
		file_legacy_blocks = 0
		for w in warnings:
			bucket = bucket_for_warning(w)
			file_buckets[bucket] += 1
			if bucket == "legacy_flat_summary":
				file_legacy_blocks += parse_legacy_flat_block_count(w)

		# enumerate lead_text strings directly from DayBlock records, no
		# warning-text re-parsing required.
		for blk in blocks:
			if blk.lead_text:
				lead_text_frequency[blk.lead_text] = (
					lead_text_frequency.get(blk.lead_text, 0) + 1
				)

		per_file.append({
			"name": short_name(path),
			"blocks": len(blocks),
			"entries": len(entries),
			"warnings": warnings,
			"has_headings": has_headings,
			"buckets": file_buckets,
			"legacy_flat_blocks": file_legacy_blocks,
		})

		totals["files"] += 1
		totals["blocks"] += len(blocks)
		totals["entries"] += len(entries)
		totals["warnings"] += len(warnings)
		totals["legacy_flat_block_total"] += file_legacy_blocks
		if has_headings:
			totals["with_headings"] += 1
		else:
			totals["buckets"]["no_headings_in_file"] += 1
		for w in warnings:
			totals["buckets"][bucket_for_warning(w)] += 1

	return {
		"paths": paths,
		"totals": totals,
		"per_file": per_file,
		"lead_text_frequency": lead_text_frequency,
	}


#============================================
def fmt_table_header(columns: list) -> list:
	"""Build a 2-line markdown table header for the given column names."""
	header = "| " + " | ".join(columns) + " |"
	sep = "| " + " | ".join(["---"] * len(columns)) + " |"
	return [header, sep]


#============================================
def build_headline(totals: dict) -> list:
	"""Construct the Headline verdict paragraph from aggregate counters."""
	lines = []
	lines.append("## Headline")
	lines.append("")
	lines.append(
		f"Parser is robust: zero crashes across {totals['files']} files, "
		f"{totals['blocks']} day blocks, {totals['entries']} entries. "
		f"Strict-form discipline (date heading + category subheadings + "
		f"bullets) is the dominant shape in recent writing but not "
		f"universal across legacy archives. Duplicate-date warnings are "
		f"the only high-priority cleanup signal; the dominant warning "
		f"shape (\"legacy flat\") is volume but not data loss, and the "
		f"per-block \"lead text under day heading\" shape is "
		f"entry-view data loss but narrowly scoped."
	)
	lines.append("")
	lines.append(
		f"Quick counts: {totals['buckets']['legacy_flat_summary']} files "
		f"flagged as legacy flat (covering "
		f"{totals['legacy_flat_block_total']} bare-flat day blocks); "
		f"{totals['buckets']['lead_text_under_heading']} blocks with "
		f"captured `DayBlock.lead_text` (author/attribution lines that "
		f"entry-view consumers would otherwise drop silently); "
		f"{totals['buckets']['duplicate_date']} duplicate-date warnings; "
		f"{totals['buckets']['bullets_before_first_category']} "
		f"orphan-bullet warnings; "
		f"{totals['buckets']['bad_date']} bad-date warnings."
	)
	lines.append("")
	return lines


#============================================
def build_report(data: dict) -> str:
	"""Assemble the full markdown report from analyzed data."""
	t = data["totals"]
	now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
	lines = []

	lines.append("# Changelog reader corpus tolerance report")
	lines.append("")
	lines.append(f"Generated by `meta/tools/analyze_corpus.py` at {now}.")
	lines.append("")
	lines.append(
		"Source corpus: every `CHANGELOG*.md` under "
		"`tests/fixtures/changelog_corpus/` (developer-local, not "
		"committed). Parser: "
		"`devel/changelog_lib.parse_file(path, strict=False)`."
	)
	lines.append("")

	# headline verdict first
	lines.extend(build_headline(t))

	#========================================
	lines.append("## Aggregate")
	lines.append("")
	lines.extend(fmt_table_header(["Metric", "Value"]))
	lines.append(f"| Files surveyed | {t['files']} |")
	lines.append(f"| Files with `## YYYY-MM-DD` headings | {t['with_headings']} |")
	lines.append(f"| Files with NO date headings | {t['buckets']['no_headings_in_file']} |")
	lines.append(f"| Day blocks parsed | {t['blocks']} |")
	lines.append(f"| Entries parsed | {t['entries']} |")
	lines.append(f"| Warnings emitted | {t['warnings']} |")
	lines.append(f"| Legacy flat block total (across summaries) | {t['legacy_flat_block_total']} |")
	lines.append("| Parser crashes | 0 |")
	lines.append("")

	#========================================
	lines.append("## Warning bucket breakdown")
	lines.append("")
	lines.extend(fmt_table_header(["Bucket", "Count", "% of warnings"]))
	bucket_meaning = {
		"bad_date": "Heading shape `## YYYY-MM-DD` but date is calendrically invalid.",
		"duplicate_date": "Same date heading appears more than once in a file.",
		"non_canonical_category": "`### Category` heading not in CANONICAL_CATEGORIES (strict mode only).",
		"legacy_flat_summary": "Per-file summary: N day blocks in this file have bullets with no `### Category` heading.",
		"bullets_before_first_category": "Per-block: bullets appear in a block before its first `### Category` heading.",
		"lead_text_under_heading": "Per-block: non-bullet, non-heading text appeared under a day heading; captured on `DayBlock.lead_text`.",
		"no_headings_in_file": "File contains zero `## YYYY-MM-DD` headings (informational, not warning).",
		"other": "Warning shape not matched by any known bucket marker.",
	}
	total_warnings = max(t["warnings"], 1)
	for name in (
		"legacy_flat_summary", "lead_text_under_heading",
		"duplicate_date", "bullets_before_first_category",
		"no_headings_in_file", "bad_date", "non_canonical_category",
		"other",
	):
		count = t["buckets"][name]
		if name == "no_headings_in_file":
			pct = "(informational)"
		else:
			pct = f"{100.0 * count / total_warnings:.1f}%"
		lines.append(f"| `{name}` | {count} | {pct} |")
	lines.append("")
	lines.append("Meanings:")
	lines.append("")
	for name, meaning in bucket_meaning.items():
		lines.append(f"- `{name}`: {meaning}")
	lines.append("")

	#========================================
	if data["lead_text_frequency"]:
		lines.append("## Captured `lead_text` frequency")
		lines.append("")
		lines.append(
			"Author/attribution lines that the parser now captures on "
			"`DayBlock.lead_text` instead of silently dropping. These "
			"are still IGNORED by `Entry`-iterating consumers "
			"(`query_changelog --category`, `commit_changelog` seed); "
			"`query_changelog` text output renders them as `> ` "
			"blockquote context under the matching date heading."
		)
		lines.append("")
		lines.extend(fmt_table_header(["Lead text", "Occurrences"]))
		tops = sorted(
			data["lead_text_frequency"].items(),
			key=lambda kv: -kv[1],
		)
		for text, count in tops:
			# escape pipes inside the lead text so the table parses
			safe = text.replace("|", r"\|").replace("\n", " ")
			lines.append(f"| `{safe}` | {count} |")
		lines.append("")

	#========================================
	# legacy_flat worst-offender table (per-file block counts from summary lines)
	flat_rows = [
		(f["name"], f["legacy_flat_blocks"])
		for f in data["per_file"]
		if f["legacy_flat_blocks"] > 0
	]
	flat_rows.sort(key=lambda r: -r[1])
	if flat_rows:
		lines.append("## Legacy-flat worst offenders")
		lines.append("")
		lines.append(
			"Counts are the number of bare-flat day blocks (no "
			"`### Category` heading) reported in the parser's per-file "
			"summary line."
		)
		lines.append("")
		lines.extend(fmt_table_header(["File", "Bare-flat day blocks"]))
		for name, count in flat_rows[:20]:
			lines.append(f"| `{name}` | {count} |")
		lines.append("")

	#========================================
	# Duplicate-date offenders
	dup_rows = []
	for f in data["per_file"]:
		c = f["buckets"]["duplicate_date"]
		if c > 0:
			dup_rows.append((f["name"], c))
	dup_rows.sort(key=lambda r: -r[1])
	if dup_rows:
		lines.append("## Duplicate-date offenders")
		lines.append("")
		lines.extend(fmt_table_header(["File", "duplicate_date warnings"]))
		for name, count in dup_rows:
			lines.append(f"| `{name}` | {count} |")
		lines.append("")
		lines.append(
			"Each warning skips one duplicate block on the default "
			"read path, dropping its entries from query, commit-helper, "
			"and rotator views. Worth a targeted cleanup pass."
		)
		lines.append("")

	#========================================
	# Files with no headings
	empties = [f["name"] for f in data["per_file"] if not f["has_headings"]]
	if empties:
		lines.append("## Files with no date headings")
		lines.append("")
		lines.append(
			"These parse as preamble-only (zero blocks). Not failures, "
			"but worth a manual triage to confirm they are intentional "
			"(new repo, drained archive) and not a corrupted "
			"post-rotation state."
		)
		lines.append("")
		for name in empties:
			lines.append(f"- `{name}`")
		lines.append("")

	#========================================
	# Full per-file table at the end (for reference)
	lines.append("## Per-file summary")
	lines.append("")
	lines.extend(fmt_table_header([
		"File", "Blocks", "Entries", "Warnings",
		"bad_date", "dup_date", "non_canon",
		"legacy_flat", "orphan", "lead_text",
	]))
	for f in data["per_file"]:
		b = f["buckets"]
		lines.append(
			f"| `{f['name']}` | {f['blocks']} | {f['entries']} | "
			f"{len(f['warnings'])} | {b['bad_date']} | "
			f"{b['duplicate_date']} | {b['non_canonical_category']} | "
			f"{b['legacy_flat_summary']} "
			f"({f['legacy_flat_blocks']} blocks) | "
			f"{b['bullets_before_first_category']} | "
			f"{b['lead_text_under_heading']} |"
		)
	lines.append("")

	return "\n".join(lines) + "\n"


#============================================
def main() -> int:
	"""Drive corpus analysis and emit the markdown report."""
	args = parse_args()
	repo_root = get_repo_root()
	sys.path.insert(0, os.path.join(repo_root, "devel"))
	import changelog_lib

	corpus_dir = args.corpus_dir or os.path.join(
		repo_root, "tests", "fixtures", "changelog_corpus",
	)
	if not os.path.isdir(corpus_dir):
		print(f"corpus directory missing: {corpus_dir}", file=sys.stderr)
		print("populate it first with meta/tools/refresh_changelog_corpus.py",
			file=sys.stderr)
		return 1

	data = analyze_corpus(corpus_dir, changelog_lib)
	report = build_report(data)

	output_path = args.output_path or os.path.join(
		repo_root, "report_changelog_corpus.md",
	)
	with open(output_path, "w", encoding="utf-8") as handle:
		handle.write(report)
	print(f"wrote: {output_path}")
	t = data["totals"]
	print(f"  files: {t['files']}, blocks: {t['blocks']}, "
		f"entries: {t['entries']}, warnings: {t['warnings']}")
	return 0


#============================================
if __name__ == "__main__":
	raise SystemExit(main())
