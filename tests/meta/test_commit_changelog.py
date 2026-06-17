"""Tests for devel/commit_changelog.py deterministic helpers.

Narrow coverage of pure-function paths where a real bug could plausibly
slip through: the cleaner composition pipeline, the message-builder
branches (empty, single entry, single-day vs multi-day grouping, body
continuation), the diff-parser (parse_added_bullet_lines), the heading-run
boundary (keep_recent_heading_run), and the select_new_entries integration
seam (monkeypatched git diff).
"""

# Standard Library
import textwrap

# pip3 modules
import pytest

# local repo modules
import changelog_lib
import commit_changelog


#============================================
# Helpers

def make_entry(date: str, title: str, body: str = "",
		category: str = "Fixes and Maintenance", lineno: int = 1) -> changelog_lib.Entry:
	"""Build an in-memory Entry record for tests."""
	text = title if not body else f"{title}. {body}"
	return changelog_lib.Entry(
		date=date,
		source="<test>",
		category=category,
		title=title,
		body=body,
		text=text,
		lineno=lineno,
	)


def make_block(date: str) -> changelog_lib.DayBlock:
	"""Build a minimal DayBlock for heading-run tests."""
	raw = f"## {date}\n\n### Fixes and Maintenance\n\n"
	return changelog_lib.DayBlock(
		date=date,
		raw_text=raw,
		source="<test>",
		lineno=1,
	)


#============================================
# clean_entry_text composition: the only round-trip that catches a real bug

def test_clean_entry_text_strips_link_bold_and_collapses_whitespace() -> None:
	raw = "**Refactor** [devel/foo.py](devel/foo.py)\nadds   a new helper"
	out = commit_changelog.clean_entry_text(raw, max_length=200)
	assert "**" not in out
	assert "[" not in out
	assert "]" not in out
	assert "  " not in out
	assert "devel/foo.py" in out


#============================================
# make_seed_message_from_entries: real branches a future change could break

def test_make_seed_message_empty_returns_none() -> None:
	assert commit_changelog.make_seed_message_from_entries([]) is None

def test_make_seed_message_single_entry_uses_title_as_subject() -> None:
	# single entry with no body: subject is the title and there is no
	# body block (the title bullet would just duplicate the subject)
	entry = make_entry("2026-05-21", "Fix link in docs/FILE.md")
	out = commit_changelog.make_seed_message_from_entries([entry])
	lines = out.splitlines()
	assert lines[0] == "Fix link in docs/FILE.md"
	assert "- Fix link in docs/FILE.md" not in lines

def test_make_seed_message_multi_day_emits_date_headings() -> None:
	entries = [
		make_entry("2026-05-21", "today bullet"),
		make_entry("2026-05-20", "yesterday bullet"),
	]
	out = commit_changelog.make_seed_message_from_entries(entries)
	assert "## 2026-05-21" in out
	assert "## 2026-05-20" in out

def test_make_seed_message_single_day_omits_heading() -> None:
	entries = [
		make_entry("2026-05-21", "first"),
		make_entry("2026-05-21", "second"),
	]
	out = commit_changelog.make_seed_message_from_entries(entries)
	assert "## 2026-05-21" not in out

def test_make_seed_message_single_entry_emits_body_as_paragraph() -> None:
	# single entry with a body: subject is the title; body is rendered as
	# a plain paragraph after the blank line (no `- title` repetition,
	# no two-space indent -- that shape is reserved for multi-entry lists)
	entry = make_entry("2026-05-21", "first line of bullet",
			body="continuation text on second line")
	out = commit_changelog.make_seed_message_from_entries([entry])
	lines = out.splitlines()
	assert lines[0] == "first line of bullet"
	assert lines[1] == ""
	assert lines[2].startswith("continuation text")
	assert not any(ln.startswith("- first line") for ln in lines)

def test_make_seed_message_multi_entry_keeps_bulleted_body() -> None:
	# multi-entry seeds keep the `- title` bullet list (each entry must
	# be individually scannable in the editor buffer)
	entries = [
		make_entry("2026-05-21", "alpha"),
		make_entry("2026-05-21", "beta"),
	]
	out = commit_changelog.make_seed_message_from_entries(entries)
	lines = out.splitlines()
	assert "- alpha" in lines
	assert "- beta" in lines


#============================================
# parse_added_bullet_lines: core of the diff-driven fix

def test_parse_added_bullet_lines_pure_insertion() -> None:
	# two added bullets, no removed bullets -> both line numbers returned
	diff = textwrap.dedent("""\
		--- a/docs/CHANGELOG.md
		+++ b/docs/CHANGELOG.md
		@@ -10,0 +11,2 @@
		+- Added first feature
		+- Added second feature
	""")
	result = commit_changelog.parse_added_bullet_lines(diff)
	assert result == {11, 12}

def test_parse_added_bullet_lines_edit_replacement() -> None:
	# one removed bullet + one added bullet -> edit replacement, empty set
	diff = textwrap.dedent("""\
		--- a/docs/CHANGELOG.md
		+++ b/docs/CHANGELOG.md
		@@ -5,1 +5,1 @@
		-- Fixed [old link](old.md) in docs
		+- Fixed [new link](new.md) in docs
	""")
	result = commit_changelog.parse_added_bullet_lines(diff)
	assert result == set()

