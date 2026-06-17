## 2026-06-16

### Additions and New Features

- Added `swift` as a recognized `REPO_TYPE` token (`meta/propagation/manifests.yaml`
  `known_repo_types`, `repolib/model.py` `LANG_SWIFT` / `REPO_TYPE_ORDER` / `KNOWN_REPO_TYPES`).
  `swift` currently ships universal files only (no `templates/swift/` overlay); future swift files
  are added by folder location with no code change. `meta/propagation/manifests.yaml` is now the
  single ordered source of truth for the consumer token set; `reset_repo.py` and the propagate
  prompt offer swift as a selectable type (`[s]wift`); `tools/detect_repo_type.py` recognizes
  `Package.swift` (high confidence) and `.swift` file counts.

### Behavior or Interface Changes

- `repolib/repo.py` `read_repo_type`: unrecognized tokens in `REPO_TYPE` or legacy
  `STARTER_REPO_TYPE` now log a warning (`repo=<name> REPO_TYPE token '<tok>' not recognized;
  treating as other`) and return `other` instead of raising `ValueError`. Previously
  `propagate_style_guides.py -R ../swift-usb-imager` aborted the entire run on the first
  unrecognized marker; the new fallback lets batch propagation continue past a single bad marker.

- `templates/typescript/tools/sync_typescript_package_pins.py`: `fetch_latest_versions` now prints
  live `[index/total] pkg: version` progress as each `npm view` round-trip resolves (or a
  `[index/total] skip (not on registry)` line), flushed per line. Previously the script printed
  nothing during the query phase and dumped all resolved versions only after every package
  finished, so a 343-package sweep looked hung. The redundant post-loop print in `main()` was
  removed.

### Fixes and Maintenance

- `repolib/repo.py` `read_repo_type`: fixed an `UnboundLocalError: cannot access local variable
  'repolib'` that crashed `propagate_style_guides.py -R <repo>` on the predict-and-write-marker
  path. The function-scoped `import repolib.model` bound the package name `repolib` as a
  function-local for the whole scope, so earlier `repolib.console.*` references (the
  high-confidence "auto-wrote marker" log line, and the legacy-marker warn line) raised
  `UnboundLocalError`. Hoisted the lazy `import repolib.model` to the top of the function body so
  `repolib` is bound before any use; removed the now-redundant second inline import in the batch
  path. The import stays function-scoped, so the model/repo import cycle remains broken. Latent
  because every previously-processed repo already had a `REPO_TYPE` marker, which takes the early
  file-read return that never touches `repolib`; the crash only fires on `-R` single-repo mode
  with a missing marker plus high-confidence detection.

- `templates/typescript/tools/sync_typescript_package_pins.py`: stop crashing on private or
  workspace-local packages that are not published to the npm registry. `npm view <pkg>` returns
  `E404` for such packages (e.g. `@kobalte/tests`); the script previously raised `RuntimeError`
  on the first one and aborted the whole sweep. Now `fetch_latest_version` returns `None` on
  `E404` and `fetch_latest_versions` omits it from the version map, routing it through the
  existing unmanaged-extras path: a `skip (not on registry)` line during the query phase and the
  existing `WARN consumer-extra (unmanaged)` line in the per-target diff. The pin is left
  untouched; never auto-bumped against the public registry. Non-404 npm failures (network, auth)
  still raise. The `main()` resolved-version print loop now guards `pkg in latest` so skipped
  packages do not `KeyError`.

## 2026-06-15

### Additions and New Features

- Added `meta_file_patterns` to `meta/propagation/manifests.yaml` (seeded with `docs/CHANGELOG-*.md`):
  a glob-pattern manifest for template-meta files that NEVER ship, sitting beside `meta_files`.
  Loaded as a frozenset via `repolib/manifests.py` (`SET_MANIFEST_KEYS`) and exposed as
  `repolib.model.META_FILE_PATTERNS`. Closes the gap where rotation-archive changelogs
  (`docs/CHANGELOG-YYYY-MM[a-z].md`) shipped universally because only the active
  `docs/CHANGELOG.md` was an exact `meta_files` entry.
- Added `repolib.files.is_meta_file(file_rel)`: the single source of truth for the template-meta
  check (exact `META_FILES` match by rel-path OR basename, plus `META_FILE_PATTERNS` globs).

- Added `tests/meta/e2e/run_all.sh`: offline runner that iterates over every `e2e_*` script under
  `tests/meta/e2e/` and reports pass/fail for each. Runs LOCAL mode only; does not invoke REMOTE.
- Added `tests/meta/test_reset_config.py`: fast offline pytest coverage for `reset_repo.py`
  config parsing and the folder-name guard. Covers required-key validation, alias normalization
  (short tokens for project_type and code_license), optional-key defaults, and the
  `starter-repo-template` basename rejection.
- WP9 (`templates/python/_pypi/` overlay): moved `submit_to_pypi.py` from `devel/` into
  `templates/python/_pypi/devel/` via `git mv` so the file location gates whether it ships to
  consumer repos. Added a minimal `templates/python/_pypi/noexist/pyproject.toml` stub
  (`[project]` table with `name = "PROJECT_NAME"` and CalVer `version = "26.06"`) that the
  reset interview will later use to seed the marker file.
