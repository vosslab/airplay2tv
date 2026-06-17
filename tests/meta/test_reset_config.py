"""Tests for reset_repo.py config-path helpers.

Covers load_config, answers_from_config, and is_template_source_dir using
synthetic tmp_path json files. All tests are fast and offline.
"""

# Standard Library
import os
import json
import pathlib

# PIP3 modules
import pytest

# local repo modules (injected by tests/meta/conftest.py sys.path setup)
import reset_repo


#============================================
# Helpers
#============================================

def write_json(tmp_path: pathlib.Path, name: str, payload: object) -> str:
	"""Write payload as json to a file inside tmp_path and return its path.

	Args:
		tmp_path: Pytest tmp_path fixture (pathlib.Path or str).
		name: Filename to write under tmp_path.
		payload: JSON-serialisable object to write.

	Returns:
		str: Absolute path to the written file.
	"""
	file_path = os.path.join(str(tmp_path), name)
	with open(file_path, "w") as f:
		f.write(json.dumps(payload))
	return file_path


#============================================
# Valid config - normalization
#============================================

class TestAnswersFromConfigNormalization:
	"""answers_from_config applies normalization to alias inputs."""

	def test_short_project_type_normalized(self, tmp_path: pathlib.Path) -> None:
		"""Short 'p' -> 'python' after passing through normalize_project_type.

		Verifies that project_type aliases accepted by the interview are also
		accepted by the config path (shared normalization).
		"""
		cfg = {"project_type": "p", "code_license": "MIT"}
		path = write_json(tmp_path, "cfg.json", cfg)
		answers = reset_repo.answers_from_config(path)
		assert answers.project_type == "python"

	def test_code_license_alias_normalized(self, tmp_path: pathlib.Path) -> None:
		"""Short 'm' -> 'MIT' via resolve_license alias mapping."""
		cfg = {"project_type": "python", "code_license": "m"}
		path = write_json(tmp_path, "cfg.json", cfg)
		answers = reset_repo.answers_from_config(path)
		assert answers.code_license == "MIT"

	def test_code_license_prefix_normalized(self, tmp_path: pathlib.Path) -> None:
		"""Unique prefix 'Apache' -> 'Apache-2.0' via resolve_license prefix match."""
		cfg = {"project_type": "python", "code_license": "apache"}
		path = write_json(tmp_path, "cfg.json", cfg)
		answers = reset_repo.answers_from_config(path)
		assert answers.code_license == "Apache-2.0"

	def test_docs_license_alias_normalized(self, tmp_path: pathlib.Path) -> None:
		"""Short docs_license alias 'cb' -> 'CC-BY-4.0'."""
		cfg = {"project_type": "python", "code_license": "MIT", "docs_license": "cb"}
		path = write_json(tmp_path, "cfg.json", cfg)
		answers = reset_repo.answers_from_config(path)
		assert answers.docs_license == "CC-BY-4.0"


#============================================
# Missing required keys -> SystemExit
#============================================

class TestAnswersFromConfigRequiredKeys:
	"""Missing required keys surface as SystemExit (reset_repo uses sys.exit)."""

	def test_missing_project_type_raises(self, tmp_path: pathlib.Path) -> None:
		"""Config without 'project_type' must raise SystemExit."""
		cfg = {"code_license": "MIT"}
		path = write_json(tmp_path, "cfg.json", cfg)
		with pytest.raises(SystemExit):
			reset_repo.answers_from_config(path)

	def test_missing_code_license_raises(self, tmp_path: pathlib.Path) -> None:
		"""Config without 'code_license' must raise SystemExit."""
		cfg = {"project_type": "python"}
		path = write_json(tmp_path, "cfg.json", cfg)
		with pytest.raises(SystemExit):
			reset_repo.answers_from_config(path)


#============================================
# Optional keys take their documented defaults
#============================================

class TestAnswersFromConfigOptionalDefaults:
	"""Omitted optional keys use documented interview defaults.

	IMPORTANT: the defaults asserted here MUST match the resolve_* interview
	defaults in reset_repo.py:
	  - docs_license: resolve_licenses() passes default="CC-BY-4.0"
	  - pypi:         resolve_pypi() returns False for an empty/non-'y' answer

	If those interview defaults ever change, update both the resolve_* functions
	and the answers_from_config defaults in the same PR so the two paths stay
	consistent.
	"""

	def test_docs_license_defaults_to_cc_by(self, tmp_path: pathlib.Path) -> None:
		"""Omitting docs_license applies the CC-BY-4.0 interview default."""
		cfg = {"project_type": "python", "code_license": "MIT"}
		path = write_json(tmp_path, "cfg.json", cfg)
		answers = reset_repo.answers_from_config(path)
		assert answers.docs_license == "CC-BY-4.0"

	def test_pypi_defaults_to_false(self, tmp_path: pathlib.Path) -> None:
		"""Omitting pypi defaults to False (interview default: no)."""
		cfg = {"project_type": "python", "code_license": "MIT"}
		path = write_json(tmp_path, "cfg.json", cfg)
		answers = reset_repo.answers_from_config(path)
		assert answers.pypi is False


