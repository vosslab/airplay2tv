"""Tests for reset_repo.py resolve_license() helper."""

import pytest

from reset_repo import resolve_license, CODE_LICENSES, DOCS_LICENSES, CODE_ALIASES, DOCS_ALIASES


class TestResolveLicenseCodeLicenses:
	def test_lowercase_aliases(self) -> None:
		assert resolve_license("m", CODE_LICENSES, CODE_ALIASES) == "MIT"
		assert resolve_license("a", CODE_LICENSES, CODE_ALIASES) == "Apache-2.0"
		assert resolve_license("l", CODE_LICENSES, CODE_ALIASES) == "LGPL-3.0"
		assert resolve_license("g", CODE_LICENSES, CODE_ALIASES) == "GPL-3.0"
		assert resolve_license("ag", CODE_LICENSES, CODE_ALIASES) == "AGPL-3.0"
		assert resolve_license("mp", CODE_LICENSES, CODE_ALIASES) == "MPL-2.0"

	def test_uppercase_aliases(self) -> None:
		assert resolve_license("MIT", CODE_LICENSES, CODE_ALIASES) == "MIT"
		assert resolve_license("A", CODE_LICENSES, CODE_ALIASES) == "Apache-2.0"
		assert resolve_license("AG", CODE_LICENSES, CODE_ALIASES) == "AGPL-3.0"
		assert resolve_license("MP", CODE_LICENSES, CODE_ALIASES) == "MPL-2.0"

	def test_case_insensitive_aliases(self) -> None:
		assert resolve_license("M", CODE_LICENSES, CODE_ALIASES) == "MIT"
		assert resolve_license("Ag", CODE_LICENSES, CODE_ALIASES) == "AGPL-3.0"

	def test_unique_prefix(self) -> None:
		assert resolve_license("mit", CODE_LICENSES, CODE_ALIASES) == "MIT"
		assert resolve_license("apache", CODE_LICENSES, CODE_ALIASES) == "Apache-2.0"
		assert resolve_license("gp", CODE_LICENSES, CODE_ALIASES) == "GPL-3.0"
		assert resolve_license("LGPL", CODE_LICENSES, CODE_ALIASES) == "LGPL-3.0"

	def test_ambiguous_prefix_raises(self) -> None:
		with pytest.raises(ValueError):
			resolve_license("c", CODE_LICENSES, CODE_ALIASES)

	def test_unknown_token_raises(self) -> None:
		with pytest.raises(ValueError):
			resolve_license("z", CODE_LICENSES, CODE_ALIASES)
		with pytest.raises(ValueError):
			resolve_license("xyz", CODE_LICENSES, CODE_ALIASES)

	def test_empty_input_no_default_raises(self) -> None:
		with pytest.raises(ValueError):
			resolve_license("", CODE_LICENSES, CODE_ALIASES)

	def test_empty_input_with_default_returns_default(self) -> None:
		assert resolve_license("", CODE_LICENSES, CODE_ALIASES, default="MIT") == "MIT"


class TestResolveLicenseDocsLicenses:
	def test_lowercase_aliases_docs(self) -> None:
		assert resolve_license("cb", DOCS_LICENSES, DOCS_ALIASES) == "CC-BY-4.0"
		assert resolve_license("cs", DOCS_LICENSES, DOCS_ALIASES) == "CC-BY-SA-4.0"
		assert resolve_license("n", DOCS_LICENSES, DOCS_ALIASES) == "none"

	def test_uppercase_aliases_docs(self) -> None:
		assert resolve_license("CB", DOCS_LICENSES, DOCS_ALIASES) == "CC-BY-4.0"
		assert resolve_license("CS", DOCS_LICENSES, DOCS_ALIASES) == "CC-BY-SA-4.0"
		assert resolve_license("N", DOCS_LICENSES, DOCS_ALIASES) == "none"

	def test_unique_prefix_docs(self) -> None:
		assert resolve_license("cc-by-4", DOCS_LICENSES, DOCS_ALIASES) == "CC-BY-4.0"
		assert resolve_license("none", DOCS_LICENSES, DOCS_ALIASES) == "none"

	def test_ambiguous_prefix_cc_raises(self) -> None:
		with pytest.raises(ValueError):
			resolve_license("cc", DOCS_LICENSES, DOCS_ALIASES)

	def test_empty_input_with_docs_default(self) -> None:
		assert resolve_license("", DOCS_LICENSES, DOCS_ALIASES, default="CC-BY-4.0") == "CC-BY-4.0"