- WP14 (`reset_repo.py`): added the PyPI reset interview. After a python type is chosen, the
  interactive interview asks `Will this Python project be published as a pypi package? [y/N]:`
  (default no). On yes, a new seed phase runs strictly before propagation: `seed_pyproject()`
  copies `templates/python/_pypi/noexist/pyproject.toml` to the repo root when absent and writes
  a synced `VERSION` file holding the same `[project] version` string (read from the stub). This
  makes `repolib.model.select_overlay_dirs` include `python/_pypi`, so `submit_to_pypi.py` ships
  in the same reset. `--dry-run` logs the seed without writing. CLI exposes only
  `-h/--dry-run/--config`; all choices (type, licenses, PyPI, stage, commit) are handled
  by the interactive interview or the JSON config file.
- WP10 (`meta/propagation/manifests.yaml`): added the single source of propagation config as a
  template-meta YAML data file (never ships). It holds every propagation manifest that
  `repolib/model.py` previously defined as a Python literal: `routing_overrides`,
  `conditional_overlays`, and the set/sequence manifests (`root_propagate_allowlist`,
  `universal_noexist`, `merge_files`, `meta_files`, `meta_dirs`, `skip_walk_dirs`,
  `auto_discover_docs_exclude`, `meta_test_prefixes`, `default_repo_skip_names`). Values match the
  prior literals exactly.
- WP11 (`repolib/manifests.py`): added `load_manifests(template_root)`, which reads
  `meta/propagation/manifests.yaml` with `yaml.safe_load` and returns the same Python types
  `model.py` exposed (set manifests as `frozenset`, `meta_test_prefixes` as a tuple,
  `routing_overrides` as a dict with `frozenset` `exclude_repos`, `conditional_overlays` as the
  nested dict). A missing file or non-mapping YAML raises loudly (no empty fallback).
- WP18 (`meta/docs/HUMAN_GUIDANCE.md`): expanded the single-line stub into a full durable
  guidance file covering location-primary routing, `ROUTING_OVERRIDES` holds only `exclude_repos`,
  `_folder` conditional overlay convention, `meta/propagation/manifests.yaml` as single source of
  truth, `reset_repo.py` interactive-first design, test-follows-live-config pattern, and the
  prefer-rule-based-over-per-file preference. Linked from `meta/docs/PROPAGATION_RULES.md`
  (meta-to-meta link; `AGENTS.md` does not link to `meta/` because that path does not exist in
  consumer repos).

### Behavior or Interface Changes

- `reset_repo.py` `confirm_plan` summary now prints the resolved `pypi:` choice
  alongside type/code/docs/stage/commit/mode, so an interactive user sees the one
  reset decision that controls whether `pyproject.toml` is seeded and the
  `_pypi` overlay applies before confirming.
- `tests/` propagation routing changed from an enumerated allowlist to a denylist in
  `repolib/files.py`. The universal walk now ships every non-meta `tests/` file by location;
  it skips only dotfiles, `_`-prefixed scratch files, `conftest.py` (still owned by
  `merge_conftest`, not bucket-routed), and `META_TEST_PREFIXES`. A non-`test_`-prefixed
  helper such as `tests/helper_thing.py` now ships, where the old allowlist would have
  dropped it.
- `reset_repo.py` gained `--config <file>`: a JSON answer file drives a non-interactive reset.
  Required keys: `project_type` (python/typescript/rust/other, short alias accepted) and
  `code_license` (SPDX or alias). Optional keys with defaults: `docs_license` (CC-BY-4.0),
  `pypi` (false, python-only), `stage` (true), `commit` (false). Config mode is the
  testing/reproducibility interface; interactive interview remains the human default.
- `reset_repo.py` CLI shrank to `--config`, `--dry-run`, and `-h`. Removed `--force`
  (confirmed no use by the human user) and `--yes` (non-interactive path now uses `--config`).
- `reset_repo.py` folder-name guard: refuses to run when the repo root basename is exactly
  `starter-repo-template`. Protects the template development checkout from accidental
  destruction. Guard is folder-name only; no remote or origin inspection.
- `reset_repo.py` now exits with a clear message when run outside a git repository instead of
  emitting a raw subprocess traceback.
- `tests/meta/e2e/e2e_reset_routing.py` reworked: uses `git clone` into consumer-named `/tmp` dirs
  instead of driving the interactive interview via stdin. Two modes: LOCAL (default, offline,
  clones committed history only) and REMOTE (GitHub HTTPS, opt-in via `remote` argument,
  GitHub HTTPS clone read-only). Per-case ephemeral JSON config; verified against the live
  propagation engine plus reset-specific anchor checks.
- WP14 (`reset_repo.py`): the keep/remove decision for `devel/submit_to_pypi.py` now derives from
  `repolib.model.select_overlay_dirs(project_type, repo_root)` (the same overlay-selection rule the
  propagator uses) instead of the old `project_type != "python"` check. A python repo without a
  `pyproject.toml` now correctly drops the tool, which the old check missed. The next-step hint now
  lists the dependency files actually present per type: python lists both `pip_requirements.txt`
  and the universal `pip_requirements-dev.txt`; typescript, rust, and other types now also list the
  universal `pip_requirements-dev.txt`.