def test_parse_added_bullet_lines_removal_only() -> None:
	# removed bullet only, nothing added -> empty set
	diff = textwrap.dedent("""\
		--- a/docs/CHANGELOG.md
		+++ b/docs/CHANGELOG.md
		@@ -5,1 +5,0 @@
		-- Removed stale bullet
	""")
	result = commit_changelog.parse_added_bullet_lines(diff)
	assert result == set()

def test_parse_added_bullet_lines_non_bullet_plus_lines_ignored() -> None:
	# added heading and context lines are not bullets -> ignored
	diff = textwrap.dedent("""\
		--- a/docs/CHANGELOG.md
		+++ b/docs/CHANGELOG.md
		@@ -1,0 +1,3 @@
		+## 2026-06-11
		+
		+### Fixes and Maintenance
	""")
	result = commit_changelog.parse_added_bullet_lines(diff)
	assert result == set()

def test_parse_added_bullet_lines_mixed_hunk() -> None:
	# r=1 removed bullet + 2 added bullets -> only the SECOND added bullet kept
	# (the first "absorbs" the single removed bullet as an edit replacement)
	diff = textwrap.dedent("""\
		--- a/docs/CHANGELOG.md
		+++ b/docs/CHANGELOG.md
		@@ -5,1 +5,2 @@
		-- Old description of a fix
		+- Updated description of the fix
		+- Completely new addition
	""")
	result = commit_changelog.parse_added_bullet_lines(diff)
	# line 5 is the first added (edit), line 6 is the surplus addition
	assert result == {6}

def test_parse_added_bullet_lines_nested_bullet_ignored() -> None:
	# indented sub-bullet should NOT be counted as a top-level addition
	diff = textwrap.dedent("""\
		--- a/docs/CHANGELOG.md
		+++ b/docs/CHANGELOG.md
		@@ -10,0 +11,2 @@
		+- Top-level bullet
		+   - nested sub-bullet
	""")
	result = commit_changelog.parse_added_bullet_lines(diff)
	# only the top-level bullet at line 11; the nested line at 12 is ignored
	assert result == {11}


#============================================
# Line-number join pin: guards the diff-lineno vs Entry.lineno seam

def test_entry_lineno_matches_bullet_position_in_parsed_text() -> None:
	# parse a known changelog string; each Entry.lineno must equal the
	# 1-based line of its "- " bullet in that text
	changelog_text = (
		"## 2026-06-11\n"          # line 1
		"\n"                        # line 2
		"### Fixes and Maintenance\n"  # line 3
		"\n"                        # line 4
		"- First bullet\n"          # line 5
		"- Second bullet\n"         # line 6
	)
	_blocks, entries, _warnings = changelog_lib.parse_text(
		changelog_text, source="<test>"
	)
	assert len(entries) == 2
	assert entries[0].title == "First bullet"
	assert entries[0].lineno == 5
	assert entries[1].title == "Second bullet"
	assert entries[1].lineno == 6


#============================================
# keep_recent_heading_run: boundary filter

def test_keep_recent_heading_run_empty_candidates_returns_empty() -> None:
	blocks = [make_block("2026-06-11"), make_block("2026-06-10")]
	result = commit_changelog.keep_recent_heading_run(blocks, [])
	assert result == []

def test_keep_recent_heading_run_two_adjacent_both_kept() -> None:
	blocks = [make_block("2026-06-11"), make_block("2026-06-10")]
	entries = [
		make_entry("2026-06-11", "bullet a"),
		make_entry("2026-06-10", "bullet b"),
	]
	result = commit_changelog.keep_recent_heading_run(blocks, entries)
	assert [e.title for e in result] == ["bullet a", "bullet b"]

def test_keep_recent_heading_run_stops_at_first_gap() -> None:
	# three dates; only first and third have candidates; second is a gap
	blocks = [
		make_block("2026-06-11"),
		make_block("2026-06-10"),
		make_block("2026-05-14"),
	]
	entries = [
		make_entry("2026-06-11", "newest"),
		make_entry("2026-05-14", "straggler"),
	]
	result = commit_changelog.keep_recent_heading_run(blocks, entries)
	# anchor = 2026-06-11; 2026-06-10 has no candidate (gap) -> stop
	# 2026-05-14 straggler is dropped
	assert [e.title for e in result] == ["newest"]

def test_keep_recent_heading_run_anchor_skips_leading_no_candidate_blocks() -> None:
	# newest block has no candidates; older block has the only candidate
	blocks = [
		make_block("2026-06-11"),
		make_block("2026-06-10"),
	]
	entries = [make_entry("2026-06-10", "old addition")]
	result = commit_changelog.keep_recent_heading_run(blocks, entries)
	# anchor skips 2026-06-11 (no candidate) and lands on 2026-06-10
	assert [e.title for e in result] == ["old addition"]

