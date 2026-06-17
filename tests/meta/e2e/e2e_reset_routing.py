#!/usr/bin/env python3
"""
e2e_reset_routing.py - clone-based end-to-end harness for reset_repo.py.

Drives reset_repo.py against REAL git clones of the template, one per case, and
verifies the on-disk result against the live propagation engine plus a set of
reset-specific anchor checks. Two clone modes are supported:

  - LOCAL (default): clone the local checkout (committed history only). Offline,
    fast, validates committed local state. This is the pre-commit inner loop.
  - REMOTE: clone the published github https URL. Needs network, read-only, no
    ssh. Validates origin/main, what a real consumer clones.

Mode is chosen by a command-line argument:

    source source_me.sh && python3 tests/meta/e2e/e2e_reset_routing.py          # LOCAL
    source source_me.sh && python3 tests/meta/e2e/e2e_reset_routing.py remote   # REMOTE

Because a `git clone` copies only COMMITTED history, LOCAL mode exercises the
reset_repo.py that is committed in the local checkout. If a new reset_repo.py
feature (for example --config) is only in the working tree and not yet
committed, the cloned reset will lack it and the harness reports the failure.

For each inline case the harness clones into a reused, consumer-named /tmp dir
(e.g. /tmp/reset_e2e_python, NEVER starter-repo-template, so the reset
folder-name guard passes), writes the case reset config to a short-lived json
file, runs `reset_repo.py --config <file>` inside the clone, removes the json,
then asserts:

  (a) the engine-derived propagated-file set is present on disk, and
  (b) the reset-specific anchors hold (template-meta removed, REPO_TYPE marker,
      license installed, pyproject seeded iff PyPI, stale submit_to_pypi
      cleaned, stage/commit state).

This is a tests/meta/e2e/ runner: it lives outside pytest, excluded by its
e2e_ filename prefix (pytest collects only test_*.py); tests/conftest.py also
lists meta/e2e in collect_ignore as defense in depth. It is self-contained,
uses real git in a /tmp dir, may use asserts, and exits non-zero on the
first mismatch.
Template-meta: never propagates to consumers; removed by reset.
"""

# Standard Library
import os
import sys
import glob
import json
import shutil
import subprocess

# The propagation engine is the oracle for expected propagated-file presence.
# Anchor sys.path on the local checkout (this file's repo) so repolib imports
# regardless of cwd, then import the planner and overlay-selection modules.
_LOCAL_CHECKOUT = subprocess.run(
	["git", "rev-parse", "--show-toplevel"],
	cwd=os.path.dirname(os.path.abspath(__file__)),
	capture_output=True, text=True, check=True,
).stdout.strip()
if _LOCAL_CHECKOUT not in sys.path:
	sys.path.insert(0, _LOCAL_CHECKOUT)

# local repo modules (sys.path insert above ensures these resolve to the local checkout)
import reset_repo
import repolib.files

# Clone sources, as module-level constants. LOCAL clones the local checkout
# (committed history only); REMOTE clones the published github https URL.
# _LOCAL_CHECKOUT is computed early for the sys.path insert; LOCAL_CHECKOUT
# is the public module constant that the rest of the harness references by name.
LOCAL_CHECKOUT = _LOCAL_CHECKOUT
REMOTE_URL = "https://github.com/vosslab/starter-repo-template.git"

# Reused /tmp parent for all per-case clones and ephemeral config files. Every
# clone dir under here is consumer-named so the reset folder-name guard passes.
# Deliberate /tmp literal: hook only allows rm under /tmp; tempfile.gettempdir()
# returns /var/folders on macOS which breaks that constraint.
TMP_PARENT = "/tmp"  # nosec B108

# Template-meta paths that reset MUST remove from the consumer. The harness
# asserts each is absent on disk after reset. (root tools/ is intentionally not
# checked: typed overlays may ship a consumer tools/ subpath.)
TEMPLATE_META_PATHS = [
	"repolib",
	"meta",
	"templates",
	"propagate_style_guides.py",
	"reset_repo.py",
]


#============================================
# Inline case matrix
#============================================

