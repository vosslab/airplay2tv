"""Tests for the block-aware merge helper merge_conftest.

merge_conftest manages two blocks in a consumer tests/conftest.py: the
collect_ignore block and the REPO_HYGIENE_FILTERS registry block. Both ship
additively. These tests exercise the real shipped template tests/conftest.py as
the canonical source so they track the actual content, and cover: missing dest
(full template), one block present (other appended, existing block untouched),
both present (no change), and a consumer-set custom filters value (preserved).
"""

# Standard Library
import os
import pathlib

# local repo modules
import file_utils
import repolib.files


SOURCE_FILE = os.path.join(file_utils.get_repo_root(), "tests", "conftest.py")


#============================================
def _write(path: str, content: str) -> None:
	"""Write content to path as UTF-8 text."""
	with open(path, 'w', encoding='utf-8') as handle:
		handle.write(content)


#============================================
def test_no_dest_returns_full_template(tmp_path: pathlib.Path) -> None:
	"""Missing dest returns the full canonical template with both blocks."""
	dest = tmp_path / "conftest.py"

	result = repolib.files.merge_conftest(SOURCE_FILE, str(dest))

	assert result is not None
	assert "collect_ignore" in result
	assert "REPO_HYGIENE_FILTERS" in result


#============================================
def test_collect_ignore_present_adds_filters_block(tmp_path: pathlib.Path) -> None:
	"""Consumer with collect_ignore but no filters block gets the scaffold appended."""
	dest = tmp_path / "conftest.py"
	consumer_text = (
		"import pytest\n"
		"\n"
		"collect_ignore = ['e2e', 'playwright', 'local_only']\n"
	)
	_write(str(dest), consumer_text)

	result = repolib.files.merge_conftest(SOURCE_FILE, str(dest))

	assert result is not None
	# Missing block is added.
	assert "REPO_HYGIENE_FILTERS" in result
	# Existing consumer collect_ignore value survives verbatim.
	assert "collect_ignore = ['e2e', 'playwright', 'local_only']" in result
	# Original consumer import line survives.
	assert "import pytest" in result


#============================================
def test_both_blocks_present_returns_none(tmp_path: pathlib.Path) -> None:
	"""Consumer carrying both markers needs no change."""
	dest = tmp_path / "conftest.py"
	consumer_text = (
		"collect_ignore = ['e2e', 'playwright']\n"
		"\n"
		"REPO_HYGIENE_FILTERS = {}\n"
	)
	_write(str(dest), consumer_text)

	result = repolib.files.merge_conftest(SOURCE_FILE, str(dest))

	assert result is None


#============================================
def test_custom_filters_preserved_adds_collect_ignore(tmp_path: pathlib.Path) -> None:
	"""Consumer with a custom filters value and no collect_ignore keeps its value."""
	dest = tmp_path / "conftest.py"
	consumer_text = 'REPO_HYGIENE_FILTERS = {"all": ["foo/**"]}\n'
	_write(str(dest), consumer_text)

	result = repolib.files.merge_conftest(SOURCE_FILE, str(dest))

	assert result is not None
	# Missing collect_ignore block is added.
	assert "collect_ignore" in result
	# Custom filters value is preserved verbatim.
	assert "foo/**" in result


#============================================
def test_neither_marker_adds_both_blocks(tmp_path: pathlib.Path) -> None:
	"""Consumer with only a fixture import gets both managed blocks."""
	dest = tmp_path / "conftest.py"
	_write(str(dest), "import pytest\n")

	result = repolib.files.merge_conftest(SOURCE_FILE, str(dest))

	assert result is not None
	assert "collect_ignore" in result
	assert "REPO_HYGIENE_FILTERS" in result
	# Original consumer content survives.
	assert "import pytest" in result
