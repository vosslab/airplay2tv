# Human guidance

Durable preferences and stable decisions for agents working in this repo.
Keep entries current. Move outdated entries to `docs/CHANGELOG.md`.

See [docs/REPO_STYLE.md](../../docs/REPO_STYLE.md) for repo-wide conventions.

## Propagation routing model

- File location is the primary routing determinant. Agents use location first;
  per-file overrides only when location cannot express the rule.
- Every file under `docs/`, `tests/`, and `devel/` ships universally to all
  consumer repos (overwrite bucket by default).
- Every file under `templates/<type>/` ships to consumer repos of that type,
  at its consumer-relative path (e.g. `templates/python/foo.py` ships as `foo.py`).
- `docs/PYTHON_STYLE.md` ships to all repo types. It is a universal doc.
- `pip_requirements-dev.txt` ships universally (root `root_propagate_allowlist`
  + `universal_noexist`). `pip_requirements.txt` is python-only noexist
  (`templates/python/noexist/pip_requirements.txt`).

## ROUTING_OVERRIDES holds only exclude_repos

- `ROUTING_OVERRIDES` in `meta/propagation/manifests.yaml` holds only one
  exception: `exclude_repos` for `docs/CLAUDE_HOOK_USAGE_GUIDE.md` (blocks
  the mirror from shipping back to its source repo `claude-code-permissions-hook`).
- Do not add `language`, `bucket`, or `requires_repo_file` fields. Those were
  removed when location-based routing replaced per-file gates.
- When a new language-specific file is needed, put it under the correct
  `templates/<type>/` folder rather than adding a `ROUTING_OVERRIDES` entry.

## Conditional overlays (_folder convention)

- An underscore folder under `templates/<type>/` (e.g. `templates/python/_pypi/`)
  is a conditional overlay. The base walk skips it; a `conditional_overlays`
  manifest rule enables it per consumer.
- Conditional overlay rules live in `meta/propagation/manifests.yaml` under
  `conditional_overlays: <type>: <overlay_name>: {when, path, description}`.
- The only supported `when` verb is `has_file`: the overlay ships when the named
  file exists at the consumer repo root.
- Current example: `_pypi` overlay (`templates/python/_pypi/`) selected when the
  consumer has `pyproject.toml`. Ships `devel/submit_to_pypi.py` and a
  `noexist/pyproject.toml` seed.
- Prefer conditional overlays over `requires_repo_file` in `ROUTING_OVERRIDES`.

## Manifests single source of truth

- All propagation manifests live in `meta/propagation/manifests.yaml`.
- `repolib/manifests.py:load_manifests()` reads the YAML at import time with
  `yaml.safe_load` and returns the correct Python types.
- `repolib/model.py` assigns loaded values to its module-level public names.
- Edit `meta/propagation/manifests.yaml` to change any manifest. Do not add
  inline literals back to `repolib/model.py`.

## reset_repo.py design

- `reset_repo.py` is the bootstrap entry point for new consumer repos.
- Interactive interview is the human default: the script asks project type, license,
  PyPI intent, stage, and commit choices at the terminal.
- CLI surface is minimal: `-h`, `--dry-run`, and `--config <file>`. The `--force` and
  `--yes` flags were removed; `--force` had no use case and `--yes` is replaced by
  `--config` for non-interactive runs.
- `--config <file>` is the testing/reproducibility interface: a JSON answer file
  drives a non-interactive reset for e2e and subagent testing. It is not required for
  normal human use. Required JSON keys: `project_type` and `code_license`. Optional
  keys with defaults: `docs_license` (CC-BY-4.0), `pypi` (false, python-only),
  `stage` (true), `commit` (false). Short aliases are accepted for both required keys.
- Folder-name guard: reset refuses to run when the repo root basename is exactly
  `starter-repo-template`. This protects the template development checkout. Guard is
  folder name only; no remote or origin inspection (remote-slug detection is fragile
  for freshly cloned consumer repos that have not yet renamed their remote).
- Running outside a git repository exits with a clear message instead of a raw
  subprocess traceback.
- Do not add automation flags for decisions the user makes once at repo creation.

## E2E harness design

- `tests/meta/e2e/e2e_reset_routing.py` clones the template into consumer-named `/tmp` dirs
  (e.g. `/tmp/my_project_python/`) so each test case is isolated and ephemeral.
  Template-meta: lives under `tests/meta/e2e/`; never propagates to consumers; removed by reset.
- LOCAL mode (default): offline, clones committed local history only. Uncommitted
  working-tree changes are not exercised; commit before running LOCAL if you need the
  harness to see them.
- REMOTE mode (opt-in via `remote` argument): GitHub HTTPS clone (read-only); exercises
  what a consumer receives from origin/main. New code must be pushed to origin/main by the
  human first; REMOTE clones whatever is already there.
- Each case uses an ephemeral per-case JSON config; verified against the live
  propagation engine (oracle) plus reset-specific anchor checks.
- `tests/meta/e2e/run_all.sh` iterates all `e2e_*` scripts under `tests/meta/e2e/`
  and reports pass/fail; offline only (LOCAL mode). Also template-meta.

## Tests follow live config

- Tests assert on propagation engine behavior using synthetic fixtures; they do
  not duplicate manifest constants inline.
- Preferred pattern: call `repolib.manifests.load_manifests()` or inspect
  `repolib.model.*` constants rather than hardcoding expected sets.
- Routing assertions use `compute_propagation_plan` on fixture repos so they
  reflect the live config automatically when manifests change.

## Prefer rule-based routing over per-file customization

- The goal is zero per-file routing entries in `ROUTING_OVERRIDES`.
- When a file needs special handling, exhaust location-based options first:
  move it to the correct folder or create a `_folder` conditional overlay.
- Only fall back to `ROUTING_OVERRIDES` for exceptions that cannot be expressed
  by directory placement (currently: `exclude_repos` only).