def case_matrix() -> list[dict]:
	"""Return the inline reset case matrix.

	Each case is a dict with a short name, the reset-config dict written to the
	ephemeral json file, and the few derived expectations the anchors read. The
	matrix covers python+PyPI, python no-PyPI, typescript, and other, and
	includes one staged/no-commit case and one commit case so both the stage and
	commit paths are exercised.

	Returns:
		list[dict]: The ordered case definitions.
	"""
	cases = [
		{
			# python + PyPI, staged but not committed.
			"name": "python_pypi",
			"config": {
				"project_type": "python",
				"code_license": "m",
				"pypi": True,
				"stage": True,
				"commit": False,
			},
		},
		{
			# python without PyPI, staged AND committed (exercises the commit path).
			"name": "python_nopypi",
			"config": {
				"project_type": "p",
				"code_license": "MIT",
				"pypi": False,
				"stage": True,
				"commit": True,
			},
		},
		{
			# typescript, staged but not committed.
			"name": "typescript",
			"config": {
				"project_type": "typescript",
				"code_license": "m",
				"stage": True,
				"commit": False,
			},
		},
		{
			# other, staged but not committed. MIT is the code license whose SPDX
			# id appears verbatim in its LICENSES/ header, which reset_repo.py's
			# copy verifier requires; other license bodies (Apache, GPL) spell out
			# the long name instead and would trip that verifier.
			"name": "other",
			"config": {
				"project_type": "o",
				"code_license": "m",
				"stage": True,
				"commit": False,
			},
		},
	]
	return cases


#============================================
# Clone helpers
#============================================

def clone_template(mode: str, dest: str) -> None:
	"""Clone the template into dest via a real git clone, then set a local identity.

	LOCAL mode clones the local checkout (committed history only); REMOTE mode
	clones the published github https URL. The dest dir is removed and recreated
	by the caller before this runs, so the clone lands in a clean directory. A
	local git user.name/user.email is set in the clone so commit cases work
	without depending on the runner's global git config.

	Args:
		mode (str): "local" or "remote".
		dest (str): Destination directory for the clone (must not yet exist).
	"""
	# Choose the clone source by mode; default to the local checkout.
	if mode == "remote":
		source = REMOTE_URL
	else:
		source = LOCAL_CHECKOUT
	# git clone refuses a non-empty existing dir; the caller cleared dest already.
	subprocess.run(
		["git", "clone", "--quiet", source, dest],
		check=True, capture_output=True, text=True,
	)
	# Set a local identity so commit cases do not depend on global git config.
	subprocess.run(
		["git", "config", "user.email", "e2e@example.com"], cwd=dest, check=True
	)
	subprocess.run(
		["git", "config", "user.name", "e2e harness"], cwd=dest, check=True
	)


def reset_clone_dir(dest: str) -> None:
	"""Remove dest if present, then recreate its parent so the clone lands clean.

	Removing + recreating at the start of each case run means a failed earlier
	run cannot poison a later one. The clone itself creates dest, so only the
	parent must exist here.

	Args:
		dest (str): Per-case clone directory path.
	"""
	# Drop any leftover clone from a previous run.
	shutil.rmtree(dest, ignore_errors=True)
	# Ensure the /tmp parent exists; the clone command creates dest itself.
	os.makedirs(os.path.dirname(dest), exist_ok=True)


#============================================
# Reset invocation
#============================================

def write_config_file(config: dict, path: str) -> None:
	"""Write a reset-config dict to a short-lived json file at path."""
	with open(path, "w") as f:
		json.dump(config, f)


def run_reset_config(clone_dir: str, config_path: str) -> subprocess.CompletedProcess:
	"""Run the cloned reset_repo.py inside clone_dir against config_path.

	The script is invoked by its path inside clone_dir so the cloned repolib
	package (next to it) is the propagation source. cwd is clone_dir so the
	script's git rev-parse resolves to the clone.

	Args:
		clone_dir (str): The clone root holding the cloned reset_repo.py.
		config_path (str): Path to the ephemeral json config file.

	Returns:
		subprocess.CompletedProcess: The completed process (not checked here so
			the caller can surface stdout/stderr on failure).
	"""
	script_path = os.path.join(clone_dir, "reset_repo.py")
	completed = subprocess.run(
		[sys.executable, script_path, "--config", config_path],
		cwd=clone_dir, capture_output=True, text=True,
	)
	return completed


def reset_must_succeed(clone_dir: str, config_path: str, label: str) -> None:
	"""Run reset and abort the harness with diagnostics if it fails."""
	completed = run_reset_config(clone_dir, config_path)
	if completed.returncode != 0:
		print(f"FAIL [{label}]: reset_repo.py exited {completed.returncode}")
		print("--- stdout ---")
		print(completed.stdout)
		print("--- stderr ---")
		print(completed.stderr)
		sys.exit(1)


