"""Round-trip tests for the set-union merge helper merge_at_imports_safe.

Covers the @-import list merge used by CLAUDE.md: created (dest missing),
unchanged (consumer already has all template @-imports), merged-add (consumer
missing one template entry), plain-shape-success (no fences required),
dedup (duplicate @-imports not re-added), and deprecation strip (lines in
meta/propagation/deprecated_claude_md.txt removed from consumer).
"""

import pathlib

import pytest

import repolib.console
import repolib.files


TEMPLATE_BODY = (
	"@AGENTS.md\n"
	"@docs/REPO_STYLE.md\n"
	"@docs/PYTHON_STYLE.md\n"
)


def _write(path: pathlib.Path, content: str) -> None:
	with open(path, 'w', encoding='utf-8') as f:
		f.write(content)


def test_creates_when_dest_missing(tmp_path: pathlib.Path) -> None:
	source = tmp_path / "template.md"
	dest = tmp_path / "consumer" / "consumer.md"
	_write(source, TEMPLATE_BODY)
	counters = repolib.console.init_counters()

	outcome = repolib.files.merge_at_imports_safe(str(source), str(dest), dry_run=False, counters=counters)

	assert outcome == 'created'
	assert dest.read_text(encoding='utf-8') == TEMPLATE_BODY


def test_unchanged_when_consumer_has_all_template_imports(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
	"""Consumer already carries every template @-import and no deprecated lines."""
	monkeypatch.setattr(repolib.files, '_load_claude_md_deprecated', lambda: [])
	source = tmp_path / "template.md"
	dest = tmp_path / "consumer.md"
	_write(source, TEMPLATE_BODY)
	_write(dest, TEMPLATE_BODY)
	counters = repolib.console.init_counters()

	outcome = repolib.files.merge_at_imports_safe(str(source), str(dest), dry_run=False, counters=counters)

	assert outcome == 'unchanged'


def test_merged_adds_missing_template_imports(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
	"""Consumer missing one template @-import gets it appended; existing entries preserved."""
	monkeypatch.setattr(repolib.files, '_load_claude_md_deprecated', lambda: [])
	source = tmp_path / "template.md"
	dest = tmp_path / "consumer.md"
	_write(source, TEMPLATE_BODY)
	consumer_text = (
		"@AGENTS.md\n"
		"@docs/REPO_STYLE.md\n"
		"@docs/LOCAL_NOTES.md\n"
	)
	_write(dest, consumer_text)
	counters = repolib.console.init_counters()

	outcome = repolib.files.merge_at_imports_safe(str(source), str(dest), dry_run=False, counters=counters)

	merged = dest.read_text(encoding='utf-8')
	assert outcome == 'merged'
	assert "@docs/PYTHON_STYLE.md" in merged, "missing template entry added"
	assert "@docs/LOCAL_NOTES.md" in merged, "consumer-local entry preserved"


def test_plain_shape_no_fences_succeeds(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
	"""Consumer with no fence markers is acceptable; no error."""
	monkeypatch.setattr(repolib.files, '_load_claude_md_deprecated', lambda: [])
	source = tmp_path / "template.md"
	dest = tmp_path / "consumer.md"
	_write(source, TEMPLATE_BODY)
	_write(dest, "@AGENTS.md\n")
	counters = repolib.console.init_counters()

	outcome = repolib.files.merge_at_imports_safe(str(source), str(dest), dry_run=False, counters=counters)

	assert outcome == 'merged'


def test_duplicate_imports_not_readded(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
	"""If consumer already contains an @-import, template's matching line is not duplicated."""
	monkeypatch.setattr(repolib.files, '_load_claude_md_deprecated', lambda: [])
	source = tmp_path / "template.md"
	dest = tmp_path / "consumer.md"
	_write(source, "@AGENTS.md\n@docs/REPO_STYLE.md\n")
	# Consumer already has @AGENTS.md - template should not add a second copy.
	_write(dest, "@AGENTS.md\n@docs/REPO_STYLE.md\n")
	counters = repolib.console.init_counters()

	outcome = repolib.files.merge_at_imports_safe(str(source), str(dest), dry_run=False, counters=counters)

	assert outcome == 'unchanged'


def test_deprecated_line_stripped(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
	"""Lines matching the deprecation list are removed from the consumer."""
	monkeypatch.setattr(
		repolib.files,
		'_load_claude_md_deprecated',
		lambda: ['<!-- === TEMPLATE-MANAGED START === -->', '<!-- === TEMPLATE-MANAGED END === -->'],
	)
	source = tmp_path / "template.md"
	dest = tmp_path / "consumer.md"
	_write(source, TEMPLATE_BODY)
	consumer_text = (
		"<!-- === TEMPLATE-MANAGED START === -->\n"
		"@AGENTS.md\n"
		"@docs/REPO_STYLE.md\n"
		"@docs/PYTHON_STYLE.md\n"
		"<!-- === TEMPLATE-MANAGED END === -->\n"
	)
	_write(dest, consumer_text)
	counters = repolib.console.init_counters()

	outcome = repolib.files.merge_at_imports_safe(str(source), str(dest), dry_run=False, counters=counters)

	merged = dest.read_text(encoding='utf-8')
	assert outcome == 'merged'
	assert "TEMPLATE-MANAGED START" not in merged
	assert "TEMPLATE-MANAGED END" not in merged
	assert "@AGENTS.md" in merged
	assert "@docs/PYTHON_STYLE.md" in merged


def test_consumer_with_zero_at_imports(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
	"""Consumer has prose but no @-imports; template entries prepend at top."""
	monkeypatch.setattr(repolib.files, '_load_claude_md_deprecated', lambda: [])
	source = tmp_path / "template.md"
	dest = tmp_path / "consumer.md"
	_write(source, TEMPLATE_BODY)
	_write(dest, "Some prose with no @-imports at all.\n")
	counters = repolib.console.init_counters()

	outcome = repolib.files.merge_at_imports_safe(str(source), str(dest), dry_run=False, counters=counters)

	merged = dest.read_text(encoding='utf-8')
	assert outcome == 'merged'
	assert "@AGENTS.md" in merged
	assert "Some prose with no @-imports at all." in merged


def test_source_missing_returns_error(tmp_path: pathlib.Path) -> None:
	"""Missing template source surfaces 'error' and leaves the dest untouched."""
	source = tmp_path / "does_not_exist.md"
	dest = tmp_path / "consumer.md"
	_write(dest, "@AGENTS.md\n")
	before = dest.read_text(encoding='utf-8')
	counters = repolib.console.init_counters()

	outcome = repolib.files.merge_at_imports_safe(str(source), str(dest), dry_run=False, counters=counters)

	assert outcome == 'error'
	assert dest.read_text(encoding='utf-8') == before


def test_dry_run_does_not_modify(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
	"""dry_run=True must not write to the dest file even when a merge would change content."""
	monkeypatch.setattr(repolib.files, '_load_claude_md_deprecated', lambda: [])
	source = tmp_path / "template.md"
	dest = tmp_path / "consumer.md"
	_write(source, TEMPLATE_BODY)
	consumer_text = "@AGENTS.md\n"
	_write(dest, consumer_text)
	counters = repolib.console.init_counters()

	outcome = repolib.files.merge_at_imports_safe(str(source), str(dest), dry_run=True, counters=counters)

	assert outcome == 'merged'
	assert dest.read_text(encoding='utf-8') == consumer_text
