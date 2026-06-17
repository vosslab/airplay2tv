"""Path setup for the meta test suite.

Meta tests import repo modules (repolib.*, file_utils, conftest,
detect_repo_type, commit_changelog) through these path entries instead of
each test inserting paths itself.
"""
import os
import sys

# Bootstrap: add tests/ so the shared file_utils helper imports. Everything
# else derives from file_utils.get_repo_root() (git rev-parse), not manual walks.
TESTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if TESTS_DIR not in sys.path:
	sys.path.insert(0, TESTS_DIR)

import file_utils

REPO_ROOT = file_utils.get_repo_root()
search_paths = (
	REPO_ROOT,
	TESTS_DIR,
	os.path.join(REPO_ROOT, "tools"),
	os.path.join(REPO_ROOT, "devel"),
)
for path in search_paths:
	if path not in sys.path:
		sys.path.insert(0, path)