#============================================
# Engine-derived oracle
#============================================

def expected_propagated_paths(repo_type: str, clone_dir: str) -> list[str]:
	"""Return the repo-root-relative paths the engine says should ship to clone_dir.

	Computes the propagation plan from the local checkout (which still holds the
	templates/ overlays) as the source, but passes repo_dir=clone_dir so
	conditional-overlay selection sees the clone's on-disk markers (for example
	pyproject.toml selecting python/_pypi). The plan's buckets are mapped to
	consumer destination paths via target_path_for_bucket semantics:

	  - overwrite_files, noexist_files, merge_files: repo-root-relative as-is.
	  - devel_files: bare names, landing at devel/<name>.
	  - test_files: already carry the tests/ prefix.

	The gitignore_block bucket is not a file list and is excluded.

	Args:
		repo_type (str): Consumer repo type (python, typescript, rust, other).
		clone_dir (str): The clone whose markers drive overlay selection.

	Returns:
		list[str]: Sorted, de-duplicated repo-root-relative consumer paths.
	"""
	plan = repolib.files.compute_propagation_plan(
		LOCAL_CHECKOUT, repo_type, repo_dir=clone_dir
	)
	consumer_paths: set[str] = set()
	# Plain repo-root-relative buckets ship at their own path.
	for bucket in ("overwrite_files", "noexist_files", "merge_files"):
		for rel_path in plan[bucket]:
			consumer_paths.add(rel_path)
	# devel_files are bare names landing under devel/.
	for bare_name in plan["devel_files"]:
		consumer_paths.add(os.path.join("devel", bare_name))
	# test_files already carry the tests/ prefix.
	for rel_path in plan["test_files"]:
		consumer_paths.add(rel_path)
	return sorted(consumer_paths)


def assert_propagated_present(clone_dir: str, repo_type: str, label: str) -> None:
	"""Assert every engine-expected propagated file exists on disk after reset."""
	expected = expected_propagated_paths(repo_type, clone_dir)
	missing: list[str] = []
	for rel_path in expected:
		full_path = os.path.join(clone_dir, rel_path)
		if not os.path.isfile(full_path):
			missing.append(rel_path)
	if missing:
		print(f"FAIL [{label}]: engine-expected propagated files missing on disk:")
		for rel_path in missing:
			print(f"    {rel_path}")
		sys.exit(1)
	print(f"  PASS [{label}]: all {len(expected)} engine-expected propagated files present")


#============================================
# Reset-specific anchor checks
#============================================

def assert_template_meta_removed(clone_dir: str, label: str) -> None:
	"""Assert every template-meta path is absent on disk after reset."""
	leftovers: list[str] = []
	for rel_path in TEMPLATE_META_PATHS:
		full_path = os.path.join(clone_dir, rel_path)
		if os.path.exists(full_path):
			leftovers.append(rel_path)
	if leftovers:
		print(f"FAIL [{label}]: template-meta paths remain after reset:")
		for rel_path in leftovers:
			print(f"    {rel_path}")
		sys.exit(1)
	print(f"  PASS [{label}]: template-meta paths removed ({', '.join(TEMPLATE_META_PATHS)})")


def assert_marker(clone_dir: str, expected_type: str, label: str) -> None:
	"""Assert the REPO_TYPE marker holds the expected token after reset."""
	marker_path = os.path.join(clone_dir, "REPO_TYPE")
	if not os.path.isfile(marker_path):
		print(f"FAIL [{label}]: REPO_TYPE marker missing")
		sys.exit(1)
	with open(marker_path, "r") as f:
		token = f.read().strip()
	if token != expected_type:
		print(f"FAIL [{label}]: REPO_TYPE is {token!r}, expected {expected_type!r}")
		sys.exit(1)
	print(f"  PASS [{label}]: REPO_TYPE marker is {token!r}")


def assert_license(clone_dir: str, code_license: str, label: str) -> None:
	"""Assert the installed code-license file exists at the clone root."""
	license_path = os.path.join(clone_dir, f"LICENSE.{code_license}.md")
	if not os.path.isfile(license_path):
		print(f"FAIL [{label}]: code license file missing: LICENSE.{code_license}.md")
		sys.exit(1)
	print(f"  PASS [{label}]: code license installed (LICENSE.{code_license}.md)")