- WP17 (propagation routing): file location is now the primary routing determinant. `docs/PYTHON_STYLE.md`
  ships universally to all repo types (previously restricted to python repos by a `language` gate in
  `ROUTING_OVERRIDES`). `devel/submit_to_pypi.py` ships via the `_pypi` conditional overlay
  (previously gated by `language + requires_repo_file` in `ROUTING_OVERRIDES`).
  `pip_requirements-dev.txt` ships universally (root allowlist + universal noexist).
- `devel/DEVEL_README.md`: shortened the folder README from script-help-style function
  inventories into a quick summary of what belongs in `devel/`, with a compact current-script
  table and a note that type-specific developer helpers live under `templates/<type>/devel/`.
- `devel/flatten_broken_md_links.py`: added `-i`/`--input` file mode (`nargs='+'`) and
  `-n`/`--dry-run`. Accepts one or more paths or glob patterns; patterns are expanded in
  Python via `glob.glob`, so quoted globs work even when the shell does not expand them
  (for example `-i 'devel/*.md'`). In this mode `--apply` is the default (writes the files);
  pass `--dry-run` to preview only. Directory mode is unchanged: dry-run by default, `--apply`
  to write. Extracted the per-file loop and summary printer into a shared `run_files()` helper
  used by both modes.

### Fixes and Maintenance

- `reset_repo.py` git calls now resolve against the resolved `repo_root` instead
  of the launch directory. `git_rm`/`git_rm_recursive` gained a `repo_root`
  parameter and pass `cwd=repo_root`; the meta-dir-walk `git ls-files` and the
  `git add -A`/`git commit`/`git status --short` calls also pass `cwd=repo_root`,
  matching the existing `templates/` and `tools/` calls. File-copy ops already
  used absolute `repo_root` paths; this removes the prior inconsistency where a
  reset launched from a subdirectory would copy files correctly but fail the
  `git rm` cleanup pathspecs.
- `reset_repo.py` typescript `package.json` version substitution now zero-pads the
  month (`f"{now.year}.{now.month:02d}.0"`, e.g. `2026.06.0`) to match the
  zero-padded CalVer convention in `docs/REPO_STYLE.md`.
- `reset_repo.py` license-copy-failure rollback hint now names the offending file
  with per-file `git restore --staged <file>` / `git restore <file>` wording,
  replacing the wholesale `git restore .` form that the permissions hook blocks.
- Moved reset E2E harness (`tests/e2e/e2e_reset_routing.py`) and its runner
  (`tests/e2e/run_all.sh`) to `tests/meta/e2e/` via `git mv`. The harness tests
  the propagation/reset engine that is removed at consumers and must therefore be
  template-meta. `tests/meta/` is already in `reset_repo.py` `TEMPLATE_OWNED_PREFIXES`
  so these files are now scrubbed by reset and never propagate. Updated
  `docs/E2E_TESTS.md`, `meta/docs/HUMAN_GUIDANCE.md`, and the run-path comment in
  both moved files to reflect the new location.

- Propagation no longer ships changelog rotation archives. Refactored the four duplicated
  meta-check sites in `repolib/files.py` (`assert_not_meta_file`, the universal walk, the
  typed-overlay walk, and the typed-overlay noexist `consumer_path` check) to call the new
  `is_meta_file` helper, which adds `META_FILE_PATTERNS` glob matching on top of the existing
  exact `META_FILES` behavior. Behavior is identical for prior exact-match cases.
- `reset_repo.py` now scrubs changelog archives from a clone: a cleanup step iterates
  `repolib.model.META_FILE_PATTERNS`, globs each pattern under the repo root, and `git rm`s every
  match (respecting `--dry-run`). The patterns are read before `repolib/` is removed. The active
  `docs/CHANGELOG.md` is still truncated.
- Doc-accuracy audit: corrected four stale claims across `README.md`, `docs/USAGE.md`,
  `docs/E2E_TESTS.md`, and `docs/CHANGELOG.md`.
  - `README.md` line 29: replaced removed `--yes` / `--force` flag descriptions with the real
    CLI: `--dry-run` prints planned actions without writing; `--config <file>` runs
    non-interactively from a JSON answer file.
  - `docs/USAGE.md` schema table: replaced fabricated aliases `GPLv3` / `gpl3` (invalid; the
    prefix resolver requires the dash, e.g. `gpl-3.0` not `gpl3`) with real aliases `GPL-3.0`
    and `g`; changed the minimal JSON example from `"GPLv3"` to `"GPL-3.0"`.
  - `docs/E2E_TESTS.md` REMOTE-mode table cell: changed "validates origin/main after push"
    (implied a push) to "GitHub HTTPS clone (read-only); exercises what a consumer receives
    from origin/main", matching the prose notes already corrected previously.
  - `docs/CHANGELOG.md` three bullets in the 2026-06-15 day block that stated reset CLI as
    `-h/--dry-run/--yes/--force`: corrected to `-h/--dry-run/--config` in all three places.

