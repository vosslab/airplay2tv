"""Behavioral tests for file_utils caching: git spawns once per repo root."""

import pytest

import file_utils


#============================================
def test_get_repo_root_resolves_once_across_many_calls(monkeypatch: pytest.MonkeyPatch) -> None:
	"""
	get_repo_root spawns git at most once even across many helper calls.

	rel_to_root and report_path both fall back to get_repo_root when no root is
	given. The lru_cache on get_repo_root means the underlying subprocess runs
	once per process, not once per helper call. Proven by call count, not timing.
	"""
	# Clear the memo so this test controls the first resolution.
	file_utils.get_repo_root.cache_clear()

	calls = {"count": 0}

	def fake_check_output(args: list[str], text: bool = False) -> str:
		calls["count"] += 1
		return "/fake/repo_root\n"

	monkeypatch.setattr(file_utils.subprocess, "check_output", fake_check_output)

	# Drive many rel_to_root/report_path calls that each fall back to get_repo_root.
	for _ in range(50):
		file_utils.rel_to_root("/fake/repo_root/tests/foo.py")
		file_utils.report_path("report_foo.txt")

	# Despite 100 fallback lookups, git resolved the root exactly once.
	assert calls["count"] == 1

	# Reset the memo so other tests resolve the real repo root.
	file_utils.get_repo_root.cache_clear()


#============================================
def test_no_pattern_listing_reuses_cache_one_git_spawn(monkeypatch: pytest.MonkeyPatch) -> None:
	"""
	Repeated no-pattern list_tracked_files/discover_files reuse one git spawn.

	discover_files lists every tracked file through the no-pattern path. The
	per-repo_root cache means git ls-files spawns once for a given root, no
	matter how many hygiene modules call discover_files at collection time.
	Proven by spawn count, not timing.
	"""
	root = "/fake/caching_root"
	# Clear any prior cache entry for this root so the count starts clean.
	file_utils._ALL_TRACKED_FILES_CACHE.pop(root, None)

	spawns = {"count": 0}

	def fake_run_git(repo_root: str, args: list[str], error_message: str) -> str:
		spawns["count"] += 1
		# git ls-files -z output: NUL-separated repo-relative paths.
		return "a.py\0b.py\0"

	monkeypatch.setattr(file_utils, "_run_git", fake_run_git)

	# Many no-pattern calls against the same root: only the first spawns git.
	for _ in range(25):
		file_utils.list_tracked_files(root)

	assert spawns["count"] == 1

	# Clean up so the cached fake listing never leaks into other tests.
	file_utils._ALL_TRACKED_FILES_CACHE.pop(root, None)


#============================================
def test_pattern_scoped_listing_is_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
	"""
	Pattern-scoped list_tracked_files always spawns git and is never cached.

	The cache covers only the whole-repo no-pattern listing. A call with
	pathspecs must hit git every time, because its result depends on the
	patterns.
	"""
	root = "/fake/pattern_root"
	file_utils._ALL_TRACKED_FILES_CACHE.pop(root, None)

	spawns = {"count": 0}

	def fake_run_git(repo_root: str, args: list[str], error_message: str) -> str:
		spawns["count"] += 1
		return "match.py\0"

	monkeypatch.setattr(file_utils, "_run_git", fake_run_git)

	# Each pattern-scoped call spawns git; nothing is served from the cache.
	file_utils.list_tracked_files(root, patterns=["*.py"])
	file_utils.list_tracked_files(root, patterns=["*.py"])

	assert spawns["count"] == 2


#============================================
def test_no_pattern_cache_keyed_per_repo_root(monkeypatch: pytest.MonkeyPatch) -> None:
	"""
	The no-pattern cache is keyed by repo_root so distinct roots stay isolated.

	A tmp-root regression test must not collide with the real repo listing. Two
	different roots each spawn git once and keep independent cached listings.
	"""
	root_a = "/fake/root_a"
	root_b = "/fake/root_b"
	file_utils._ALL_TRACKED_FILES_CACHE.pop(root_a, None)
	file_utils._ALL_TRACKED_FILES_CACHE.pop(root_b, None)

	spawns = {"count": 0}

	def fake_run_git(repo_root: str, args: list[str], error_message: str) -> str:
		spawns["count"] += 1
		return "x.py\0"

	monkeypatch.setattr(file_utils, "_run_git", fake_run_git)

	# Two distinct roots each spawn once; repeats reuse their own cache entry.
	file_utils.list_tracked_files(root_a)
	file_utils.list_tracked_files(root_b)
	file_utils.list_tracked_files(root_a)
	file_utils.list_tracked_files(root_b)

	assert spawns["count"] == 2

	file_utils._ALL_TRACKED_FILES_CACHE.pop(root_a, None)
	file_utils._ALL_TRACKED_FILES_CACHE.pop(root_b, None)


#============================================
def test_cached_listing_returns_independent_copies(monkeypatch: pytest.MonkeyPatch) -> None:
	"""
	Mutating a returned listing does not corrupt the cached one.

	list_tracked_files returns a fresh copy each call so a caller that mutates
	the result leaves the cache intact for the next caller.
	"""
	root = "/fake/copy_root"
	file_utils._ALL_TRACKED_FILES_CACHE.pop(root, None)

	def fake_run_git(repo_root: str, args: list[str], error_message: str) -> str:
		return "one.py\0two.py\0"

	monkeypatch.setattr(file_utils, "_run_git", fake_run_git)

	first = file_utils.list_tracked_files(root)
	first.append("injected.py")
	second = file_utils.list_tracked_files(root)

	# The mutation to the first copy must not leak into the cached listing.
	assert "injected.py" not in second

	file_utils._ALL_TRACKED_FILES_CACHE.pop(root, None)