def assert_pyproject(clone_dir: str, pypi: bool, label: str) -> None:
	"""Assert pyproject.toml is present iff the case is a PyPI python case."""
	pyproject_path = os.path.join(clone_dir, "pyproject.toml")
	present = os.path.isfile(pyproject_path)
	if present != pypi:
		state = "present" if present else "absent"
		want = "present" if pypi else "absent"
		print(f"FAIL [{label}]: pyproject.toml is {state}, expected {want}")
		sys.exit(1)
	state = "present" if present else "absent"
	print(f"  PASS [{label}]: pyproject.toml {state} (pypi={pypi})")


def assert_submit_to_pypi(clone_dir: str, pypi: bool, label: str) -> None:
	"""Assert devel/submit_to_pypi.py is present iff the _pypi overlay applies."""
	submit_path = os.path.join(clone_dir, "devel", "submit_to_pypi.py")
	present = os.path.isfile(submit_path)
	if present != pypi:
		state = "present" if present else "absent"
		want = "present" if pypi else "absent"
		print(f"FAIL [{label}]: devel/submit_to_pypi.py is {state}, expected {want}")
		sys.exit(1)
	state = "present" if present else "absent"
	print(f"  PASS [{label}]: devel/submit_to_pypi.py {state} (pypi={pypi})")


def reset_commit_present(clone_dir: str) -> bool:
	"""Return True when the clone's HEAD commit is the reset-generated commit.

	The reset commit message starts with 'initial commit: reset repo to base
	template'. The subject of the current HEAD is read via git log; an empty or
	non-matching subject means reset did not create the commit.

	Args:
		clone_dir (str): The clone root.

	Returns:
		bool: True when HEAD is the reset commit.
	"""
	result = subprocess.run(
		["git", "log", "-1", "--pretty=%s"],
		cwd=clone_dir, capture_output=True, text=True, check=True,
	)
	subject = result.stdout.strip()
	return subject.startswith("initial commit: reset repo to base template")


def assert_commit_state(clone_dir: str, commit: bool, label: str) -> None:
	"""Assert the reset commit is present iff the case requested a commit."""
	present = reset_commit_present(clone_dir)
	if present != commit:
		state = "present" if present else "absent"
		want = "present" if commit else "absent"
		print(f"FAIL [{label}]: reset commit is {state}, expected {want}")
		sys.exit(1)
	state = "present" if present else "absent"
	print(f"  PASS [{label}]: reset commit {state} (commit={commit})")


def assert_no_changelog_archives(clone_dir: str, label: str) -> None:
	"""Assert no docs/CHANGELOG-*.md rotation archive remains in the clone after reset.

	Rotation archives are template-meta: they record the template's own changelog
	history and must be git-rm'd during reset. The active docs/CHANGELOG.md may still
	exist (truncated) but dated archives matching the META_FILE_PATTERNS glob must all
	be absent.

	Args:
		clone_dir (str): The clone root to inspect.
		label (str): Case label for output messages.
	"""
	# Match the same pattern as META_FILE_PATTERNS: docs/CHANGELOG-*.md
	archive_pattern = os.path.join(clone_dir, 'docs', 'CHANGELOG-*.md')
	found_archives = sorted(glob.glob(archive_pattern))
	if found_archives:
		print(f"FAIL [{label}]: changelog rotation archives remain after reset:")
		for archive in found_archives:
			print(f"    {os.path.relpath(archive, clone_dir)}")
		sys.exit(1)
	# Verify the active changelog is still present (truncated/empty is fine).
	active_changelog = os.path.join(clone_dir, 'docs', 'CHANGELOG.md')
	if not os.path.isfile(active_changelog):
		print(f"FAIL [{label}]: docs/CHANGELOG.md missing after reset (should be truncated, not removed)")
		sys.exit(1)
	print(f"  PASS [{label}]: no changelog archives remain, docs/CHANGELOG.md present")


def assert_stage_state(clone_dir: str, stage: bool, commit: bool, label: str) -> None:
	"""Assert the index has staged changes when stage is requested without commit.

	When stage is True and commit is False, reset runs `git add -A`, so the index
	must differ from HEAD (staged changes pending). When commit is True the staged
	changes were swept into the reset commit, so this staged-diff check is skipped
	(assert_commit_state covers that path). The check uses `git diff --cached
	--quiet`, which exits non-zero when staged changes exist.

	Args:
		clone_dir (str): The clone root.
		stage (bool): Whether the case requested staging.
		commit (bool): Whether the case requested a commit.
		label (str): Case label for output.
	"""
	# A commit consumes the staged changes, so only check the staged-but-not-committed path.
	if commit or not stage:
		return
	# `git diff --cached --quiet` exits 1 when staged changes are present.
	result = subprocess.run(
		["git", "diff", "--cached", "--quiet"],
		cwd=clone_dir, capture_output=True, text=True,
	)
	if result.returncode == 0:
		print(f"FAIL [{label}]: stage=True requested but the index has no staged changes")
		sys.exit(1)
	print(f"  PASS [{label}]: staged changes present in the index (stage=True, commit=False)")