#============================================
# Invalid json -> SystemExit
#============================================

class TestLoadConfigInvalidJson:
	"""Malformed json surfaces as SystemExit via load_config."""

	def test_invalid_json_raises(self, tmp_path: pathlib.Path) -> None:
		"""A file containing invalid json must raise SystemExit."""
		file_path = os.path.join(str(tmp_path), "bad.json")
		with open(file_path, "w") as f:
			# Write text that is not valid json at all.
			f.write("{not valid json}")
		with pytest.raises(SystemExit):
			reset_repo.load_config(file_path)

	def test_missing_file_raises(self, tmp_path: pathlib.Path) -> None:
		"""A path that does not exist must raise SystemExit."""
		absent = os.path.join(str(tmp_path), "no_such_file.json")
		with pytest.raises(SystemExit):
			reset_repo.load_config(absent)


#============================================
# Non-dict top-level json -> SystemExit
#============================================

class TestLoadConfigNonDictTopLevel:
	"""A json file whose top-level value is not an object must raise SystemExit."""

	def test_bare_list_raises(self, tmp_path: pathlib.Path) -> None:
		"""Top-level json array is not a valid config object."""
		path = write_json(tmp_path, "list.json", ["python", "MIT"])
		with pytest.raises(SystemExit):
			reset_repo.load_config(path)

	def test_bare_string_raises(self, tmp_path: pathlib.Path) -> None:
		"""Top-level json string is not a valid config object."""
		path = write_json(tmp_path, "str.json", "python")
		with pytest.raises(SystemExit):
			reset_repo.load_config(path)


#============================================
# normalize_project_type swift aliases
#============================================

class TestNormalizeProjectTypeSwift:
	"""normalize_project_type accepts 's' and 'swift' and returns 'swift'."""

	def test_single_letter_s_returns_swift(self) -> None:
		"""Single-letter alias 's' normalizes to 'swift'."""
		result = reset_repo.normalize_project_type("s", "python")
		assert result == "swift"

	def test_full_name_swift_returns_swift(self) -> None:
		"""Full name 'swift' normalizes to 'swift'."""
		result = reset_repo.normalize_project_type("swift", "python")
		assert result == "swift"

	def test_swift_config_path_normalizes(self, tmp_path: pathlib.Path) -> None:
		"""Config with project_type 'swift' resolves to 'swift' via answers_from_config."""
		cfg = {"project_type": "swift", "code_license": "MIT"}
		path = write_json(tmp_path, "cfg.json", cfg)
		answers = reset_repo.answers_from_config(path)
		assert answers.project_type == "swift"

	def test_swift_short_alias_config_path_normalizes(self, tmp_path: pathlib.Path) -> None:
		"""Config with project_type 's' resolves to 'swift' via answers_from_config."""
		cfg = {"project_type": "s", "code_license": "MIT"}
		path = write_json(tmp_path, "cfg.json", cfg)
		answers = reset_repo.answers_from_config(path)
		assert answers.project_type == "swift"


#============================================
# PyPI forced False for non-python types
#============================================

class TestAnswersFromConfigPypiForced:
	"""Non-python repos must have pypi forced to False, mirroring resolve_pypi."""

	def test_pypi_forced_false_for_typescript(self, tmp_path: pathlib.Path) -> None:
		"""Typescript config with pypi=True must have pypi forced to False."""
		cfg = {"project_type": "typescript", "code_license": "MIT", "pypi": True}
		path = write_json(tmp_path, "cfg.json", cfg)
		answers = reset_repo.answers_from_config(path)
		assert answers.pypi is False

	def test_pypi_false_for_rust(self, tmp_path: pathlib.Path) -> None:
		"""Rust config with pypi=True must have pypi forced to False."""
		cfg = {"project_type": "rust", "code_license": "MIT", "pypi": True}
		path = write_json(tmp_path, "cfg.json", cfg)
		answers = reset_repo.answers_from_config(path)
		assert answers.pypi is False


#============================================
# is_template_source_dir basename check
#============================================

class TestIsTemplateSourceDir:
	"""is_template_source_dir inspects basename only; no real git repo needed."""

	def test_returns_true_for_template_name(self, tmp_path: pathlib.Path) -> None:
		"""A path whose basename is 'starter-repo-template' returns True."""
		template_dir = os.path.join(str(tmp_path), "starter-repo-template")
		assert reset_repo.is_template_source_dir(template_dir) is True

	def test_returns_false_for_consumer_name(self, tmp_path: pathlib.Path) -> None:
		"""A path with any other basename returns False."""
		consumer_dir = os.path.join(str(tmp_path), "my-project")
		assert reset_repo.is_template_source_dir(consumer_dir) is False

	def test_returns_false_for_similar_name(self, tmp_path: pathlib.Path) -> None:
		"""A path whose basename contains but is not 'starter-repo-template' returns False."""
		similar_dir = os.path.join(str(tmp_path), "my-starter-repo-template-fork")
		assert reset_repo.is_template_source_dir(similar_dir) is False