- Rotated `docs/CHANGELOG.md` (exceeded 1000 lines); older day blocks moved to
  [docs/CHANGELOG-2026-06a.md](CHANGELOG-2026-06a.md) (dates 2026-06-11 through 2026-02-14).
- WP11 (`repolib/model.py`): removed the inline manifest literals and now loads them once at
  import from `meta/propagation/manifests.yaml` via `repolib.manifests.load_manifests`, assigning
  the same module-level public names (`ROUTING_OVERRIDES`, `CONDITIONAL_OVERLAYS`,
  `ROOT_PROPAGATE_ALLOWLIST`, `UNIVERSAL_NOEXIST`, `MERGE_FILES`, `META_FILES`, `META_DIRS`,
  `SKIP_WALK_DIRS`, `AUTO_DISCOVER_DOCS_EXCLUDE`, `META_TEST_PREFIXES`, `DEFAULT_REPO_SKIP_NAMES`)
  so existing importers and `dir()` keep working. `LANG_*` constants, `PropagateContext`, and the
  path-resolution helpers are unchanged.
- `repolib/repo.py`: moved its `import repolib.model` from module top into `read_repo_type` (the
  only caller) to break a `repolib.model` <-> `repolib.repo` import cycle. `model.py` resolves the
  template root via `repolib.repo.resolve_source_dir` at import; the top-level import left
  `resolve_source_dir` undefined when `repolib.repo` was imported first. Deferring both imports
  fixes every import order.
- Root `pip_requirements.txt`: added `pyyaml` because the propagation engine now imports `yaml`.
  This root manifest is template-meta and does not propagate; the empty consumer seed at
  `templates/python/noexist/pip_requirements.txt` stays empty.
- WP17 (`repolib/repo.py`): fixed stale comments at lines 25-26 and 114-116 that said
  `LANG_UNKNOWN gates language-specific file routing via should_ship_override`. The accurate
  statement is that `LANG_UNKNOWN` means no `ROUTING_OVERRIDES` `exclude_repos` rule applies;
  universal walker-routed files still ship. Comment-only change; no code or logic altered.
- WP17 (`docs/REPO_STYLE.md`): updated the `## Project type marker` paragraph. Replaced the
  stale claim that `other`-typed repos do not receive `docs/PYTHON_STYLE.md` (that exception was
  removed). Stated that `docs/PYTHON_STYLE.md` is now a universal doc shipping to all repo types.
  Added location-primary routing summary, `ROUTING_OVERRIDES` holds only `exclude_repos`, and a
  pointer to `meta/docs/PROPAGATION_RULES.md` for the `_folder` conditional overlay convention.
- WP17 (`meta/docs/PROPAGATION_RULES.md`): updated to the location-primary model. Added the
  `_folder` / conditional overlay section with the `_pypi` YAML example. Updated the Hardcoding
  principles section to point at `meta/propagation/manifests.yaml` as the manifest home. Updated
  the Exceptions section (`ROUTING_OVERRIDES` now holds only `exclude_repos`; removed `language`,
  `requires_repo_file`, and `bucket` field documentation). Updated the Routing override gates
  section accordingly. Updated Examples to show `docs/PYTHON_STYLE.md` as universal and
  `devel/submit_to_pypi.py` via `_pypi` overlay. Removed the stale `ROUTING_OVERRIDES` python-only
  language gate example.
- `README.md`: removed the Markdown link to `meta/docs/PROPAGATION_RULES.md` from the Template
  layout section. That path never ships to consumer repos, so the link 404s there. Inlined the
  key fact (manifests live in `meta/propagation/manifests.yaml`) as prose.
- `docs/CHANGELOG.md`: corrected the WP14 Additions bullet to state the final CLI flag set
  positively (`-h/--dry-run/--config` only; all choices handled by the interactive interview
  or the JSON config file) instead of listing removed flags.
- `repolib/model.py` `find_source_for_bucket`: fixed devel-bucket source resolution to search
  typed/overlay roots before the universal root, mirroring overwrite-bucket precedence. A
  consumer-modified `devel/submit_to_pypi.py` is now correctly refreshed from
  `templates/python/_pypi/` during a single-repo reset instead of resolving to the consumer's
  own stale file.
- `reset_repo.py`: the PyPI=no cleanup of `devel/submit_to_pypi.py` now uses a forced removal so
  a just-refreshed working-tree copy is reliably removed when the `_pypi` overlay does not apply.
- Docs: removed the shipped-markdown link from `README.md` that pointed to
  `meta/docs/PROPAGATION_RULES.md`; shipped markdown no longer links to local meta files so
  consumer links stay valid. Corrected a CHANGELOG WP-era bullet that described removed reset
  flags; reset CLI is interactive-first with only `-h/--dry-run/--config`.
- Cleanup: removed the unused `LANG_UNIVERSAL` constant; fixed a stale "five-bucket" docstring
  (now six) in `repolib/files.py`; tightened the manifest-loader override schema test to assert
  `frozenset`; added missing import-section headings, function separators, and a `parse_args`
  docstring; corrected a `parse_repo_type_choice` type hint.

### Removals and Deprecations

