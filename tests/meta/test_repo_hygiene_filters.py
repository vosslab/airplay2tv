import os

import file_utils
import conftest

tests_dir = os.path.join(file_utils.get_repo_root(), "tests")


#============================================
def _valid_test_keys() -> set:
	"""
	Return the set of valid REPO_HYGIENE_FILTERS keys: "all" plus the stem of
	every vendored hygiene test (tests/test_<stem>.py).
	"""
	valid = {"all"}
	for name in os.listdir(tests_dir):
		# Only test_*.py files at the top of tests/ (not in subdirs)
		if name.startswith("test_") and name.endswith(".py"):
			stem = name[len("test_"):-len(".py")]
			valid.add(stem)
	return valid


#============================================
def test_repo_hygiene_filters_is_dict() -> None:
	"""
	REPO_HYGIENE_FILTERS must be a dict; missing attribute is treated as empty.
	"""
	registry = getattr(conftest, "REPO_HYGIENE_FILTERS", {})
	assert isinstance(registry, dict)


#============================================
def test_repo_hygiene_filters_keys_are_valid() -> None:
	"""
	Every key in REPO_HYGIENE_FILTERS must be "all" or match a vendored test stem.

	A vendored test stem is the filename stem of tests/test_<stem>.py.
	This guards downstream repos: a stale or mistyped key silently does nothing,
	so the guard catches it before confusion arises.
	"""
	registry = getattr(conftest, "REPO_HYGIENE_FILTERS", {})
	valid_keys = _valid_test_keys()
	for key in registry:
		assert key in valid_keys, (
			f"REPO_HYGIENE_FILTERS key {key!r} is not 'all' and does not match "
			f"any tests/test_<key>.py file. Valid keys: {sorted(valid_keys)}"
		)


#============================================
def test_repo_hygiene_filters_values_are_lists_of_strings() -> None:
	"""
	Every value in REPO_HYGIENE_FILTERS must be a list of strings.

	Each string is a repo-relative POSIX glob pattern passed to
	fnmatch.fnmatchcase. An empty list is allowed (vacuous exclusion).
	"""
	registry = getattr(conftest, "REPO_HYGIENE_FILTERS", {})
	for key, patterns in registry.items():
		assert isinstance(patterns, list), (
			f"REPO_HYGIENE_FILTERS[{key!r}] must be a list, got {type(patterns).__name__}"
		)
		for i, pattern in enumerate(patterns):
			assert isinstance(pattern, str), (
				f"REPO_HYGIENE_FILTERS[{key!r}][{i}] must be a str, got {type(pattern).__name__}"
			)
