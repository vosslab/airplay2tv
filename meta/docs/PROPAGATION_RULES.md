# Propagation rules

Where to drop a file so the propagator ships it to the right repos.

See [HUMAN_GUIDANCE.md](HUMAN_GUIDANCE.md) for durable propagation decisions and design rationale.

## Hardcoding principles

Manifests live in `meta/propagation/manifests.yaml` (loaded by `repolib/manifests.py:load_manifests()`
and assigned to `repolib/model.py` module-level names). Three hardcoding categories apply:

- **Good hardcoding** -- root files with special semantics, noexist files, exclude_repos exceptions.
  These need explicit intent because no directory convention can express them.
- **Expected hardcoding** -- root allowlist, root meta files. Root has mixed semantics (some ship,
  some don't, some need bootstrap-time customization); per-file lists are correct.
- **Bad hardcoding** -- files classifiable by directory listed individually. Move them to a
  META_DIRS entry. Example: `tools/detect_repo_type.py` lived in META_FILES; now `tools` is in
  META_DIRS and the file entry is gone.

The cleaner principle:

1. **Directory convention when possible.** If every file under a directory shares the same routing,
   put the directory name in META_DIRS / SKIP_WALK_DIRS, not each file.
2. **Explicit list when root-level meaning is ambiguous.** Root files (`README.md`, `VERSION`,
   `Brewfile`, `.gitignore`, `REPO_TYPE`) need per-repo customization; list them in META_FILES.
3. **Override table only for true routing exceptions.** Currently the only exception encoded in
   `ROUTING_OVERRIDES` is `exclude_repos` (blocks a universal file from shipping back to its
   source repo). Language gates, `requires_repo_file` gates, and `bucket` fields have been removed.

Do not try to eliminate all hardcoding. Root has mixed semantics; explicit lists are correct there.

## Folder convention

| Want to ... | Put the file under | Ships to |
|---|---|---|
| Doc that every repo gets | docs/ | every repo, overwrite |
| Universal test or helper | tests/ (any non-meta file) | every repo, overwrite |
| Helper script in devel/ | devel/ | every repo, overwrite |
| Starter file that must not clobber existing | templates/<type>/noexist/<consumer-path> | only when missing |
| TypeScript-only file (any subpath, including tools/) | templates/typescript/<consumer-path> | typescript repos only |
| Rust-only file (any subpath, including tools/) | templates/rust/<consumer-path> | rust repos only |
| Conditionally-shipped overlay (e.g. PyPI tools) | templates/<type>/_overlay/<consumer-path> + conditional_overlays rule | selected repos only (see below) |
| Root-level file like AGENTS.md | template root + add to ROOT_PROPAGATE_ALLOWLIST | every repo, overwrite |
| Universal gitignore blocks | templates/gitignore.universal | every repo, merged into .gitignore under `# === UNIVERSAL ===` |
| MERGE bucket (set-union @-import merge with strip list) | template root + add to `MERGE_FILES` | every repo; template @-imports union-added to consumer; strip list at `meta/propagation/deprecated_claude_md.txt` removes retired entries (see [MERGE_BUCKET_SPEC.md](MERGE_BUCKET_SPEC.md)) |
| Template-only tooling at ROOT | tools/<file> (repo-root tools/, e.g. tools/detect_repo_type.py) | never (template-meta); removed at reset |
| Typed-overlay tooling | templates/<type>/tools/<file> (e.g. templates/typescript/tools/sync_typescript_package_pins.py) | that type only, ships at consumer tools/<file> |

**Standard: every file under `templates/<type>/` ships** to consumers of that
type, at its path relative to `templates/<type>/`. This includes `tools/`
subpaths. The typed-overlay walker no longer filters subdirectories against
META_DIRS; only the META_FILES basename guard still applies (so a stray
`templates/<type>/README.md` cannot clobber a consumer README). The ROOT `tools/`
directory is separate: it holds template infrastructure (e.g.
`tools/detect_repo_type.py`), never ships, and is removed during reset.

**Underscore folders (`_folder`) are conditional overlays.** Any folder whose
name starts with `_` under `templates/<type>/` (e.g. `templates/python/_pypi/`)
is a conditional overlay. The base typed-overlay walk skips it. A matching rule
in `conditional_overlays` in `meta/propagation/manifests.yaml` enables it per
consumer. Conditional overlay shape:

```yaml
conditional_overlays:
  python:
    _pypi:
      when: has_file
      path: pyproject.toml
      description: >-
        PyPI packaging overlay: ships submit_to_pypi.py and a pyproject.toml
        seed only to python repos that are packaged for PyPI.
```

The only supported `when` verb is `has_file`. The overlay ships when the named
`path` exists at the consumer repo root. Files inside the overlay are routed
using the same noexist/overwrite rules as other typed overlay files.

## Precedence

File routing honors a strict precedence order; earlier rules win on conflict:

1. **META_FILES / META_DIRS** - Files in these block-lists never ship to any consumer, even if matched by other rules.
2. **MERGE_FILES** - Files in this set route to the `merge_files` bucket regardless of where the walker would otherwise place them. Post-walker step 6 in `compute_propagation_plan` moves matching entries out of `overwrite_files` / `noexist_files` into `merge_files`. See [MERGE_BUCKET_SPEC.md](MERGE_BUCKET_SPEC.md).
3. **ROUTING_OVERRIDES** - Per-file exceptions. Currently the only supported field is `exclude_repos` (blocks a file from shipping to its source repo). Language and requires_repo_file gates have been removed; use location-based routing or conditional overlays instead.
4. **UNIVERSAL_NOEXIST** - Files in this list override the universal overwrite default; they move to noexist_files instead.
5. **Typed noexist** - Templates/<type>/noexist/<path> overrides typed overlay overwrite; same path in noexist always wins.
6. **Typed overlay shadows universal** - When both universal and typed overlay define the same consumer destination, the typed version ships. The propagator prints `[OVERLAY-OVERRIDE] <consumer-path>: typed overlay shadows universal source` to stdout for visibility.

## Classification criterion

Every file the propagator ships is classified into one of four policy categories. The classification rule for new files:

- **OVERWRITE** -- template centrally owns the file; consumer divergence is a bug to erase on next sync. Use for style guides, shared lint tests, shared helper scripts, and the universal clean sweep.
- **MERGE** -- template ships an `@`-import set; the propagator union-adds it to the consumer file and strips entries listed in `meta/propagation/deprecated_claude_md.txt`. Consumer-local `@`-imports and non-`@` content are preserved. Currently used by `CLAUDE.md` only. See [MERGE_BUCKET_SPEC.md](MERGE_BUCKET_SPEC.md).
- **NOEXIST** -- starter seed; consumer owns the file thereafter. Use when the consumer reasonably extends the file with project-specific content the template cannot anticipate (e.g., `AGENTS.md`, `source_me.sh`, `tsconfig.json`, deploy scripts).
- **META** -- never ships, any bucket, any repo type. Use for template-only infrastructure (propagator itself, reset_repo, README, VERSION) and per-repo content the template cannot author (CHANGELOG, .gitignore, REPO_TYPE).

## Exceptions in the manifest

Most additions are drop-and-go. All manifests live in `meta/propagation/manifests.yaml`
(single source of truth). `repolib/manifests.py:load_manifests()` reads the YAML at import time;
`repolib/model.py` assigns the loaded values to its module-level public names. Do not add inline
manifest literals back to `repolib/model.py`.

- `ROOT_PROPAGATE_ALLOWLIST` -- root files that DO ship. Default: CLAUDE.md, AGENTS.md, source_me.sh,
  dist_clean.sh, pip_requirements-dev.txt. Add here when introducing a new root-level file all repos need.
- `UNIVERSAL_NOEXIST` -- universal files that ship only when missing at consumer. Default: AGENTS.md,
  source_me.sh, docs/AUTHORS.md, tests/TESTS_README.md, pip_requirements-dev.txt.

The two sets compose: `ROOT_PROPAGATE_ALLOWLIST` decides IF a root file ships; `UNIVERSAL_NOEXIST`
then decides HOW (overwrite vs noexist-only). Overlap is intentional: `AGENTS.md` and `source_me.sh`
appear in both - allowlisted to ship, then routed noexist-only so they don't clobber consumer
customizations. `CLAUDE.md` is allowlisted and routed via `MERGE_FILES` (set-union of `@`-imports plus
deprecation-strip list); consumer keeps any local `@`-imports and non-`@` content.
- `MERGE_FILES` -- files routed to the MERGE bucket. Default: CLAUDE.md. Template `@`-imports are
  union-added to the consumer file; any consumer line matching `meta/propagation/deprecated_claude_md.txt`
  is stripped.
- `meta/propagation/deprecated_claude_md.txt` -- user-editable strip manifest for the CLAUDE.md
  set-union merge. Lines in this file are removed from every consumer CLAUDE.md on every sync (after
  comment/blank-line filtering). Add a line when retiring an `@`-import from the template.
- `ROUTING_OVERRIDES` -- per-file exceptions. Currently holds only one entry:
  `docs/CLAUDE_HOOK_USAGE_GUIDE.md: {exclude_repos: [claude-code-permissions-hook]}` (blocks the
  mirror from shipping back to its source repo). Language gates, `requires_repo_file` gates, and
  `bucket` fields have been removed; use location or `conditional_overlays` instead. `docs/PYTHON_STYLE.md`
  and `devel/submit_to_pypi.py` now route by location (universal doc and `_pypi` overlay respectively).
- `conditional_overlays` -- per-type underscore-folder rules. See the `_folder` section above.
- `META_FILES` / `META_DIRS` / `META_TEST_PREFIXES` -- block-lists for files that NEVER ship
  (propagator itself, reset_repo, LICENSES/, etc.).

## Examples

- Adding `docs/SHELL_STYLE.md` -- drop in `docs/`, no manifest edit. Every repo gets it.
- Adding `docs/PYTHON_STYLE.md` -- already universal; drop in `docs/`. Every repo type gets it.
- Adding `tests/test_security_audit.py` -- drop in `tests/`, every repo gets it. The `tests/` walk is a denylist: it ships every non-meta `tests/` file by location and skips only dotfiles, `_`-prefixed scratch, `conftest.py` (owned by `merge_conftest`), and `META_TEST_PREFIXES`. A non-`test_`-prefixed helper like `tests/helper_thing.py` ships too.
- Adding `templates/typescript/.eslintignore` -- drop under `templates/typescript/`. TypeScript repos get it at consumer root.
- Adding a new starter `Makefile` that must not clobber existing ones -- drop at `templates/<type>/noexist/Makefile` (per type) or add path to `UNIVERSAL_NOEXIST` + place at template root.
- Adding a python-only tool needed only when `pyproject.toml` exists -- place under `templates/python/_pypi/<consumer-path>` and add a `conditional_overlays.python._pypi` rule (already defined). Example: `devel/submit_to_pypi.py` lives at `templates/python/_pypi/devel/submit_to_pypi.py`.
- Adding an `exclude_repos` exception -- add to `ROUTING_OVERRIDES` in `meta/propagation/manifests.yaml` with `exclude_repos: [<repo-basename>]`. Use only to prevent a mirror file from shipping back to its source repo.

## Routing override gates

The `ROUTING_OVERRIDES` dict in `meta/propagation/manifests.yaml` now holds only `exclude_repos`
exceptions. Language gates, `requires_repo_file` gates, and `bucket` fields have been removed.

- **`exclude_repos` gate** - Blocks a file from shipping when the destination repo basename matches
  any entry in the list. Use only for mirror files that must not overwrite the source repo.
  Example: `docs/CLAUDE_HOOK_USAGE_GUIDE.md` is sourced from `claude-code-permissions-hook`; the
  `exclude_repos` rule prevents the mirror from shipping back to that repo.

For all other routing needs, use location-based conventions (folder placement, `noexist/`,
typed overlay, or `_folder` conditional overlay).

## What never propagates

Listed in `META_FILES` / `META_DIRS` / `META_TEST_PREFIXES`. Includes the propagator entry script `propagate_style_guides.py`, reset_repo.py, README.md, VERSION, Brewfile, .gitignore, REPO_TYPE, pip_extras.txt (root META_FILES); `repolib/` helper package, ROOT `tools/` (detect_repo_type.py and other root-level template infrastructure; note that `templates/<type>/tools/` is a separate path that DOES ship), `meta/` (this doc and other template-meta), `templates/` (every file under `templates/<type>/` ships at its relative path, including tools/ subpaths), `LICENSES/`, `docs/active_plans/`, `docs/archive/`, `experiment_reports/`, `__pycache__/`, `.git/` (META_DIRS). Tests are excluded via two mechanisms: `tests/meta/` is excluded as a whole via `SKIP_WALK_DIRS` containing `'meta'`, and tests starting with `test_repolib_`, `test_reset_repo_`, or `test_detect_repo_type` are also excluded via `META_TEST_PREFIXES`.

## Link bucket isolation

A file may only link to targets that propagate with it. The rule prevents universal docs from hardcoding links to template-specific overlays, which would silently break when those overlays do not ship to a given repo type.

Allowed link transitions:

- `universal` -> `universal` only. Universal files (docs, tests, devel scripts) link only to other universal targets that ship to every repo type.
- `overlay-<type>` -> `universal` or `overlay-<type>` (same type). TypeScript-specific docs may link to universal docs or other TypeScript overlay docs, but not to Rust overlays or other types.
- `meta` -> any bucket in the template. Meta files (template-only tooling and documentation) never ship to consumers, so they may link anywhere.

Enforcement: [../../tests/meta/test_link_bucket_isolation.py](../../tests/meta/test_link_bucket_isolation.py) walks all tracked `*.md` files, classifies each file's bucket, resolves local links, and hard-fails on disallowed transitions.