- `reset_repo.py` `--force` flag removed; the human user confirmed it has no use.
- `reset_repo.py` `--yes` flag removed; config mode (`--config`) is the non-interactive path.
- Removed the redundant empty root `pip_requirements.txt`. The propagation manifest seed for
  python consumers is `templates/python/noexist/pip_requirements.txt`; the template's `pyyaml`
  tooling dependency is declared in the template-only `pip_requirements-meta.txt`.
- WP17 (`ROUTING_OVERRIDES`): removed `language`, `requires_repo_file`, and `bucket` fields from
  `ROUTING_OVERRIDES` in `meta/propagation/manifests.yaml`. These per-file gates are replaced by
  location-based routing: typed overlay folders (`templates/<type>/`) handle language specificity
  and `_folder` conditional overlays (with `has_file` rules) handle `requires_repo_file` cases.
  The `bucket` shorthand is no longer needed because location already determines noexist/overwrite
  classification. `ROUTING_OVERRIDES` now holds only `exclude_repos` exceptions.

### Decisions and Failures

- Removed the over-engineered `tests/` allowlist: per docs/REPO_STYLE.md location is the primary
  routing determinant. An audit showed the enumerated allowlist
  (`test_*`/`check_*`/`fix_*`/`file_utils.py`/`TESTS_README.md`) excluded only one tracked
  `tests/` file in practice -- `conftest.py` -- which is already handled by `merge_conftest`. The
  denylist replaces the enumeration with three code-level skips (dotfiles, `_`-scratch,
  `conftest.py`) plus the existing `META_TEST_PREFIXES`. `conftest.py` stays merge-owned and is
  deliberately NOT routed to `noexist`.
- Config format is JSON (stdlib `json`, no extra deps): chosen because config files are
  short-lived machine fixtures generated per test case, not human-authored YAML. JSON also avoids
  adding a `pyyaml` dependency at the `reset_repo.py` level.
- Guard uses folder name only (no remote or origin slug inspection): remote-slug detection was
  rejected as fragile -- a cloned consumer repo may temporarily keep the template remote before
  renaming. Folder name is deterministic and sufficient.
- `--force` removal confirmed by the human user: the flag had no use case that config mode does
  not already cover.

## 2026-06-12

### Additions and New Features

- Added `file_utils.clear_stale_reports() -> None` (WP0b): deletes all `report_*.txt` files at
  the repo root; guarded once per process via a module-level flag so multiple hygiene modules
  in the same session each invoke it but only the first does filesystem work. Replaces the
  per-module `purge_report` call that previously ran before every fixture, which caused
  stale-report races when modules ran in parallel.
- Added `file_utils.collect_file_violations`, `collect_python_violations`,
  `format_violation_report`, `format_violation_assert_message`, `write_report_lines`, and
  `rel_id` to the shared harness (WP1): canonical helpers for the precompute-fixture pattern.
  `collect_python_violations` parses each `.py` file once into an AST and records `SyntaxError`
  entries for unparseable files; `collect_file_violations` delegates parsing to the checker.
  `format_violation_assert_message` is evaluated only on failure so passing cases pay no cost.
  `rel_id` wraps `rel_to_root` for direct use as `ids=file_utils.rel_id` in parametrize.

### Behavior or Interface Changes

- `templates/typescript/tools/sync_typescript_package_pins.py`: flipped the default mode to
  apply (write changes back). `-a`/`--apply` now sets `dry_run=False` (still accepted, redundant
  with the new default); added `-n`/`--dry-run` to preview the per-target diff and write nothing.
  Default ships to typescript consumer repos as a write-by-default pin bump.
- `sync_typescript_package_pins.py`: broadened scope from `devDependencies` only to both
  `dependencies` and `devDependencies` (new `DEP_SECTIONS` constant). The diff now groups bumps
  under per-section `[dependencies]` / `[devDependencies]` headers, and `collect_devdep_keys` was
  renamed to `collect_dep_keys`. The tool still rewrites `package.json` only; after an apply run
  it prints the follow-up `npm install` (lockfile regen) and `npm audit` commands rather than
  editing `package-lock.json` or `node_modules`, which npm owns.
- Migrated 11 plan hygiene modules (WP1 + WP2) plus `tests/test_init_files.py` (finished as
  obvious follow-on) to the shared harness: autouse module-scope `collect_report` fixture,
  `VIOLATIONS_BY_FILE: dict[str, list[str]]` precomputed once, `write_report_lines` called only
  when violations exist, `clear_stale_reports` as fixture first line. Per-file parametrized tests
  use plain `assert rel not in VIOLATIONS_BY_FILE`. No `raise AssertionError` or `pytest.fail(`
  in any migrated hygiene module. `tests/test_whitespace.py` initially stayed on the legacy
  per-file raise pattern but was subsequently migrated in this same change set (see bullet below).
- Migrated `tests/test_whitespace.py` to the canonical hygiene harness as a user-approved
  follow-on: `collect_file_violations`, module-level `VIOLATIONS_BY_FILE`, autouse
  `collect_report` fixture (the `fix_whitespace.py` auto-fix pass moved from per-test to
  fixture-level, still gated on `--no_ascii_fix`), `rel_id` parametrize ids, standard
  `format_violation_assert_message` asserts, and a new `report_whitespace.txt` report on
  violations.