def test_keep_recent_heading_run_straggler_separated_by_gap_dropped() -> None:
	# anchor at newest; one gap heading separates the straggler
	blocks = [
		make_block("2026-06-11"),
		make_block("2026-06-08"),  # gap: no candidate
		make_block("2026-05-14"),  # straggler
	]
	entries = [
		make_entry("2026-06-11", "today"),
		make_entry("2026-05-14", "straggler"),
	]
	result = commit_changelog.keep_recent_heading_run(blocks, entries)
	assert [e.title for e in result] == ["today"]


#============================================
# select_new_entries integration (monkeypatched git diff)

def _build_select_fixture() -> tuple[str, str]:
	"""Return (changelog_text, diff_text) for integration tests.

	The changelog has:
	  line 1  ## 2026-06-11
	  line 2  (blank)
	  line 3  ### Fixes and Maintenance
	  line 4  (blank)
	  line 5  - New bullet added today   <- appears as + in diff
	  line 6  ## 2026-05-14
	  line 7  (blank)
	  line 8  ### Fixes and Maintenance
	  line 9  (blank)
	  line 10 - Old bullet rephrased     <- appears as edit in diff (- + +)

	The diff adds line 5 as a pure insertion and replaces line 10 as an edit.
	"""
	changelog_text = (
		"## 2026-06-11\n"
		"\n"
		"### Fixes and Maintenance\n"
		"\n"
		"- New bullet added today\n"
		"## 2026-05-14\n"
		"\n"
		"### Fixes and Maintenance\n"
		"\n"
		"- Old bullet rephrased\n"
	)
	# diff: line 5 is a pure insertion; lines 10 is edit (remove + add)
	diff_text = (
		"--- a/docs/CHANGELOG.md\n"
		"+++ b/docs/CHANGELOG.md\n"
		"@@ -4,0 +5,1 @@\n"
		"+- New bullet added today\n"
		"@@ -10,1 +10,1 @@\n"
		"-- Old bullet original phrasing\n"
		"+- Old bullet rephrased\n"
	)
	return changelog_text, diff_text


def test_select_new_entries_only_added_bullet_in_seed(monkeypatch: pytest.MonkeyPatch) -> None:
	# added current-date bullet + edited old bullet -> seed has only the current-date bullet
	changelog_text, diff_text = _build_select_fixture()
	monkeypatch.setattr(commit_changelog, "get_diff_vs_head", lambda _path: diff_text)
	monkeypatch.setattr(changelog_lib, "read_changelog", lambda _path: changelog_text)
	entries, warnings = commit_changelog.select_new_entries()
	assert len(entries) == 1
	assert entries[0].title == "New bullet added today"
	# silent drop: no warning about the excluded straggler
	assert not any("Old bullet" in w for w in warnings)

def test_select_new_entries_two_adjacent_headings_both_survive(
		monkeypatch: pytest.MonkeyPatch) -> None:
	# two adjacent headings each with a new bullet -> both survive
	changelog_text = (
		"## 2026-06-11\n"
		"\n"
		"### Fixes and Maintenance\n"
		"\n"
		"- Bullet under june 11\n"
		"## 2026-06-10\n"
		"\n"
		"### Fixes and Maintenance\n"
		"\n"
		"- Bullet under june 10\n"
	)
	# both bullets are pure insertions (no removed lines)
	diff_text = (
		"--- a/docs/CHANGELOG.md\n"
		"+++ b/docs/CHANGELOG.md\n"
		"@@ -4,0 +5,1 @@\n"
		"+- Bullet under june 11\n"
		"@@ -9,0 +10,1 @@\n"
		"+- Bullet under june 10\n"
	)
	monkeypatch.setattr(commit_changelog, "get_diff_vs_head", lambda _path: diff_text)
	monkeypatch.setattr(changelog_lib, "read_changelog", lambda _path: changelog_text)
	entries, _warnings = commit_changelog.select_new_entries()
	assert len(entries) == 2
	assert entries[0].title == "Bullet under june 11"
	assert entries[1].title == "Bullet under june 10"

def test_select_new_entries_no_added_bullets_returns_empty(
		monkeypatch: pytest.MonkeyPatch) -> None:
	# diff with only edits/removals -> no added bullets -> empty result
	changelog_text = (
		"## 2026-06-11\n"
		"\n"
		"### Fixes and Maintenance\n"
		"\n"
		"- Existing bullet rephrased\n"
	)
	# edit: remove old version, add new version (same line number)
	diff_text = (
		"--- a/docs/CHANGELOG.md\n"
		"+++ b/docs/CHANGELOG.md\n"
		"@@ -5,1 +5,1 @@\n"
		"-- Old phrasing\n"
		"+- Existing bullet rephrased\n"
	)
	monkeypatch.setattr(commit_changelog, "get_diff_vs_head", lambda _path: diff_text)
	monkeypatch.setattr(changelog_lib, "read_changelog", lambda _path: changelog_text)
	entries, _warnings = commit_changelog.select_new_entries()
	assert entries == []


if __name__ == "__main__":
	pytest.main([__file__, "-v"])