#============================================
# Per-case driver
#============================================

def run_case(mode: str, case: dict) -> None:
	"""Clone, reset, and verify one case end to end."""
	name = case["name"]
	config = case["config"]
	label = f"{mode}/{name}"
	print(f"\n=== case {label} ===")

	# Consumer-named clone dir (never starter-repo-template) so the guard passes.
	clone_dir = os.path.join(TMP_PARENT, f"reset_e2e_{name}")
	config_path = os.path.join(TMP_PARENT, f"reset_e2e_{name}.json")

	# Remove + recreate so a failed earlier run cannot poison this one.
	reset_clone_dir(clone_dir)
	clone_template(mode, clone_dir)

	# Write the ephemeral config, run reset, then remove the config file.
	write_config_file(config, config_path)
	try:
		reset_must_succeed(clone_dir, config_path, label)
	finally:
		# The short-lived config file is always removed, even on failure exit.
		if os.path.isfile(config_path):
			os.remove(config_path)

	# Derive the expectations the anchors read from the case config.
	repo_type = normalize_case_type(config["project_type"])
	pypi = case_pypi(config, repo_type)
	code_license = resolve_case_code_license(config["code_license"])
	stage = config.get("stage", True)
	commit = config.get("commit", False)

	# (c) engine-derived propagated-file presence.
	assert_propagated_present(clone_dir, repo_type, label)
	# (d) reset-specific anchors.
	assert_template_meta_removed(clone_dir, label)
	assert_no_changelog_archives(clone_dir, label)
	assert_marker(clone_dir, repo_type, label)
	assert_license(clone_dir, code_license, label)
	assert_pyproject(clone_dir, pypi, label)
	assert_submit_to_pypi(clone_dir, pypi, label)
	assert_stage_state(clone_dir, stage, commit, label)
	assert_commit_state(clone_dir, commit, label)


#============================================
# Config-value normalization (mirrors reset_repo.py accepted values)
#============================================

def normalize_case_type(raw: str) -> str:
	"""Map a case project_type token to its canonical form for oracle/anchors.

	Delegates to reset_repo.normalize_project_type so the harness and the script
	share a single mapping that cannot drift.

	Args:
		raw (str): The case project_type value (e.g. 'p' or 'python').

	Returns:
		str: One of python, typescript, rust, other.
	"""
	return reset_repo.normalize_project_type(raw, "python")


def case_pypi(config: dict, repo_type: str) -> bool:
	"""Return the effective pypi flag for a case (only python repos can be PyPI)."""
	# Non-python repos never seed pyproject, mirroring reset_repo.py.
	if repo_type != "python":
		return False
	return bool(config.get("pypi", False))


def resolve_case_code_license(raw: str) -> str:
	"""Resolve a case code_license token to its SPDX id via reset_repo.py rules.

	Imports reset_repo.py from the local checkout so the harness uses the exact
	same alias/prefix resolution reset applies, keeping the license anchor honest.

	Args:
		raw (str): The case code_license value (e.g. 'm' or 'MIT').

	Returns:
		str: The resolved SPDX license id (e.g. 'MIT').
	"""
	return reset_repo.resolve_license(
		raw, reset_repo.CODE_LICENSES, reset_repo.CODE_ALIASES, default=None
	)


#============================================
# Main
#============================================

def select_mode(argv: list[str]) -> str:
	"""Return the clone mode from argv: 'remote' when argv[1] == 'remote', else 'local'."""
	if len(argv) > 1 and argv[1] == "remote":
		return "remote"
	return "local"


def main() -> None:
	"""Run every case in the case matrix and print a PASS summary on success."""
	mode = select_mode(sys.argv)
	print(f"clone mode:     {mode}")
	if mode == "remote":
		print(f"clone source:   {REMOTE_URL}")
	else:
		print(f"clone source:   {LOCAL_CHECKOUT}")

	for case in case_matrix():
		run_case(mode, case)

	print("\n=== SUMMARY ===")
	print("PASS: all reset clone cases succeeded.")


if __name__ == "__main__":
	main()