- Report file formats normalized to a single header line per violation: legacy second-level
  subheaders (`Violations:` in import_dot/import_star/import_requirements, `Parse errors:` block
  grouping in import_requirements, the category-grouped layout in shebangs) were intentionally
  dropped or restructured to one-violation-per-line keyed by file. All violation information is
  preserved; only the grouping structure changed.
- Performance: expensive scanners (bandit JSON subprocess, batched pyflakes, tracked-file sets,
  ASCII fixer pass) run once in the precompute fixture and distribute results by file. Failure
  messages are built only on failure. Suite now ~990 cases in ~3.1s (hard gate: 30s; target:
  10s). Measured via `pytest tests/ --durations=50`, median of 3 clean runs.
- `-k <file>` is now meaningful suite-wide: because the fixture precomputes all violations,
  a `-k tests/foo.py` run selects only that file's per-file assert cases across all hygiene
  modules while still scanning every file and writing complete reports for any module that
  has violations. Partial reports are no longer possible.
- Relocated `tests/test_test_naming_conventions.py` to
  `templates/typescript/tests/test_test_naming_conventions.py` (WP0c) via `git mv`: the test
  targets `tests/e2e/` and `tests/playwright/` subtrees present only in TypeScript repos; in
  this Python repo all checks early-skipped and the module was inert. It now ships only to
  `REPO_TYPE=typescript` consumer repos.
- Renamed `PropagateContext` field `bootstrap` -> `initial_setup` (parameters, docstrings, log
  messages); batch propagation behavior is identical with `initial_setup=False`. Updated all
  callers in `repolib/`, `reset_repo.py`, `tests/meta/test_propagate_cli.py`, and
  `tests/meta/test_repolib_helpers.py`.
- `reset_repo.py` cleanup now also removes `templates/` after propagation and gitignore merge
  have read from it; absent or untracked `templates/` is handled cleanly. Two new end-state
  checks added: `verify_scaffold_sentinel` (per-type sentinel file -- typescript:
  `eslint.config.js`, python: `docs/PYTHON_STYLE.md`) and `verify_clean_end_state` (raises
  listing any leftover `templates/`, `repolib/`, `LICENSES/`, `meta/`, or `tests/meta/` paths
  found in `git ls-files` or on disk). Note: `tools/` is intentionally not in this list -- see
  the later same-day standard-change entry; typed-overlay `tools/` files may legitimately
  remain on a consumer after cleanup.
- New propagation standard: every file under `templates/<type>/` ships to consumers of that
  type, at its path relative to `templates/<type>/`, including `tools/` subpaths. The
  typed-overlay walker (`repolib/files.py` step 2) no longer trims the `tools`/`meta`
  directories or filters subdirectories against `META_DIRS`; only the `META_FILES`
  basename/path guard remains (so a stray `templates/<type>/README.md` cannot clobber a
  consumer README). Split `assert_not_meta` into `assert_not_meta` (strict: also rejects
  `META_DIRS` traversal, used by the universal walk for ROOT `tools/` infrastructure) and
  `assert_not_meta_file` (`META_FILES`-only, used by typed-overlay appends and the apply-time
  dispatcher in `repolib/process.py`) so legitimate consumer `tools/` paths are not rejected.
  The ROOT `tools/` directory (template infrastructure, e.g. `tools/detect_repo_type.py`) is
  unchanged: it never ships and is removed at reset.
- Relocated `sync_typescript_package_pins.py` to `templates/typescript/tools/` (user `git mv`);
  under the new standard it now ships to typescript consumers at
  `tools/sync_typescript_package_pins.py`. This supersedes this morning's entry that described
  it shipping via the devel bucket to `devel/`: the file lives under `tools/`, not `devel/`,
  and reaches consumers through the typed overlay. Docstring updated to the new location and a
  Run example of `python3 tools/sync_typescript_package_pins.py [--apply]` (CWD-anchored).
- `reset_repo.py` end-state verification: removed `tools/` from `TEMPLATE_OWNED_PREFIXES`.
  Consumers may now legitimately receive `tools/` files from the typed overlay, so a `tools/`
  directory remaining after cleanup must not fail `verify_clean_end_state`. The cleanup-phase
  `git rm -r tools/` still removes the template's own tracked root `tools/` (e.g.
  `tools/detect_repo_type.py`); it removes tracked entries only, so freshly propagated untracked
  `tools/` files survive. The `git rm -r tools/` step now guards on tracked content (logs and
  skips when `tools/` holds only untracked propagated files) instead of failing on a no-match
  pathspec, mirroring the existing `templates/` handling.
- Moved `run_web_server.sh` from `templates/typescript/noexist/` to
  `templates/typescript/run_web_server.sh` (overwrite/always-propagate bucket) via `git mv`,
  reversing the prior audit decision at CHANGELOG.md:478 that placed it in `noexist/` for
  per-consumer port choice. Rationale: the port is now random with a `PORT` override and the
  fleet shows consumers do not customize the file, so the hardened script can always overwrite.
  Propagation routing verified (WP-A2): `compute_propagation_plan` typed-overlay walk (step 2,
  `repolib/files.py:1018-1025`) routes every non-special-prefix file under `templates/<type>/`
  to `overwrite_files` at its relative path; `run_web_server.sh` at the `templates/typescript/`
  root has no `noexist/`, `devel/`, or `tests/` prefix and is not a META file, so it lands in
  `overwrite_files` as `run_web_server.sh` and ships to every TypeScript consumer on every
  propagation run. Consumer-impact summary (WP-A2): 2 of 6 deployed copies diverged --
  `stem-lesson-quiz-game` had a comment-only rewrite of the header and a different
  setup-missing error message (`setup_game.sh` reference instead of `devel/setup_typescript.sh`);
  `virtual-lab-protocol-simulation` had the auto-install path already present (bare
  `bash devel/setup_typescript.sh`, no existence guard) plus comment-only diffs. Neither
  carries any logic not already folded into the canonical hardened script by WP-A1. Overwrite
  is safe; nothing of value is lost. `pytest tests/` confirmed green: 1032 passed in 2.04s
  (includes `tests/test_shebangs.py` and `tests/meta/` routing tests). Doc link
  `templates/typescript/docs/TYPESCRIPT_STYLE.md:269` (`../run_web_server.sh`) resolves to
  the new location. `templates/typescript/noexist/package.json` `"serve": "./run_web_server.sh"`
  still points at the consumer-root script (package.json stays in `noexist/`; unchanged).
  (WP-A1/WP-A2)
- `run_web_server.sh` auto-install: on missing `node_modules` the script now runs
  `bash devel/setup_typescript.sh` (when present) instead of erroring; if the setup script is
  missing it exits with a helpful message. Folds in the `virtual-lab-protocol-simulation`
  consumer's useful divergence. Reported separately from the lifecycle fix so future setup
  debugging is easy. (WP-A1)

### Fixes and Maintenance

- `run_web_server.sh` lifecycle fix: added an idempotent cleanup `trap` on EXIT/INT/TERM/HUP that
  kills only the http.server child and the script's own browser-open helper (own-child-only; no
  `pkill`/`pgrep`/`ps` scanning, no PID file). The server now starts in the background with its
  PID captured and `wait`ed on, and cleanup preserves the real exit status. Stops the script from
  leaving orphaned `http.server` processes when a backgrounded launcher's parent shell dies.
  Caveat: the trap only fires for trappable signals; `SIGKILL` and some shell-death cases remain
  out of scope. (WP-A1/WP-A2)
- Bumped the `esbuild` devDependency floor in `templates/typescript/noexist/package.json` from
  `>=0.28.0` to `>=0.28.1` to clear GHSA esbuild dev-server path-traversal (affected
  `>=0.27.3, <0.28.1`, patched `0.28.1`). No real exposure for this repo (the build uses
  `npx esbuild --bundle`, not the `--servedir` dev server; the bug is Windows-only; GitHub Pages
  output is static), but the prior floor `0.28.0` sat one patch inside the advisory window.
  Dependabot's separate "no lockfile" notice is per-consumer: run `npm install` and commit the
  generated `package-lock.json` in the affected consumer repo.
- Changed `file_utils.run_fixer_script(script_name, target)` contract: function now
  returns `(returncode: int, stderr: str)` for every subprocess completion and never raises on a
  non-zero exit code. Previously it raised `AssertionError` on any non-zero exit, which caused
  fixer exit code 2 (success-with-changes in `fix_ascii_compliance.py`) to be treated as a
  failure inside a module-scoped autouse fixture, cascading 565 test errors in consumer repos.
  `RuntimeError` is raised only for environment preconditions: script not found (checked via
  `os.path.isfile` before launch) or `FileNotFoundError` from a missing Python interpreter
  (re-raised as `RuntimeError`). Callers now inspect the return value; exit-code contracts:
  `fix_ascii_compliance.py` 0=clean, 1=issues remain, 2=auto-fixed; `fix_whitespace.py`
  0=clean-or-fixed, 1=missing/no-input. Added `tests/meta/test_file_utils_fixer.py` with
  monkeypatched unit tests covering return codes 2 (regression guard for the cascade bug) and 7
  (unexpected), plus nonexistent script and missing interpreter `RuntimeError` paths. Updated
  `tests/TESTS_README.md` and `docs/PYTEST_STYLE.md` run_fixer_script bullets. Consumer repos
  need propagation via `propagate_style_guides.py` to receive the updated `file_utils.py`.
- Memoized `file_utils.get_repo_root` (process-lifetime `functools.lru_cache`) and the no-pattern whole-repo `list_tracked_files` listing (per-`repo_root` cache; pattern-scoped calls stay uncached), and made the per-file hygiene modules build their failure messages lazily inside the assert (WP0); eliminates per-test `git rev-parse` fanout and collection-time `git ls-files` fanout; pinned by call-count meta tests in `tests/meta/test_file_utils_caching.py`.
- Updated `docs/PYTEST_STYLE.md` hygiene-report section: replaced stale `sync_report` /
  `purge_report` API with the current `write_report_lines` + `clear_stale_reports` shape,
  added the canonical module code example (with TABS), documented the report lifecycle and
  `-k`-independence rule, and updated the additional-helpers list.
- Updated `tests/TESTS_README.md` helper list to match reality: added `collect_file_violations`,
  `collect_python_violations`, `format_violation_report`, `format_violation_assert_message`,
  `write_report_lines`, `rel_id`, and `clear_stale_reports`; removed stale `sync_report` and
  `purge_report` entries.
- Fixed stale reference in `docs/E2E_TESTS.md` "Naming conventions test" section: updated
  `tests/test_test_naming_conventions.py` reference to
  `templates/typescript/tests/test_test_naming_conventions.py` with a note that it ships only
  to TypeScript repos.
- Fixed `reset_repo.py` initial-setup propagation silent no-op in consumer clones:
  `process_repo`'s self-skip guard (template root anchored on `repolib/__file__`) matched the
  consumer repo itself and returned `None`, which `run_propagate` ignored; zero typed-overlay
  files shipped (observed on a typescript consumer: no scaffold, no TYPESCRIPT gitignore block,
  `templates/` left tracked). Fixed by gating the self-skip on the context `initial_setup`
  flag and raising `RuntimeError` in `run_propagate` when `process_repo` returns `None`.
- Relocated `templates/typescript/tools/html_to_pdf.mjs` to
  `templates/typescript/devel/html_to_pdf.mjs` via `git mv` so it ships via the `devel_files`
  bucket (verified in the typescript plan `devel_files` listing). Note: at the time of this move
  typed-overlay `tools/` did not ship, so devel/ was the route to reach consumers; the later
  same-day standard change makes `templates/<type>/tools/` ship directly, but this file remains
  in `devel/` as a deliberate placement.

### Behavior or Interface Changes

- Restored auto-fix behavior in `tests/test_whitespace.py`: the `collect_report` fixture now
  accepts `pytestconfig`, resolves `apply_fix = not pytestconfig.getoption("no_ascii_fix", default=False)`,
  and for each initially-violating file runs `file_utils.run_fixer_script("fix_whitespace.py", abs_path)`
  then re-scans; only files with remaining violations after fixing are recorded in `VIOLATIONS_BY_FILE`.
  This matches the gating convention in `test_ascii_compliance.py` (same option name and default).
  The fixer runs once in the fixture, never inside a parametrized test case.

### Removals and Deprecations

- Removed `templates/typescript/tools/check_css_content_policy.py` from the template: the script
  contains project-specific virtual-lab DOM selectors and is not appropriate for general typescript
  consumers. It stays in its origin repo (virtual-lab) where it belongs. The `check_codebase.sh`
  step 5 `css:policy` gate already uses `[ -f tools/check_css_content_policy.py ]` so consumers
  without the script get a clean SKIP and are unaffected. No stub or replacement ships from the
  template.

- Removed the `css:policy` step from `templates/typescript/check_codebase.sh` (header renumbered):
  a permanently skipped step caused confusion and concern once `check_css_content_policy.py` no
  longer ships; repos that carry their own policy script can add a local step.

- Removed `file_utils.sync_report` and `file_utils.purge_report` (dead code, M3 plan): all 11
  plan modules plus `tests/test_init_files.py` migrated to `write_report_lines` +
  `clear_stale_reports`; zero active callers
  remained. Deleted `tests/meta/test_sync_report.py` (pinned only the removed helpers).
  Updated `tests/TESTS_README.md` and the `write_report_lines` docstring to remove stale
  references.

### Developer Tests and Notes

- Added `tests/meta/test_reset_repo_self_propagation.py` (14 tests): `initial_setup`-on-self
  applies correct buckets, batch self-skip returns `None`, `run_propagate` raises on `None`,
  end-state verifier raises on planted leftovers, scaffold-present + templates-absent ordering
  invariant. Updated `bootstrap=` keyword in `tests/meta/test_propagate_cli.py` and
  `tests/meta/test_repolib_helpers.py`. Suite: 1008 passed.

### Decisions and Failures

- Why the exception channel was rejected for `run_fixer_script`: raising on non-zero exit
  inside a module-scoped autouse fixture errors every parametrized test in the module, not just
  the one file that triggered the fix. Per-file fixer outcomes (clean, needs-fix, fixed,
  unexpected error) belong in per-file report data -- the fixture should collect them and the
  per-file test should assert on them. Using exceptions conflates environment failure (broken
  interpreter, missing script -- genuine RuntimeError territory) with normal fixer output
  (non-zero exit is a documented, meaningful result). The return-tuple contract makes the
  distinction explicit and puts outcome handling in the right place.
- Root cause of the reset_repo initial-setup no-op: regression introduced when `reset_repo.py`
  switched from shelling out to `propagate_style_guides.py` to calling `repolib` directly; the
  batch-mode self-skip guard was correct for batch propagation but silently disabled the entire
  initial-setup use case. E2E in `/tmp` scratch clones confirmed all 18 typescript files land
  and the TYPESCRIPT gitignore block is written. Full live exit-0 run requires a committed HEAD
  (uncommitted-overlay clones cause `git rm` to refuse modified files -- test-setup artifact,
  not a product bug).
